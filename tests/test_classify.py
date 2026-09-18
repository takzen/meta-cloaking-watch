"""Testy klasyfikacji M0-M4 na danych syntetycznych.

Wszystkie hashe mają prefiks SYNTHETIC-, żeby żaden testowy artefakt nie dał się
pomylić z dowodem (CODEBOOK.md sekcja 1, zasada niemieszania danych).

Najważniejszy test w tym pliku to `test_brak_pomiaru_to_nie_brak_rekordu`.
Pomylenie tych dwóch rzeczy zawyżyłoby M4, czyli dokładnie tę liczbę, która jest
głównym wynikiem badania.
"""

from __future__ import annotations

import pytest

from src.classify import (
    CHECKPOINTS,
    Observation,
    Result,
    Snapshot,
    classify,
    exact_matcher,
)

OBSERVED = "SYNTHETIC-observed"
OTHER = "SYNTHETIC-other"
THIRD = "SYNTHETIC-third"


def snap(checkpoint, *, present=True, hashes=(OBSERVED,), measured=True, multi=False):
    return Snapshot(
        checkpoint=checkpoint,
        measured=measured,
        record_present=present if measured else False,
        creative_hashes=tuple(hashes) if measured and present else (),
        multi_version_flag=multi,
    )


def obs(*snapshots, observed_hash=OBSERVED):
    return Observation(
        ad_ref="AD-0001",
        library_id="SYNTHETIC-lib-id",
        observed_creative_hash=observed_hash,
        snapshots=tuple(snapshots),
    )


def full(**kwargs):
    """Komplet sześciu pomiarów o jednakowej charakterystyce."""
    return [snap(c, **kwargs) for c in CHECKPOINTS]


# --------------------------------------------------------------------------- #
# Kategorie podstawowe                                                          #
# --------------------------------------------------------------------------- #

def test_m0_zgodnosc_od_pierwszego_pomiaru():
    result = classify(obs(*full()))
    assert result.category == "M0"


def test_m1_rekord_pojawia_sie_z_opoznieniem():
    snapshots = [
        snap("t+1h", present=False),
        snap("t+6h", present=False),
        snap("t+24h"),
        snap("t+72h"),
        snap("t+7d"),
        snap("t+30d"),
    ]
    result = classify(obs(*snapshots))
    assert result.category == "M1"
    assert result.evidence["first_seen"] == "t+24h"


def test_m2_obserwowana_kreacja_nigdy_nieudostepniona():
    result = classify(obs(*full(hashes=(OTHER,), multi=True)))
    assert result.category == "M2"
    assert result.evidence["multi_version_flag"] is True


def test_m3_podmiana_kreacji():
    snapshots = [
        snap("t+1h", hashes=(OBSERVED,)),
        snap("t+6h", hashes=(OBSERVED,)),
        snap("t+24h", hashes=(OTHER,)),
        snap("t+72h", hashes=(OTHER,)),
        snap("t+7d", hashes=(OTHER,)),
        snap("t+30d", hashes=(OTHER,)),
    ]
    result = classify(obs(*snapshots))
    assert result.category == "M3"
    assert result.evidence["kind"] == "podmiana"
    assert result.evidence["between"] == ["t+6h", "t+24h"]
    assert result.evidence["removed"] == [OBSERVED]


def test_m3_rozroznia_dodanie_od_usuniecia():
    dodanie = [
        snap("t+1h", hashes=(OBSERVED,)),
        *[snap(c, hashes=(OBSERVED, OTHER)) for c in CHECKPOINTS[1:]],
    ]
    assert classify(obs(*dodanie)).evidence["kind"] == "dodanie"

    usuniecie = [
        snap("t+1h", hashes=(OBSERVED, OTHER)),
        *[snap(c, hashes=(OBSERVED,)) for c in CHECKPOINTS[1:]],
    ]
    assert classify(obs(*usuniecie)).evidence["kind"] == "usunięcie"


def test_m4_rekord_nieobecny_wszedzie():
    result = classify(obs(*full(present=False)))
    assert result.category == "M4"


# --------------------------------------------------------------------------- #
# Kolejność pierwszeństwa (CODEBOOK.md sekcja 4)                                #
# --------------------------------------------------------------------------- #

def test_m3_ma_pierwszenstwo_przed_m2():
    """Kreacja nigdy niezgodna z obserwowaną, ale zbiór hashy się zmienia.
    Zmiana w czasie jest mocniejszym dowodem, więc nie wolno jej zgubić w M2."""
    snapshots = [
        snap("t+1h", hashes=(OTHER,)),
        *[snap(c, hashes=(THIRD,)) for c in CHECKPOINTS[1:]],
    ]
    assert classify(obs(*snapshots)).category == "M3"


def test_m2_ma_pierwszenstwo_przed_m1():
    """Rekord pojawia się z opóźnieniem, ale obserwowana kreacja nigdy nie jest
    udostępniona. Trwała rozbieżność jest istotniejsza niż samo opóźnienie."""
    snapshots = [
        snap("t+1h", present=False),
        *[snap(c, hashes=(OTHER,)) for c in CHECKPOINTS[1:]],
    ]
    assert classify(obs(*snapshots)).category == "M2"


def test_m4_ma_pierwszenstwo_przed_wszystkim():
    snapshots = full(present=False)
    assert classify(obs(*snapshots)).category == "M4"


# --------------------------------------------------------------------------- #
# Brak pomiaru kontra brak rekordu                                              #
# --------------------------------------------------------------------------- #

def test_brak_pomiaru_to_nie_brak_rekordu():
    """Regresja krytyczna. Nieudane odpytanie nie może podbijać M4."""
    snapshots = [
        snap("t+1h", measured=False),
        snap("t+6h", measured=False),
        snap("t+24h"),
        snap("t+72h"),
        snap("t+7d"),
        snap("t+30d"),
    ]
    result = classify(obs(*snapshots))
    assert result.category == "M0"
    assert result.evidence["first_checked"] == "t+24h"


def test_zbyt_wiele_brakow_daje_unresolved():
    snapshots = [
        snap("t+1h", measured=False),
        snap("t+6h", measured=False),
        snap("t+24h", measured=False),
        snap("t+72h"),
        snap("t+7d"),
        snap("t+30d"),
    ]
    result = classify(obs(*snapshots))
    assert result.category == "UNRESOLVED"
    assert result.evidence["missing"] == ["t+1h", "t+6h", "t+24h"]


def test_brak_rekordu_bez_pomiaru_koncowego_daje_unresolved():
    """Bez skutecznego pomiaru t+30d nie wolno orzec M4."""
    snapshots = [
        snap("t+1h", present=False),
        snap("t+6h", present=False),
        snap("t+24h", present=False),
        snap("t+72h", present=False),
        snap("t+7d", present=False),
        snap("t+30d", measured=False),
    ]
    result = classify(obs(*snapshots))
    assert result.category == "UNRESOLVED"
    assert "t+30d" in result.reason


# --------------------------------------------------------------------------- #
# Porównanie kreacji                                                            #
# --------------------------------------------------------------------------- #

def test_niepewne_porownanie_idzie_do_kodera():
    def uncertain(observed, disclosed):
        return None

    result = classify(obs(*full(hashes=(OTHER,))), matcher=uncertain)
    assert result.category == "NEEDS_CODER"


def test_matcher_moze_uznac_przekodowana_kreacje_za_zgodna():
    """Biblioteka przekodowuje materiały, więc docelowy matcher perceptualny
    ma uznawać wariant za zgodny mimo różnego hasha bitowego."""
    def perceptual(observed, disclosed):
        return disclosed.startswith("SYNTHETIC-observed")

    snapshots = full(hashes=("SYNTHETIC-observed-recoded",))
    assert classify(obs(*snapshots), matcher=perceptual).category == "M0"
    assert classify(obs(*snapshots)).category == "M2"


def test_exact_matcher_jest_zachowawczy():
    assert exact_matcher("a", "a") is True
    assert exact_matcher("a", "b") is False


# --------------------------------------------------------------------------- #
# Walidacja wejścia                                                             #
# --------------------------------------------------------------------------- #

def test_kolejnosc_snapshotow_nie_ma_znaczenia():
    uporzadkowane = full()
    odwrocone = list(reversed(uporzadkowane))
    assert classify(obs(*odwrocone)).category == classify(obs(*uporzadkowane)).category


def test_nieznany_checkpoint_odrzucony():
    with pytest.raises(ValueError, match="nieznany checkpoint"):
        Snapshot(checkpoint="t+3h")


def test_brak_pomiaru_nie_moze_niesc_tresci():
    with pytest.raises(ValueError, match="brak pomiaru"):
        Snapshot(checkpoint="t+1h", measured=False, record_present=True)


def test_zduplikowany_checkpoint_odrzucony():
    with pytest.raises(ValueError, match="zduplikowane"):
        classify(obs(snap("t+1h"), snap("t+1h")))


def test_wynik_jest_zawsze_jedna_kategoria():
    dozwolone = {"M0", "M1", "M2", "M3", "M4", "UNRESOLVED", "NEEDS_CODER"}
    for snapshots in (full(), full(present=False), full(hashes=(OTHER,))):
        result = classify(obs(*snapshots))
        assert isinstance(result, Result)
        assert result.category in dozwolone
        assert result.reason

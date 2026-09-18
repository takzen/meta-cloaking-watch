"""Testy magazynu obserwacji, prób i pomiarów.

Każdy test pracuje na katalogu tymczasowym, więc nic nie dotyka prawdziwych
dowodów.

Najważniejsze testy to `test_manifest_wykrywa_podmiane_pliku` oraz
`test_zamkniete_okno_wchodzi_jako_brak_pomiaru`. Pierwszy pilnuje łańcucha
dowodowego, drugi tego, żeby luka w pomiarach nie udawała braku rekordu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.classify import classify
from src.store import Store, iso, parse_iso

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
LIB = "SYNTHETIC-lib-1"
OBSERVED = "SYNTHETIC-observed"


@pytest.fixture()
def store(tmp_path):
    return Store(root=tmp_path)


def add(store, ad_ref="AD-0001", persona="poisoned"):
    return store.add_observation(
        ad_ref=ad_ref,
        library_id=LIB,
        observed_creative_hash=OBSERVED,
        observed_at=T0,
        persona=persona,
    )


def parsed(present=True, hashes=(OBSERVED,), multi=False):
    return {
        "record_present": present,
        "creative_hashes": tuple(hashes) if present else (),
        "multi_version_flag": multi,
        "variant_count": len(hashes) if present else 0,
        "beneficiary_payers_present": False,
    }


# --------------------------------------------------------------------------- #
# Obserwacje                                                                    #
# --------------------------------------------------------------------------- #

def test_obserwacja_zapisuje_sie_i_odczytuje(store):
    add(store)
    records = store.observations()
    assert len(records) == 1
    assert records[0]["library_id"] == LIB
    assert records[0]["observed_at"] == iso(T0)


def test_identyfikatory_nie_sa_reuzywane(store):
    add(store)
    with pytest.raises(ValueError, match="już istnieje"):
        add(store)


def test_kolejny_identyfikator_rosnie(store):
    assert store.next_ad_ref() == "AD-0001"
    add(store, "AD-0001")
    assert store.next_ad_ref() == "AD-0002"
    add(store, "AD-0042")
    assert store.next_ad_ref() == "AD-0043"


def test_czas_bez_strefy_odrzucony(store):
    with pytest.raises(ValueError, match="UTC"):
        store.add_observation(
            ad_ref="AD-0001",
            library_id=LIB,
            observed_creative_hash=OBSERVED,
            observed_at=datetime(2026, 9, 18, 12, 0, 0),
            persona="p",
        )


# --------------------------------------------------------------------------- #
# Próby                                                                         #
# --------------------------------------------------------------------------- #

def test_nieudane_proby_tez_sa_zapisywane(store):
    add(store)
    store.record_attempt(
        ad_ref="AD-0001", checkpoint="t+1h", attempted_at=T0, ok=False, error="613"
    )
    store.record_attempt(
        ad_ref="AD-0001", checkpoint="t+1h", attempted_at=T0, ok=True
    )
    attempts = store.attempts("AD-0001")
    assert len(attempts) == 2
    assert attempts[0].error == "613"
    assert attempts[1].ok is True


def test_proby_sa_filtrowane_po_obserwacji(store):
    add(store, "AD-0001")
    add(store, "AD-0002")
    store.record_attempt(ad_ref="AD-0001", checkpoint="t+1h", attempted_at=T0, ok=True)
    assert len(store.attempts("AD-0001")) == 1
    assert store.attempts("AD-0002") == []


# --------------------------------------------------------------------------- #
# Łańcuch dowodowy                                                              #
# --------------------------------------------------------------------------- #

def test_surowa_odpowiedz_trafia_do_manifestu(store):
    path, digest = store.save_raw("AD-0001", "t+1h", {"data": []})
    assert path.exists()
    assert len(digest) == 64
    assert store.verify_manifest() == []


def test_manifest_wykrywa_podmiane_pliku(store):
    """Regresja krytyczna. Dowód zmieniony po zapisie musi być wykrywalny."""
    path, _ = store.save_raw("AD-0001", "t+1h", {"data": []})
    path.write_text('{"data": [{"id": "podmienione"}]}', encoding="utf-8")
    problems = store.verify_manifest()
    assert len(problems) == 1
    assert "zmieniona treść" in problems[0]


def test_manifest_wykrywa_brak_pliku(store):
    path, _ = store.save_raw("AD-0001", "t+1h", {"data": []})
    path.unlink()
    assert "brak pliku" in store.verify_manifest()[0]


def test_pomiar_wskazuje_konkretny_plik_dowodowy(store):
    add(store)
    _, digest = store.save_raw("AD-0001", "t+1h", {"data": []})
    store.add_snapshot(
        ad_ref="AD-0001",
        checkpoint="t+1h",
        measured_at=T0,
        parsed=parsed(),
        raw_sha256=digest,
    )
    line = next(iter(store._read(store.snapshots_path)))
    assert line["raw_sha256"] == digest


# --------------------------------------------------------------------------- #
# Złożenie do klasyfikacji                                                      #
# --------------------------------------------------------------------------- #

def _measure_all(store, ad_ref="AD-0001", **kwargs):
    for c in ("t+1h", "t+6h", "t+24h", "t+72h", "t+7d", "t+30d"):
        store.add_snapshot(
            ad_ref=ad_ref,
            checkpoint=c,
            measured_at=T0,
            parsed=parsed(**kwargs),
            raw_sha256="0" * 64,
        )


def test_pelna_trajektoria_klasyfikuje_sie_jako_m0(store):
    record = add(store)
    _measure_all(store)
    assert classify(store.build_observation(record)).category == "M0"


def test_zamkniete_okno_wchodzi_jako_brak_pomiaru(store):
    """Regresja krytyczna. Przepadły punkt to brak danych, nie brak rekordu."""
    record = add(store)
    for c in ("t+24h", "t+72h", "t+7d", "t+30d"):
        store.add_snapshot(
            ad_ref="AD-0001",
            checkpoint=c,
            measured_at=T0,
            parsed=parsed(),
            raw_sha256="0" * 64,
        )
    obs = store.build_observation(record, missed=("t+1h", "t+6h"))
    gaps = [s for s in obs.snapshots if not s.measured]
    assert {s.checkpoint for s in gaps} == {"t+1h", "t+6h"}
    assert all(not s.record_present for s in gaps)
    # Dwa braki mieszczą się w progu, więc wynik nadal jest rozstrzygalny.
    assert classify(obs).category == "M0"


def test_pomiary_sa_filtrowane_po_obserwacji(store):
    add(store, "AD-0001")
    record2 = add(store, "AD-0002")
    _measure_all(store, "AD-0001")
    assert store.snapshots("AD-0002") == []
    assert classify(store.build_observation(record2)).category == "UNRESOLVED"


# --------------------------------------------------------------------------- #
# Czas                                                                          #
# --------------------------------------------------------------------------- #

def test_czas_robi_obieg_bez_straty():
    assert parse_iso(iso(T0)) == T0


def test_czas_lokalny_jest_konwertowany_do_utc():
    warsaw = timezone(timedelta(hours=2))
    assert iso(T0.astimezone(warsaw)) == iso(T0)

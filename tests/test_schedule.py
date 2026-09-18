"""Testy harmonogramu odpytań.

Cała logika czasowa jest sterowana argumentem `now`, więc trzydziestodniowe okno
testujemy w milisekundach.

Najważniejszy test to `test_spozniony_pomiar_nie_liczy_sie_jako_ten_punkt`.
Bez niego harmonogram po cichu dopisywałby pomiary, których nie było o czasie,
co jest najprostszą drogą do wyniku nie do obrony.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.schedule import (
    MAX_ATTEMPTS_PER_CHECKPOINT,
    PLAN,
    RETRY_BACKOFF,
    Attempt,
    due,
    is_closed,
    missed,
    next_wakeup,
    pending,
    window,
)

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def at(**kwargs):
    return T0 + timedelta(**kwargs)


def ok(checkpoint, moment):
    return Attempt(checkpoint=checkpoint, attempted_at=moment, ok=True)


def fail(checkpoint, moment, error="613"):
    return Attempt(checkpoint=checkpoint, attempted_at=moment, ok=False, error=error)


# --------------------------------------------------------------------------- #
# Wymagalność                                                                   #
# --------------------------------------------------------------------------- #

def test_nic_nie_jest_wymagalne_natychmiast_po_obserwacji():
    assert due(T0, T0) == []
    assert len(pending(T0, T0)) == len(PLAN)


def test_pierwszy_punkt_staje_sie_wymagalny_po_godzinie():
    assert due(T0, at(minutes=59)) == []
    assert due(T0, at(hours=1)) == ["t+1h"]


def test_udany_pomiar_zdejmuje_punkt_z_kolejki():
    attempts = [ok("t+1h", at(hours=1))]
    assert "t+1h" not in due(T0, at(hours=1, minutes=10), attempts)


def test_kilka_punktow_moze_byc_wymagalnych_naraz():
    """Jeśli proces nie działał przez dobę, łapiemy wszystko, czego okna są otwarte."""
    result = due(T0, at(hours=24, minutes=1))
    assert result == ["t+24h"]


# --------------------------------------------------------------------------- #
# Okna tolerancji                                                               #
# --------------------------------------------------------------------------- #

def test_spozniony_pomiar_nie_liczy_sie_jako_ten_punkt():
    """Regresja krytyczna. Odpytanie dziesięć godzin po obserwacji nie jest
    pomiarem t+1h i harmonogram nie ma prawa go zaplanować."""
    assert "t+1h" not in due(T0, at(hours=10))
    assert "t+1h" in missed(T0, at(hours=10))


def test_okno_jest_domkniete_obustronnie():
    opens, closes = window(T0, "t+1h")
    assert opens == at(hours=1)
    assert closes == at(hours=1, minutes=30)
    assert due(T0, opens) == ["t+1h"]
    assert due(T0, closes) == ["t+1h"]
    assert due(T0, closes + timedelta(seconds=1)) == []


def test_tolerancja_rosnie_z_odstepem():
    tolerances = [spec.tolerance for spec in PLAN]
    assert tolerances == sorted(tolerances)


def test_punkt_po_zamknieciu_okna_jest_trwale_przepadly():
    late = at(days=40)
    assert missed(T0, late) == [spec.name for spec in PLAN]
    assert due(T0, late) == []
    assert is_closed(T0, late)


def test_zmierzone_punkty_nie_sa_przepadle():
    attempts = [ok(spec.name, T0 + spec.offset) for spec in PLAN]
    assert missed(T0, at(days=40), attempts) == []


# --------------------------------------------------------------------------- #
# Ponawianie                                                                    #
# --------------------------------------------------------------------------- #

def test_nieudana_proba_wraca_po_odstepie():
    attempts = [fail("t+1h", at(hours=1))]
    assert due(T0, at(hours=1, minutes=5), attempts) == []
    assert due(T0, at(hours=1) + RETRY_BACKOFF, attempts) == ["t+1h"]


def test_limit_prob_konczy_ponawianie():
    moment = at(hours=1)
    attempts = []
    for i in range(MAX_ATTEMPTS_PER_CHECKPOINT):
        attempts.append(fail("t+1h", moment + i * RETRY_BACKOFF))
    later = moment + (MAX_ATTEMPTS_PER_CHECKPOINT + 1) * RETRY_BACKOFF
    assert "t+1h" not in due(T0, later, attempts)


def test_ponawianie_nie_wychodzi_poza_okno():
    """Nieudana próba tuż przed zamknięciem okna nie generuje próby po nim."""
    attempts = [fail("t+1h", at(hours=1, minutes=25))]
    assert due(T0, at(hours=1, minutes=40), attempts) == []
    assert "t+1h" in missed(T0, at(hours=1, minutes=40), attempts)


# --------------------------------------------------------------------------- #
# Domknięcie trajektorii                                                        #
# --------------------------------------------------------------------------- #

def test_trajektoria_nie_jest_domknieta_dopoki_cos_czeka():
    assert not is_closed(T0, at(hours=2))


def test_trajektoria_domknieta_po_ostatnim_oknie():
    attempts = [ok(spec.name, T0 + spec.offset) for spec in PLAN]
    assert is_closed(T0, at(days=31), attempts)


# --------------------------------------------------------------------------- #
# Planowanie następnego przebiegu                                               #
# --------------------------------------------------------------------------- #

def test_nastepne_wybudzenie_to_otwarcie_najblizszego_okna():
    assert next_wakeup(T0, T0) == at(hours=1)


def test_nastepne_wybudzenie_uwzglednia_ponowienie():
    attempts = [fail("t+1h", at(hours=1))]
    assert next_wakeup(T0, at(hours=1, minutes=1), attempts) == at(hours=1) + RETRY_BACKOFF


def test_brak_wybudzenia_gdy_nie_ma_juz_nic_do_zrobienia():
    attempts = [ok(spec.name, T0 + spec.offset) for spec in PLAN]
    assert next_wakeup(T0, at(days=31), attempts) is None


# --------------------------------------------------------------------------- #
# Walidacja                                                                     #
# --------------------------------------------------------------------------- #

def test_naiwny_czas_jest_odrzucany():
    """Czas bez strefy to najprostsza droga do cichego przesunięcia o dwie godziny."""
    with pytest.raises(ValueError, match="UTC"):
        due(T0, datetime(2026, 9, 18, 13, 0, 0))
    with pytest.raises(ValueError, match="UTC"):
        window(datetime(2026, 9, 18, 12, 0, 0), "t+1h")

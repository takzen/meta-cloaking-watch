"""Testy runnera odpytań.

Pobieranie jest podstawiane atrapą, więc cały przebieg leci bez sieci i bez tokena.

Najważniejszy test to `test_blad_api_nie_zapisuje_pomiaru`. Runner ma prawo
zapisać pomiar tylko wtedy, gdy naprawdę go wykonał. Zapisanie błędu jako
pomiaru bez rekordu byłoby cichym zawyżeniem M4.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.library import creative_fingerprints
from src.recheck import build_query, classify_closed, plan, run
from src.store import Store

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
LIB = "SYNTHETIC-lib-1"
PAGE = "SYNTHETIC-page-1"


@pytest.fixture()
def store(tmp_path):
    s = Store(root=tmp_path)
    s.add_observation(
        ad_ref="AD-0001",
        library_id=LIB,
        page_id=PAGE,
        observed_creative_hash=creative_fingerprints(
            {"ad_creative_bodies": ["Inwestuj teraz"], "ad_creative_link_titles": ["Oferta"]}
        )[0],
        observed_at=T0,
        persona="poisoned",
    )
    return s


def at(**kwargs):
    return T0 + timedelta(**kwargs)


def responder(body):
    def fetch(_params):
        return body
    return fetch


def exploding(exc=RuntimeError("sieć padła")):
    def fetch(_params):
        raise exc
    return fetch


MATCHING = {
    "data": [
        {
            "id": LIB,
            "ad_creative_bodies": ["Inwestuj teraz"],
            "ad_creative_link_titles": ["Oferta"],
        }
    ]
}
EMPTY = {"data": []}
ERROR = {"error": {"type": "OAuthException", "code": 613, "message": "rate limit"}}


# --------------------------------------------------------------------------- #
# Zapytanie                                                                     #
# --------------------------------------------------------------------------- #

def test_zapytanie_idzie_przez_konto_nadawcy(store):
    record = store.observations()[0]
    query = build_query(record, "id")
    assert query["search_page_ids"] == f"[{PAGE}]"
    assert query["ad_active_status"] == "ALL"
    assert query["unmask_removed_content"] == "true"


def test_brak_page_id_jest_bledem_wprost(tmp_path):
    """Bez identyfikatora nadawcy rekordu nie da się odnaleźć. Lepiej głośno
    zawieść przy pierwszej obserwacji niż cicho produkować fałszywe M4."""
    s = Store(root=tmp_path)
    record = s.add_observation(
        ad_ref="AD-0001",
        library_id=LIB,
        observed_creative_hash="SYNTHETIC-x",
        observed_at=T0,
        persona="p",
    )
    with pytest.raises(ValueError, match="page_id"):
        build_query(record, "id")


# --------------------------------------------------------------------------- #
# Przebieg                                                                      #
# --------------------------------------------------------------------------- #

def test_nic_nie_jest_wymagalne_zaraz_po_obserwacji(store):
    assert run(store, responder(MATCHING), now=T0) == {"measured": 0, "failed": 0, "at": T0}


def test_udany_pomiar_zapisuje_snapshot_i_probe(store):
    summary = run(store, responder(MATCHING), now=at(hours=1))
    assert summary["measured"] == 1
    snaps = store.snapshots("AD-0001")
    assert len(snaps) == 1
    assert snaps[0].checkpoint == "t+1h"
    assert snaps[0].record_present is True
    assert store.attempts("AD-0001")[0].ok is True
    assert store.verify_manifest() == []


def test_brak_rekordu_to_udany_pomiar(store):
    run(store, responder(EMPTY), now=at(hours=1))
    snaps = store.snapshots("AD-0001")
    assert len(snaps) == 1
    assert snaps[0].record_present is False


def test_blad_api_nie_zapisuje_pomiaru(store):
    """Regresja krytyczna. Błąd to brak pomiaru, nie brak rekordu."""
    summary = run(store, responder(ERROR), now=at(hours=1))
    assert summary == {"measured": 0, "failed": 1, "at": at(hours=1)}
    assert store.snapshots("AD-0001") == []
    attempts = store.attempts("AD-0001")
    assert attempts[0].ok is False
    assert "613" in attempts[0].error


def test_wyjatek_sieciowy_jest_zapisany_jako_nieudana_proba(store):
    run(store, exploding(), now=at(hours=1))
    assert store.snapshots("AD-0001") == []
    assert "RuntimeError" in store.attempts("AD-0001")[0].error


def test_nieudany_punkt_wraca_do_kolejki(store):
    run(store, responder(ERROR), now=at(hours=1))
    assert plan(store, at(hours=1, minutes=15))[0]["due"] == ["t+1h"]
    run(store, responder(MATCHING), now=at(hours=1, minutes=15))
    assert len(store.snapshots("AD-0001")) == 1


def test_zmierzony_punkt_nie_jest_powtarzany(store):
    run(store, responder(MATCHING), now=at(hours=1))
    run(store, responder(MATCHING), now=at(hours=1, minutes=20))
    assert len(store.snapshots("AD-0001")) == 1


def test_surowa_odpowiedz_jest_zachowana_dla_kazdego_pomiaru(store):
    run(store, responder(MATCHING), now=at(hours=1))
    run(store, responder(EMPTY), now=at(hours=6))
    raws = list(store.raw_dir.glob("AD-0001_*.json"))
    assert len(raws) == 2
    assert store.verify_manifest() == []


# --------------------------------------------------------------------------- #
# Klasyfikacja domkniętych trajektorii                                          #
# --------------------------------------------------------------------------- #

def _walk(store, bodies):
    for checkpoint, body in bodies:
        offset = {
            "t+1h": {"hours": 1},
            "t+6h": {"hours": 6},
            "t+24h": {"hours": 24},
            "t+72h": {"hours": 72},
            "t+7d": {"days": 7},
            "t+30d": {"days": 30},
        }[checkpoint]
        run(store, responder(body), now=at(**offset))


def test_nie_klasyfikujemy_niedomknietej_trajektorii(store):
    _walk(store, [("t+1h", MATCHING)])
    assert classify_closed(store, at(hours=2)) == []


def test_domknieta_trajektoria_dostaje_kategorie(store):
    checkpoints = ["t+1h", "t+6h", "t+24h", "t+72h", "t+7d", "t+30d"]
    _walk(store, [(c, MATCHING) for c in checkpoints])
    rows = classify_closed(store, at(days=31))
    assert len(rows) == 1
    assert rows[0]["category"] == "M0"
    assert rows[0]["persona"] == "poisoned"


def test_brak_rekordu_przez_cale_okno_daje_m4(store):
    checkpoints = ["t+1h", "t+6h", "t+24h", "t+72h", "t+7d", "t+30d"]
    _walk(store, [(c, EMPTY) for c in checkpoints])
    rows = classify_closed(store, at(days=31))
    assert rows[0]["category"] == "M4"


def test_podmiana_kreacji_daje_m3(store):
    swapped = {
        "data": [
            {
                "id": LIB,
                "ad_creative_bodies": ["Damskie jeansy z wysokim stanem"],
                "ad_creative_link_titles": ["Sklep"],
            }
        ]
    }
    _walk(
        store,
        [
            ("t+1h", MATCHING),
            ("t+6h", MATCHING),
            ("t+24h", swapped),
            ("t+72h", swapped),
            ("t+7d", swapped),
            ("t+30d", swapped),
        ],
    )
    rows = classify_closed(store, at(days=31))
    assert rows[0]["category"] == "M3"
    assert rows[0]["evidence"]["between"] == ["t+6h", "t+24h"]

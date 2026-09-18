"""Testy odczytu odpowiedzi Ad Library API.

Payloady syntetyczne, w kształcie zgodnym z tym, co zwraca endpoint ads_archive.

Najważniejszy test to `test_blad_to_nie_brak_rekordu`. Potraktowanie błędu API
jako braku rekordu byłoby najprostszą drogą do zawyżenia M4, czyli do wyniku,
ktorego nie dalo by sie obronic.
"""

from __future__ import annotations

from src.library import (
    creative_fingerprints,
    fingerprint,
    normalize,
    parse_snapshot,
)

LIB_ID = "SYNTHETIC-2229603364244480"


def ad(ad_id=LIB_ID, bodies=("Inwestuj teraz",), titles=("Oferta",), **extra):
    out = {"id": ad_id}
    if bodies is not None:
        out["ad_creative_bodies"] = list(bodies)
    if titles is not None:
        out["ad_creative_link_titles"] = list(titles)
    out.update(extra)
    return out


# --------------------------------------------------------------------------- #
# Normalizacja i odciski                                                        #
# --------------------------------------------------------------------------- #

def test_normalizacja_scala_biale_znaki_i_wielkosc_liter():
    assert normalize("  Inwestuj   TERAZ\n") == "inwestuj teraz"


def test_normalizacja_ujednolica_apostrofy_i_cudzyslowy():
    assert normalize("don’t") == normalize("don't")
    assert normalize("“tekst”") == normalize('"tekst"')


def test_kosmetyczna_roznica_nie_zmienia_odcisku():
    """Bez tego zmiana spacji w Bibliotece udawałaby podmianę kreacji i podbijała M3."""
    assert fingerprint("Inwestuj teraz") == fingerprint("  inwestuj   TERAZ ")


def test_rozna_tresc_daje_rozny_odcisk():
    assert fingerprint("Inwestuj teraz") != fingerprint("Damskie jeansy")


def test_odciski_sa_uporzadkowane_i_bez_powtorzen():
    """Kolejność wariantów w odpowiedzi API nie jest gwarantowana."""
    a = creative_fingerprints(ad(bodies=("A", "B"), titles=("t1", "t2")))
    b = creative_fingerprints(ad(bodies=("B", "A"), titles=("t2", "t1")))
    assert a == tuple(sorted(a))
    assert set(a) == set(b)


def test_warianty_licza_sie_osobno():
    fps = creative_fingerprints(ad(bodies=("Scam", "Jeansy"), titles=("A", "B")))
    assert len(fps) == 2


def test_rekord_bez_tresci_nie_ma_odciskow():
    assert creative_fingerprints({"id": LIB_ID}) == ()


# --------------------------------------------------------------------------- #
# Parsowanie odpowiedzi                                                         #
# --------------------------------------------------------------------------- #

def test_rekord_obecny():
    snap = parse_snapshot({"data": [ad()]}, LIB_ID)
    assert snap["ok"] is True
    assert snap["record_present"] is True
    assert len(snap["creative_hashes"]) == 1
    assert snap["multi_version_flag"] is False


def test_pusta_lista_to_brak_rekordu_ale_udany_pomiar():
    snap = parse_snapshot({"data": []}, LIB_ID)
    assert snap["ok"] is True
    assert snap["record_present"] is False
    assert snap["creative_hashes"] == ()


def test_blad_to_nie_brak_rekordu():
    """Regresja krytyczna. Błąd API nie może wyglądać jak brak rekordu."""
    body = {"error": {"type": "OAuthException", "code": 613, "message": "rate limit"}}
    snap = parse_snapshot(body, LIB_ID)
    assert snap["ok"] is False
    assert snap["record_present"] is False
    assert "613" in snap["error"]


def test_odpowiedz_bez_data_i_bez_error_jest_bledem():
    snap = parse_snapshot({"paging": {}}, LIB_ID)
    assert snap["ok"] is False
    assert snap["record_present"] is False


def test_wiele_wariantow_ustawia_flage():
    snap = parse_snapshot({"data": [ad(bodies=("Scam", "Jeansy"), titles=("A", "B"))]}, LIB_ID)
    assert snap["multi_version_flag"] is True
    assert snap["variant_count"] == 2


def test_wiele_rekordow_dla_tego_samego_id_ustawia_flage():
    snap = parse_snapshot({"data": [ad(bodies=("A",)), ad(bodies=("B",))]}, LIB_ID)
    assert snap["multi_version_flag"] is True


def test_beneficiary_payers_jest_raportowane():
    with_payer = parse_snapshot(
        {"data": [ad(beneficiary_payers=[{"beneficiary": "X", "payer": "Y"}])]}, LIB_ID
    )
    without = parse_snapshot({"data": [ad()]}, LIB_ID)
    assert with_payer["beneficiary_payers_present"] is True
    assert without["beneficiary_payers_present"] is False


def test_odfiltrowuje_rekordy_o_innym_id():
    body = {"data": [ad(ad_id="SYNTHETIC-inny", bodies=("Nie ta",)), ad(bodies=("Ta",))]}
    snap = parse_snapshot(body, LIB_ID)
    assert snap["creative_hashes"] == creative_fingerprints(ad(bodies=("Ta",)))


def test_eu_total_reach_przechodzi_dalej():
    snap = parse_snapshot({"data": [ad(eu_total_reach=12345)]}, LIB_ID)
    assert snap["eu_total_reach"] == 12345

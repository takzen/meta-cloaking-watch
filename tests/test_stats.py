"""Testy statystyki.

Przedział Wilsona sprawdzamy wobec wartości znanych z literatury, żeby test
wykrywał pomyłkę we wzorze, a nie tylko utrwalał to, co akurat zwrócił kod.

Najważniejszy test to `test_klastrowanie_rozszerza_przedzial`. Bez korekty na
klastrowanie przedziały byłyby za wąskie, czyli wynik wyglądałby na pewniejszy,
niż jest. To dokładnie ten rodzaj błędu, który zarzucamy cudzym analizom.
"""

from __future__ import annotations

import pytest

from src.stats import (
    analyse,
    by_category,
    cluster_bootstrap,
    format_table,
    wilson,
)


# --------------------------------------------------------------------------- #
# Wilson                                                                        #
# --------------------------------------------------------------------------- #

def test_wilson_zgadza_sie_z_wartoscia_znana():
    """Dla 0/10 przy 95% górna granica wynosi 0,2775."""
    result = wilson(0, 10)
    assert result.low == pytest.approx(0.0, abs=1e-9)
    assert result.high == pytest.approx(0.2775, abs=5e-4)


def test_wilson_jest_symetryczny_na_odbicie():
    a, b = wilson(3, 10), wilson(7, 10)
    assert a.low == pytest.approx(1 - b.high, abs=1e-12)
    assert a.high == pytest.approx(1 - b.low, abs=1e-12)


def test_wilson_nie_wychodzi_poza_zakres():
    for x, n in ((0, 5), (5, 5), (1, 3), (99, 100)):
        r = wilson(x, n)
        assert 0.0 <= r.low <= r.high <= 1.0


def test_wilson_zawsze_obejmuje_punkt():
    for x, n in ((0, 10), (1, 10), (5, 10), (10, 10), (41, 108)):
        r = wilson(x, n)
        assert r.low <= r.point <= r.high


def test_wieksza_proba_daje_wezszy_przedzial():
    assert wilson(41, 108).width > wilson(410, 1080).width


def test_wyzszy_poziom_ufnosci_daje_szerszy_przedzial():
    assert wilson(41, 108, 0.99).width > wilson(41, 108, 0.95).width


def test_pusta_proba_nie_udaje_wiedzy():
    r = wilson(0, 0)
    assert (r.low, r.high) == (0.0, 1.0)


def test_bledne_wejscie_odrzucone():
    with pytest.raises(ValueError):
        wilson(11, 10)
    with pytest.raises(ValueError):
        wilson(-1, 10)
    with pytest.raises(ValueError, match="ufności"):
        wilson(1, 10, confidence=1.5)


def test_odsetek_zawsze_niesie_granice():
    """Nie ma sciezki, ktora zwraca sama liczbe punktowa."""
    text = str(wilson(41, 108))
    assert "[" in text and ";" in text


# --------------------------------------------------------------------------- #
# Klastrowanie                                                                  #
# --------------------------------------------------------------------------- #

def test_klastrowanie_rozszerza_przedzial():
    """Regresja krytyczna. Persony rozniace sie miedzy soba musza dac przedzial
    szerszy niz ten policzony tak, jakby obserwacje byly niezalezne."""
    clusters = {
        "p1": [True] * 20,
        "p2": [False] * 20,
        "p3": [True] * 20,
        "p4": [False] * 20,
    }
    res = analyse(clusters, iterations=2000)
    assert res.clustered.width > res.naive.width
    assert res.design_effect > 1.0
    assert res.effective_n < res.clustered.n


def test_jednorodne_persony_daja_maly_efekt_schematu():
    clusters = {f"p{i}": [True] * 5 + [False] * 5 for i in range(6)}
    res = analyse(clusters, iterations=2000)
    assert res.design_effect < 2.0


def test_jedna_persona_daje_przedzial_nieinformatywny():
    """Z jednego konta nie da sie wnioskowac o zmiennosci miedzy kontami."""
    res = cluster_bootstrap({"p1": [True, False, True]})
    assert (res.low, res.high) == (0.0, 1.0)
    assert "1 klaster" in res.method


def test_efekt_schematu_nieokreslony_przy_jednym_klastrze():
    res = analyse({"p1": [True, False]})
    assert res.design_effect != res.design_effect  # NaN
    assert res.clusters == 1


def test_efekt_schematu_nieokreslony_przy_zerowym_odsetku():
    """Przy zerze sukcesow wariancja dwumianowa znika, wiec iloraz nie ma sensu.
    Zwrocenie jedynki sugerowaloby pelna efektywna probe, czyli pewnosc,
    ktorej nie mamy."""
    res = analyse({"p1": [False] * 10, "p2": [False] * 10}, iterations=500)
    assert res.design_effect != res.design_effect
    assert res.effective_n != res.effective_n
    assert res.clustered.point == 0.0


def test_punkt_nie_zalezy_od_klastrowania():
    clusters = {"p1": [True, False], "p2": [True, True]}
    res = analyse(clusters, iterations=500)
    assert res.clustered.point == pytest.approx(0.75)
    assert res.naive.point == pytest.approx(0.75)


def test_wynik_jest_odtwarzalny():
    """Bez tego zadna liczba w publikacji nie bylaby weryfikowalna.

    Sprawdzamy wylacznie powtarzalnosc przy tym samym ziarnie. Celowo NIE zadamy,
    zeby inne ziarno dalo inny przedzial: przy kilku klastrach rozklad bootstrapu
    jest dyskretny i ma niewiele mozliwych wartosci, wiec dwa rozne ziarna moga
    zgodnie z prawda trafic w te same percentyle. Test wymagajacy roznicy bylby
    po prostu chwiejny.
    """
    for clusters in (
        {"p1": [True, False, True], "p2": [False, False, True]},
        {f"p{i}": [True] * i + [False] * (5 - i) for i in range(1, 6)},
    ):
        a = cluster_bootstrap(clusters, iterations=500, seed=7)
        b = cluster_bootstrap(clusters, iterations=500, seed=7)
        assert (a.low, a.point, a.high) == (b.low, b.point, b.high)


def test_ziarno_faktycznie_steruje_losowaniem():
    """Przy wiekszej liczbie zroznicowanych klastrow rozklad bootstrapu jest na
    tyle bogaty, ze rozne ziarna daja rozne przedzialy."""
    clusters = {f"p{i}": [i % 2 == 0] * (i + 1) for i in range(12)}
    variants = {
        (cluster_bootstrap(clusters, iterations=2000, seed=s).low,
         cluster_bootstrap(clusters, iterations=2000, seed=s).high)
        for s in (1, 2, 3, 4, 5)
    }
    assert len(variants) > 1


def test_puste_klastry_sa_pomijane():
    res = analyse({"p1": [True, False], "p2": [], "p3": [True, True]}, iterations=500)
    assert res.clusters == 2


# --------------------------------------------------------------------------- #
# Zestawienie kategorii                                                         #
# --------------------------------------------------------------------------- #

def rows():
    return [
        {"ad_ref": "AD-0001", "persona": "poisoned", "category": "M4"},
        {"ad_ref": "AD-0002", "persona": "poisoned", "category": "M1"},
        {"ad_ref": "AD-0003", "persona": "neutral", "category": "M0"},
        {"ad_ref": "AD-0004", "persona": "neutral", "category": "M4"},
    ]


def test_udzialy_kategorii_sumuja_sie_do_jednosci():
    results = by_category(rows(), iterations=500)
    assert sum(r.clustered.point for r in results.values()) == pytest.approx(1.0)


def test_kazda_kategoria_ma_przedzial():
    for res in by_category(rows(), iterations=500).values():
        assert 0.0 <= res.clustered.low <= res.clustered.high <= 1.0


def test_mozna_wymusic_kategorie_nieobecne_w_danych():
    results = by_category(rows(), categories=["M0", "M1", "M2", "M3", "M4"], iterations=500)
    assert results["M2"].clustered.point == 0.0
    assert results["M2"].clustered.n == 4


def test_brak_danych_daje_pusty_wynik():
    assert by_category([]) == {}


def test_tabela_zawiera_przedzialy_i_efekt_schematu():
    text = format_table(by_category(rows(), iterations=500))
    assert "95% CI" in text and "deff" in text and "n_eff" in text
    assert "M4" in text

"""Statystyka wyników: przedziały ufności i korekta na klastrowanie.

Dwie zasady, które ten moduł egzekwuje.

**Żadnego odsetka bez przedziału.** Funkcje zwracają obiekt `Proportion`, który
zawsze niesie granice. Nie ma tu ścieżki, którą da się dostać samą liczbę punktową.

**Reklamy z jednego konta nie są niezależne.** Persona widzi reklamy dobrane przez
ten sam algorytm personalizacji, więc dwie obserwacje z jednego konta niosą mniej
informacji niż dwie z różnych. Przedział policzony tak, jakby były niezależne,
jest za wąski. Dlatego obok przedziału Wilsona liczymy bootstrap po klastrach
i raportujemy efekt schematu (design effect) oraz efektywną liczebność próby.

Bez zewnętrznych zależności. Kwantyl normalny z `statistics.NormalDist`,
losowanie z ustalonym ziarnem, żeby każdy wynik dał się odtworzyć co do cyfry.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import NormalDist
from typing import Iterable, Mapping, Optional, Sequence

DEFAULT_CONFIDENCE = 0.95
DEFAULT_BOOTSTRAP = 10_000
DEFAULT_SEED = 20260918


def _z(confidence: float) -> float:
    if not 0 < confidence < 1:
        raise ValueError("poziom ufności musi leżeć w (0, 1)")
    return NormalDist().inv_cdf(1 - (1 - confidence) / 2)


@dataclass(frozen=True)
class Proportion:
    """Odsetek z przedziałem. Nie istnieje bez granic."""

    successes: int
    n: int
    point: float
    low: float
    high: float
    confidence: float
    method: str

    @property
    def width(self) -> float:
        return self.high - self.low

    def __str__(self) -> str:
        return (
            f"{self.point:.1%} [{self.low:.1%}; {self.high:.1%}] "
            f"({self.successes}/{self.n}, {self.method})"
        )


def wilson(successes: int, n: int, confidence: float = DEFAULT_CONFIDENCE) -> Proportion:
    """Przedział Wilsona dla odsetka.

    Wybrany zamiast klasycznego przedziału Walda, bo Wald przy odsetkach bliskich
    zera i jedynki daje granice poza [0, 1] i przy małych próbach zwyczajnie kłamie.
    Przy n rzędu stu obserwacji, a tyle planujemy, ta różnica jest istotna.
    """
    if n < 0 or successes < 0:
        raise ValueError("liczby nie mogą być ujemne")
    if successes > n:
        raise ValueError("sukcesów nie może być więcej niż obserwacji")
    if n == 0:
        return Proportion(0, 0, float("nan"), 0.0, 1.0, confidence, "wilson")

    z = _z(confidence)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    low, high = max(0.0, center - half), min(1.0, center + half)

    # Przy zerze sukcesów dolna granica wynosi dokładnie zero, a przy komplecie
    # górna dokładnie jeden. Arytmetyka zmiennoprzecinkowa zostawia tam resztkę
    # rzędu 1e-17, przez którą przedział przestaje obejmować własny punkt.
    if successes == 0:
        low = 0.0
    if successes == n:
        high = 1.0

    return Proportion(
        successes=successes,
        n=n,
        point=p,
        low=low,
        high=high,
        confidence=confidence,
        method="wilson",
    )


def cluster_bootstrap(
    clusters: Mapping[str, Sequence[bool]],
    confidence: float = DEFAULT_CONFIDENCE,
    iterations: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> Proportion:
    """Przedział z losowania klastrów ze zwracaniem.

    Losujemy całe persony, nie pojedyncze obserwacje. Dzięki temu przedział
    uwzględnia to, że obserwacje w obrębie persony są do siebie podobne.

    Przy jednej personie przedział jest z definicji nieinformatywny i taki
    właśnie zostaje zwrócony. To nie jest usterka, tylko uczciwe stwierdzenie,
    że z jednego konta nie da się wnioskować o zmienności między kontami.
    """
    keys = [k for k, v in clusters.items() if len(v) > 0]
    if not keys:
        return Proportion(0, 0, float("nan"), 0.0, 1.0, confidence, "cluster-bootstrap")

    flat = [bool(x) for k in keys for x in clusters[k]]
    successes, n = sum(flat), len(flat)
    point = successes / n

    if len(keys) == 1:
        return Proportion(
            successes, n, point, 0.0, 1.0, confidence,
            "cluster-bootstrap (1 klaster, przedział nieinformatywny)",
        )

    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(iterations):
        picked = [clusters[rng.choice(keys)] for _ in keys]
        total = sum(len(c) for c in picked)
        if total == 0:
            continue
        draws.append(sum(sum(bool(x) for x in c) for c in picked) / total)

    draws.sort()
    alpha = (1 - confidence) / 2
    low = draws[max(0, int(alpha * len(draws)) - 1)]
    high = draws[min(len(draws) - 1, int((1 - alpha) * len(draws)))]
    return Proportion(
        successes, n, point, low, high, confidence, "cluster-bootstrap"
    )


@dataclass(frozen=True)
class ClusteredProportion:
    naive: Proportion
    clustered: Proportion
    design_effect: float
    effective_n: float
    clusters: int

    def __str__(self) -> str:
        return (
            f"{self.clustered.point:.1%} "
            f"[{self.clustered.low:.1%}; {self.clustered.high:.1%}]  "
            f"n={self.clustered.n} w {self.clusters} klastrach, "
            f"deff={self.design_effect:.2f}, n_eff={self.effective_n:.0f}"
        )


def analyse(
    clusters: Mapping[str, Sequence[bool]],
    confidence: float = DEFAULT_CONFIDENCE,
    iterations: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> ClusteredProportion:
    """Pełny wynik dla jednej cechy dwuwartościowej.

    `design_effect` to empiryczny stosunek wariancji z bootstrapu po klastrach do
    wariancji dwumianowej. Wartość powyżej jedynki mówi, ile informacji tracimy
    przez to, że obserwacje pochodzą z niewielu kont. `effective_n` to liczebność,
    która dałaby taką samą precyzję przy próbie niezależnej.
    """
    flat = [bool(x) for v in clusters.values() for x in v]
    successes, n = sum(flat), len(flat)
    naive = wilson(successes, n, confidence)
    clustered = cluster_bootstrap(clusters, confidence, iterations, seed)
    used = [k for k, v in clusters.items() if len(v) > 0]

    p = successes / n if n else 0.0
    binomial_var = p * (1 - p) / n if n else 0.0
    z = _z(confidence)
    clustered_var = (clustered.width / (2 * z)) ** 2

    # Efekt schematu jest nieokreślony, gdy klaster jest jeden (nie ma między czym
    # mierzyć zmienności) albo gdy odsetek wynosi dokładnie zero lub jeden
    # (wariancja dwumianowa znika, więc iloraz nie ma sensu). W obu przypadkach
    # zwracamy NaN zamiast jedynki, żeby nie sugerować pełnej efektywnej próby
    # tam, gdzie po prostu nic nie wiemy.
    if len(used) > 1 and binomial_var > 0:
        deff = max(clustered_var / binomial_var, 1.0)
        effective = n / deff
    else:
        deff = float("nan")
        effective = float("nan")
    return ClusteredProportion(naive, clustered, deff, effective, len(used))


def by_category(
    rows: Iterable[Mapping[str, object]],
    categories: Optional[Sequence[str]] = None,
    confidence: float = DEFAULT_CONFIDENCE,
    iterations: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> dict[str, ClusteredProportion]:
    """Udział każdej kategorii, z przedziałami i korektą na klastrowanie.

    Wejście to wiersze z `src.recheck.classify_closed`, czyli słowniki z polami
    `category` i `persona`.
    """
    rows = list(rows)
    if not rows:
        return {}
    present = Counter(str(r["category"]) for r in rows)
    names = list(categories) if categories else sorted(present)

    out: dict[str, ClusteredProportion] = {}
    for name in names:
        grouped: dict[str, list[bool]] = defaultdict(list)
        for row in rows:
            persona = str(row.get("persona") or "brak")
            grouped[persona].append(str(row["category"]) == name)
        out[name] = analyse(grouped, confidence, iterations, seed)
    return out


def format_table(results: Mapping[str, ClusteredProportion]) -> str:
    """Tekstowa tabela wyników, gotowa do wklejenia do raportu."""
    lines = [
        f"{'kategoria':<12} {'udział':>8} {'95% CI':>20} {'n':>6} {'deff':>6} {'n_eff':>7}",
        "-" * 64,
    ]
    for name, res in results.items():
        c = res.clustered
        ci = f"[{c.low:.1%}; {c.high:.1%}]"
        deff = "n/d" if res.design_effect != res.design_effect else f"{res.design_effect:.2f}"
        neff = "n/d" if res.effective_n != res.effective_n else f"{res.effective_n:.0f}"
        lines.append(f"{name:<12} {c.point:>8.1%} {ci:>20} {c.n:>6} {deff:>6} {neff:>7}")
    return "\n".join(lines)

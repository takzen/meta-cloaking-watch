"""Klasyfikacja trajektorii obserwacji do kategorii M0-M4.

Implementacja reguł z CODEBOOK.md, sekcje 3 i 4. Funkcja `classify` jest czysta:
nie sięga do sieci, nie czyta plików, nie zna czasu bieżącego. Dzięki temu cała
logika, od której zależy główny wynik badania, jest w pełni testowalna bez API.

Kolejność pierwszeństwa (CODEBOOK.md sekcja 4):

    1. UNRESOLVED   niekompletna trajektoria
    2. M4           rekord nieobecny we wszystkich pomiarach
    3. M3           zbiór hashy kreacji zmienił się w czasie
    4. M2           obserwowana kreacja nigdy nieudostępniona
    5. M1           rekord pojawił się z opóźnieniem, kreacja zgodna
    6. M0           zgodność od pierwszego pomiaru

Osobno zwracamy NEEDS_CODER, gdy o wyniku decyduje porównanie kreacji, którego
automat nie rozstrzyga (CODEBOOK.md sekcja 5). To nie jest kategoria wynikowa,
tylko skierowanie do człowieka.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

# Zaplanowane momenty pomiaru (PROTOCOL.md sekcja 7).
CHECKPOINTS: tuple[str, ...] = ("t+1h", "t+6h", "t+24h", "t+72h", "t+7d", "t+30d")

FINAL_CHECKPOINT = "t+30d"

# Powyżej tylu brakujących pomiarów trajektoria jest nierozstrzygalna
# (PROTOCOL.md sekcja 10, punkt 3).
MAX_MISSING_MEASUREMENTS = 2


@dataclass(frozen=True)
class Snapshot:
    """Pojedynczy pomiar Biblioteki Reklam dla jednego identyfikatora."""

    checkpoint: str
    measured: bool = True
    """False oznacza brak pomiaru (błąd sieci, błąd API, limit).
    To NIE to samo co brak rekordu i nigdy nie jest tak traktowane."""

    record_present: bool = False
    creative_hashes: tuple[str, ...] = ()
    multi_version_flag: bool = False
    measured_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.checkpoint not in CHECKPOINTS:
            raise ValueError(f"nieznany checkpoint: {self.checkpoint!r}")
        if not self.measured and (self.record_present or self.creative_hashes):
            raise ValueError("brak pomiaru nie może nieść treści rekordu")


@dataclass(frozen=True)
class Observation:
    """Jedna reklama zaobserwowana na urządzeniu, wraz z trajektorią pomiarów."""

    ad_ref: str
    library_id: str
    observed_creative_hash: str
    snapshots: tuple[Snapshot, ...]
    persona: Optional[str] = None
    observed_at: Optional[str] = None


@dataclass(frozen=True)
class Result:
    category: str
    reason: str
    evidence: dict = field(default_factory=dict)


# Wynik porównania kreacji: True zgodna, False niezgodna, None nierozstrzygnięte.
Matcher = Callable[[str, str], Optional[bool]]


def exact_matcher(observed: str, disclosed: str) -> Optional[bool]:
    """Domyślne porównanie: równość hashy.

    Świadomie zachowawcze. Biblioteka przekodowuje materiały, więc hash bitowy
    będzie się różnił nawet dla tej samej kreacji. Docelowo podstawiamy tu hash
    perceptualny z progiem ustalonym na zbiorze kalibracyjnym (CODEBOOK.md
    sekcja 5). Do tego czasu rozbieżność trafia do kodera, a nie do wyniku.
    """
    return observed == disclosed


def _matches_any(
    observed: str, disclosed: Sequence[str], matcher: Matcher
) -> Optional[bool]:
    """True gdy któraś kreacja pasuje, None gdy pojawiła się niepewność."""
    uncertain = False
    for candidate in disclosed:
        verdict = matcher(observed, candidate)
        if verdict is True:
            return True
        if verdict is None:
            uncertain = True
    return None if uncertain else False


def _measured(snapshots: Sequence[Snapshot]) -> list[Snapshot]:
    return [s for s in snapshots if s.measured]


def _ordered(snapshots: Sequence[Snapshot]) -> list[Snapshot]:
    return sorted(snapshots, key=lambda s: CHECKPOINTS.index(s.checkpoint))


def classify(obs: Observation, matcher: Matcher = exact_matcher) -> Result:
    """Przypisuje trajektorii dokładnie jedną kategorię."""
    ordered = _ordered(obs.snapshots)
    seen = {s.checkpoint for s in ordered}
    duplicates = len(ordered) - len(seen)
    if duplicates:
        raise ValueError("zduplikowane checkpointy w trajektorii")

    measured = _measured(ordered)
    missing = [c for c in CHECKPOINTS if c not in {s.checkpoint for s in measured}]
    final = next((s for s in measured if s.checkpoint == FINAL_CHECKPOINT), None)
    with_record = [s for s in measured if s.record_present]

    # 1. UNRESOLVED
    if len(missing) > MAX_MISSING_MEASUREMENTS:
        return Result(
            "UNRESOLVED",
            f"brak {len(missing)} pomiarów, próg to {MAX_MISSING_MEASUREMENTS}",
            {"missing": missing},
        )
    if not with_record and final is None:
        return Result(
            "UNRESOLVED",
            "rekord nieobecny, a brak pomiaru t+30d nie pozwala orzec M4",
            {"missing": missing},
        )
    if not measured:
        return Result("UNRESOLVED", "brak jakiegokolwiek pomiaru", {"missing": missing})

    # 2. M4
    if not with_record:
        return Result(
            "M4",
            "rekord nieobecny we wszystkich pomiarach, łącznie z t+30d",
            {"checked": [s.checkpoint for s in measured]},
        )

    # 3. M3
    swap = _detect_swap(with_record)
    if swap is not None:
        return Result("M3", swap["reason"], swap["evidence"])

    # Porównania kreacji: od tego miejsca wynik zależy od matchera.
    per_snapshot: list[Optional[bool]] = [
        _matches_any(obs.observed_creative_hash, s.creative_hashes, matcher)
        for s in with_record
    ]

    # 4. M2
    if all(v is False for v in per_snapshot):
        return Result(
            "M2",
            "obserwowana kreacja nie występuje wśród udostępnionych w żadnym pomiarze",
            {
                "checkpoints_with_record": [s.checkpoint for s in with_record],
                "multi_version_flag": any(s.multi_version_flag for s in with_record),
            },
        )
    if any(v is None for v in per_snapshot) and not any(v is True for v in per_snapshot):
        return Result(
            "NEEDS_CODER",
            "porównanie kreacji nierozstrzygnięte automatycznie",
            {"checkpoints_with_record": [s.checkpoint for s in with_record]},
        )

    # 5. M1 / 6. M0
    first_measured = measured[0]
    first_match = per_snapshot[0] if with_record[0] is first_measured else None

    absent_at_start = not first_measured.record_present
    if absent_at_start:
        appeared = with_record[0].checkpoint
        return Result(
            "M1",
            f"rekord nieobecny w pierwszym pomiarze, pojawił się w {appeared}",
            {"first_seen": appeared, "first_checked": first_measured.checkpoint},
        )

    if first_match is True:
        return Result(
            "M0",
            "rekord obecny i zgodny od pierwszego pomiaru",
            {"first_checked": first_measured.checkpoint},
        )

    # Rekord obecny od początku, ale pierwsza kreacja nie pasowała, a późniejsza
    # tak, przy niezmienionym zbiorze hashy. To nie jest podmiana ani trwałe
    # maskowanie, więc oddajemy koderowi zamiast zgadywać.
    return Result(
        "NEEDS_CODER",
        "rekord obecny od początku, ale zgodność kreacji zmienna bez zmiany hashy",
        {"per_snapshot": per_snapshot},
    )


def _detect_swap(with_record: Sequence[Snapshot]) -> Optional[dict]:
    """M3: zbiór hashy kreacji zmienia się między kolejnymi pomiarami.

    Rozróżniamy dodanie, usunięcie i podmianę, bo mają różną wymowę. Samo dodanie
    wariantu jest słabszym sygnałem niż usunięcie albo podmiana, ale CODEBOOK.md
    traktuje każdą zmianę jako M3. Szczegół zapisujemy w dowodzie.
    """
    for previous, current in zip(with_record, with_record[1:]):
        before, after = set(previous.creative_hashes), set(current.creative_hashes)
        if before == after:
            continue
        added, removed = sorted(after - before), sorted(before - after)
        if added and removed:
            kind = "podmiana"
        elif removed:
            kind = "usunięcie"
        else:
            kind = "dodanie"
        return {
            "reason": f"zbiór kreacji zmienił się ({kind}) "
            f"między {previous.checkpoint} a {current.checkpoint}",
            "evidence": {
                "kind": kind,
                "between": [previous.checkpoint, current.checkpoint],
                "added": added,
                "removed": removed,
            },
        }
    return None

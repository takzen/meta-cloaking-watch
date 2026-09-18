"""Harmonogram odpytań Biblioteki Reklam.

Czysta logika czasowa: co jest wymagalne teraz, co jeszcze poczeka, a co
bezpowrotnie przepadło. Bez sieci i bez zegara systemowego, `now` zawsze
wchodzi jako argument. Dzięki temu cały harmonogram da się przetestować,
nie czekając trzydziestu dni.

Odpowiada za jedno rozstrzygnięcie, które łatwo przeoczyć, a które decyduje
o wiarygodności wyniku: **pomiar spóźniony poza okno tolerancji nie jest
pomiarem tego punktu**. Odpytanie wykonane dziesięć godzin po obserwacji nie
jest pomiarem t+1h i nie wolno go tak zapisać. Punkt, którego okno się
zamknęło bez udanego odpytania, jest trwale nieudany i wchodzi do trajektorii
jako brak pomiaru, nigdy jako brak rekordu.

Okna tolerancji: PROTOCOL.md sekcja 12, poprawka P-01.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from src.classify import CHECKPOINTS


@dataclass(frozen=True)
class CheckpointSpec:
    name: str
    offset: timedelta
    tolerance: timedelta
    """Połowa szerokości okna. Pomiar jest ważny w przedziale
    [observed_at + offset, observed_at + offset + tolerance]."""


# Tolerancja rośnie wraz z odstępem, bo przy t+30d godzina w jedną stronę nie
# zmienia interpretacji, a przy t+1h zmienia ją zasadniczo.
PLAN: tuple[CheckpointSpec, ...] = (
    CheckpointSpec("t+1h", timedelta(hours=1), timedelta(minutes=30)),
    CheckpointSpec("t+6h", timedelta(hours=6), timedelta(hours=1)),
    CheckpointSpec("t+24h", timedelta(hours=24), timedelta(hours=2)),
    CheckpointSpec("t+72h", timedelta(hours=72), timedelta(hours=6)),
    CheckpointSpec("t+7d", timedelta(days=7), timedelta(hours=12)),
    CheckpointSpec("t+30d", timedelta(days=30), timedelta(hours=24)),
)

BY_NAME = {spec.name: spec for spec in PLAN}

assert tuple(spec.name for spec in PLAN) == CHECKPOINTS, (
    "harmonogram i klasyfikacja muszą znać te same punkty pomiaru"
)

MAX_ATTEMPTS_PER_CHECKPOINT = 5
RETRY_BACKOFF = timedelta(minutes=10)


@dataclass(frozen=True)
class Attempt:
    """Jedna próba odpytania. Nieudana też jest zapisywana, bo liczba prób
    i treść błędów są danymi o niezawodności interfejsu, a nie śmieciem."""

    checkpoint: str
    attempted_at: datetime
    ok: bool
    error: Optional[str] = None


def _require_utc(moment: datetime, label: str) -> None:
    if moment.tzinfo is None:
        raise ValueError(f"{label} musi być świadome strefy czasowej (UTC)")


def window(observed_at: datetime, checkpoint: str) -> tuple[datetime, datetime]:
    """Przedział, w którym pomiar danego punktu jest ważny."""
    _require_utc(observed_at, "observed_at")
    spec = BY_NAME[checkpoint]
    opens = observed_at + spec.offset
    return opens, opens + spec.tolerance


def _attempts_for(attempts: Iterable[Attempt], checkpoint: str) -> list[Attempt]:
    return [a for a in attempts if a.checkpoint == checkpoint]


def succeeded(attempts: Iterable[Attempt], checkpoint: str) -> bool:
    return any(a.ok for a in _attempts_for(attempts, checkpoint))


def due(
    observed_at: datetime,
    now: datetime,
    attempts: Sequence[Attempt] = (),
) -> list[str]:
    """Punkty, które należy odpytać w tej chwili.

    Punkt jest wymagalny, gdy jego okno jest otwarte, nie został jeszcze zmierzony
    skutecznie, nie wyczerpał limitu prób i minął odstęp od ostatniej nieudanej próby.
    """
    _require_utc(now, "now")
    result: list[str] = []
    for spec in PLAN:
        if succeeded(attempts, spec.name):
            continue
        opens, closes = window(observed_at, spec.name)
        if not (opens <= now <= closes):
            continue
        tried = _attempts_for(attempts, spec.name)
        if len(tried) >= MAX_ATTEMPTS_PER_CHECKPOINT:
            continue
        if tried:
            last = max(a.attempted_at for a in tried)
            if now - last < RETRY_BACKOFF:
                continue
        result.append(spec.name)
    return result


def missed(
    observed_at: datetime,
    now: datetime,
    attempts: Sequence[Attempt] = (),
) -> list[str]:
    """Punkty, których okno zamknęło się bez udanego pomiaru.

    Trwale nieodwracalne. Wchodzą do trajektorii jako brak pomiaru, przez co mogą
    doprowadzić do UNRESOLVED, i tak ma być: lepiej stracić obserwację, niż
    dopisać jej pomiar, którego nie było.
    """
    _require_utc(now, "now")
    out: list[str] = []
    for spec in PLAN:
        if succeeded(attempts, spec.name):
            continue
        _, closes = window(observed_at, spec.name)
        if now > closes:
            out.append(spec.name)
    return out


def pending(
    observed_at: datetime,
    now: datetime,
    attempts: Sequence[Attempt] = (),
) -> list[str]:
    """Punkty jeszcze przed otwarciem okna."""
    _require_utc(now, "now")
    return [
        spec.name
        for spec in PLAN
        if not succeeded(attempts, spec.name) and now < window(observed_at, spec.name)[0]
    ]


def is_closed(
    observed_at: datetime,
    now: datetime,
    attempts: Sequence[Attempt] = (),
) -> bool:
    """Czy trajektoria jest domknięta, czyli każdy punkt jest albo zmierzony,
    albo bezpowrotnie przepadł. Dopiero wtedy wolno klasyfikować."""
    return not due(observed_at, now, attempts) and not pending(observed_at, now, attempts)


def next_wakeup(
    observed_at: datetime,
    now: datetime,
    attempts: Sequence[Attempt] = (),
) -> Optional[datetime]:
    """Najbliższy moment, w którym warto wrócić do tej obserwacji."""
    moments: list[datetime] = []
    for name in pending(observed_at, now, attempts):
        moments.append(window(observed_at, name)[0])
    for name in due(observed_at, now, attempts):
        moments.append(now)
    for spec in PLAN:
        if succeeded(attempts, spec.name):
            continue
        tried = _attempts_for(attempts, spec.name)
        if not tried:
            continue
        opens, closes = window(observed_at, spec.name)
        retry_at = max(a.attempted_at for a in tried) + RETRY_BACKOFF
        if now < retry_at <= closes and len(tried) < MAX_ATTEMPTS_PER_CHECKPOINT:
            moments.append(retry_at)
    return min(moments) if moments else None

"""Magazyn obserwacji, prób i pomiarów.

Trzy dzienniki JSONL, wyłącznie dopisywane, plus katalog surowych odpowiedzi API
i manifest ich hashy.

    data/observations.jsonl   jedna linia na zaobserwowaną reklamę
    data/attempts.jsonl       jedna linia na próbę odpytania, także nieudaną
    data/snapshots.jsonl      jedna linia na udany pomiar
    data/library/snapshots/   surowe odpowiedzi API, niezmieniane
    data/manifest.jsonl       sha256 każdego surowego pliku

Każda linia `snapshots.jsonl` niesie `raw_sha256`, czyli wiąże wynik z konkretnym
plikiem dowodowym. Dzięki temu da się sprawdzić, że liczba w publikacji pochodzi
z odpowiedzi API, która nadal leży na dysku i nie została zmieniona.

Nic tu nie nadpisuje i nie kasuje. Poprawka to nowy wpis, nie edycja starego.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from src.classify import Observation, Snapshot
from src.schedule import Attempt

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("czas musi być świadomy strefy (UTC)")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, root: Path | str = DEFAULT_ROOT) -> None:
        self.root = Path(root)
        self.data = self.root / "data"
        self.raw_dir = self.data / "library" / "snapshots"
        self.observations_path = self.data / "observations.jsonl"
        self.attempts_path = self.data / "attempts.jsonl"
        self.snapshots_path = self.data / "snapshots.jsonl"
        self.manifest_path = self.data / "manifest.jsonl"

    # ----------------------------------------------------------------- #
    # Prymitywy                                                          #
    # ----------------------------------------------------------------- #

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _read(self, path: Path) -> Iterator[dict[str, Any]]:
        if not path.exists():
            return iter(())
        def gen() -> Iterator[dict[str, Any]]:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield json.loads(line)
        return gen()

    # ----------------------------------------------------------------- #
    # Obserwacje                                                         #
    # ----------------------------------------------------------------- #

    def add_observation(
        self,
        *,
        ad_ref: str,
        library_id: str,
        observed_creative_hash: str,
        observed_at: datetime,
        persona: str,
        page_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """`page_id` to identyfikator konta nadawcy, odczytywany w aplikacji razem
        z identyfikatorem Biblioteki. Jest potrzebny, bo endpoint `ads_archive`
        nie udostępnia wyszukiwania po identyfikatorze pojedynczej reklamy, więc
        rekord odnajdujemy przez nadawcę i filtrujemy po stronie klienta.
        Szczegóły: PROTOCOL.md poprawka P-02."""
        if any(o["ad_ref"] == ad_ref for o in self.observations()):
            raise ValueError(f"{ad_ref} już istnieje, identyfikatory nie są reużywane")
        record = {
            "ad_ref": ad_ref,
            "library_id": str(library_id),
            "page_id": str(page_id) if page_id is not None else None,
            "observed_creative_hash": observed_creative_hash,
            "observed_at": iso(observed_at),
            "persona": persona,
            "session_id": session_id,
            "logged_at": iso(utc_now()),
        }
        self._append(self.observations_path, record)
        return record

    def observations(self) -> list[dict[str, Any]]:
        return list(self._read(self.observations_path))

    def next_ad_ref(self) -> str:
        used = [o["ad_ref"] for o in self.observations()]
        numbers = [int(r.split("-")[1]) for r in used if r.startswith("AD-")]
        return f"AD-{max(numbers, default=0) + 1:04d}"

    # ----------------------------------------------------------------- #
    # Próby                                                              #
    # ----------------------------------------------------------------- #

    def record_attempt(
        self,
        *,
        ad_ref: str,
        checkpoint: str,
        attempted_at: datetime,
        ok: bool,
        error: Optional[str] = None,
    ) -> None:
        self._append(
            self.attempts_path,
            {
                "ad_ref": ad_ref,
                "checkpoint": checkpoint,
                "attempted_at": iso(attempted_at),
                "ok": ok,
                "error": error,
            },
        )

    def attempts(self, ad_ref: str) -> list[Attempt]:
        return [
            Attempt(
                checkpoint=r["checkpoint"],
                attempted_at=parse_iso(r["attempted_at"]),
                ok=bool(r["ok"]),
                error=r.get("error"),
            )
            for r in self._read(self.attempts_path)
            if r["ad_ref"] == ad_ref
        ]

    # ----------------------------------------------------------------- #
    # Pomiary                                                            #
    # ----------------------------------------------------------------- #

    def save_raw(self, ad_ref: str, checkpoint: str, payload: Any) -> tuple[Path, str]:
        """Zapisuje surową odpowiedź i dopisuje jej hash do manifestu."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        safe = checkpoint.replace("+", "plus")
        path = self.raw_dir / f"{ad_ref}_{safe}_{stamp}.json"
        blob = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(blob)
        digest = hashlib.sha256(blob).hexdigest()
        self._append(
            self.manifest_path,
            {
                "path": str(path.relative_to(self.root)).replace("\\", "/"),
                "sha256": digest,
                "bytes": len(blob),
                "captured_at": iso(utc_now()),
                "ad_ref": ad_ref,
                "checkpoint": checkpoint,
            },
        )
        return path, digest

    def add_snapshot(
        self,
        *,
        ad_ref: str,
        checkpoint: str,
        measured_at: datetime,
        parsed: dict[str, Any],
        raw_sha256: str,
    ) -> None:
        self._append(
            self.snapshots_path,
            {
                "ad_ref": ad_ref,
                "checkpoint": checkpoint,
                "measured_at": iso(measured_at),
                "record_present": bool(parsed["record_present"]),
                "creative_hashes": list(parsed["creative_hashes"]),
                "multi_version_flag": bool(parsed["multi_version_flag"]),
                "variant_count": parsed.get("variant_count"),
                "beneficiary_payers_present": parsed.get("beneficiary_payers_present"),
                "raw_sha256": raw_sha256,
            },
        )

    def snapshots(self, ad_ref: str) -> list[Snapshot]:
        return [
            Snapshot(
                checkpoint=r["checkpoint"],
                measured=True,
                record_present=bool(r["record_present"]),
                creative_hashes=tuple(r["creative_hashes"]),
                multi_version_flag=bool(r["multi_version_flag"]),
                measured_at=r["measured_at"],
            )
            for r in self._read(self.snapshots_path)
            if r["ad_ref"] == ad_ref
        ]

    # ----------------------------------------------------------------- #
    # Złożenie                                                           #
    # ----------------------------------------------------------------- #

    def build_observation(self, record: dict[str, Any], missed: Iterable[str] = ()) -> Observation:
        """Składa obiekt do klasyfikacji.

        Punkty, których okno się zamknęło bez udanego pomiaru, wchodzą jako
        `measured=False`. To jest miejsce, w którym nieudane odpytanie zamienia
        się w jawny brak danych, a nie w brak rekordu.
        """
        ad_ref = record["ad_ref"]
        measured = self.snapshots(ad_ref)
        known = {s.checkpoint for s in measured}
        gaps = tuple(
            Snapshot(checkpoint=c, measured=False)
            for c in missed
            if c not in known
        )
        return Observation(
            ad_ref=ad_ref,
            library_id=record["library_id"],
            observed_creative_hash=record["observed_creative_hash"],
            snapshots=tuple(measured) + gaps,
            persona=record.get("persona"),
            observed_at=record.get("observed_at"),
        )

    def verify_manifest(self) -> list[str]:
        """Sprawdza, czy surowe pliki nadal mają zapisane hashe.

        Zwraca listę problemów. Pusta lista oznacza, że łańcuch dowodowy trzyma.
        """
        problems: list[str] = []
        for entry in self._read(self.manifest_path):
            path = self.root / entry["path"]
            if not path.exists():
                problems.append(f"brak pliku: {entry['path']}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry["sha256"]:
                problems.append(f"zmieniona treść: {entry['path']}")
        return problems

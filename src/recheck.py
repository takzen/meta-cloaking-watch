"""Runner odpytań longitudinalnych.

Spina harmonogram, API i magazyn. Sam nie podejmuje żadnych decyzji
metodologicznych: co jest wymagalne, rozstrzyga `src.schedule`, jak odczytać
odpowiedź, rozstrzyga `src.library`, a co z tego wynika, `src.classify`.

Pobieranie jest wstrzykiwane jako `fetch`, więc cały przebieg da się przetestować
bez sieci i bez tokena.

## Dlaczego odpytujemy przez nadawcę, a nie przez identyfikator reklamy

Endpoint `ads_archive` nie udostępnia filtra po identyfikatorze pojedynczej
reklamy. Filtruje między innymi po `search_page_ids`, czyli po koncie nadawcy.
Dlatego rekord odnajdujemy tak: pobieramy reklamy danego nadawcy i wyszukujemy
wśród nich nasz identyfikator.

Konsekwencja dla zbierania: przy obserwacji trzeba odczytać z aplikacji **dwie**
wartości, identyfikator Biblioteki i identyfikator konta nadawcy. Sam identyfikator
Biblioteki nie wystarcza. Zapisane jako poprawka P-02 w PROTOCOL.md.

Stan ograniczenia: **do weryfikacji w rekonesansie**. Jeżeli okaże się, że
istnieje bezpośrednie odpytanie po identyfikatorze, ścieżka przez nadawcę
pozostanie poprawna, tylko mniej ekonomiczna.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any, Callable, Optional

from src.classify import classify
from src.library import parse_snapshot
from src.schedule import due, missed, next_wakeup
from src.store import Store, parse_iso, utc_now

Fetch = Callable[[dict[str, Any]], dict[str, Any]]

PAGE_SIZE = 200


def build_query(record: dict[str, Any], fields: str) -> dict[str, Any]:
    """Zapytanie odnajdujące rekord danej reklamy przez konto nadawcy."""
    page_id = record.get("page_id")
    if not page_id:
        raise ValueError(
            f"{record['ad_ref']}: brak page_id, a bez niego nie da się odnaleźć "
            "rekordu w Bibliotece (PROTOCOL.md, poprawka P-02)"
        )
    return {
        "search_page_ids": f"[{page_id}]",
        "ad_reached_countries": "['PL']",
        "ad_active_status": "ALL",
        "unmask_removed_content": "true",
        "fields": fields,
        "limit": PAGE_SIZE,
    }


DEFAULT_FIELDS = ",".join(
    (
        "id",
        "ad_creation_time",
        "ad_delivery_start_time",
        "ad_delivery_stop_time",
        "ad_creative_bodies",
        "ad_creative_link_titles",
        "ad_creative_link_descriptions",
        "ad_creative_link_captions",
        "ad_snapshot_url",
        "page_id",
        "page_name",
        "publisher_platforms",
        "eu_total_reach",
        "beneficiary_payers",
    )
)


def plan(store: Store, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Co trzeba zrobić w tej chwili. Nie dotyka sieci."""
    now = now or utc_now()
    out: list[dict[str, Any]] = []
    for record in store.observations():
        observed_at = parse_iso(record["observed_at"])
        attempts = store.attempts(record["ad_ref"])
        out.append(
            {
                "ad_ref": record["ad_ref"],
                "record": record,
                "due": due(observed_at, now, attempts),
                "missed": missed(observed_at, now, attempts),
                "next_wakeup": next_wakeup(observed_at, now, attempts),
            }
        )
    return out


def run(
    store: Store,
    fetch: Fetch,
    now: Optional[datetime] = None,
    fields: str = DEFAULT_FIELDS,
) -> dict[str, Any]:
    """Wykonuje wszystkie wymagalne odpytania i zapisuje wyniki."""
    now = now or utc_now()
    ok_count = failed = 0

    for item in plan(store, now):
        if not item["due"]:
            continue
        record = item["record"]
        for checkpoint in item["due"]:
            try:
                body = fetch(build_query(record, fields))
            except Exception as exc:  # noqa: BLE001
                store.record_attempt(
                    ad_ref=record["ad_ref"],
                    checkpoint=checkpoint,
                    attempted_at=now,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failed += 1
                continue

            parsed = parse_snapshot(body, record["library_id"])
            raw_path, digest = store.save_raw(record["ad_ref"], checkpoint, body)

            if not parsed["ok"]:
                # Błąd API to brak pomiaru. Punkt wróci do kolejki, dopóki jego
                # okno jest otwarte. Nigdy nie zapisujemy tego jako braku rekordu.
                store.record_attempt(
                    ad_ref=record["ad_ref"],
                    checkpoint=checkpoint,
                    attempted_at=now,
                    ok=False,
                    error=parsed["error"],
                )
                failed += 1
                continue

            store.add_snapshot(
                ad_ref=record["ad_ref"],
                checkpoint=checkpoint,
                measured_at=now,
                parsed=parsed,
                raw_sha256=digest,
            )
            store.record_attempt(
                ad_ref=record["ad_ref"],
                checkpoint=checkpoint,
                attempted_at=now,
                ok=True,
            )
            ok_count += 1
            del raw_path

    return {"measured": ok_count, "failed": failed, "at": now}


def classify_closed(store: Store, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Klasyfikuje wyłącznie trajektorie domknięte.

    Klasyfikowanie obserwacji, której okna jeszcze się nie zamknęły, dawałoby
    wynik zmienny w czasie, a więc bezużyteczny.
    """
    now = now or utc_now()
    results: list[dict[str, Any]] = []
    for item in plan(store, now):
        if item["due"] or item["next_wakeup"] is not None:
            continue
        obs = store.build_observation(item["record"], missed=item["missed"])
        result = classify(obs)
        results.append(
            {
                "ad_ref": item["ad_ref"],
                "persona": item["record"].get("persona"),
                "category": result.category,
                "reason": result.reason,
                "evidence": result.evidence,
            }
        )
    return results


def _live_fetch(params: dict[str, Any]) -> dict[str, Any]:
    from src.recon.probe import call  # import leniwy, żeby --dry-run działał bez tokena

    body, _headers, _status = call(params)
    return body


def main() -> None:
    ap = argparse.ArgumentParser(description="Odpytania longitudinalne Biblioteki Reklam")
    ap.add_argument("--dry-run", action="store_true", help="pokaż plan, nie odpytuj")
    ap.add_argument("--classify", action="store_true", help="sklasyfikuj domknięte trajektorie")
    args = ap.parse_args()

    store = Store()
    now = utc_now()

    if args.classify:
        for row in classify_closed(store, now):
            print(f"{row['ad_ref']}  {row['category']:<12} {row['reason']}")
        return

    items = plan(store, now)
    if not items:
        print("Brak obserwacji. Najpierw dopisz je do data/observations.jsonl")
        return

    pending_now = [i for i in items if i["due"]]
    print(f"obserwacji: {len(items)}   wymagalnych teraz: {len(pending_now)}")
    for item in items:
        bits = []
        if item["due"]:
            bits.append("teraz: " + ", ".join(item["due"]))
        if item["missed"]:
            bits.append("przepadło: " + ", ".join(item["missed"]))
        if item["next_wakeup"]:
            bits.append(f"następnie: {item['next_wakeup']:%Y-%m-%d %H:%M}Z")
        print(f"  {item['ad_ref']}  " + "   ".join(bits or ["domknięte"]))

    if args.dry_run:
        return

    summary = run(store, _live_fetch, now)
    print(f"\nzmierzone: {summary['measured']}   nieudane: {summary['failed']}")
    problems = store.verify_manifest()
    print("manifest: OK" if not problems else f"manifest: {len(problems)} problemów")


if __name__ == "__main__":
    main()

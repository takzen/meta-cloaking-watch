"""Faza 1 — rekonesans Meta Ad Library API.

Pięć pytań tak/nie, od których zależy kształt całego projektu (PLAN.md, Faza 1).
To NIE jest kolektor produkcyjny. Każda sonda ma zwrócić werdykt i surowy dowód.

    H1  Czy API daje zasięg per kraj (a nie tylko eu_total_reach)?
    H2  Czy unmask_removed_content=true odsłania treść reklam usuniętych?
    H3  Jakie są faktyczne limity i czy da się odtworzyć "nieznany błąd"?
    H4  Czy API wystawia wszystkie warianty kreacji, czy tylko jeden?
    H5  Czy beneficiary_payers jest realnie wypełniane?

Użycie:
    export META_AD_LIBRARY_TOKEN=...      # albo plik .env
    python -m src.recon.probe h1
    python -m src.recon.probe all

Każde wywołanie zapisuje surową odpowiedź do data/library/recon/ i dopisuje
hash do data/manifest.jsonl. Werdykty NIE są zapisywane automatycznie —
wnioski wpisujemy ręcznie do docs/faza1-wyniki.md po obejrzeniu dowodu.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Wersja Graph API — ZWERYFIKOWAĆ aktualną przed uruchomieniem.
API_VERSION = os.environ.get("META_API_VERSION", "v22.0")
ENDPOINT = f"https://graph.facebook.com/{API_VERSION}/ads_archive"

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data" / "library" / "recon"
MANIFEST = REPO / "data" / "manifest.jsonl"

# Pola, o które w ogóle pytamy. Rozbite na grupy, bo część jest dostępna
# wyłącznie dla reklam emitowanych w UE i przy braku dostępu API zwraca błąd.
FIELDS_BASE = [
    "id",
    "ad_creation_time",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_captions",
    "ad_snapshot_url",
    "page_id",
    "page_name",
    "publisher_platforms",
    "languages",
]
FIELDS_EU = [
    "eu_total_reach",
    "age_country_gender_reach_breakdown",
    "total_reach_by_location",
    "beneficiary_payers",
    "target_locations",
    "target_ages",
    "target_gender",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def token() -> str:
    tok = os.environ.get("META_AD_LIBRARY_TOKEN")
    if not tok:
        env = REPO / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("META_AD_LIBRARY_TOKEN="):
                    tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not tok:
        sys.exit(
            "Brak tokena. Ustaw META_AD_LIBRARY_TOKEN w środowisku albo w pliku .env\n"
            "(.env jest w .gitignore — token NIGDY nie trafia do repo)."
        )
    return tok


def save_raw(name: str, payload: dict | list) -> Path:
    """Zapis surowej odpowiedzi + wpis do manifestu (CLAUDE.md R3, R5)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{name}_{ts}.json"
    blob = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(blob)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "path": str(path.relative_to(REPO)).replace("\\", "/"),
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "bytes": len(blob),
                    "captured_at": now_iso(),
                    "tool": "src/recon/probe.py",
                    "api_version": API_VERSION,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return path


def call(params: dict, *, timeout: int = 60) -> tuple[dict, dict, int]:
    """Zwraca (body, istotne_nagłówki, status). Nie podnosi wyjątku na 4xx/5xx —
    treść błędu jest tu danymi badawczymi, nie awarią."""
    p = dict(params)
    p["access_token"] = token()
    r = requests.get(ENDPOINT, params=p, timeout=timeout)
    headers = {
        k: r.headers.get(k)
        for k in ("x-app-usage", "x-business-use-case-usage", "x-ad-account-usage")
        if r.headers.get(k)
    }
    try:
        body = r.json()
    except ValueError:
        body = {"_non_json_body": r.text[:4000]}
    return body, headers, r.status_code


def _redact(params: dict) -> dict:
    return {k: v for k, v in params.items() if k != "access_token"}


def _probe(name: str, params: dict, *, note: str = "") -> dict:
    print(f"\n=== {name} ===")
    if note:
        print(note)
    print(f"GET {ENDPOINT}")
    print(f"    {json.dumps(_redact(params), ensure_ascii=False)}")
    body, headers, status = call(params)
    record = {
        "probe": name,
        "requested_at": now_iso(),
        "api_version": API_VERSION,
        "params": _redact(params),
        "http_status": status,
        "rate_limit_headers": headers,
        "response": body,
    }
    path = save_raw(name, record)
    print(f"HTTP {status}   -> {path.relative_to(REPO)}")
    if headers:
        print(f"rate-limit: {json.dumps(headers, ensure_ascii=False)}")
    if "error" in body:
        err = body["error"]
        print(
            f"BŁĄD: {err.get('type')} / code={err.get('code')} "
            f"subcode={err.get('error_subcode')}\n      {err.get('message')}"
        )
    return record


# --------------------------------------------------------------------------- #
# H1 — zasięg per kraj                                                          #
# --------------------------------------------------------------------------- #

def h1(args) -> None:
    """Instrat: 'Meta nie umożliwia uzyskania zasięgu wyłącznie dla Polski' (s. 4).
    Sprawdzamy, czy age_country_gender_reach_breakdown / total_reach_by_location
    faktycznie tego nie dają. Jeśli dają — główne źródło błędu w Części 1 znika."""
    rec = _probe(
        "h1_reach_per_country",
        {
            "search_terms": args.terms,
            "ad_reached_countries": "['PL']",
            "ad_active_status": "ALL",
            "fields": ",".join(FIELDS_BASE + FIELDS_EU),
            "limit": 25,
        },
        note="H1: czy da się uzyskać zasięg per kraj zamiast eu_total_reach?",
    )
    data = rec["response"].get("data") or []
    if not data:
        print("\nWERDYKT: brak danych — sprawdź zapytanie i uprawnienia tokena.")
        return

    have_breakdown = sum(1 for a in data if a.get("age_country_gender_reach_breakdown"))
    have_by_loc = sum(1 for a in data if a.get("total_reach_by_location"))
    have_eu = sum(1 for a in data if a.get("eu_total_reach") is not None)

    print(f"\nrekordów: {len(data)}")
    print(f"  eu_total_reach ....................... {have_eu}")
    print(f"  age_country_gender_reach_breakdown ... {have_breakdown}")
    print(f"  total_reach_by_location .............. {have_by_loc}")

    for ad in data:
        br = ad.get("age_country_gender_reach_breakdown")
        if br:
            print("\nprzykład age_country_gender_reach_breakdown:")
            print(json.dumps(br, ensure_ascii=False, indent=2)[:1200])
            break

    if have_breakdown or have_by_loc:
        print(
            "\nWERDYKT H1: TAK — API zwraca rozbicie zasięgu. Sprawdź ręcznie, czy da się "
            "z niego wyciąć samą Polskę. Jeśli tak, zarzut B2 jest naprawialny."
        )
    else:
        print(
            "\nWERDYKT H1: NIE — tylko eu_total_reach. Każde przejście EU->PL wymaga "
            "jawnego modelu z własnym przedziałem (albo rezygnacji z Toru B)."
        )


# --------------------------------------------------------------------------- #
# H2 — treść reklam usuniętych                                                  #
# --------------------------------------------------------------------------- #

def h2(args) -> None:
    """Instrat przyjął 'usunięta przez Metę = oszukańcza' jako ground truth (s. 9),
    bez walidacji. Jeśli unmask_removed_content odsłania treść, walidację da się
    zrobić ręcznie na próbce — bez niczyjej zgody."""
    base = {
        "search_terms": args.terms,
        "ad_reached_countries": "['PL']",
        "ad_active_status": "ALL",
        "fields": ",".join(FIELDS_BASE + ["eu_total_reach"]),
        "limit": 25,
    }
    off = _probe("h2_masked", base, note="H2a: bez unmask_removed_content")
    on = _probe("h2_unmasked", {**base, "unmask_removed_content": "true"},
                note="H2b: z unmask_removed_content=true")

    def bodies(rec):
        return sum(1 for a in (rec["response"].get("data") or [])
                   if a.get("ad_creative_bodies"))

    n_off, n_on = bodies(off), bodies(on)
    print(f"\nrekordów z ad_creative_bodies:  bez flagi {n_off}  |  z flagą {n_on}")
    if "error" in on["response"]:
        print("\nWERDYKT H2: NIE — parametr odrzucony. Klasyfikator Instratu pozostaje "
              "niewalidowalny, więc NIE WOLNO go używać (CLAUDE.md R1/R8).")
    elif n_on > n_off:
        print("\nWERDYKT H2: TAK — flaga odsłania dodatkowe treści. Walidacja "
              "klasyfikatora na próbce N=300-500 jest wykonalna (PLAN.md, Faza 9).")
    else:
        print("\nWERDYKT H2: NIEROZSTRZYGNIĘTE — brak różnicy na tej próbce. "
              "Powtórz na zapytaniu, które na pewno zawiera reklamy usunięte.")


# --------------------------------------------------------------------------- #
# H3 — limity                                                                   #
# --------------------------------------------------------------------------- #

def h3(args) -> None:
    """Instrat: ~50 tys. rekordów/dobę na osobę + niereprodukowalny 'nieznany błąd'
    (s. 6, 8). Mierzymy realną przepustowość i próbujemy odtworzyć błąd."""
    print(f"\n=== h3_rate_limits ===\nCel: {args.max_records} rekordów, strona={args.page_size}")
    params = {
        "search_terms": args.terms,
        "ad_reached_countries": "['PL']",
        "ad_active_status": "ALL",
        "fields": "id,ad_delivery_start_time,page_id",
        "limit": args.page_size,
    }
    total, pages, t0 = 0, 0, time.time()
    log: list[dict] = []
    after = None

    while total < args.max_records:
        p = dict(params)
        if after:
            p["after"] = after
        t1 = time.time()
        body, headers, status = call(p)
        dt = time.time() - t1
        pages += 1

        if "error" in body or status != 200:
            print(f"\nZATRZYMANIE na stronie {pages} po {total} rekordach")
            print(json.dumps(body.get("error", body), ensure_ascii=False, indent=2)[:1500])
            log.append({"page": pages, "status": status, "error": body.get("error"),
                        "elapsed_s": round(dt, 2), "headers": headers})
            break

        got = len(body.get("data") or [])
        total += got
        log.append({"page": pages, "status": status, "records": got,
                    "elapsed_s": round(dt, 2), "headers": headers})
        print(f"  strona {pages:>3}  +{got:<5} razem {total:<7} {dt:5.2f}s  {headers or ''}")

        after = (body.get("paging") or {}).get("cursors", {}).get("after")
        if not after or got == 0:
            print("\nKoniec paginacji.")
            break
        time.sleep(args.sleep)

    elapsed = time.time() - t0
    rate = total / elapsed * 3600 if elapsed else 0
    print(f"\nrekordów: {total}  stron: {pages}  czas: {elapsed:.1f}s")
    print(f"tempo: ~{rate:,.0f} rekordów/h  ->  ~{rate * 24:,.0f}/dobę (ekstrapolacja liniowa)")
    save_raw("h3_rate_limits", {
        "probe": "h3_rate_limits", "requested_at": now_iso(), "api_version": API_VERSION,
        "params": _redact(params), "records": total, "pages": pages,
        "elapsed_s": round(elapsed, 1), "records_per_hour": round(rate), "pages_log": log,
    })
    print("\nWERDYKT H3: porównaj z deklarowanym limitem ~50 tys./dobę. Sprawdź nagłówki "
          "x-app-usage — czy limit jest per token, czy per aplikacja (B13).")


# --------------------------------------------------------------------------- #
# H4 — warianty kreacji                                                         #
# --------------------------------------------------------------------------- #

def h4(args) -> None:
    """Instrat (s. 7): API wystawia tylko pojedyncze warianty reklam, a scamerzy
    chowają wariant oszukańczy wśród neutralnych. To mechanizm M2. Sprawdzamy,
    ile wariantów zwraca API dla wskazanego ad_id."""
    if not args.ad_id:
        sys.exit(
            "H4 wymaga --ad-id.\n"
            "Znajdź w aplikacji reklamę z flagą 'Reklama ma kilka wersji', odczytaj\n"
            "identyfikator Biblioteki ('Dlaczego widzę tę reklamę' -> 'Link do reklamy')\n"
            "i podaj go tutaj. Porównanie UI vs API jest sednem tej sondy."
        )
    rec = _probe(
        "h4_variants",
        {
            "search_terms": "",
            "ad_reached_countries": "['PL']",
            "ad_active_status": "ALL",
            "search_page_ids": "",
            "fields": ",".join(FIELDS_BASE + FIELDS_EU),
            "limit": 100,
            "ad_ids": f"['{args.ad_id}']",
        },
        note=f"H4: ile wariantów API zwraca dla ad_id={args.ad_id}?",
    )
    data = rec["response"].get("data") or []
    print(f"\nrekordów zwróconych dla tego ad_id: {len(data)}")
    for ad in data:
        bodies = ad.get("ad_creative_bodies") or []
        titles = ad.get("ad_creative_link_titles") or []
        print(f"  id={ad.get('id')}  kreacji(body)={len(bodies)}  tytułów={len(titles)}")
    print("\nWERDYKT H4: porównaj z liczbą wariantów widoczną w UI (pager '1 z N'). "
          "Różnica = M2, czyli maskowanie wariantem.")


# --------------------------------------------------------------------------- #
# H5 — beneficiary_payers                                                       #
# --------------------------------------------------------------------------- #

def h5(args) -> None:
    """DSA art. 39 ust. 2 lit. b wymaga wskazania, w czyim imieniu reklama jest
    prezentowana. Mierzymy, jak często pole jest realnie wypełnione."""
    rec = _probe(
        "h5_beneficiary_payers",
        {
            "search_terms": args.terms,
            "ad_reached_countries": "['PL']",
            "ad_active_status": "ALL",
            "fields": "id,page_name,beneficiary_payers",
            "limit": args.page_size,
        },
        note="H5: kompletność beneficiary_payers",
    )
    data = rec["response"].get("data") or []
    if not data:
        print("\nWERDYKT: brak danych.")
        return
    filled = [a for a in data if a.get("beneficiary_payers")]
    pct = 100 * len(filled) / len(data)
    print(f"\nwypełnione: {len(filled)}/{len(data)}  ({pct:.1f}%)")
    if filled:
        print("przykład:", json.dumps(filled[0]["beneficiary_payers"], ensure_ascii=False)[:400])
    print("\nWERDYKT H5: to tylko surowy odsetek na małej próbce. Do publikacji "
          "policzyć przedział Wilsona na próbie losowej (CLAUDE.md R1).")


PROBES = {"h1": h1, "h2": h2, "h3": h3, "h4": h4, "h5": h5}


def main() -> None:
    ap = argparse.ArgumentParser(description="Faza 1 — rekonesans Ad Library API")
    ap.add_argument("probe", choices=[*PROBES, "all"])
    ap.add_argument("--terms", default="inwestycja",
                    help="search_terms; API wymaga niepustego zapytania")
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--max-records", type=int, default=5000,
                    help="H3: górny limit, żeby nie palić budżetu zapytań")
    ap.add_argument("--sleep", type=float, default=0.5, help="H3: przerwa między stronami")
    ap.add_argument("--ad-id", help="H4: identyfikator Biblioteki odczytany z aplikacji")
    args = ap.parse_args()

    print(f"API: {ENDPOINT}")
    print("UWAGA: zweryfikuj, czy to aktualna wersja Graph API (META_API_VERSION).")

    if args.probe == "all":
        for name in ("h1", "h2", "h5"):
            PROBES[name](args)
        print("\nH3 i H4 uruchom osobno — H3 zużywa budżet zapytań, H4 wymaga --ad-id.")
    else:
        PROBES[args.probe](args)


if __name__ == "__main__":
    main()

"""Odczyt odpowiedzi Ad Library API do postaci pomiaru.

Czysta warstwa tłumacząca: surowa odpowiedź API wchodzi, ustrukturyzowany pomiar
wychodzi. Bez sieci, więc testowalna na syntetycznych payloadach.

## Ograniczenie, które trzeba znać

API udostępnia treść kreacji jako **tekst** (`ad_creative_bodies`, tytuły,
podpisy). Materiał graficzny jest dostępny wyłącznie przez `ad_snapshot_url`,
czyli stronę HTML do wyrenderowania, a nie jako plik obrazu.

Dlatego odcisk kreacji liczony tutaj jest odciskiem **warstwy tekstowej**.
Porównanie z obserwacją z telefonu, która jest zrzutem ekranu, wymaga albo
decyzji kodera, albo osobnego kroku renderowania `ad_snapshot_url`. Jest to
zgodne z CODEBOOK.md sekcja 5, gdzie porównanie graniczne trafia do człowieka.

Nie udajemy, że porównujemy obrazy, skoro porównujemy tekst.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Optional

# Pola niosące treść kreacji, w kolejności istotności dla rozpoznania reklamy.
CREATIVE_TEXT_FIELDS = (
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_descriptions",
    "ad_creative_link_captions",
)

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Normalizacja przed hashowaniem.

    Biblioteka bywa niestabilna w drobiazgach (spacje, warianty apostrofów,
    wielkość liter), a my nie chcemy, żeby taka zmiana udawała podmianę kreacji
    i podbijała M3. Normalizujemy agresywnie, bo fałszywe M3 jest kosztowniejsze
    niż przeoczenie kosmetycznej różnicy.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("”", '"').replace("“", '"')
    text = _WHITESPACE.sub(" ", text)
    return text.strip().casefold()


def fingerprint(text: str) -> str:
    """Odcisk pojedynczego wariantu kreacji, w warstwie tekstowej."""
    return "txt:" + hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:32]


def creative_fingerprints(ad: dict[str, Any]) -> tuple[str, ...]:
    """Odciski wszystkich wariantów kreacji w jednym rekordzie.

    Każdy wariant to konkatenacja pól tekstowych o tym samym indeksie. API zwraca
    je jako listy równoległe, ale o różnej długości, więc indeksujemy defensywnie.
    """
    columns = [ad.get(f) or [] for f in CREATIVE_TEXT_FIELDS]
    width = max((len(c) for c in columns), default=0)
    out: list[str] = []
    for i in range(width):
        parts = [str(col[i]) for col in columns if i < len(col) and col[i]]
        if parts:
            out.append(fingerprint("".join(parts)))
    # Kolejność wariantów w odpowiedzi API nie jest gwarantowana, a porównujemy
    # zbiory, więc porządkujemy, żeby sama przestawiona kolejność nie dała M3.
    return tuple(sorted(set(out)))


def parse_snapshot(body: dict[str, Any], library_id: str) -> dict[str, Any]:
    """Odpowiedź API na zapytanie o jeden identyfikator -> pomiar.

    Zwraca `ok=False`, gdy odpowiedź jest błędem. Brak rekordu przy poprawnej
    odpowiedzi to `ok=True, record_present=False` i jest to zupełnie inna
    sytuacja niż błąd. Mieszanie ich zawyżałoby M4.
    """
    if "error" in body:
        err = body["error"] or {}
        return {
            "ok": False,
            "error": f"{err.get('type')}/{err.get('code')}: {err.get('message')}",
            "record_present": False,
            "creative_hashes": (),
            "multi_version_flag": False,
        }

    data = body.get("data")
    if data is None:
        return {
            "ok": False,
            "error": "odpowiedź bez pola data i bez pola error",
            "record_present": False,
            "creative_hashes": (),
            "multi_version_flag": False,
        }

    matching = [ad for ad in data if str(ad.get("id")) == str(library_id)] or list(data)

    if not matching:
        return {
            "ok": True,
            "error": None,
            "record_present": False,
            "creative_hashes": (),
            "multi_version_flag": False,
            "variant_count": 0,
        }

    hashes: list[str] = []
    for ad in matching:
        hashes.extend(creative_fingerprints(ad))
    unique = tuple(sorted(set(hashes)))

    return {
        "ok": True,
        "error": None,
        "record_present": True,
        "creative_hashes": unique,
        # Wiele wariantów rozpoznajemy po liczbie odcisków albo po liczbie
        # rekordów zwróconych dla tego samego identyfikatora.
        "multi_version_flag": len(unique) > 1 or len(matching) > 1,
        "variant_count": len(unique),
        "beneficiary_payers_present": any(ad.get("beneficiary_payers") for ad in matching),
        "page_names": sorted({str(ad.get("page_name")) for ad in matching if ad.get("page_name")}),
        "eu_total_reach": _first(matching, "eu_total_reach"),
    }


def _first(ads: list[dict[str, Any]], key: str) -> Optional[Any]:
    for ad in ads:
        if ad.get(key) is not None:
            return ad[key]
    return None

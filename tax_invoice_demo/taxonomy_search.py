from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TAXONOMY_PATH = Path(__file__).resolve().parent / "data" / "taxonomy_master_v0.1.csv"


@dataclass(frozen=True)
class TaxonomySearchResult:
    official_code: str
    official_name: str
    category_short_name: str
    description: str
    is_summary: bool

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "official_code": self.official_code,
            "official_name": self.official_name,
            "category_short_name": self.category_short_name,
            "description": self.description,
            "is_summary": self.is_summary,
            "label": f"{self.official_name}｜{self.category_short_name}｜{self.official_code}",
        }


def search_taxonomy(query: str, *, limit: int = 12) -> list[TaxonomySearchResult]:
    normalized_query = _normalize(query)
    if not normalized_query:
        return []
    scored: list[tuple[int, TaxonomySearchResult]] = []
    for entry in _load_taxonomy_entries():
        score = _score_entry(entry, normalized_query)
        if score <= 0:
            continue
        if not entry.is_summary:
            score += 8
        scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1].is_summary, item[1].official_code))
    return [entry for _, entry in scored[:limit]]


def _score_entry(entry: TaxonomySearchResult, query: str) -> int:
    code = _normalize(entry.official_code)
    name = _normalize(entry.official_name)
    category = _normalize(entry.category_short_name)
    description = _normalize(entry.description)
    if query == code:
        return 120
    if code.startswith(query):
        return 105
    if name == query:
        return 100
    if category == query:
        return 92
    if name.startswith(query):
        return 88
    if category.startswith(query):
        return 82
    if query in name:
        return 72
    if query in category:
        return 64
    if query in description:
        return 38
    return 0


@lru_cache(maxsize=1)
def _load_taxonomy_entries() -> tuple[TaxonomySearchResult, ...]:
    rows: list[dict[str, str]] = []
    if not TAXONOMY_PATH.exists():
        return tuple()
    with TAXONOMY_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    codes = {(row.get("official_code") or "").strip() for row in rows}
    entries: list[TaxonomySearchResult] = []
    for row in rows:
        code = (row.get("official_code") or "").strip()
        if not code:
            continue
        entries.append(
            TaxonomySearchResult(
                official_code=code,
                official_name=(row.get("official_name") or "").strip(),
                category_short_name=(row.get("category_short_name") or "").strip(),
                description=(row.get("description") or "").strip(),
                is_summary=_has_child_code(code, codes),
            )
        )
    return tuple(entries)


def _has_child_code(code: str, codes: set[str]) -> bool:
    normalized = code.strip()
    if not normalized or set(normalized) <= {"0"}:
        return False
    prefix = normalized.rstrip("0")
    return any(other != normalized and other.startswith(prefix) for other in codes)


def _normalize(value: str) -> str:
    return str(value or "").strip().replace(" ", "").replace("　", "").lower()

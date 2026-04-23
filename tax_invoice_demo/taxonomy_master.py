from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class TaxonomyEntry:
    official_code: str
    official_name: str
    category_short_name: str
    description: str


@dataclass(frozen=True)
class TaxonomySuggestion:
    entry: TaxonomyEntry
    score: int
    matched_on: str


@lru_cache(maxsize=1)
def load_taxonomy_master() -> tuple[TaxonomyEntry, ...]:
    taxonomy_path = locate_taxonomy_file("taxonomy_master_v0.1.csv")
    if taxonomy_path is None:
        return ()

    entries: list[TaxonomyEntry] = []
    with taxonomy_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            official_name = (row.get("official_name") or "").strip()
            if not official_name:
                continue
            entries.append(
                TaxonomyEntry(
                    official_code=(row.get("official_code") or "").strip(),
                    official_name=official_name,
                    category_short_name=(row.get("category_short_name") or "").strip(),
                    description=(row.get("description") or "").strip(),
                )
            )
    return tuple(entries)


def suggest_taxonomy(query: str) -> TaxonomySuggestion | None:
    query_norm = _normalize(query)
    if not query_norm:
        return None

    best: TaxonomySuggestion | None = None
    for entry in load_taxonomy_master():
        official_norm = _normalize(entry.official_name)
        short_norm = _normalize(entry.category_short_name)
        score = 0
        matched_on = ""
        for candidate_score, candidate_match in (
            _score_official_candidate(query_norm, official_norm, "taxonomy_name"),
            _score_short_candidate(query_norm, short_norm, "taxonomy_short"),
        ):
            if candidate_score > score:
                score = candidate_score
                matched_on = candidate_match
        if score <= 0:
            continue
        suggestion = TaxonomySuggestion(entry=entry, score=score, matched_on=matched_on)
        if best is None or suggestion.score > best.score:
            best = suggestion
    return best


def locate_taxonomy_file(filename: str) -> Path | None:
    package_dir = Path(__file__).resolve().parent
    candidates = [
        package_dir / "data" / filename,
        package_dir.parent / "invoice-demo" / "tax_invoice_demo" / "data" / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).upper()


def _score_official_candidate(query_norm: str, target_norm: str, prefix: str) -> tuple[int, str]:
    if not query_norm or not target_norm:
        return 0, ""
    if query_norm == target_norm:
        return 98, f"{prefix}_exact"
    if len(query_norm) >= 2 and query_norm in target_norm:
        return 88, f"{prefix}_contains"
    if len(target_norm) >= 2 and target_norm in query_norm:
        return 74, f"{prefix}_reverse_contains"

    bigrams = _bigrams(query_norm)
    hit_count = sum(1 for token in bigrams if token in target_norm)
    if hit_count:
        return min(64 + hit_count * 6, 78), f"{prefix}_bigram"
    return 0, ""


def _score_short_candidate(query_norm: str, target_norm: str, prefix: str) -> tuple[int, str]:
    if not query_norm or not target_norm:
        return 0, ""
    if query_norm == target_norm:
        return 92, f"{prefix}_exact"
    if len(query_norm) >= 2 and query_norm in target_norm:
        return 82, f"{prefix}_contains"
    if len(target_norm) >= 2 and target_norm in query_norm:
        return 70, f"{prefix}_reverse_contains"
    hit_count = sum(1 for token in _bigrams(query_norm) if token in target_norm)
    if hit_count:
        return min(58 + hit_count * 5, 72), f"{prefix}_bigram"
    return 0, ""


def _bigrams(value: str) -> tuple[str, ...]:
    if len(value) < 2:
        return (value,) if value else ()
    return tuple(value[index : index + 2] for index in range(len(value) - 1))

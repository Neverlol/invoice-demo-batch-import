from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .models import InvoiceLine
from .taxonomy_master import TaxonomyEntry, load_taxonomy_master, suggest_taxonomy


@dataclass(frozen=True)
class CodingLibraryEntry:
    entry_id: str
    raw_alias: str
    normalized_invoice_name: str
    tax_category: str
    tax_treatment_or_rate: str
    decision_basis: str
    confidence: str
    source_case_ids: str

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in re.split(r"[\\/、,，]+", self.raw_alias) if part.strip())


@dataclass(frozen=True)
class CodingSuggestion:
    entry: CodingLibraryEntry
    matched_alias: str
    matched_on: str


def enrich_invoice_lines(
    lines: Iterable[InvoiceLine],
    *,
    raw_text: str = "",
    note: str = "",
    preserve_existing_tax_rate: bool = False,
) -> list[InvoiceLine]:
    enriched: list[InvoiceLine] = []
    context_text = f"{raw_text}\n{note}".strip()
    for line in lines:
        _normalize_inline_tax_category(line)
        suggestion = suggest_line(line, context_text=context_text)
        if suggestion is None:
            taxonomy_suggestion = suggest_taxonomy(line.project_name)
            if taxonomy_suggestion is not None and taxonomy_suggestion.score >= 84:
                if not line.tax_category and taxonomy_suggestion.entry.category_short_name:
                    line.tax_category = taxonomy_suggestion.entry.category_short_name
                if not line.tax_code and taxonomy_suggestion.score >= 95:
                    line.tax_code = taxonomy_suggestion.entry.official_code
                if not line.coding_reference:
                    line.coding_reference = (
                        f"官方分类候选 {taxonomy_suggestion.entry.official_name}"
                        f" / {taxonomy_suggestion.entry.category_short_name}"
                        f" / {taxonomy_suggestion.entry.official_code}"
                    )
            elif line.tax_category and not line.coding_reference:
                line.coding_reference = f"来源表格/材料识别税目大类: {line.tax_category}"
            _apply_taxonomy_code(line)
            enriched.append(line)
            continue

        if _should_replace_project_name(line.project_name, suggestion):
            line.project_name = suggestion.entry.normalized_invoice_name
        if not line.tax_category:
            line.tax_category = suggestion.entry.tax_category
        if _should_replace_tax_rate(
            line.tax_rate,
            suggestion.entry.tax_treatment_or_rate,
            context_text=context_text,
            preserve_existing=preserve_existing_tax_rate,
        ):
            line.tax_rate = suggestion.entry.tax_treatment_or_rate
        if not line.coding_reference:
            rate_hint = f" / {suggestion.entry.tax_treatment_or_rate}" if suggestion.entry.tax_treatment_or_rate else ""
            line.coding_reference = (
                f"命中 {suggestion.matched_alias} -> {suggestion.entry.tax_category}"
                f"{rate_hint}"
            )
        _apply_taxonomy_code(line)
        enriched.append(line)
    return enriched


def suggest_line(line: InvoiceLine, *, context_text: str = "") -> CodingSuggestion | None:
    project_text = line.project_name.strip()
    if not project_text and not context_text.strip():
        return None

    best: tuple[int, CodingLibraryEntry, str, str] | None = None
    for entry in load_formal_coding_library():
        for alias in entry.aliases:
            score, matched_on = _match_alias(alias, project_text, context_text)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, entry, alias, matched_on)
    if best is None:
        return None
    return CodingSuggestion(entry=best[1], matched_alias=best[2], matched_on=best[3])


@lru_cache(maxsize=1)
def load_formal_coding_library() -> tuple[CodingLibraryEntry, ...]:
    library_path = locate_library_file("coding_library_formal_v0.1.csv")
    if library_path is None:
        return ()

    entries: list[CodingLibraryEntry] = []
    with library_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("status") or "").strip() != "ready":
                continue
            entries.append(
                CodingLibraryEntry(
                    entry_id=(row.get("entry_id") or "").strip(),
                    raw_alias=(row.get("raw_alias") or "").strip(),
                    normalized_invoice_name=(row.get("normalized_invoice_name") or "").strip(),
                    tax_category=(row.get("tax_category") or "").strip(),
                    tax_treatment_or_rate=(row.get("tax_treatment_or_rate") or "").strip(),
                    decision_basis=(row.get("decision_basis") or "").strip(),
                    confidence=(row.get("confidence") or "").strip(),
                    source_case_ids=(row.get("source_case_ids") or "").strip(),
                )
            )
    return tuple(entries)


def locate_library_file(filename: str) -> Path | None:
    package_dir = Path(__file__).resolve().parent
    candidates = [
        package_dir / "data" / filename,
        package_dir.parent / "invoice-demo" / "tax_invoice_demo" / "data" / filename,
        package_dir.parent / "案例库原始材料" / filename,
        package_dir.parent / "invoice-demo" / "案例库原始材料" / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _match_alias(alias: str, project_text: str, context_text: str) -> tuple[int, str]:
    alias_norm = _normalize(alias)
    project_norm = _normalize(project_text)
    context_norm = _normalize(context_text)
    if not alias_norm:
        return 0, ""
    if project_norm and project_norm == alias_norm:
        return 100, "project_exact"
    if project_norm and alias_norm in project_norm:
        return 90, "project_contains"
    if project_norm and project_norm in alias_norm and not _looks_like_generic_project_name(project_text):
        return 88, "project_alias_expand"
    if context_norm and alias_norm in context_norm:
        return 55, "context_contains"
    return 0, ""


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).upper()


def _normalize_rate_text(value: str) -> str:
    return value.strip().replace("％", "%")


def _should_replace_project_name(current_name: str, suggestion: CodingSuggestion) -> bool:
    normalized = suggestion.entry.normalized_invoice_name.strip()
    if not normalized:
        return False
    current_norm = _normalize(current_name)
    normalized_norm = _normalize(normalized)
    alias_norm = _normalize(suggestion.matched_alias)
    if not current_norm:
        return True
    if current_norm == normalized_norm:
        return False
    if suggestion.matched_on == "context_contains" and _looks_like_low_confidence_project_name(current_name):
        return True
    return current_norm == alias_norm or alias_norm in current_norm or current_norm in alias_norm


def _should_replace_tax_rate(
    current_rate: str,
    suggested_rate: str,
    *,
    context_text: str = "",
    preserve_existing: bool = False,
) -> bool:
    suggested = _normalize_rate_text(suggested_rate)
    current = _normalize_rate_text(current_rate)
    if not suggested:
        return False
    if not current:
        return True
    if preserve_existing:
        return False
    if current == suggested:
        return False
    if _has_explicit_tax_rate(context_text, current):
        return False
    return current in {"3", "3%", "0.03"}


def _has_explicit_tax_rate(context_text: str, current_rate: str) -> bool:
    if not context_text.strip() or not current_rate.strip():
        return False
    current_norm = _normalize_rate_for_compare(current_rate)
    for matched in re.finditer(r"(?:税率|税率/征收率)[：:\s]*([0-9]+(?:\.[0-9]+)?%?|免税|不征税|免征增值税)", context_text):
        if _normalize_rate_for_compare(matched.group(1)) == current_norm:
            return True
    return False


def _normalize_rate_for_compare(value: str) -> str:
    text = value.strip().replace("％", "%")
    if text in {"免税", "不征税", "免征增值税"}:
        return text
    if text.endswith("%"):
        text = text[:-1]
    try:
        numeric = float(text)
    except ValueError:
        return text
    if numeric <= 1:
        numeric *= 100
    return f"{numeric:.8f}".rstrip("0").rstrip(".")


def _looks_like_low_confidence_project_name(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if re.search(r"[|/=:_]", stripped):
        return True
    if re.search(r"[\u4e00-\u9fff]", stripped):
        return False
    alnum = re.sub(r"[^A-Za-z0-9]+", "", stripped)
    return len(alnum) <= 6


def _looks_like_generic_project_name(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    return compact in {
        "服务费",
        "费用",
        "货款",
        "商品",
        "产品",
        "材料",
        "材料费",
        "货物",
    }


def _normalize_inline_tax_category(line: InvoiceLine) -> None:
    if line.tax_category:
        return
    stripped = line.project_name.strip()
    matched = re.match(r"^\*(?P<category>[^*]+)\*(?P<name>.+)$", stripped)
    if not matched:
        matched = re.match(r"^(?P<category>[\u4e00-\u9fffA-Za-z0-9（）()、]{2,30})\*(?P<name>.+)$", stripped)
    if not matched:
        return
    line.tax_category = matched.group("category").strip()
    line.project_name = matched.group("name").strip()


def _apply_taxonomy_code(line: InvoiceLine) -> None:
    if line.tax_code.strip():
        return
    matched = _resolve_taxonomy_for_line(line)
    if matched is None:
        return
    line.tax_code = matched.official_code
    if not line.tax_category:
        line.tax_category = matched.category_short_name
    if line.coding_reference and matched.official_code not in line.coding_reference:
        line.coding_reference = f"{line.coding_reference}; 官方编码 {matched.official_code}"


def _resolve_taxonomy_for_line(line: InvoiceLine) -> TaxonomyEntry | None:
    preferred_short_name = line.tax_category.strip()
    for query in (preferred_short_name, line.project_name.strip()):
        if not query:
            continue
        matched = _match_taxonomy_by_query(query, preferred_short_name=preferred_short_name)
        if matched is not None:
            return _prefer_leaf_taxonomy_entry(matched)
    return None


def _match_taxonomy_by_query(query: str, *, preferred_short_name: str = "") -> TaxonomyEntry | None:
    normalized_query = _normalize(query)
    normalized_preferred = _normalize(preferred_short_name)
    best: tuple[int, TaxonomyEntry] | None = None
    for entry in load_taxonomy_master():
        official_norm = _normalize(entry.official_name)
        short_norm = _normalize(entry.category_short_name)
        score = 0
        if normalized_preferred and short_norm == normalized_preferred:
            score = 120
        elif normalized_query and official_norm == normalized_query:
            score = 110
        elif normalized_query and short_norm == normalized_query:
            score = 105
        elif normalized_query and normalized_query in official_norm:
            score = 90
        elif normalized_query and normalized_query in short_norm:
            score = 88
        elif normalized_query and short_norm and short_norm in normalized_query:
            score = 70
        if score and (best is None or score > best[0]):
            best = (score, entry)
    return best[1] if best else None


def _prefer_leaf_taxonomy_entry(entry: TaxonomyEntry) -> TaxonomyEntry:
    children = _child_taxonomy_entries(entry.official_code)
    if not children:
        return entry

    other_children = [
        child
        for child in children
        if child.official_name.startswith("其他") or f"其他{entry.official_name}" in child.official_name
    ]
    leaf_candidates = [
        child
        for child in (other_children or children)
        if not _child_taxonomy_entries(child.official_code)
    ]
    if leaf_candidates:
        return sorted(leaf_candidates, key=lambda item: item.official_code)[0]
    return sorted(children, key=lambda item: item.official_code)[0]


def _child_taxonomy_entries(code: str) -> list[TaxonomyEntry]:
    prefix = code.rstrip("0")
    if not prefix or prefix == code:
        return []
    return [
        entry
        for entry in load_taxonomy_master()
        if entry.official_code != code and entry.official_code.startswith(prefix)
    ]

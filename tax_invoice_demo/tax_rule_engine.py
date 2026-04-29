from __future__ import annotations

import csv
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .llm_adapter import LLMAdapterError, get_llm_adapter
from .models import InvoiceLine
from .taxonomy_master import TaxonomyEntry, load_taxonomy_master, suggest_taxonomy

LEARNED_RULES_PATH = Path(__file__).resolve().parent.parent / "output" / "workbench" / "tax_invoice_demo" / "本地即时学习赋码规则.csv"
TENANT_RULES_PATH = Path(__file__).resolve().parent.parent / "output" / "workbench" / "tax_invoice_demo" / "客户同步赋码规则.csv"

LEARNED_RULE_HEADERS = [
    "rule_id",
    "status",
    "raw_alias",
    "normalized_invoice_name",
    "tax_category",
    "tax_code",
    "tax_treatment_or_rate",
    "decision_basis",
    "confidence",
    "source_case_ids",
    "company_name",
    "source_operator",
    "original_project_name",
    "final_project_name",
    "conflict_with_rule_id",
    "created_at",
    "updated_at",
    "hit_count",
]


@dataclass(frozen=True)
class CodingLibraryEntry:
    entry_id: str
    raw_alias: str
    normalized_invoice_name: str
    tax_category: str
    tax_code: str
    tax_treatment_or_rate: str
    decision_basis: str
    confidence: str
    source_case_ids: str
    source_label: str

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in re.split(r"[\\/、,，]+", self.raw_alias) if part.strip())


@dataclass(frozen=True)
class CodingSuggestion:
    entry: CodingLibraryEntry
    matched_alias: str
    matched_on: str


class TaxRuleEngine:
    def enrich_invoice_lines(
        self,
        lines: Iterable[InvoiceLine],
        *,
        raw_text: str = "",
        note: str = "",
        preserve_existing_tax_rate: bool = False,
    ) -> list[InvoiceLine]:
        enriched: list[InvoiceLine] = []
        context_text = f"{raw_text}\n{note}".strip()
        smart_coding_cache: dict[str, TaxonomyEntry | None] = {}
        for line in lines:
            _normalize_inline_tax_category(line)
            suggestion = self.suggest_line(line, context_text=context_text)
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
                if not line.tax_category or not line.tax_code:
                    smart_entry = _suggest_taxonomy_with_llm(line, cache=smart_coding_cache)
                    if smart_entry is not None:
                        if not line.tax_category:
                            line.tax_category = smart_entry.category_short_name
                        if not line.tax_code:
                            line.tax_code = smart_entry.official_code
                        line.coding_reference = (
                            "智能推荐，需人工复核: "
                            f"大类 {smart_entry.category_short_name} / "
                            f"细分 {smart_entry.official_name} / "
                            f"编码 {smart_entry.official_code}"
                        )
                enriched.append(line)
                continue

            if _should_replace_project_name(line.project_name, suggestion):
                line.project_name = suggestion.entry.normalized_invoice_name
            if not line.tax_category:
                line.tax_category = suggestion.entry.tax_category
            if not line.tax_code and suggestion.entry.tax_code:
                line.tax_code = suggestion.entry.tax_code
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
                    f"命中 {suggestion.entry.source_label}: {suggestion.matched_alias} -> {suggestion.entry.tax_category}"
                    f"{rate_hint}"
                )
            _apply_taxonomy_code(line)
            enriched.append(line)
        return enriched

    def suggest_line(self, line: InvoiceLine, *, context_text: str = "") -> CodingSuggestion | None:
        project_text = line.project_name.strip()
        if not project_text and not context_text.strip():
            return None

        best: tuple[int, CodingLibraryEntry, str, str] | None = None
        for entry in (*load_tenant_coding_library(), *load_learned_coding_library(), *load_formal_coding_library()):
            for alias in entry.aliases:
                score, matched_on = _match_alias(alias, project_text, context_text)
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, entry, alias, matched_on)
        if best is None:
            return None
        return CodingSuggestion(entry=best[1], matched_alias=best[2], matched_on=best[3])


def get_tax_rule_engine() -> TaxRuleEngine:
    return _TAX_RULE_ENGINE


_TAX_RULE_ENGINE = TaxRuleEngine()


def enrich_invoice_lines(
    lines: Iterable[InvoiceLine],
    *,
    raw_text: str = "",
    note: str = "",
    preserve_existing_tax_rate: bool = False,
) -> list[InvoiceLine]:
    return _TAX_RULE_ENGINE.enrich_invoice_lines(
        lines,
        raw_text=raw_text,
        note=note,
        preserve_existing_tax_rate=preserve_existing_tax_rate,
    )


def suggest_line(line: InvoiceLine, *, context_text: str = "") -> CodingSuggestion | None:
    return _TAX_RULE_ENGINE.suggest_line(line, context_text=context_text)


def write_learned_rules_from_manual_update(
    *,
    before_lines: list[InvoiceLine],
    after_lines: list[InvoiceLine],
    case_id: str,
    draft_id: str,
    company_name: str,
) -> list[dict[str, str]]:
    """Persist user-confirmed coding fixes for immediate reuse on this client."""
    learned_rows = _read_learned_rule_rows()
    changed_rows: list[dict[str, str]] = []
    existing_keys = {_learned_row_key(row): row for row in learned_rows}
    now = datetime.now().isoformat(timespec="seconds")

    for index, after in enumerate(after_lines):
        before = before_lines[index] if index < len(before_lines) else InvoiceLine(project_name="", amount_with_tax="")
        if not _is_learning_candidate(before, after):
            continue
        aliases = _learned_aliases(before, after)
        if not aliases:
            continue
        primary_alias = aliases[0]
        row = {
            "rule_id": _learned_rule_id(primary_alias, after),
            "status": "ready",
            "raw_alias": "、".join(aliases),
            "normalized_invoice_name": after.project_name.strip(),
            "tax_category": after.tax_category.strip(),
            "tax_code": after.tax_code.strip(),
            "tax_treatment_or_rate": after.normalized_tax_rate(),
            "decision_basis": "本地即时学习: 草稿复核人工修正后保存",
            "confidence": "local_confirmed",
            "source_case_ids": f"learned:{case_id}:{draft_id}:{index + 1}",
            "company_name": company_name.strip(),
            "source_operator": _current_operator(),
            "original_project_name": before.project_name.strip(),
            "final_project_name": after.project_name.strip(),
            "conflict_with_rule_id": "",
            "created_at": now,
            "updated_at": now,
            "hit_count": "0",
        }
        key = _learned_row_key(row)
        existing = existing_keys.get(key)
        if existing:
            existing["raw_alias"] = _merge_alias_text(existing.get("raw_alias", ""), row["raw_alias"])
            existing["normalized_invoice_name"] = row["normalized_invoice_name"] or existing.get("normalized_invoice_name", "")
            existing["tax_category"] = row["tax_category"] or existing.get("tax_category", "")
            existing["tax_code"] = row["tax_code"] or existing.get("tax_code", "")
            existing["tax_treatment_or_rate"] = row["tax_treatment_or_rate"] or existing.get("tax_treatment_or_rate", "")
            existing["decision_basis"] = row["decision_basis"]
            existing["confidence"] = row["confidence"]
            existing["source_case_ids"] = _append_source_case(existing.get("source_case_ids", ""), row["source_case_ids"])
            existing["company_name"] = row["company_name"] or existing.get("company_name", "")
            existing["source_operator"] = row["source_operator"] or existing.get("source_operator", "")
            existing["original_project_name"] = _merge_alias_text(
                existing.get("original_project_name", ""),
                row["original_project_name"],
            )
            existing["final_project_name"] = row["final_project_name"] or existing.get("final_project_name", "")
            existing["updated_at"] = now
            changed_rows.append(existing.copy())
        else:
            conflict = _find_conflicting_learned_row(learned_rows, row)
            if conflict is not None:
                row["status"] = "pending_review"
                row["rule_id"] = f"conflict-{row['rule_id'].removeprefix('learned-')}"
                row["conflict_with_rule_id"] = conflict.get("rule_id", "")
                row["decision_basis"] = (
                    "本地即时学习冲突待审核: "
                    f"已有规则 {conflict.get('rule_id', '')} -> "
                    f"{conflict.get('tax_category', '')}/{conflict.get('tax_code', '')}/{conflict.get('tax_treatment_or_rate', '')}; "
                    f"本次修正 -> {row['tax_category']}/{row['tax_code']}/{row['tax_treatment_or_rate']}"
                )
                learned_rows.append(row)
                changed_rows.append(row.copy())
                continue
            learned_rows.append(row)
            existing_keys[key] = row
            changed_rows.append(row.copy())

    if changed_rows:
        _write_learned_rule_rows(learned_rows)
        load_learned_coding_library.cache_clear()
    return changed_rows


def write_tenant_rule_package(rules: list[dict], *, package_id: str = "", version: str = "", tenant: str = "") -> int:
    """Replace the client-side reviewed rule package downloaded from sync center."""
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, str]] = []
    for index, rule in enumerate(rules, start=1):
        raw_alias = str(rule.get("raw_alias") or rule.get("关键词") or "").strip()
        tax_category = str(rule.get("tax_category") or rule.get("标准分类") or "").strip()
        if not raw_alias or not tax_category:
            continue
        tax_code = str(rule.get("tax_code") or rule.get("税收编码") or "").strip()
        tax_rate = str(rule.get("tax_treatment_or_rate") or rule.get("税率") or "").strip()
        normalized_name = str(
            rule.get("normalized_invoice_name")
            or rule.get("开票名称")
            or rule.get("项目名称")
            or raw_alias.split("、")[0]
        ).strip()
        rows.append(
            {
                "rule_id": str(rule.get("rule_id") or rule.get("entry_id") or f"tenant-{index:04d}"),
                "status": str(rule.get("status") or "ready").strip() or "ready",
                "raw_alias": raw_alias,
                "normalized_invoice_name": normalized_name,
                "tax_category": tax_category,
                "tax_code": tax_code,
                "tax_treatment_or_rate": tax_rate,
                "decision_basis": str(rule.get("decision_basis") or f"云端审核规则包 {version or package_id}").strip(),
                "confidence": str(rule.get("confidence") or "tenant_reviewed").strip(),
                "source_case_ids": str(rule.get("source_case_ids") or f"rule_package:{tenant}:{version}:{package_id}").strip(),
                "company_name": str(rule.get("company_name") or tenant).strip(),
                "created_at": str(rule.get("created_at") or now).strip(),
                "updated_at": now,
                "hit_count": str(rule.get("hit_count") or "0").strip(),
            }
        )
    _write_rule_rows(TENANT_RULES_PATH, rows)
    load_tenant_coding_library.cache_clear()
    return len(rows)


@lru_cache(maxsize=1)
def load_tenant_coding_library() -> tuple[CodingLibraryEntry, ...]:
    return _rows_to_coding_entries(_read_rule_rows(TENANT_RULES_PATH), fallback_prefix="tenant")


@lru_cache(maxsize=1)
def load_learned_coding_library() -> tuple[CodingLibraryEntry, ...]:
    return _rows_to_coding_entries(_read_learned_rule_rows(), fallback_prefix="learned")


def _rows_to_coding_entries(rows: list[dict[str, str]], *, fallback_prefix: str) -> tuple[CodingLibraryEntry, ...]:
    entries: list[CodingLibraryEntry] = []
    source_label = {
        "tenant": "客户规则",
        "learned": "本地即时规则",
        "formal": "内置基础规则",
    }.get(fallback_prefix, fallback_prefix)
    for row in rows:
        if (row.get("status") or "").strip() != "ready":
            continue
        raw_alias = (row.get("raw_alias") or "").strip()
        tax_category = (row.get("tax_category") or "").strip()
        tax_code = (row.get("tax_code") or "").strip()
        tax_rate = (row.get("tax_treatment_or_rate") or "").strip()
        if not raw_alias or not tax_category:
            continue
        entries.append(
            CodingLibraryEntry(
                entry_id=(row.get("rule_id") or "").strip(),
                raw_alias=raw_alias,
                normalized_invoice_name=(row.get("normalized_invoice_name") or "").strip(),
                tax_category=tax_category,
                tax_code=tax_code,
                tax_treatment_or_rate=tax_rate,
                decision_basis=(row.get("decision_basis") or "").strip(),
                confidence=(row.get("confidence") or "").strip(),
                source_case_ids=(row.get("source_case_ids") or "").strip() or f"{fallback_prefix}:{tax_code}",
                source_label=source_label,
            )
        )
    return tuple(entries)


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
                    tax_code="",
                    tax_treatment_or_rate=(row.get("tax_treatment_or_rate") or "").strip(),
                    decision_basis=(row.get("decision_basis") or "").strip(),
                    confidence=(row.get("confidence") or "").strip(),
                    source_case_ids=(row.get("source_case_ids") or "").strip(),
                    source_label="内置基础规则",
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


def _bigrams(value: str) -> tuple[str, ...]:
    if len(value) < 2:
        return (value,) if value else ()
    return tuple(value[index : index + 2] for index in range(len(value) - 1))


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


def _is_learning_candidate(before: InvoiceLine, after: InvoiceLine) -> bool:
    if not after.project_name.strip():
        return False
    if not after.tax_category.strip():
        return False
    changed_fields = (
        before.tax_category.strip() != after.tax_category.strip(),
        before.tax_code.strip() != after.tax_code.strip(),
        before.normalized_tax_rate() != after.normalized_tax_rate(),
        before.project_name.strip() != after.project_name.strip(),
    )
    if not any(changed_fields):
        return False
    if not after.tax_code.strip() and after.tax_category.strip() == before.tax_category.strip():
        return False
    return True


def _learned_aliases(before: InvoiceLine, after: InvoiceLine) -> list[str]:
    aliases: list[str] = []
    for value in (before.project_name, after.project_name):
        stripped = value.strip()
        if not stripped:
            continue
        if _normalize(stripped) in {_normalize(alias) for alias in aliases}:
            continue
        aliases.append(stripped)
    return aliases


def _learned_rule_id(alias: str, line: InvoiceLine) -> str:
    basis = "|".join(
        [
            _normalize(alias),
            _normalize(line.tax_category),
            _normalize(line.tax_code),
            _normalize_rate_for_compare(line.normalized_tax_rate()),
        ]
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"learned-{digest}"


def _learned_row_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        _normalize(row.get("raw_alias", "").split("、")[0]),
        _normalize(row.get("tax_category", "")),
        _normalize(row.get("tax_code", "")),
        _normalize_rate_for_compare(row.get("tax_treatment_or_rate", "")),
    )


def _find_conflicting_learned_row(rows: list[dict[str, str]], candidate: dict[str, str]) -> dict[str, str] | None:
    candidate_aliases = {_normalize(alias) for alias in re.split(r"[、,，/\\]+", candidate.get("raw_alias", "")) if alias.strip()}
    if not candidate_aliases:
        return None
    candidate_target = _learned_target_key(candidate)
    for row in rows:
        if (row.get("status") or "").strip() == "pending_review":
            continue
        row_aliases = {_normalize(alias) for alias in re.split(r"[、,，/\\]+", row.get("raw_alias", "")) if alias.strip()}
        if not candidate_aliases.intersection(row_aliases):
            continue
        if _learned_target_key(row) != candidate_target:
            return row
    return None


def _learned_target_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        _normalize(row.get("tax_category", "")),
        _normalize(row.get("tax_code", "")),
        _normalize_rate_for_compare(row.get("tax_treatment_or_rate", "")),
    )


def _read_learned_rule_rows() -> list[dict[str, str]]:
    return _read_rule_rows(LEARNED_RULES_PATH)


def _read_rule_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_learned_rule_rows(rows: list[dict[str, str]]) -> None:
    _write_rule_rows(LEARNED_RULES_PATH, rows)


def _write_rule_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEARNED_RULE_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in LEARNED_RULE_HEADERS})


def _merge_alias_text(existing: str, new_value: str) -> str:
    aliases: list[str] = []
    for value in re.split(r"[、,，/\\]+", f"{existing}、{new_value}"):
        stripped = value.strip()
        if not stripped:
            continue
        if _normalize(stripped) in {_normalize(alias) for alias in aliases}:
            continue
        aliases.append(stripped)
    return "、".join(aliases)


def _append_source_case(existing: str, new_value: str) -> str:
    parts = [part.strip() for part in existing.split(";") if part.strip()]
    if new_value and new_value not in parts:
        parts.append(new_value)
    return ";".join(parts)


def _current_operator() -> str:
    return (
        os.environ.get("TAX_INVOICE_OPERATOR")
        or os.environ.get("USERNAME")
        or os.environ.get("USER")
        or ""
    ).strip()


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


def _suggest_taxonomy_with_llm(line: InvoiceLine, *, cache: dict[str, TaxonomyEntry | None]) -> TaxonomyEntry | None:
    key = _smart_coding_cache_key(line)
    if key in cache:
        return cache[key]
    cache[key] = None
    candidates = _llm_taxonomy_candidates(line)
    if not candidates:
        return None
    adapter = get_llm_adapter()
    if not adapter.is_enabled:
        return None
    candidate_text = [
        "｜".join(
            part
            for part in [
                entry.official_name,
                entry.category_short_name,
                entry.official_code,
                entry.description[:120],
            ]
            if part
        )
        for entry in candidates
    ]
    item_name = " / ".join(part for part in [line.project_name.strip(), line.specification.strip()] if part)
    try:
        response = adapter.classify_tax_code(item_name, candidate_text)
    except LLMAdapterError:
        return None
    entry = _resolve_llm_taxonomy_choice(response.parsed_json, candidates)
    cache[key] = entry
    return entry


def _smart_coding_cache_key(line: InvoiceLine) -> str:
    # 同一商品/服务项目通常应共用同一个税收分类；规格不同不应触发多次 LLM 调用。
    return _normalize(line.project_name)


def _llm_taxonomy_candidates(line: InvoiceLine, *, limit: int = 60) -> list[TaxonomyEntry]:
    text = f"{line.project_name} {line.specification} {line.tax_category}".strip()
    normalized = _normalize(text)
    scored: list[tuple[int, TaxonomyEntry]] = []
    medical_hint = bool(re.search(r"医|药|械|针|电极|耗材|一次性|导管|探头|诊断|治疗|手术|卫生", text))
    for entry in load_taxonomy_master():
        official = _normalize(entry.official_name)
        short = _normalize(entry.category_short_name)
        description = _normalize(entry.description)
        score = 0
        if normalized:
            for token in _bigrams(normalized):
                if token and token in official:
                    score += 10
                elif token and token in short:
                    score += 7
                elif token and token in description:
                    score += 3
        if medical_hint and (
            entry.official_code.startswith("109024")
            or "医" in entry.official_name
            or "医疗" in entry.description
            or "医用" in entry.description
        ):
            score += 32
        if "针" in text and re.search(r"注射|穿刺|针", entry.official_name + entry.description):
            score += 45
        if "电极" in text and re.search(r"电极|高频|诊断|治疗|监护", entry.official_name + entry.description):
            score += 28
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1].official_code))
    seen: set[str] = set()
    candidates: list[TaxonomyEntry] = []
    for _, entry in scored:
        if entry.official_code in seen:
            continue
        seen.add(entry.official_code)
        candidates.append(entry)
        if len(candidates) >= limit:
            break
    return candidates


def _resolve_llm_taxonomy_choice(payload: dict, candidates: list[TaxonomyEntry]) -> TaxonomyEntry | None:
    code_map = {entry.official_code: entry for entry in candidates}
    name_map = {_normalize(entry.official_name): entry for entry in candidates}
    candidate_items = payload.get("候选分类") if isinstance(payload, dict) else None
    if isinstance(candidate_items, list):
        for item in candidate_items:
            if not isinstance(item, dict):
                continue
            code = str(item.get("税收编码") or item.get("编码") or "").strip()
            if code in code_map:
                return code_map[code]
            name = _normalize(str(item.get("分类名称") or item.get("细分品类") or item.get("大类") or ""))
            if name in name_map:
                return name_map[name]
    code = str(payload.get("税收编码") or payload.get("编码") or "").strip() if isinstance(payload, dict) else ""
    if code in code_map:
        return code_map[code]
    return None


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

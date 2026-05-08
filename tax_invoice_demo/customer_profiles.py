from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from dataclasses import dataclass

from . import ledger
from .models import BuyerInfo, InvoiceLine


PROFILE_CACHE_PATH = Path(__file__).resolve().parent.parent / "output" / "workbench" / "tax_invoice_demo" / "客户档案缓存.json"


@dataclass(frozen=True)
class BuyerHistoryMatch:
    buyer: BuyerInfo
    matched_alias: str
    confidence: str


@dataclass(frozen=True)
class LineHistoryMatch:
    project_name: str
    tax_category: str
    tax_code: str
    tax_rate: str
    specification: str
    unit: str
    quantity: str
    matched_source: str
    confidence: str


def resolve_buyer_from_history(raw_text: str, *, company_name: str = "") -> BuyerHistoryMatch | None:
    compact_text = _normalize(raw_text)
    if not compact_text:
        return None
    candidates: list[tuple[int, str, str, str]] = []
    for row in _profile_rows(company_name=company_name):
        buyer_name = row.get("buyer_name", "").strip()
        buyer_tax_id = row.get("buyer_tax_id", "").strip()
        if not buyer_name or not buyer_tax_id:
            continue
        for alias in _buyer_aliases(buyer_name):
            normalized_alias = _normalize(alias)
            if not normalized_alias or normalized_alias not in compact_text:
                continue
            score = len(normalized_alias)
            if buyer_name in raw_text:
                score += 20
            candidates.append((score, alias, buyer_name, buyer_tax_id))
    if not candidates:
        return None
    score, alias, buyer_name, buyer_tax_id = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    return BuyerHistoryMatch(
        buyer=BuyerInfo(name=buyer_name, tax_id=buyer_tax_id),
        matched_alias=alias,
        confidence="high" if score >= 6 else "medium",
    )


def seller_default_line_profile(company_name: str) -> LineHistoryMatch | None:
    # 销售主体级常用项目必须绑定明确销售方；不能在销售方为空时从所有客户档案里取“全局最高频”，
    # 否则餐饮平台截图可能被其它主体的商品/服务项目污染。
    if not company_name.strip():
        return None
    rows = _profile_rows(company_name=company_name)
    if not rows:
        return None
    return _dominant_line_profile(rows)



def apply_line_history_hints(
    lines: list[InvoiceLine],
    *,
    company_name: str,
    buyer: BuyerInfo,
    raw_text: str = "",
) -> list[InvoiceLine]:
    if not lines or not company_name.strip():
        return lines
    # 销售主体级历史项目本身就有价值：很多现场材料先能确认销售方和项目，
    # 但图片/截图里的购买方可能遮挡。此时也允许按销售主体项目档案做“推荐”，
    # 但所有历史推荐都保留“需人工复核”的说明，不做最终开具承诺。
    buyer_filter = buyer if buyer.name.strip() or buyer.tax_id.strip() else None
    rows = _profile_rows(company_name=company_name, buyer=buyer_filter)
    if not rows:
        return lines
    return [_apply_single_line_history_hint(line, rows, raw_text=raw_text) for line in lines]


def _apply_single_line_history_hint(line: InvoiceLine, rows: list[dict[str, str]], *, raw_text: str) -> InvoiceLine:
    exact_match, conflict_note = _exact_line_history_match(line, rows, raw_text=raw_text)
    if conflict_note:
        explicit_rate = _explicit_tax_rate_from_context(raw_text)
        if explicit_rate:
            line.tax_rate = explicit_rate
        _append_history_reference(line, conflict_note)
        return line
    if exact_match is not None:
        return _apply_history_match_to_line(line, exact_match, exact=True)

    # 弱简称（服务/服务费/代理等）再用相似历史兜底；明确项目名如果没有精确历史，
    # 不让历史高频项目直接覆盖，避免“本行商品”被其它上下文项目污染。
    if not _is_weak_project_name(line.project_name):
        return line
    match = _match_line_history(line, rows, raw_text=raw_text)
    if match is None:
        return line
    return _apply_history_match_to_line(line, match, exact=False)


def _apply_history_match_to_line(line: InvoiceLine, match: LineHistoryMatch, *, exact: bool) -> InvoiceLine:
    if exact and not line.tax_code:
        line.project_name = match.project_name or line.project_name
    elif not exact:
        line.project_name = match.project_name or line.project_name
    if not line.tax_category and match.tax_category:
        line.tax_category = match.tax_category
    if not line.tax_code and match.tax_code:
        line.tax_code = match.tax_code
    elif line.tax_code and match.tax_code and line.tax_code != match.tax_code:
        _append_history_reference(
            line,
            "历史开票档案提示，需人工复核: "
            f"{match.matched_source} 历史编码为 {match.tax_code}，当前编码为 {line.tax_code}",
        )
        return line
    if (not line.tax_rate or line.tax_rate == "3%") and match.tax_rate:
        line.tax_rate = match.tax_rate
    if not line.specification and match.specification and not _is_weak_project_name(match.specification):
        line.specification = match.specification
    if not line.unit and match.unit:
        line.unit = match.unit
    if not line.quantity:
        line.quantity = line.quantity or "1"
    prefix = "历史开票档案精确匹配" if exact else "历史开票档案推荐"
    _append_history_reference(
        line,
        f"{prefix}，需人工复核: {match.matched_source} -> "
        f"{match.tax_category or '未记录大类'} / {match.tax_code or '未记录编码'}"
        f" / {match.tax_rate or '未记录税率'}",
    )
    return line


def _exact_line_history_match(line: InvoiceLine, rows: list[dict[str, str]], *, raw_text: str = "") -> tuple[LineHistoryMatch | None, str]:
    query = line.project_name.strip()
    normalized_query = _normalize(query)
    if not normalized_query:
        return None, ""
    exact_rows = [row for row in rows if _normalize(row.get("project_name", "")) == normalized_query and row.get("tax_code", "").strip()]
    if not exact_rows:
        return None, ""

    # 编码/品类和税率是两件事：编码只决定品类，税率由本次客户要求或历史习惯决定。
    code_variants: Counter[tuple[str, str, str, str, str]] = Counter()
    latest_row_by_code_key: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    rows_by_code_key: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = {}
    for row in exact_rows:
        key = (
            row.get("project_name", "").strip(),
            row.get("tax_category", "").strip(),
            row.get("tax_code", "").strip(),
            row.get("unit", "").strip(),
            row.get("specification", "").strip(),
        )
        weight = _safe_int(row.get("line_count", ""), default=1)
        code_variants[key] += max(weight, 1)
        latest_row_by_code_key[key] = row
        rows_by_code_key.setdefault(key, []).append(row)
    if not code_variants:
        return None, ""

    selected_key, count = code_variants.most_common(1)[0]
    selected_rows = rows_by_code_key.get(selected_key) or exact_rows
    row = latest_row_by_code_key[selected_key]

    explicit_rate = _explicit_tax_rate_from_context(raw_text)
    historical_rate, historical_rate_note = _recommended_history_tax_rate(selected_rows)
    tax_rate = explicit_rate or historical_rate

    source_notes: list[str] = []
    if explicit_rate:
        source_notes.append(f"本次材料明确 {explicit_rate}")
    elif historical_rate_note:
        source_notes.append(historical_rate_note)

    code_samples = sorted({f"{key[1] or '未记录大类'} / {key[2] or '未记录编码'}" for key in code_variants})
    if len(code_samples) > 1:
        source_notes.append(f"历史同项目还出现过 {'；'.join(code_samples[:4])}，本次按最高频品类推荐")

    matched_source = selected_key[0] or query
    if source_notes:
        matched_source = f"{matched_source}（{'；'.join(source_notes)}）"

    return LineHistoryMatch(
        project_name=selected_key[0] or query,
        tax_category=selected_key[1],
        tax_code=selected_key[2],
        tax_rate=tax_rate,
        specification=selected_key[4],
        unit=selected_key[3] or "项",
        quantity=row.get("quantity", "").strip() or "1",
        matched_source=matched_source,
        confidence="high" if count >= 2 and len(code_samples) == 1 else "medium",
    ), ""


def _recommended_history_tax_rate(rows: list[dict[str, str]]) -> tuple[str, str]:
    rate_counts: Counter[str] = Counter()
    original_by_normalized: dict[str, str] = {}
    for row in rows:
        normalized = _normalize_tax_rate(row.get("tax_rate", ""))
        if not normalized:
            continue
        weight = _safe_int(row.get("line_count", ""), default=1)
        rate_counts[normalized] += max(weight, 1)
        original_by_normalized[normalized] = row.get("tax_rate", "").strip() or normalized
    if not rate_counts:
        return "", ""
    selected, _count = rate_counts.most_common(1)[0]
    if len(rate_counts) <= 1:
        return original_by_normalized.get(selected, selected), ""
    samples = "；".join(f"{rate}" for rate, _ in rate_counts.most_common(4))
    return original_by_normalized.get(selected, selected), f"客户本次未写税率，按历史最高频 {selected} 推荐；历史税率还出现过 {samples}"


def _explicit_tax_rate_from_context(text: str) -> str:
    compact = _normalize(text)
    if not compact:
        return ""
    if re.search(r"(免税|免征增值税|不征税)", compact):
        return "免税"
    rate_patterns = [
        ("1%", r"(一个点|1个点|一%|1%|税率1|按1点|开1点)"),
        ("3%", r"(三个点|3个点|三%|3%|税率3|按3点|开3点)"),
        ("6%", r"(六个点|6个点|六%|6%|税率6|按6点|开6点)"),
        ("9%", r"(九个点|9个点|九%|9%|税率9|按9点|开9点)"),
        ("13%", r"(十三个点|13个点|十三%|13%|税率13|按13点|开13点)"),
    ]
    for normalized, pattern in rate_patterns:
        if re.search(pattern, compact):
            return normalized
    return ""


def _normalize_tax_rate(value: str) -> str:
    compact = str(value or "").strip().replace("％", "%")
    if compact in {"免税", "免征增值税", "不征税"}:
        return "免税" if compact != "不征税" else compact
    if not compact:
        return ""
    if compact.endswith("%"):
        return compact
    try:
        number = float(compact)
    except ValueError:
        return compact
    if number <= 1:
        number *= 100
    text = str(int(number)) if number.is_integer() else str(number).rstrip("0").rstrip(".")
    return f"{text}%"


def _append_history_reference(line: InvoiceLine, reference: str) -> None:
    if not reference:
        return
    if not line.coding_reference:
        line.coding_reference = reference
    elif reference not in line.coding_reference:
        line.coding_reference = f"{line.coding_reference}; {reference}"


def _safe_int(value: str, *, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except ValueError:
        return default


def _dominant_line_profile(rows: list[dict[str, str]]) -> LineHistoryMatch | None:
    scored: Counter[tuple[str, str, str, str, str]] = Counter()
    latest_row_by_key: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in rows:
        if not _row_is_positive_normal_invoice(row):
            continue
        project_name = row.get("project_name", "").strip()
        if not project_name:
            continue
        key = (
            project_name,
            row.get("tax_category", "").strip(),
            row.get("tax_code", "").strip(),
            row.get("tax_rate", "").strip(),
            row.get("unit", "").strip(),
        )
        scored[key] += 1
        latest_row_by_key[key] = row
    if not scored:
        return None
    key, _count = scored.most_common(1)[0]
    row = latest_row_by_key[key]
    return LineHistoryMatch(
        project_name=key[0],
        tax_category=key[1],
        tax_code=key[2],
        tax_rate=key[3] or "1%",
        specification=row.get("specification", "").strip(),
        unit=key[4] or "项",
        quantity="1",
        matched_source=key[0],
        confidence="high" if _count >= 2 else "medium",
    )



def _match_line_history(line: InvoiceLine, rows: list[dict[str, str]], *, raw_text: str) -> LineHistoryMatch | None:
    query = line.project_name.strip()
    normalized_query = _normalize(query)
    normalized_text = _normalize(raw_text)
    scored: list[tuple[int, dict[str, str]]] = []
    frequency = Counter(row.get("project_name", "").strip() for row in rows if row.get("project_name", "").strip())
    for index, row in enumerate(rows):
        project_name = row.get("project_name", "").strip()
        if not project_name:
            continue
        normalized_project = _normalize(project_name)
        score = 0
        if normalized_query and normalized_query == normalized_project:
            score += 120
        elif normalized_query and normalized_query in normalized_project:
            score += 90
        elif normalized_project and normalized_project in normalized_query:
            score += 75
        else:
            score += _token_overlap_score(normalized_query, normalized_project)
        if _is_weak_project_name(query):
            score += 15
        for token in _business_tokens(project_name):
            if token and token in normalized_text:
                score += 18
        if row.get("tax_code", "").strip():
            score += 12
        if row.get("tax_category", "").strip():
            score += 6
        score += min(frequency[project_name], 8)
        score += min(index, 20) // 5
        if score >= 36:
            scored.append((score, row))
    if not scored:
        return None
    _, row = sorted(scored, key=lambda item: item[0], reverse=True)[0]
    return LineHistoryMatch(
        project_name=row.get("project_name", "").strip(),
        tax_category=row.get("tax_category", "").strip(),
        tax_code=row.get("tax_code", "").strip(),
        tax_rate=row.get("tax_rate", "").strip(),
        specification=row.get("specification", "").strip(),
        unit=row.get("unit", "").strip(),
        quantity=row.get("quantity", "").strip(),
        matched_source=row.get("project_name", "").strip(),
        confidence="medium",
    )


def _row_is_positive_normal_invoice(row: dict[str, str]) -> bool:
    amount = row.get("amount_with_tax", "").strip().replace(",", "")
    if amount.startswith("-"):
        return False
    note = " ".join(str(row.get(key, "")) for key in ["note", "coding_reference", "invoice_status", "invoice_direction"])
    if any(marker in note for marker in ["红字", "红冲", "作废"]):
        return False
    return True



def profile_cache_summary() -> dict[str, str | int]:
    sellers = _load_cached_sellers()
    return {
        "cache_path": str(PROFILE_CACHE_PATH),
        "exists": PROFILE_CACHE_PATH.exists(),
        "seller_count": len(sellers),
        "buyer_count": sum(len(seller.get("buyer_profiles") or []) for seller in sellers if isinstance(seller, dict)),
        "project_profile_count": sum(len(seller.get("project_profiles") or []) for seller in sellers if isinstance(seller, dict)),
    }


def profile_counts_for_seller(seller_query: str) -> dict[str, str | int | bool]:
    query = seller_query.strip()
    for seller in _load_cached_sellers():
        if not isinstance(seller, dict):
            continue
        seller_name = str(seller.get("seller_name") or "").strip()
        seller_tax_id = str(seller.get("seller_tax_id") or "").strip()
        if query and query not in {seller_name, seller_tax_id}:
            continue
        return {
            "matched": True,
            "seller_name": seller_name,
            "seller_tax_id": seller_tax_id,
            "buyer_count": len(seller.get("buyer_profiles") or []),
            "project_profile_count": len(seller.get("project_profiles") or []),
        }
    return {
        "matched": False,
        "seller_name": "",
        "seller_tax_id": "",
        "buyer_count": 0,
        "project_profile_count": 0,
    }


def _profile_rows(*, company_name: str = "", buyer: BuyerInfo | None = None) -> list[dict[str, str]]:
    cached_rows = _cached_profile_rows(company_name=company_name, buyer=buyer)
    ledger_rows = _ledger_profile_rows(company_name=company_name, buyer=buyer)
    return cached_rows + ledger_rows


def _ledger_profile_rows(*, company_name: str = "", buyer: BuyerInfo | None = None) -> list[dict[str, str]]:
    path = ledger.LEDGER_CSV_PATH
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return []
    seller = company_name.strip()
    buyer_name = (buyer.name if buyer else "").strip()
    buyer_tax_id = (buyer.tax_id if buyer else "").strip()
    filtered = []
    for row in rows:
        if seller and row.get("company_name", "").strip() != seller:
            continue
        if buyer_tax_id and row.get("buyer_tax_id", "").strip() and row.get("buyer_tax_id", "").strip() != buyer_tax_id:
            continue
        if not buyer_tax_id and buyer_name and row.get("buyer_name", "").strip() != buyer_name:
            continue
        filtered.append(row)
    return filtered


def _cached_profile_rows(*, company_name: str = "", buyer: BuyerInfo | None = None) -> list[dict[str, str]]:
    seller_query = company_name.strip()
    buyer_name = (buyer.name if buyer else "").strip()
    buyer_tax_id = (buyer.tax_id if buyer else "").strip()
    rows: list[dict[str, str]] = []
    for seller in _load_cached_sellers():
        if not isinstance(seller, dict):
            continue
        seller_name = str(seller.get("seller_name") or "").strip()
        seller_tax_id = str(seller.get("seller_tax_id") or "").strip()
        if seller_query and seller_query not in {seller_name, seller_tax_id}:
            continue
        buyer_profiles = [item for item in (seller.get("buyer_profiles") or []) if isinstance(item, dict)]
        matching_buyers = _matching_cached_buyers(buyer_profiles, buyer_name=buyer_name, buyer_tax_id=buyer_tax_id)
        if buyer is not None and (buyer_name or buyer_tax_id) and matching_buyers:
            target_buyers = matching_buyers
        elif buyer is not None and (buyer_name or buyer_tax_id):
            # 云端 P0 的 seller_project_profiles 是销售主体级常用项目，不一定绑定购买方。
            # 找不到 buyer 专属项目时仍允许使用销售主体常用项目兜底。
            target_buyers = [{"buyer_name": buyer_name, "buyer_tax_id": buyer_tax_id}]
        else:
            target_buyers = buyer_profiles or [{"buyer_name": "", "buyer_tax_id": ""}]

        for line in seller.get("project_profiles") or []:
            if not isinstance(line, dict):
                continue
            for buyer_profile in target_buyers:
                rows.append(_cached_line_to_row(seller_name, seller_tax_id, buyer_profile, line))

        # 让 resolve_buyer_from_history 即使没有项目行也能从云端 buyer_profiles 召回购买方。
        for buyer_profile in matching_buyers if buyer is not None else buyer_profiles:
            rows.append(_cached_line_to_row(seller_name, seller_tax_id, buyer_profile, {}))
    return rows


def _load_cached_sellers() -> list[dict]:
    if not PROFILE_CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(PROFILE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _matching_cached_buyers(buyers: list[dict], *, buyer_name: str, buyer_tax_id: str) -> list[dict]:
    if not buyer_name and not buyer_tax_id:
        return buyers
    matched = []
    for buyer in buyers:
        cached_name = str(buyer.get("buyer_name") or "").strip()
        cached_tax_id = str(buyer.get("buyer_tax_id") or "").strip()
        if buyer_tax_id and cached_tax_id and cached_tax_id == buyer_tax_id:
            matched.append(buyer)
        elif not buyer_tax_id and buyer_name and cached_name == buyer_name:
            matched.append(buyer)
    return matched


def _cached_line_to_row(seller_name: str, seller_tax_id: str, buyer_profile: dict, line: dict) -> dict[str, str]:
    return {
        "company_name": seller_name,
        "seller_tax_id": seller_tax_id,
        "buyer_name": str(buyer_profile.get("buyer_name") or "").strip(),
        "buyer_tax_id": str(buyer_profile.get("buyer_tax_id") or "").strip(),
        "project_name": str(line.get("project_name") or "").strip(),
        "tax_category": str(line.get("tax_category") or "").strip(),
        "tax_code": str(line.get("tax_code") or "").strip(),
        "tax_rate": str(line.get("tax_rate") or line.get("tax_treatment_or_rate") or "").strip(),
        "unit": str(line.get("unit") or "项").strip(),
        "specification": str(line.get("specification") or "").strip(),
        "quantity": str(line.get("quantity") or "1").strip(),
        "amount_with_tax": str(line.get("amount_with_tax") or "").strip(),
        "line_count": str(line.get("line_count") or "1").strip(),
        "full_item_name": str(line.get("full_item_name") or "").strip(),
        "invoice_status": "正常",
        "invoice_direction": "蓝字",
        "coding_reference": "云端客户档案推荐，需人工复核",
    }


def _buyer_aliases(buyer_name: str) -> set[str]:
    aliases = {buyer_name}
    core = re.sub(r"(有限责任公司|股份有限公司|有限公司|公司)$", "", buyer_name).strip()
    if core:
        aliases.add(core)
        if len(core) >= 4:
            aliases.add(core[:4])
        # 保留核心名后 2-4 字，支持“恒润那个公司”这类口语简称；过短简称不参与匹配。
        for size in (4, 3, 2):
            if len(core) >= size:
                aliases.add(core[-size:])
    return {alias for alias in aliases if len(alias) >= 2}


def _business_tokens(value: str) -> set[str]:
    compact = _normalize(value)
    tokens = set(re.findall(r"[A-Za-z0-9]+", compact))
    for token in ["代理", "记账", "税务", "申报", "咨询", "服务", "财税", "办公", "纸", "文件", "医疗", "器械"]:
        if token in compact:
            tokens.add(token)
    return tokens


def _token_overlap_score(left: str, right: str) -> int:
    if not left or not right:
        return 0
    left_tokens = _business_tokens(left)
    right_tokens = _business_tokens(right)
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens) * 22


def _is_weak_project_name(value: str) -> bool:
    compact = _normalize(value)
    return compact in {"代理服务", "服务", "服务费", "业务服务", "代理", "财税服务"}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("，", ",").upper()

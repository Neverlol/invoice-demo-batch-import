from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .llm_adapter import (
    LLMAdapterError,
    get_llm_adapter,
    validate_extract_invoice_payload,
)
from .models import BuyerInfo, InvoiceLine
from .parsing import extract_buyer_info_from_text, extract_invoice_lines_from_text


@dataclass
class ExtractionOutcome:
    buyer: BuyerInfo
    lines: list[InvoiceLine]
    parse_source: str
    strategy: str = "rules_only"
    llm_provider: str = ""
    extracted_note: str = ""
    warnings: list[str] = field(default_factory=list)
    llm_metrics: list[dict] = field(default_factory=list)


@dataclass
class RuleReviewAssessment:
    reasons: list[str] = field(default_factory=list)
    confidence: str = "high"
    should_call_llm: bool = False

    @property
    def should_try_llm(self) -> bool:
        return self.should_call_llm


def compose_parse_source(raw_text: str, document_text: str, ocr_text: str) -> str:
    return "\n\n".join(part for part in [raw_text.strip(), document_text.strip(), ocr_text.strip()] if part)


def extract_invoice_structured_data(
    *,
    raw_text: str,
    note: str,
    document_text: str,
    ocr_text: str,
    image_paths: list[Path] | None = None,
    force_llm_review: bool = False,
    material_tags: list[str] | None = None,
) -> ExtractionOutcome:
    parse_source = compose_parse_source(raw_text, document_text, ocr_text)
    buyer = extract_buyer_info_from_text(parse_source)
    lines = extract_invoice_lines_from_text(parse_source)
    lines = _apply_current_amount_from_user_text(
        lines,
        raw_text=raw_text,
        reference_text=parse_source,
    )
    outcome = ExtractionOutcome(
        buyer=buyer,
        lines=lines,
        parse_source=parse_source,
    )

    assessment = _assess_rule_review_need(
        buyer,
        lines,
        parse_source,
        raw_text=raw_text,
        document_text=document_text,
        ocr_text=ocr_text,
        image_paths=image_paths or [],
        material_tags=material_tags or [],
        force_llm_review=force_llm_review,
    )
    adapter = get_llm_adapter()
    should_try_vision = _should_try_vision_extract(image_paths or [])
    should_try_text_llm = assessment.should_try_llm
    if not adapter.is_enabled or not (should_try_vision or should_try_text_llm):
        outcome.lines = _apply_current_amount_from_user_text(
            outcome.lines,
            raw_text=raw_text,
            reference_text=parse_source,
        )
        if assessment.reasons:
            outcome.warnings = _review_reason_warnings(assessment)
        return outcome

    llm_errors: list[str] = []
    llm_metrics: list[dict] = []
    candidate_tasks: list[tuple[str, object]] = []
    if _should_try_vision_extract(image_paths or []):
        candidate_tasks.append(("vision_extract_invoice", list(image_paths or [])))
    candidate_tasks.append(("extract_invoice", None))
    for attempt, (task_type, task_payload) in enumerate(candidate_tasks, start=1):
        started_at = time.monotonic()
        try:
            if task_type == "vision_extract_invoice":
                response = adapter.extract_invoice_info_from_images(f"{parse_source}\n\n备注：{note}".strip(), task_payload)  # type: ignore[arg-type]
            else:
                response = adapter.extract_invoice_info(f"{parse_source}\n\n备注：{note}".strip())
            elapsed_seconds = round(time.monotonic() - started_at, 3)
            llm_metrics.append(
                {
                    "task_type": task_type,
                    "provider": response.provider,
                    "model": response.model,
                    "status": "success",
                    "elapsed_seconds": elapsed_seconds,
                    "attempt": attempt,
                }
            )
            validation_errors = validate_extract_invoice_payload(response.parsed_json)
            if validation_errors:
                llm_errors.append(f"第 {attempt} 次 LLM 返回结构无效: {'; '.join(validation_errors)}")
                continue
            llm_buyer = _buyer_from_llm_payload(response.parsed_json)
            llm_lines = _lines_from_llm_payload(response.parsed_json)
            llm_note = _note_from_llm_payload(response.parsed_json)
            conflict_warnings = _build_extraction_conflict_warnings(buyer, lines, llm_buyer, llm_lines)
            merged_buyer = _merge_buyer(buyer, llm_buyer)
            merged_lines = _merge_lines(lines, llm_lines)
            merged_lines = _apply_current_amount_from_user_text(
                merged_lines,
                raw_text=raw_text,
                reference_text=parse_source,
            )
            return ExtractionOutcome(
                buyer=merged_buyer,
                lines=merged_lines,
                parse_source=parse_source,
                strategy="rules_plus_vision" if task_type == "vision_extract_invoice" else "rules_plus_llm",
                llm_provider=response.provider,
                extracted_note=llm_note,
                warnings=[*_review_reason_warnings(assessment), *llm_errors, f"LLM 结构化识别耗时 {elapsed_seconds:.1f} 秒。", *conflict_warnings],
                llm_metrics=llm_metrics,
            )
        except LLMAdapterError as exc:
            elapsed_seconds = round(time.monotonic() - started_at, 3)
            llm_metrics.append(
                {
                    "task_type": task_type,
                    "provider": getattr(adapter, "provider_name", ""),
                    "model": getattr(adapter, "model", ""),
                    "status": "failed",
                    "elapsed_seconds": elapsed_seconds,
                    "attempt": attempt,
                    "error": str(exc),
                }
            )
            llm_errors.append(f"{task_type} 调用失败，耗时 {elapsed_seconds:.1f} 秒: {exc}")
    outcome.lines = _apply_current_amount_from_user_text(
        outcome.lines,
        raw_text=raw_text,
        reference_text=parse_source,
    )
    outcome.warnings = [*_review_reason_warnings(assessment), *llm_errors]
    outcome.llm_metrics = llm_metrics
    return outcome


def _current_amount_from_user_text(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    candidates: list[str] = []
    for matched in re.finditer(r"(?<![A-Za-z0-9])(?:[¥￥]\s*)?(\d{1,8}(?:\.\d{1,2})?)\s*(?:元|块钱|块)?", text):
        value = matched.group(1)
        start, end = matched.span()
        window = text[max(0, start - 12): min(len(text), end + 12)]
        has_currency_hint = bool(re.search(r"[¥￥]|元|块钱|块|金额|开票|合计|总共|共计", window))
        text_is_short_amount = len(re.sub(r"\s+", "", text)) <= 12
        if has_currency_hint or text_is_short_amount:
            candidates.append(value)
    if not candidates:
        return ""
    return candidates[-1]


def _looks_like_repair_reference(reference_text: str) -> bool:
    text = str(reference_text or "")
    return bool(re.search(r"修理修配|维修费|修理费|汽车维修|车辆维修|汽修|保险|车牌|车辆照片", text))


def _infer_reference_tax_rate(reference_text: str) -> str:
    rates = re.findall(r"(?<!\d)(\d{1,2}(?:\.\d+)?)\s*%", str(reference_text or ""))
    return f"{rates[-1]}%" if rates else "1%"


def _should_override_single_line_amount(raw_text: str, lines: list[InvoiceLine]) -> bool:
    text = str(raw_text or "")
    if not text.strip() or len(lines) != 1:
        return False
    amount_mentions = re.findall(r"(?:[¥￥]\s*)?\d{1,8}(?:\.\d{1,2})?\s*(?:元|块钱|块)", text)
    if len(amount_mentions) != 1:
        return False
    return bool(re.search(r"本次|这次|开票|发票|金额|合计|总共|共计", text))



def _apply_current_amount_from_user_text(
    lines: list[InvoiceLine],
    *,
    raw_text: str,
    reference_text: str,
) -> list[InvoiceLine]:
    amount = _current_amount_from_user_text(raw_text)
    if not amount:
        return lines
    is_repair = _looks_like_repair_reference(reference_text)
    if not is_repair and not _should_override_single_line_amount(raw_text, lines):
        return lines
    if not lines:
        return [
            InvoiceLine(
                project_name="维修费" if is_repair else "开票项目",
                amount_with_tax=amount,
                tax_rate=_infer_reference_tax_rate(reference_text),
                unit="项",
                quantity="1",
            )
        ]
    target_index = 0
    for index, line in enumerate(lines):
        if is_repair and re.search(r"修理修配|维修|修理", line.project_name):
            target_index = index
            break
    patched: list[InvoiceLine] = []
    for index, line in enumerate(lines):
        if index == target_index:
            patched.append(
                InvoiceLine(
                    project_name=line.project_name or "维修费",
                    amount_with_tax=amount,
                    tax_rate=line.tax_rate or _infer_reference_tax_rate(reference_text),
                    tax_category=line.tax_category,
                    specification=line.specification,
                    unit=line.unit or "项",
                    quantity=line.quantity or "1",
                    unit_price=line.unit_price,
                    tax_code=line.tax_code,
                    source_item_code=line.source_item_code,
                    coding_reference=line.coding_reference,
                )
            )
        else:
            patched.append(line)
    return patched


def _should_try_vision_extract(image_paths: list[Path]) -> bool:
    if not image_paths:
        return False
    toggle = os.environ.get("TAX_INVOICE_LLM_VISION_EXTRACT", "auto").strip().lower()
    if toggle in {"0", "off", "false", "disabled"}:
        return False
    try:
        max_images = int(os.environ.get("TAX_INVOICE_LLM_VISION_MAX_IMAGES", "5") or "5")
    except ValueError:
        max_images = 5
    return len(image_paths) <= max(1, max_images)


def _assess_rule_review_need(
    buyer: BuyerInfo,
    lines: list[InvoiceLine],
    parse_source: str,
    *,
    raw_text: str,
    document_text: str,
    ocr_text: str,
    image_paths: list[Path],
    material_tags: list[str],
    force_llm_review: bool = False,
) -> RuleReviewAssessment:
    if not parse_source.strip() and not image_paths:
        return RuleReviewAssessment()
    reasons: list[str] = []
    if force_llm_review:
        reasons.append("调用方要求智能复核：当前材料适合让 LLM 做二次理解。")
    if image_paths:
        reasons.append(f"包含 {len(image_paths)} 张图片/截图：图片字段容易被 OCR 误读，建议视觉 LLM 复核。")
    if ocr_text.strip():
        reasons.append("OCR 文本参与了解析：请复核图片/OCR 得到的购买方、税号、金额和备注。")
    joined_tags = " / ".join(material_tags)
    if any(tag in joined_tags for tag in ["财务流水/余额线索", "压缩包材料", "压缩包需解压"]):
        reasons.append(f"材料类型为 {joined_tags}：不应仅按本地规则直接生成开票明细。")
    if "样票 PDF" in joined_tags and _has_amount_hint(raw_text):
        reasons.append("存在样票 PDF 和本次文字金额：需判断样票旧金额是否应被本次金额覆盖。")
    if len(_company_candidates(parse_source)) >= 2:
        reasons.append("材料中出现多个公司名称：需确认销售主体、购买方和样票主体没有串位。")
    if len(_amount_candidates(parse_source)) >= 2:
        reasons.append("材料中出现多个金额：需确认哪个是本次开票金额，哪些只是样票/历史金额。")
    if not buyer.name.strip():
        reasons.append("购买方名称未可靠识别。")
    if not buyer.tax_id.strip():
        reasons.append("购买方税号未可靠识别。")
    if not lines:
        reasons.append("本地规则未形成开票明细。")
    elif all(not line.resolved_amount_with_tax() for line in lines):
        reasons.append("本地规则未形成可靠含税金额。")
    elif sum(1 for line in lines if line.project_name.strip()) == 0:
        reasons.append("本地规则未形成可靠项目名称。")
    if _has_low_confidence_line(lines):
        reasons.append("明细来源含兜底/异常/需人工复核标记，建议智能复核。")

    strong = _rules_are_strong_enough_for_fast_draft(buyer, lines)
    blocking_review_mode = os.environ.get("TAX_INVOICE_LLM_BLOCKING_REVIEW", "fast").strip().lower()
    if strong and not reasons:
        return RuleReviewAssessment(confidence="high", should_call_llm=False)
    if strong and reasons and blocking_review_mode in {"", "0", "fast", "off", "false", "disabled"}:
        # 快速模式下，强结构化草稿不强行阻塞；但原因会进入草稿提醒，供 Windows/MIMO 或人工复核。
        return RuleReviewAssessment(reasons=_dedupe_reasons(reasons), confidence="medium", should_call_llm=False)
    confidence = "low" if reasons else "high"
    return RuleReviewAssessment(reasons=_dedupe_reasons(reasons), confidence=confidence, should_call_llm=bool(reasons))


def _review_reason_warnings(assessment: RuleReviewAssessment) -> list[str]:
    if not assessment.reasons:
        return []
    prefix = "建议智能复核" if assessment.should_call_llm else "建议人工重点复核"
    return [f"{prefix}：{reason}" for reason in assessment.reasons[:8]]



def _dedupe_reasons(reasons: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        cleaned = str(reason or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result[:10]



def _has_amount_hint(text: str) -> bool:
    return bool(re.search(r"(?:[¥￥]\s*)?\d{1,8}(?:\.\d{1,2})?\s*(?:元|块钱|块)|金额|合计|总共|共计", str(text or "")))



def _amount_candidates(text: str) -> list[str]:
    values: list[str] = []
    raw = str(text or "")
    for matched in re.finditer(r"(?<![A-Za-z0-9])(?:[¥￥]\s*)?(\d{1,8}(?:\.\d{1,2})?)\s*(?:元|块钱|块|万元)?", raw):
        start, end = matched.span()
        before = raw[max(0, start - 8): start]
        nearby = raw[max(0, start - 3): min(len(raw), end + 3)]
        has_unit_or_currency = bool(re.search(r"[¥￥]|元|块钱|块|万元", nearby))
        has_amount_label_before = bool(re.search(r"金额|合计|总共|共计|价税", before))
        if not (has_unit_or_currency or has_amount_label_before):
            continue
        values.append(matched.group(1))
    return values[:20]



def _company_candidates(text: str) -> list[str]:
    pattern = r"([\u4e00-\u9fffA-Za-z0-9（）()·\-]{2,40}(?:有限公司|有限责任公司|个体工商户|中心|门诊部|医院|学校|大学|研究院|研究所|商店|饭店|物业|餐饮|传媒))"
    values = []
    for match in re.finditer(pattern, str(text or "")):
        value = match.group(1).strip(" ：:，,。；;（）()")
        if value and value not in values:
            values.append(value)
    return values[:12]



def _has_low_confidence_line(lines: list[InvoiceLine]) -> bool:
    low_markers = ["兜底", "异常", "需人工复核", "未命中", "OCR", "视觉", "样票", "历史"]
    for line in lines:
        reference = f"{line.coding_reference} {line.project_name} {line.specification}"
        if any(marker in reference for marker in low_markers):
            return True
    return False



def _rules_are_strong_enough_for_fast_draft(buyer: BuyerInfo, lines: list[InvoiceLine]) -> bool:
    if not buyer.name.strip() or not buyer.tax_id.strip() or not lines:
        return False
    return all(line.project_name.strip() and line.resolved_amount_with_tax() for line in lines)



def _build_extraction_conflict_warnings(
    rule_buyer: BuyerInfo,
    rule_lines: list[InvoiceLine],
    llm_buyer: BuyerInfo,
    llm_lines: list[InvoiceLine],
) -> list[str]:
    warnings: list[str] = []
    _append_conflict(warnings, "购买方名称", rule_buyer.name, llm_buyer.name)
    _append_conflict(warnings, "购买方税号", rule_buyer.tax_id, llm_buyer.tax_id)
    if rule_lines and llm_lines and len(rule_lines) != len(llm_lines):
        warnings.append(f"识别差异需确认：规则识别出 {len(rule_lines)} 行明细，智能识别为 {len(llm_lines)} 行。")
    for index, (rule_line, llm_line) in enumerate(zip(rule_lines, llm_lines), start=1):
        _append_conflict(warnings, f"第 {index} 行项目名称", rule_line.project_name, llm_line.project_name)
        _append_conflict(warnings, f"第 {index} 行金额", rule_line.resolved_amount_with_tax(), llm_line.resolved_amount_with_tax())
        _append_conflict(warnings, f"第 {index} 行税率", rule_line.normalized_tax_rate(), llm_line.normalized_tax_rate())
        _append_conflict(warnings, f"第 {index} 行税收编码", rule_line.tax_code, llm_line.tax_code)
    return warnings[:12]


def _append_conflict(warnings: list[str], label: str, rule_value: str, llm_value: str) -> None:
    rule_normalized = _normalize_compare_value(rule_value)
    llm_normalized = _normalize_compare_value(llm_value)
    if not rule_normalized or not llm_normalized or rule_normalized == llm_normalized:
        return
    warnings.append(f"识别差异需确认：{label}，规则识别为“{rule_value}”，智能识别为“{llm_value}”。")


def _normalize_compare_value(value: str) -> str:
    return str(value or "").strip().replace(" ", "").replace("，", ",").upper()


def _buyer_from_llm_payload(payload: dict) -> BuyerInfo:
    address_phone = str(payload.get("地址电话", "") or "").strip()
    bank_account = str(payload.get("开户行及账号", "") or "").strip()
    return BuyerInfo(
        name=str(payload.get("客户名称", "") or "").strip(),
        tax_id=str(payload.get("纳税人识别号", "") or "").strip(),
        address=address_phone,
        phone="",
        bank_name=bank_account,
        bank_account="",
    )


def _note_from_llm_payload(payload: dict) -> str:
    return str(
        payload.get("备注", "")
        or payload.get("发票备注", "")
        or payload.get("备注信息", "")
        or ""
    ).strip()


def _lines_from_llm_payload(payload: dict) -> list[InvoiceLine]:
    lines: list[InvoiceLine] = []
    top_level_amount = str(
        payload.get("价税合计", "")
        or payload.get("开票金额", "")
        or payload.get("含税金额", "")
        or payload.get("金额", "")
        or ""
    ).strip()
    items = payload.get("项目列表", [])
    if isinstance(items, dict):
        items = [items]
    for item in items:
        if not isinstance(item, dict):
            continue
        line = InvoiceLine(
            project_name=str(item.get("项目名称", "") or "").strip(),
            specification=str(item.get("规格型号", "") or "").strip(),
            unit=str(item.get("单位", "") or "").strip(),
            quantity=str(item.get("数量", "") or "").strip(),
            unit_price=str(item.get("单价", "") or item.get("含税单价", "") or "").strip(),
            amount_with_tax=str(
                item.get("金额", "")
                or item.get("含税金额", "")
                or item.get("开票金额", "")
                or item.get("价税合计", "")
                or (top_level_amount if len(items) == 1 else "")
                or ""
            ).strip(),
            tax_rate=str(item.get("税率", "") or item.get("税点", "") or "").strip() or "3%",
            tax_code=str(item.get("税收编码", "") or item.get("税收分类编码", "") or item.get("商品和服务税收编码", "") or "").strip(),
        )
        if line.project_name or line.amount_with_tax:
            lines.append(line)
    return lines


def _merge_buyer(primary: BuyerInfo, fallback: BuyerInfo) -> BuyerInfo:
    return BuyerInfo(
        name=primary.name or fallback.name,
        tax_id=primary.tax_id or fallback.tax_id,
        address=primary.address or fallback.address,
        phone=primary.phone or fallback.phone,
        bank_name=primary.bank_name or fallback.bank_name,
        bank_account=primary.bank_account or fallback.bank_account,
    )


def _merge_lines(primary: list[InvoiceLine], fallback: list[InvoiceLine]) -> list[InvoiceLine]:
    if not primary and fallback:
        return fallback
    if not fallback:
        return primary
    if _lines_are_weak(primary) and len(fallback) >= len(primary):
        return fallback
    merged: list[InvoiceLine] = []
    max_len = max(len(primary), len(fallback))
    for index in range(max_len):
        base = primary[index] if index < len(primary) else InvoiceLine(project_name="", amount_with_tax="")
        extra = fallback[index] if index < len(fallback) else InvoiceLine(project_name="", amount_with_tax="")
        merged.append(
            InvoiceLine(
                project_name=base.project_name or extra.project_name,
                amount_with_tax=base.amount_with_tax or extra.amount_with_tax,
                tax_rate=base.tax_rate or extra.tax_rate or "3%",
                tax_category=base.tax_category or extra.tax_category,
                specification=base.specification or extra.specification,
                unit=base.unit or extra.unit,
                quantity=base.quantity or extra.quantity,
                unit_price=base.unit_price or extra.unit_price,
                tax_code=base.tax_code or extra.tax_code,
                source_item_code=base.source_item_code or extra.source_item_code,
                coding_reference=base.coding_reference or extra.coding_reference,
            )
        )
    return [line for line in merged if line.project_name or line.amount_with_tax]


def _lines_are_weak(lines: list[InvoiceLine]) -> bool:
    if not lines:
        return True
    filled_names = sum(1 for line in lines if line.project_name.strip())
    filled_amounts = sum(1 for line in lines if line.resolved_amount_with_tax())
    return filled_names == 0 or filled_amounts == 0

from __future__ import annotations

import os
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
    warnings: list[str] = field(default_factory=list)
    llm_metrics: list[dict] = field(default_factory=list)


def compose_parse_source(raw_text: str, document_text: str, ocr_text: str) -> str:
    return "\n\n".join(part for part in [raw_text.strip(), document_text.strip(), ocr_text.strip()] if part)


def extract_invoice_structured_data(
    *,
    raw_text: str,
    note: str,
    document_text: str,
    ocr_text: str,
    image_paths: list[Path] | None = None,
) -> ExtractionOutcome:
    parse_source = compose_parse_source(raw_text, document_text, ocr_text)
    buyer = extract_buyer_info_from_text(parse_source)
    lines = extract_invoice_lines_from_text(parse_source)
    outcome = ExtractionOutcome(
        buyer=buyer,
        lines=lines,
        parse_source=parse_source,
    )

    adapter = get_llm_adapter()
    should_try_vision = _should_try_vision_extract(image_paths or [])
    should_try_text_llm = _should_try_llm(
        buyer,
        lines,
        parse_source,
        raw_text=raw_text,
        document_text=document_text,
        ocr_text=ocr_text,
    )
    if not adapter.is_enabled or not (should_try_vision or should_try_text_llm):
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
            conflict_warnings = _build_extraction_conflict_warnings(buyer, lines, llm_buyer, llm_lines)
            merged_buyer = _merge_buyer(buyer, llm_buyer)
            merged_lines = _merge_lines(lines, llm_lines)
            return ExtractionOutcome(
                buyer=merged_buyer,
                lines=merged_lines,
                parse_source=parse_source,
                strategy="rules_plus_vision" if task_type == "vision_extract_invoice" else "rules_plus_llm",
                llm_provider=response.provider,
                warnings=[*llm_errors, f"LLM 结构化识别耗时 {elapsed_seconds:.1f} 秒。", *conflict_warnings],
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
    outcome.warnings = llm_errors
    outcome.llm_metrics = llm_metrics
    return outcome


def _should_try_vision_extract(image_paths: list[Path]) -> bool:
    if not image_paths:
        return False
    toggle = os.environ.get("TAX_INVOICE_LLM_VISION_EXTRACT", "auto").strip().lower()
    if toggle in {"0", "off", "false", "disabled"}:
        return False
    try:
        max_images = int(os.environ.get("TAX_INVOICE_LLM_VISION_MAX_IMAGES", "3") or "3")
    except ValueError:
        max_images = 3
    return len(image_paths) <= max(1, max_images)


def _should_try_llm(
    buyer: BuyerInfo,
    lines: list[InvoiceLine],
    parse_source: str,
    *,
    raw_text: str,
    document_text: str,
    ocr_text: str,
) -> bool:
    if not parse_source.strip():
        return False
    blocking_review_mode = os.environ.get("TAX_INVOICE_LLM_BLOCKING_REVIEW", "fast").strip().lower()
    if _rules_are_strong_enough_for_fast_draft(buyer, lines) and blocking_review_mode in {
        "",
        "0",
        "fast",
        "off",
        "false",
        "disabled",
    }:
        return False
    if _rules_are_strong_enough_for_fast_draft(buyer, lines) and blocking_review_mode in {"1", "true", "on", "yes"}:
        return True
    # 规则未能形成完整草稿时，上传附件、OCR、长文本需要让 LLM 做识别补充。
    if document_text.strip() or ocr_text.strip() or len(raw_text.strip()) >= 120:
        return True
    if not buyer.name.strip() or not buyer.tax_id.strip():
        return True
    if not lines:
        return True
    if all(not line.resolved_amount_with_tax() for line in lines):
        return True
    if sum(1 for line in lines if line.project_name.strip()) == 0:
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


def _lines_from_llm_payload(payload: dict) -> list[InvoiceLine]:
    lines: list[InvoiceLine] = []
    for item in payload.get("项目列表", []):
        if not isinstance(item, dict):
            continue
        line = InvoiceLine(
            project_name=str(item.get("项目名称", "") or "").strip(),
            specification=str(item.get("规格型号", "") or "").strip(),
            unit=str(item.get("单位", "") or "").strip(),
            quantity=str(item.get("数量", "") or "").strip(),
            unit_price=str(item.get("单价", "") or "").strip(),
            amount_with_tax=str(item.get("金额", "") or "").strip(),
            tax_rate=str(item.get("税率", "") or "").strip() or "3%",
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

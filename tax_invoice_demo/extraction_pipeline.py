from __future__ import annotations

from dataclasses import dataclass, field

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


def compose_parse_source(raw_text: str, document_text: str, ocr_text: str) -> str:
    return "\n\n".join(part for part in [raw_text.strip(), document_text.strip(), ocr_text.strip()] if part)


def extract_invoice_structured_data(
    *,
    raw_text: str,
    note: str,
    document_text: str,
    ocr_text: str,
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
    if not adapter.is_enabled or not _should_try_llm(buyer, lines, parse_source):
        return outcome

    llm_errors: list[str] = []
    for attempt in range(1, 3):
        try:
            response = adapter.extract_invoice_info(f"{parse_source}\n\n备注：{note}".strip())
            validation_errors = validate_extract_invoice_payload(response.parsed_json)
            if validation_errors:
                llm_errors.append(f"第 {attempt} 次 LLM 返回结构无效: {'; '.join(validation_errors)}")
                continue
            llm_buyer = _buyer_from_llm_payload(response.parsed_json)
            llm_lines = _lines_from_llm_payload(response.parsed_json)
            merged_buyer = _merge_buyer(buyer, llm_buyer)
            merged_lines = _merge_lines(lines, llm_lines)
            return ExtractionOutcome(
                buyer=merged_buyer,
                lines=merged_lines,
                parse_source=parse_source,
                strategy="rules_plus_llm",
                llm_provider=response.provider,
                warnings=llm_errors,
            )
        except LLMAdapterError as exc:
            llm_errors.append(f"第 {attempt} 次 LLM 调用失败: {exc}")
    outcome.warnings = llm_errors
    return outcome


def _should_try_llm(buyer: BuyerInfo, lines: list[InvoiceLine], parse_source: str) -> bool:
    if not parse_source.strip():
        return False
    if not buyer.name.strip() or not buyer.tax_id.strip():
        return True
    if not lines:
        return True
    if all(not line.resolved_amount_with_tax() for line in lines):
        return True
    if sum(1 for line in lines if line.project_name.strip()) == 0:
        return True
    return False


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

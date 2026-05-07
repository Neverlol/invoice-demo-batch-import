from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import platform
from typing import Dict
from typing import List


def _parse_decimal(raw: str) -> Decimal | None:
    normalized = (
        raw.strip()
        .replace(",", "")
        .replace("，", "")
        .replace("￥", "")
        .replace("¥", "")
    )
    if not normalized:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _format_decimal(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:.2f}"


def _format_percent(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return text or "0"


def default_browser_engine() -> str:
    return "system_edge" if platform.system() == "Windows" else "playwright_chromium"


def default_execution_backend() -> str:
    return "playwright_cdp" if platform.system() == "Windows" else "playwright_browser"


def default_desktop_window_title_re() -> str:
    return ".*(国家税务总局|电子税务局|电子发票服务平台|蓝字发票|税务数字账户|税务数字账户).*"


@dataclass
class BuyerInfo:
    name: str
    tax_id: str
    address: str = ""
    phone: str = ""
    bank_name: str = ""
    bank_account: str = ""


@dataclass
class InvoiceLine:
    project_name: str
    amount_with_tax: str
    tax_rate: str = "3%"
    tax_category: str = ""
    specification: str = ""
    unit: str = ""
    quantity: str = ""
    unit_price: str = ""
    tax_code: str = ""
    source_item_code: str = ""
    coding_reference: str = ""

    def resolved_amount_with_tax(self) -> str:
        direct_amount = _parse_decimal(self.amount_with_tax)
        if direct_amount is not None:
            return _format_decimal(direct_amount)
        quantity = _parse_decimal(self.quantity)
        unit_price = _parse_decimal(self.unit_price)
        if quantity is not None and unit_price is not None:
            return _format_decimal(quantity * unit_price)
        return ""

    def normalized_tax_rate(self) -> str:
        normalized = self.tax_rate.strip().replace("％", "%")
        if not normalized:
            return "3%"
        if normalized in {"免税", "不征税", "免征增值税"}:
            return normalized
        if normalized.endswith("%"):
            return normalized
        rate_value = _parse_decimal(normalized)
        if rate_value is None:
            return normalized
        if rate_value <= Decimal("1"):
            rate_value *= Decimal("100")
        return f"{_format_percent(rate_value)}%"


@dataclass
class InvoiceTask:
    company_name: str
    buyer: BuyerInfo
    lines: List[InvoiceLine]
    invoice_kind: str = "普通发票"
    invoice_medium: str = "电子发票"
    special_business: str = ""
    extract_strategy: str = "rules_only"
    llm_provider: str = ""
    extract_warnings: list[str] = field(default_factory=list)
    execution_backend: str = field(default_factory=default_execution_backend)
    session_start_mode: str = "manual_prelogged"
    browser_session_mode: str = "operator_persistent"
    browser_engine: str = field(default_factory=default_browser_engine)
    desktop_window_title_re: str = field(default_factory=default_desktop_window_title_re)
    login_entry_mode: str = "enterprise_default"
    run_mode: str = "enterprise_check"
    note: str = ""
    cdp_endpoint: str = "http://127.0.0.1:9222"

    @property
    def primary_line(self) -> InvoiceLine:
        if self.lines:
            return self.lines[0]
        return InvoiceLine(project_name="", amount_with_tax="")

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.company_name.strip():
            errors.append("纳税主体名称不能为空。")
        if self.run_mode == "fill_invoice":
            if not self.buyer.name.strip():
                errors.append("购买方名称不能为空。")
            if not self.buyer.tax_id.strip():
                errors.append("购买方税号不能为空。")
            if not self.lines:
                errors.append("至少需要 1 行开票明细。")
            for index, line in enumerate(self.lines, start=1):
                if not line.project_name.strip():
                    errors.append(f"第 {index} 行项目名称不能为空。")
                if not line.resolved_amount_with_tax():
                    errors.append(f"第 {index} 行含税金额不能为空。")
        return errors


@dataclass
class DraftAttachment:
    original_name: str
    stored_name: str
    mime_type: str = ""
    size_bytes: int = 0


@dataclass
class InvoiceDraft:
    draft_id: str
    case_id: str
    company_name: str
    buyer: BuyerInfo
    lines: List[InvoiceLine]
    raw_text: str = ""
    note: str = ""
    issues: List[str] = field(default_factory=list)
    source_images: List[DraftAttachment] = field(default_factory=list)
    workbook_name: str = ""
    created_at: str = ""
    invoice_kind: str = "普通发票"
    invoice_medium: str = "电子发票"
    special_business: str = ""
    ocr_status: str = "not_requested"
    ocr_engine: str = ""
    ocr_text: str = ""
    ocr_note: str = ""
    source_doc_status: str = "not_requested"
    source_doc_text: str = ""
    source_doc_note: str = ""
    extract_strategy: str = "rules_only"
    llm_provider: str = ""
    extract_warnings: List[str] = field(default_factory=list)
    material_tags: List[str] = field(default_factory=list)
    field_review_reasons: Dict[str, List[str]] = field(default_factory=dict)

    def detail_lines_text(self) -> str:
        headers = [
            "项目名称",
            "赋码大类",
            "税收编码",
            "零件编码",
            "规格型号",
            "单位",
            "数量",
            "单价",
            "含税金额",
            "税率/征收率",
            "赋码说明",
        ]
        rows = ["\t".join(headers)]
        for line in self.lines:
            rows.append(
                "\t".join(
                    [
                        line.project_name,
                        line.tax_category,
                        line.tax_code,
                        line.source_item_code,
                        line.specification,
                        line.unit,
                        line.quantity,
                        line.unit_price,
                        line.resolved_amount_with_tax(),
                        line.normalized_tax_rate(),
                        line.coding_reference,
                    ]
                )
            )
        return "\n".join(rows)

    def combined_source_text(self) -> str:
        return "\n\n".join(
            part
            for part in [self.raw_text.strip(), self.source_doc_text.strip(), self.ocr_text.strip()]
            if part
        )

    def as_form_defaults(self) -> Dict[str, str]:
        return {
            "company_name": self.company_name,
            "buyer_name": self.buyer.name,
            "buyer_tax_id": self.buyer.tax_id,
            "buyer_address": self.buyer.address,
            "buyer_phone": self.buyer.phone,
            "buyer_bank_name": self.buyer.bank_name,
            "buyer_bank_account": self.buyer.bank_account,
            "detail_lines_text": self.detail_lines_text(),
            "raw_text": self.raw_text,
            "note": self.note,
            "invoice_kind": self.invoice_kind or "普通发票",
            "invoice_medium": self.invoice_medium or "电子发票",
            "special_business": self.special_business or "",
            "session_start_mode": "manual_prelogged",
            "browser_session_mode": "operator_persistent",
            "execution_backend": default_execution_backend(),
            "browser_engine": default_browser_engine(),
            "desktop_window_title_re": default_desktop_window_title_re(),
            "login_entry_mode": "enterprise_default",
            "run_mode": "fill_invoice",
            "headless": "",
            "keep_browser_open": "on",
            "cdp_endpoint": "http://127.0.0.1:9222",
        }

    @property
    def coding_hit_count(self) -> int:
        return sum(1 for line in self.lines if line.tax_category or line.coding_reference)

    @property
    def coding_pending_count(self) -> int:
        return sum(1 for line in self.lines if not line.tax_category)

    @property
    def total_amount_with_tax(self) -> str:
        total = Decimal("0")
        has_amount = False
        for line in self.lines:
            amount = _parse_decimal(line.resolved_amount_with_tax())
            if amount is None:
                continue
            total += amount
            has_amount = True
        return _format_decimal(total) if has_amount else ""

    @property
    def project_preview(self) -> str:
        names = [line.project_name.strip() for line in self.lines if line.project_name.strip()]
        if not names:
            return "待补充"
        if len(names) <= 3:
            return " / ".join(names)
        return " / ".join(names[:3]) + f" 等 {len(names)} 项"


@dataclass
class DraftBatchItem:
    draft_id: str
    buyer_name: str
    invoice_kind: str
    amount_total: str
    project_summary: str
    line_count: int
    issue_summary: str = ""


@dataclass
class DraftBatch:
    batch_id: str
    case_id: str
    company_name: str
    created_at: str
    items: list[DraftBatchItem]
    raw_text: str = ""
    note: str = ""
    issues: list[str] = field(default_factory=list)
    source_images: list[DraftAttachment] = field(default_factory=list)
    invoice_kind: str = "普通发票"
    invoice_medium: str = "电子发票"
    special_business: str = ""
    extract_strategy: str = ""
    llm_provider: str = ""
    extract_warnings: list[str] = field(default_factory=list)
    material_tags: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: str
    status: str
    current_step: str
    logs: List[str] = field(default_factory=list)
    artifact_paths: List[str] = field(default_factory=list)
    error: str = ""

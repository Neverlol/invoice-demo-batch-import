from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from werkzeug.datastructures import FileStorage

from .batch_template import export_template_invoices, invoice_from_workbench_draft
from .failure_details import build_failure_report
from .validation import validate_batch_workbook


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent
for search_path in (str(PACKAGE_ROOT), str(PROJECT_ROOT)):
    if search_path in sys.path:
        sys.path.remove(search_path)
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PACKAGE_ROOT))

from tax_invoice_demo.models import BuyerInfo, DraftBatch, InvoiceDraft, InvoiceLine  # noqa: E402
from tax_invoice_demo.case_events import batch_snapshot, draft_snapshot, record_case_event  # noqa: E402
from tax_invoice_demo.workbench import (  # noqa: E402
    create_draft_from_workbench,
    draft_directory,
    load_draft,
    load_draft_batch,
    update_draft_from_form,
)


BATCH_OUTPUT_ROOT = PACKAGE_ROOT / "output" / "batch_import_preview"
SUCCESS_LEDGER_CSV = BATCH_OUTPUT_ROOT / "批量导入成功明细.csv"
SUCCESS_LEDGER_XLSX = BATCH_OUTPUT_ROOT / "批量导入成功明细.xlsx"

SUCCESS_LEDGER_HEADERS = [
    "recorded_at",
    "case_id",
    "draft_id",
    "company_name",
    "invoice_kind",
    "buyer_name",
    "buyer_tax_id",
    "line_no",
    "project_name",
    "tax_category",
    "tax_code",
    "specification",
    "unit",
    "quantity",
    "unit_price",
    "amount_with_tax",
    "tax_rate",
    "coding_reference",
    "note",
]


def default_form() -> dict[str, str]:
    return {
        "company_name": "",
        "raw_text": "",
        "note": "",
    }


def create_lean_draft(*, company_name: str, raw_text: str, note: str, uploaded_files: list[FileStorage]) -> InvoiceDraft | DraftBatch:
    return create_draft_from_workbench(
        company_name=company_name,
        raw_text=raw_text,
        note=note,
        uploaded_files=uploaded_files,
    )


def save_lean_draft_from_form(draft_id: str, form: dict[str, Any], uploaded_files: list[FileStorage] | None = None) -> InvoiceDraft:
    return update_draft_from_form(
        draft_id,
        company_name=(form.get("company_name") or "").strip(),
        raw_text=form.get("raw_text", ""),
        note=form.get("note", ""),
        buyer=BuyerInfo(
            name=(form.get("buyer_name") or "").strip(),
            tax_id=(form.get("buyer_tax_id") or "").strip(),
            address=(form.get("buyer_address") or "").strip(),
            phone=(form.get("buyer_phone") or "").strip(),
            bank_name=(form.get("buyer_bank_name") or "").strip(),
            bank_account=(form.get("buyer_bank_account") or "").strip(),
        ),
        lines=_lines_from_form(form),
        invoice_kind=form.get("invoice_kind") or "普通发票",
        invoice_medium="电子发票",
        special_business=(form.get("special_business") or "").strip(),
        uploaded_files=uploaded_files or [],
    )


def export_draft_template(draft: InvoiceDraft) -> dict[str, Any]:
    output_path = BATCH_OUTPUT_ROOT / f"{draft.draft_id}_batch_import.xlsx"
    invoice = invoice_from_workbench_draft(draft, serial_no=draft.draft_id)
    export_template_invoices([invoice], output_path)
    issues = validate_batch_workbook(output_path)
    result = {
        "output_path": output_path,
        "validation_issues": [asdict(issue) for issue in issues],
        "error_count": sum(1 for issue in issues if issue.level == "error"),
        "warning_count": sum(1 for issue in issues if issue.level == "warning"),
    }
    record_case_event(
        case_id=draft.case_id,
        draft_id=draft.draft_id,
        event_type="template_exported",
        payload={
            **draft_snapshot(draft),
            "output_path": str(output_path),
            "error_count": result["error_count"],
            "warning_count": result["warning_count"],
        },
    )
    return result


def export_batch_template(batch_id: str) -> dict[str, Any]:
    from .workbench_bridge import export_saved_workbench_items

    output_path = BATCH_OUTPUT_ROOT / f"{batch_id}_batch_import.xlsx"
    export_saved_workbench_items([batch_id], output_path)
    issues = validate_batch_workbook(output_path)
    result = {
        "output_path": output_path,
        "validation_issues": [asdict(issue) for issue in issues],
        "error_count": sum(1 for issue in issues if issue.level == "error"),
        "warning_count": sum(1 for issue in issues if issue.level == "warning"),
    }
    batch = load_draft_batch(batch_id)
    if batch is not None:
        record_case_event(
            case_id=batch.case_id,
            batch_id=batch.batch_id,
            event_type="batch_template_exported",
            payload={
                **batch_snapshot(batch),
                "output_path": str(output_path),
                "error_count": result["error_count"],
                "warning_count": result["warning_count"],
            },
        )
    return result


def parse_failure_file(file: FileStorage, *, draft: InvoiceDraft | None = None) -> dict[str, Any]:
    BATCH_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "failure.xlsx").name
    target = BATCH_OUTPUT_ROOT / f"failure_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    file.save(target)
    report = build_failure_report(target)
    if draft is not None:
        record_case_event(
            case_id=draft.case_id,
            draft_id=draft.draft_id,
            event_type="failure_report_uploaded",
            payload={
                "file_name": safe_name,
                "stored_path": str(target),
                "report": report,
            },
        )
    return report


def record_success_to_ledger(draft: InvoiceDraft) -> Path:
    BATCH_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = _read_success_rows()
    rows = [row for row in rows if row.get("draft_id") != draft.draft_id]
    recorded_at = datetime.now().isoformat(timespec="seconds")
    for index, line in enumerate(draft.lines, start=1):
        rows.append(
            {
                "recorded_at": recorded_at,
                "case_id": draft.case_id,
                "draft_id": draft.draft_id,
                "company_name": draft.company_name,
                "invoice_kind": draft.invoice_kind,
                "buyer_name": draft.buyer.name,
                "buyer_tax_id": draft.buyer.tax_id,
                "line_no": str(index),
                "project_name": line.project_name,
                "tax_category": line.tax_category,
                "tax_code": line.tax_code,
                "specification": line.specification,
                "unit": line.unit,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount_with_tax": line.resolved_amount_with_tax(),
                "tax_rate": line.normalized_tax_rate(),
                "coding_reference": line.coding_reference,
                "note": draft.note,
            }
        )
    _write_success_rows(rows)
    record_case_event(
        case_id=draft.case_id,
        draft_id=draft.draft_id,
        event_type="success_recorded",
        payload={
            **draft_snapshot(draft),
            "recorded_at": recorded_at,
        },
    )
    return SUCCESS_LEDGER_XLSX


def draft_preview(draft: InvoiceDraft) -> dict[str, Any]:
    amount_total = Decimal("0")
    tax_total = Decimal("0")
    line_rows: list[dict[str, str]] = []
    for index, line in enumerate(draft.lines, start=1):
        amount = _decimal(line.resolved_amount_with_tax())
        rate = _rate_decimal(line.normalized_tax_rate())
        tax_amount = _money(amount - (amount / (Decimal("1") + rate))) if amount is not None and rate is not None else ""
        if amount is not None:
            amount_total += amount
        if tax_amount:
            tax_total += Decimal(tax_amount)
        line_rows.append(
            {
                "line_no": str(index),
                "project_name": line.project_name,
                "tax_category": line.tax_category,
                "tax_code": line.tax_code,
                "specification": line.specification,
                "unit": line.unit,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount_with_tax": line.resolved_amount_with_tax(),
                "tax_rate": line.normalized_tax_rate(),
                "coding_reference": line.coding_reference,
                "tax_amount_preview": tax_amount,
            }
        )
    return {
        "amount_total": _money(amount_total),
        "tax_total": _money(tax_total),
        "line_rows": line_rows,
        "issues": draft.issues,
        "attachments": draft.source_images,
    }


def line_form_rows(draft: InvoiceDraft) -> list[dict[str, str]]:
    return draft_preview(draft)["line_rows"] or [
        {
            "project_name": "",
            "tax_category": "",
            "tax_code": "",
            "specification": "",
            "unit": "",
            "quantity": "",
            "unit_price": "",
            "amount_with_tax": "",
            "tax_rate": "3%",
            "coding_reference": "",
        }
    ]


def _lines_from_form(form: dict[str, Any]) -> list[InvoiceLine]:
    project_names = _form_list(form, "line_project_name")
    lines: list[InvoiceLine] = []
    for index, project_name in enumerate(project_names):
        if not any(
            [
                project_name.strip(),
                _form_value(form, "line_amount_with_tax", index),
                _form_value(form, "line_tax_code", index),
            ]
        ):
            continue
        lines.append(
            InvoiceLine(
                project_name=project_name.strip(),
                amount_with_tax=_form_value(form, "line_amount_with_tax", index),
                tax_rate=_form_value(form, "line_tax_rate", index) or "3%",
                tax_category=_form_value(form, "line_tax_category", index),
                tax_code=_form_value(form, "line_tax_code", index),
                specification=_form_value(form, "line_specification", index),
                unit=_form_value(form, "line_unit", index),
                quantity=_form_value(form, "line_quantity", index),
                unit_price=_form_value(form, "line_unit_price", index),
                coding_reference=_form_value(form, "line_coding_reference", index),
            )
        )
    return lines


def _form_list(form: dict[str, Any], key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [str(item) for item in form.getlist(key)]
    value = form.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value else []


def _form_value(form: dict[str, Any], key: str, index: int) -> str:
    values = _form_list(form, key)
    return values[index].strip() if index < len(values) else ""


def _read_success_rows() -> list[dict[str, str]]:
    if not SUCCESS_LEDGER_CSV.exists():
        return []
    with SUCCESS_LEDGER_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_success_rows(rows: list[dict[str, str]]) -> None:
    with SUCCESS_LEDGER_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUCCESS_LEDGER_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "批量导入成功明细"
    sheet.append(SUCCESS_LEDGER_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DCEFE9")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in rows:
        sheet.append([row.get(header, "") for header in SUCCESS_LEDGER_HEADERS])
    sheet.freeze_panes = "A2"
    last_column = get_column_letter(len(SUCCESS_LEDGER_HEADERS))
    sheet.auto_filter.ref = f"A1:{last_column}{max(sheet.max_row, 1)}"
    for column in range(1, len(SUCCESS_LEDGER_HEADERS) + 1):
        sheet.column_dimensions[chr(64 + column)].width = 16
    workbook.save(SUCCESS_LEDGER_XLSX)


def _decimal(raw: str) -> Decimal | None:
    text = (raw or "").replace(",", "").replace("，", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _rate_decimal(raw: str) -> Decimal | None:
    text = (raw or "").strip().replace("％", "%")
    if text in {"免税", "不征税", "免征增值税"}:
        return Decimal("0")
    if text.endswith("%"):
        text = text[:-1]
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value > Decimal("1"):
        value = value / Decimal("100")
    return value


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}"

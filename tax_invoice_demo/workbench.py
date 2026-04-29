from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from werkzeug.datastructures import FileStorage

from .case_events import batch_snapshot, diff_drafts, draft_snapshot, record_case_event
from .coding_library import enrich_invoice_lines, load_formal_coding_library
from .extraction_pipeline import compose_parse_source, extract_invoice_structured_data
from .ledger import sync_draft_to_ledger
from .models import BuyerInfo, DraftAttachment, DraftBatch, DraftBatchItem, InvoiceDraft, InvoiceLine
from .ocr import run_optional_ocr
from .source_documents import extract_supported_documents, serialize_document_results
from .tax_rule_engine import write_learned_rules_from_manual_update

WORKBENCH_ROOT = Path(__file__).resolve().parent.parent / "output" / "workbench" / "tax_invoice_demo"


def default_workbench_form() -> dict[str, str]:
    return {
        "company_name": "",
        "raw_text": "",
        "note": "",
    }


def create_draft_from_workbench(company_name: str, raw_text: str, note: str, uploaded_files: list[FileStorage]) -> InvoiceDraft | DraftBatch:
    draft_id = uuid4().hex[:10]
    case_id = draft_id
    draft_dir = draft_directory(draft_id)
    draft_dir.mkdir(parents=True, exist_ok=True)
    attachments = _save_uploads(draft_dir, uploaded_files)
    document_result = _run_document_extraction(draft_dir, attachments)
    ocr_result = _run_draft_ocr(draft_dir, attachments)
    extraction = extract_invoice_structured_data(
        raw_text=raw_text,
        note=note,
        document_text=document_result.combined_text,
        ocr_text=ocr_result.combined_text,
    )
    parse_source = extraction.parse_source
    buyer = extraction.buyer
    buyer = _enrich_buyer_from_sheet_context(company_name, buyer, parse_source)
    lines = extraction.lines
    invoice_profile = _infer_invoice_profile(parse_source, note=note)
    split_lines = _build_amount_split_lines(
        company_name=company_name,
        parse_source=parse_source,
        buyer=buyer,
        lines=lines,
        invoice_profile=invoice_profile,
    )
    if split_lines:
        batch = _create_split_draft_batch(
            batch_id=draft_id,
            case_id=case_id,
            draft_dir=draft_dir,
            company_name=company_name,
            raw_text=raw_text,
            note=note,
            buyer=buyer,
            attachments=attachments,
            document_result=document_result,
            ocr_result=ocr_result,
            invoice_profile=invoice_profile,
            split_lines=split_lines,
            extract_strategy=extraction.strategy,
            llm_provider=extraction.llm_provider,
            extract_warnings=extraction.warnings,
        )
        return batch

    lines = enrich_invoice_lines(lines, raw_text=parse_source, note=note)

    issues = _build_draft_issues(
        company_name=company_name,
        raw_text=raw_text,
        attachments=attachments,
        buyer=buyer,
        lines=lines,
        special_business=invoice_profile["special_business"],
        document_status=document_result.status,
        document_note=document_result.note,
        ocr_status=ocr_result.status,
        ocr_note=ocr_result.note,
    )

    draft = InvoiceDraft(
        draft_id=draft_id,
        case_id=case_id,
        company_name=company_name.strip(),
        buyer=buyer,
        lines=lines,
        raw_text=raw_text,
        note=note.strip(),
        issues=issues,
        source_images=attachments,
        workbook_name="开票明细表.xlsx",
        created_at=datetime.now().isoformat(timespec="seconds"),
        invoice_kind=invoice_profile["invoice_kind"],
        invoice_medium=invoice_profile["invoice_medium"],
        special_business=invoice_profile["special_business"],
        ocr_status=ocr_result.status,
        ocr_engine=ocr_result.engine,
        ocr_text=ocr_result.combined_text,
        ocr_note=ocr_result.note,
        source_doc_status=document_result.status,
        source_doc_text=document_result.combined_text,
        source_doc_note=document_result.note,
        extract_strategy=extraction.strategy,
        llm_provider=extraction.llm_provider,
        extract_warnings=extraction.warnings,
    )
    save_draft(draft)
    record_case_event(
        case_id=draft.case_id,
        draft_id=draft.draft_id,
        event_type="draft_created",
        payload={
            **draft_snapshot(draft),
            "attachment_count": len(attachments),
            "source_doc_status": document_result.status,
            "ocr_status": ocr_result.status,
        },
    )
    return draft


def update_draft_from_form(
    draft_id: str,
    *,
    company_name: str,
    raw_text: str,
    note: str,
    buyer: BuyerInfo,
    lines: list[InvoiceLine],
    invoice_kind: str,
    invoice_medium: str,
    special_business: str,
    uploaded_files: list[FileStorage],
) -> InvoiceDraft:
    existing = load_draft(draft_id)
    if existing is None:
        raise FileNotFoundError(draft_id)

    attachments = [*existing.source_images, *_save_uploads(draft_directory(draft_id), uploaded_files)]
    document_result = _run_document_extraction(draft_directory(draft_id), attachments)
    ocr_result = _run_draft_ocr(draft_directory(draft_id), attachments)
    extraction = extract_invoice_structured_data(
        raw_text=raw_text,
        note=note,
        document_text=document_result.combined_text,
        ocr_text=ocr_result.combined_text,
    )
    parse_source = extraction.parse_source
    inferred_buyer = extraction.buyer
    inferred_buyer = _enrich_buyer_from_sheet_context(company_name, inferred_buyer, parse_source)
    inferred_lines = extraction.lines
    inferred_profile = _infer_invoice_profile(parse_source, note=note)
    resolved_buyer = BuyerInfo(
        name=buyer.name or inferred_buyer.name,
        tax_id=buyer.tax_id or inferred_buyer.tax_id,
        address=buyer.address or inferred_buyer.address,
        phone=buyer.phone or inferred_buyer.phone,
        bank_name=buyer.bank_name or inferred_buyer.bank_name,
        bank_account=buyer.bank_account or inferred_buyer.bank_account,
    )
    resolved_lines = lines or inferred_lines
    manual_input_lines = bool(lines)
    if manual_input_lines:
        _mark_manual_coding_changes(resolved_lines, existing.lines)
    resolved_lines = enrich_invoice_lines(
        resolved_lines,
        raw_text=parse_source,
        note=note,
        preserve_existing_tax_rate=manual_input_lines,
    )
    learned_rule_rows = []
    if manual_input_lines:
        learned_rule_rows = write_learned_rules_from_manual_update(
            before_lines=existing.lines,
            after_lines=resolved_lines,
            case_id=existing.case_id or draft_id,
            draft_id=draft_id,
            company_name=company_name,
        )
    issues = _build_draft_issues(
        company_name=company_name,
        raw_text=raw_text,
        attachments=attachments,
        buyer=resolved_buyer,
        lines=resolved_lines,
        special_business=(special_business or existing.special_business or inferred_profile["special_business"]),
        document_status=document_result.status,
        document_note=document_result.note,
        ocr_status=ocr_result.status,
        ocr_note=ocr_result.note,
    )

    draft = InvoiceDraft(
        draft_id=draft_id,
        case_id=existing.case_id or draft_id,
        company_name=company_name.strip(),
        buyer=resolved_buyer,
        lines=resolved_lines,
        raw_text=raw_text,
        note=note.strip(),
        issues=issues,
        source_images=attachments,
        workbook_name=existing.workbook_name or "开票明细表.xlsx",
        created_at=existing.created_at,
        invoice_kind=invoice_kind or existing.invoice_kind or inferred_profile["invoice_kind"],
        invoice_medium=invoice_medium or existing.invoice_medium or inferred_profile["invoice_medium"],
        special_business=special_business or existing.special_business or inferred_profile["special_business"],
        ocr_status=ocr_result.status,
        ocr_engine=ocr_result.engine,
        ocr_text=ocr_result.combined_text,
        ocr_note=ocr_result.note,
        source_doc_status=document_result.status,
        source_doc_text=document_result.combined_text,
        source_doc_note=document_result.note,
        extract_strategy=extraction.strategy,
        llm_provider=extraction.llm_provider,
        extract_warnings=extraction.warnings,
    )
    save_draft(draft)
    edit_diffs = diff_drafts(existing, draft)
    record_case_event(
        case_id=draft.case_id,
        draft_id=draft.draft_id,
        event_type="draft_updated",
        payload={
            **draft_snapshot(draft),
            "diff_count": len(edit_diffs),
        },
    )
    if edit_diffs:
        record_case_event(
            case_id=draft.case_id,
            draft_id=draft.draft_id,
            event_type="manual_edits_recorded",
            payload={"diffs": edit_diffs},
        )
    if learned_rule_rows:
        record_case_event(
            case_id=draft.case_id,
            draft_id=draft.draft_id,
            event_type="local_learned_rules_saved",
            payload={
                "rule_count": len(learned_rule_rows),
                "rules": learned_rule_rows,
            },
        )
    return draft


def _mark_manual_coding_changes(current_lines: list[InvoiceLine], previous_lines: list[InvoiceLine]) -> None:
    for index, current in enumerate(current_lines):
        if index >= len(previous_lines):
            continue
        previous = previous_lines[index]
        changes = []
        for field_name, label in (
            ("tax_category", "赋码大类"),
            ("tax_code", "税收编码"),
            ("tax_rate", "税率"),
        ):
            old_value = _manual_compare_value(previous, field_name)
            new_value = _manual_compare_value(current, field_name)
            if old_value == new_value:
                continue
            changes.append(f"{label}: {old_value or '空'} -> {new_value or '空'}")
        if not changes:
            continue
        current_reference = current.coding_reference.strip()
        if current_reference.startswith("人工修正赋码"):
            current.coding_reference = "人工修正赋码: " + "；".join(changes)
            continue
        origin = f"；原依据: {current_reference}" if current_reference else ""
        current.coding_reference = "人工修正赋码: " + "；".join(changes) + origin


def _manual_compare_value(line: InvoiceLine, field_name: str) -> str:
    if field_name == "tax_rate":
        return line.normalized_tax_rate()
    return str(getattr(line, field_name, "") or "").strip()


def save_draft(draft: InvoiceDraft) -> None:
    draft_dir = draft_directory(draft.draft_id)
    draft_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "draft_id": draft.draft_id,
        "case_id": draft.case_id,
        "company_name": draft.company_name,
        "buyer": asdict(draft.buyer),
        "lines": [asdict(line) for line in draft.lines],
        "raw_text": draft.raw_text,
        "note": draft.note,
        "issues": draft.issues,
        "source_images": [asdict(image) for image in draft.source_images],
        "workbook_name": draft.workbook_name,
        "created_at": draft.created_at,
        "invoice_kind": draft.invoice_kind,
        "invoice_medium": draft.invoice_medium,
        "special_business": draft.special_business,
        "ocr_status": draft.ocr_status,
        "ocr_engine": draft.ocr_engine,
        "ocr_text": draft.ocr_text,
        "ocr_note": draft.ocr_note,
        "source_doc_status": draft.source_doc_status,
        "source_doc_text": draft.source_doc_text,
        "source_doc_note": draft.source_doc_note,
        "extract_strategy": draft.extract_strategy,
        "llm_provider": draft.llm_provider,
        "extract_warnings": draft.extract_warnings,
    }
    (draft_dir / "draft.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (draft_dir / "raw_text.txt").write_text(draft.raw_text, encoding="utf-8")
    (draft_dir / "source_docs_text.txt").write_text(draft.source_doc_text, encoding="utf-8")
    (draft_dir / "ocr_text.txt").write_text(draft.ocr_text, encoding="utf-8")
    (draft_dir / "source_combined.txt").write_text(draft.combined_source_text(), encoding="utf-8")
    (draft_dir / "ocr_meta.json").write_text(
        json.dumps(
            {
                "status": draft.ocr_status,
                "engine": draft.ocr_engine,
                "note": draft.ocr_note,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_workbook(draft_dir / draft.workbook_name, draft)
    sync_draft_to_ledger(draft)


def save_draft_batch(batch: DraftBatch) -> None:
    batch_dir = draft_directory(batch.batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "batch_id": batch.batch_id,
        "case_id": batch.case_id,
        "company_name": batch.company_name,
        "created_at": batch.created_at,
        "items": [asdict(item) for item in batch.items],
        "raw_text": batch.raw_text,
        "note": batch.note,
        "issues": batch.issues,
        "source_images": [asdict(image) for image in batch.source_images],
        "invoice_kind": batch.invoice_kind,
        "invoice_medium": batch.invoice_medium,
        "special_business": batch.special_business,
        "extract_strategy": batch.extract_strategy,
        "llm_provider": batch.llm_provider,
        "extract_warnings": batch.extract_warnings,
    }
    (batch_dir / "batch.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (batch_dir / "raw_text.txt").write_text(batch.raw_text, encoding="utf-8")


def load_draft_batch(batch_id: str) -> DraftBatch | None:
    batch_path = draft_directory(batch_id) / "batch.json"
    if not batch_path.exists():
        return None
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    return DraftBatch(
        batch_id=payload["batch_id"],
        case_id=payload.get("case_id", payload["batch_id"]),
        company_name=payload.get("company_name", ""),
        created_at=payload.get("created_at", ""),
        items=[DraftBatchItem(**item) for item in payload.get("items", [])],
        raw_text=payload.get("raw_text", ""),
        note=payload.get("note", ""),
        issues=payload.get("issues", []),
        source_images=[DraftAttachment(**item) for item in payload.get("source_images", [])],
        invoice_kind=payload.get("invoice_kind", "普通发票"),
        invoice_medium=payload.get("invoice_medium", "电子发票"),
        special_business=payload.get("special_business", ""),
        extract_strategy=payload.get("extract_strategy", "rules_only"),
        llm_provider=payload.get("llm_provider", ""),
        extract_warnings=payload.get("extract_warnings", []),
    )


def load_draft(draft_id: str) -> InvoiceDraft | None:
    draft_path = draft_directory(draft_id) / "draft.json"
    if not draft_path.exists():
        return None
    payload = json.loads(draft_path.read_text(encoding="utf-8"))
    return InvoiceDraft(
        draft_id=payload["draft_id"],
        case_id=payload.get("case_id", payload["draft_id"]),
        company_name=payload.get("company_name", ""),
        buyer=BuyerInfo(**payload.get("buyer", {})),
        lines=[InvoiceLine(**line) for line in payload.get("lines", [])],
        raw_text=payload.get("raw_text", ""),
        note=payload.get("note", ""),
        issues=payload.get("issues", []),
        source_images=[DraftAttachment(**item) for item in payload.get("source_images", [])],
        workbook_name=payload.get("workbook_name", ""),
        created_at=payload.get("created_at", ""),
        invoice_kind=payload.get("invoice_kind", "普通发票"),
        invoice_medium=payload.get("invoice_medium", "电子发票"),
        special_business=payload.get("special_business", ""),
        ocr_status=payload.get("ocr_status", "not_requested"),
        ocr_engine=payload.get("ocr_engine", ""),
        ocr_text=payload.get("ocr_text", ""),
        ocr_note=payload.get("ocr_note", ""),
        source_doc_status=payload.get("source_doc_status", "not_requested"),
        source_doc_text=payload.get("source_doc_text", ""),
        source_doc_note=payload.get("source_doc_note", ""),
        extract_strategy=payload.get("extract_strategy", "rules_only"),
        llm_provider=payload.get("llm_provider", ""),
        extract_warnings=payload.get("extract_warnings", []),
    )


def draft_directory(draft_id: str) -> Path:
    return WORKBENCH_ROOT / draft_id


def _create_split_draft_batch(
    *,
    batch_id: str,
    case_id: str,
    draft_dir: Path,
    company_name: str,
    raw_text: str,
    note: str,
    buyer: BuyerInfo,
    attachments: list[DraftAttachment],
    document_result,
    ocr_result,
    invoice_profile: dict[str, str],
    split_lines: list[InvoiceLine],
    extract_strategy: str,
    llm_provider: str,
    extract_warnings: list[str],
) -> DraftBatch:
    batch_issues = [
        "当前材料命中了“一份输入 -> 多张草稿”规则；系统已按金额自动拆成多张待复核草稿。",
        "这类草稿通常来自聊天里只给买方资料、税点和多笔金额。请重点复核每张草稿的项目名称、税率和票种。",
    ]
    items: list[DraftBatchItem] = []

    for line in split_lines:
        child_draft_id = uuid4().hex[:10]
        child_dir = draft_directory(child_draft_id)
        child_dir.mkdir(parents=True, exist_ok=True)
        child_attachments = _clone_attachments_to_directory(
            source_dir=draft_dir,
            target_dir=child_dir,
            attachments=attachments,
        )
        enriched_lines = enrich_invoice_lines([line], raw_text=_compose_parse_source(raw_text, document_result.combined_text, ocr_result.combined_text), note=note)
        child_issues = _build_draft_issues(
            company_name=company_name,
            raw_text=raw_text,
            attachments=child_attachments,
            buyer=buyer,
            lines=enriched_lines,
            special_business=invoice_profile["special_business"],
            document_status=document_result.status,
            document_note=document_result.note,
            ocr_status=ocr_result.status,
            ocr_note=ocr_result.note,
        )
        child_issues.insert(0, "本草稿由金额拆票规则自动生成；请复核项目名称、税率和是否确实需要分两张票开具。")
        child_draft = InvoiceDraft(
            draft_id=child_draft_id,
            case_id=case_id,
            company_name=company_name.strip(),
            buyer=buyer,
            lines=enriched_lines,
            raw_text=raw_text,
            note=note.strip(),
            issues=child_issues,
            source_images=child_attachments,
            workbook_name="开票明细表.xlsx",
            created_at=datetime.now().isoformat(timespec="seconds"),
            invoice_kind=invoice_profile["invoice_kind"],
            invoice_medium=invoice_profile["invoice_medium"],
            special_business=invoice_profile["special_business"],
            ocr_status=ocr_result.status,
            ocr_engine=ocr_result.engine,
            ocr_text=ocr_result.combined_text,
            ocr_note=ocr_result.note,
            source_doc_status=document_result.status,
            source_doc_text=document_result.combined_text,
            source_doc_note=document_result.note,
            extract_strategy=extract_strategy,
            llm_provider=llm_provider,
            extract_warnings=list(extract_warnings),
        )
        save_draft(child_draft)
        record_case_event(
            case_id=case_id,
            draft_id=child_draft_id,
            batch_id=batch_id,
            event_type="split_child_draft_created",
            payload=draft_snapshot(child_draft),
        )
        items.append(
            DraftBatchItem(
                draft_id=child_draft_id,
                buyer_name=buyer.name,
                invoice_kind=invoice_profile["invoice_kind"],
                amount_total=line.resolved_amount_with_tax(),
                project_summary=_summarize_projects(enriched_lines),
                line_count=len(enriched_lines),
                issue_summary=child_issues[0] if child_issues else "",
            )
        )

    batch = DraftBatch(
        batch_id=batch_id,
        case_id=case_id,
        company_name=company_name.strip(),
        created_at=datetime.now().isoformat(timespec="seconds"),
        items=items,
        raw_text=raw_text,
        note=note.strip(),
        issues=batch_issues,
        source_images=attachments,
        invoice_kind=invoice_profile["invoice_kind"],
        invoice_medium=invoice_profile["invoice_medium"],
        special_business=invoice_profile["special_business"],
        extract_strategy=extract_strategy,
        llm_provider=llm_provider,
        extract_warnings=list(extract_warnings),
    )
    save_draft_batch(batch)
    record_case_event(
        case_id=case_id,
        batch_id=batch_id,
        event_type="draft_batch_created",
        payload=batch_snapshot(batch),
    )
    return batch


def _save_uploads(draft_dir: Path, uploaded_files: list[FileStorage]) -> list[DraftAttachment]:
    uploads_dir = draft_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    attachments: list[DraftAttachment] = []
    next_index = len([path for path in uploads_dir.iterdir() if path.is_file()]) + 1

    for file in uploaded_files:
        if not file.filename:
            continue
        original_name = Path(file.filename).name
        safe_base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", Path(original_name).stem).strip("_") or f"image_{next_index}"
        suffix = Path(original_name).suffix.lower() or ".bin"
        stored_name = f"{next_index:02d}_{safe_base}{suffix}"
        target = uploads_dir / stored_name
        file.save(target)
        attachments.append(
            DraftAttachment(
                original_name=original_name,
                stored_name=f"uploads/{stored_name}",
                mime_type=file.mimetype or "",
                size_bytes=target.stat().st_size,
            )
        )
        next_index += 1
    return attachments


def _clone_attachments_to_directory(*, source_dir: Path, target_dir: Path, attachments: list[DraftAttachment]) -> list[DraftAttachment]:
    cloned: list[DraftAttachment] = []
    for attachment in attachments:
        source_path = source_dir / attachment.stored_name
        target_path = target_dir / attachment.stored_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.exists():
            shutil.copy2(source_path, target_path)
        cloned.append(
            DraftAttachment(
                original_name=attachment.original_name,
                stored_name=attachment.stored_name,
                mime_type=attachment.mime_type,
                size_bytes=attachment.size_bytes,
            )
        )
    return cloned


def _write_workbook(path: Path, draft: InvoiceDraft) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "开票明细"
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
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DCEFE9")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for line in draft.lines:
        sheet.append(
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
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:K{max(sheet.max_row, 1)}"
    widths = {
        "A": 28,
        "B": 18,
        "C": 24,
        "D": 18,
        "E": 18,
        "F": 10,
        "G": 10,
        "H": 12,
        "I": 14,
        "J": 12,
        "K": 34,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width

    meta = workbook.create_sheet("来源")
    meta["A1"] = "Case ID"
    meta["B1"] = draft.case_id
    meta["A2"] = "草稿ID"
    meta["B2"] = draft.draft_id
    meta["A3"] = "纳税主体"
    meta["B3"] = draft.company_name
    meta["A4"] = "购买方名称"
    meta["B4"] = draft.buyer.name
    meta["A5"] = "购买方税号"
    meta["B5"] = draft.buyer.tax_id
    meta["A6"] = "生成时间"
    meta["B6"] = draft.created_at
    meta["A7"] = "票种配置"
    meta["B7"] = f"{draft.invoice_medium} / {draft.invoice_kind}" + (f" / {draft.special_business}" if draft.special_business else "")
    meta["A8"] = "抽取策略"
    meta["B8"] = draft.extract_strategy
    meta["A9"] = "LLM Provider"
    meta["B9"] = draft.llm_provider
    meta["A10"] = "原始输入"
    meta["B10"] = draft.raw_text
    meta["A11"] = "备注"
    meta["B11"] = draft.note
    meta["A12"] = "附件"
    meta["B12"] = "\n".join(item.original_name for item in draft.source_images)
    meta["A13"] = "文档解析状态"
    meta["B13"] = draft.source_doc_status
    meta["A14"] = "文档解析备注"
    meta["B14"] = draft.source_doc_note
    meta["A15"] = "识别提醒"
    meta["B15"] = "\n".join(draft.issues + draft.extract_warnings)
    meta["A16"] = "OCR 状态"
    meta["B16"] = draft.ocr_status
    meta["A17"] = "OCR 引擎"
    meta["B17"] = draft.ocr_engine
    meta["A18"] = "OCR 备注"
    meta["B18"] = draft.ocr_note
    meta.column_dimensions["A"].width = 14
    meta.column_dimensions["B"].width = 90
    for row in range(1, 19):
        meta[f"B{row}"].alignment = Alignment(wrap_text=True, vertical="top")

    workbook.save(path)


def _compose_parse_source(raw_text: str, document_text: str, ocr_text: str) -> str:
    return "\n\n".join(part for part in [raw_text.strip(), document_text.strip(), ocr_text.strip()] if part)


def _build_amount_split_lines(
    *,
    company_name: str,
    parse_source: str,
    buyer: BuyerInfo,
    lines: list[InvoiceLine],
    invoice_profile: dict[str, str],
) -> list[InvoiceLine]:
    if lines or not buyer.name or not buyer.tax_id:
        return []

    amounts = _extract_split_amounts(parse_source)
    if len(amounts) < 2:
        return []

    line_profile = _infer_split_line_profile(
        company_name=company_name,
        parse_source=parse_source,
        invoice_profile=invoice_profile,
    )
    if not line_profile:
        return []

    return [
        InvoiceLine(
            project_name=line_profile["project_name"],
            amount_with_tax=amount,
            tax_rate=line_profile["tax_rate"],
            tax_category=line_profile["tax_category"],
            coding_reference=line_profile["coding_reference"],
        )
        for amount in amounts
    ]


def _extract_split_amounts(parse_source: str) -> list[str]:
    lines = [line.strip() for line in parse_source.splitlines() if line.strip()]
    staged: list[str] = []
    capture = False

    for line in lines:
        compact = line.replace(" ", "")
        if compact in {"金额", "开票金额", "金额：", "金额:"}:
            capture = True
            continue
        if capture:
            if _looks_like_split_amount_line(compact):
                staged.append(_normalize_amount_text(compact))
                continue
            if staged:
                break

    if len(staged) >= 2:
        return _dedupe_preserving_order(staged)

    fallbacks: list[str] = []
    for line in lines:
        compact = line.replace(" ", "")
        if _looks_like_split_amount_line(compact):
            fallbacks.append(_normalize_amount_text(compact))
    return _dedupe_preserving_order(fallbacks)


def _looks_like_split_amount_line(value: str) -> bool:
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        return False
    if "." not in value and len(value) > 6:
        return False
    return True


def _normalize_amount_text(value: str) -> str:
    compact = value.replace(",", "").replace("，", "").replace(" ", "")
    if "." in compact:
        whole, decimal = compact.split(".", 1)
        return f"{whole}.{decimal[:2].ljust(2, '0')}"
    return f"{compact}.00"


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _infer_split_line_profile(
    *,
    company_name: str,
    parse_source: str,
    invoice_profile: dict[str, str],
) -> dict[str, str] | None:
    compact = f"{company_name}\n{parse_source}".replace(" ", "")
    tax_rate = _infer_split_tax_rate(compact)
    if tax_rate != "1%":
        return None

    if re.search(r"(服务|科技|咨询|传媒|调试|运营|出租汽车|网约车)", compact):
        return {
            "project_name": "服务费",
            "tax_category": "现代服务",
            "tax_rate": tax_rate,
            "coding_reference": "金额拆票规则：聊天只给买方资料、多个金额和一个点票种，系统按现代服务/服务费自动拆成多张草稿。",
        }

    if invoice_profile.get("invoice_kind") == "增值税专用发票":
        return {
            "project_name": "服务费",
            "tax_category": "现代服务",
            "tax_rate": tax_rate,
            "coding_reference": "金额拆票规则：当前材料未给出明确项目名，先按通用服务费口径拆成多张草稿，待人工确认。",
        }
    return None


def _infer_split_tax_rate(compact_text: str) -> str:
    if re.search(r"(一个点|1个点|一%|1%)", compact_text):
        return "1%"
    return "3%"


def _summarize_projects(lines: list[InvoiceLine]) -> str:
    names = [line.project_name for line in lines if line.project_name]
    if not names:
        return "待人工补充"
    return " / ".join(names[:3])


def _infer_invoice_profile(parse_source: str, *, note: str = "") -> dict[str, str]:
    context = f"{parse_source}\n{note}".strip()
    compact = context.replace(" ", "")

    invoice_kind = "普通发票"
    invoice_medium = "电子发票"
    special_business = ""

    labeled_type = re.search(
        r"(?:发票类型|票种|开票类型)[：:\t ]?(增值税专用发票|专用发票|专票|增票|增值税普通发票|普通发票|普票)",
        compact,
    )
    checked_special = re.search(r"(?:增值税专用发票|专用发票)(?:[（(]?[√✓✔][）)]?)", compact)
    checked_normal = re.search(r"(?:增值税普通发票|普通发票)(?:[（(]?[√✓✔][）)]?)", compact)
    explicit_special = bool(re.search(r"(开专票|专票)", compact))
    explicit_normal = bool(re.search(r"(开普票|普票|普通发票（?√|普通发票√|增值税普通发票（?√|增值税普通发票√)", compact))

    if labeled_type and labeled_type.group(1) in {"普通发票", "增值税普通发票", "普票"}:
        invoice_kind = "普通发票"
        explicit_normal = True
    elif labeled_type and labeled_type.group(1) in {"增值税专用发票", "专用发票", "专票", "增票"}:
        invoice_kind = "增值税专用发票"
        explicit_special = True
    elif checked_normal and not checked_special:
        invoice_kind = "普通发票"
    elif checked_special and not checked_normal:
        invoice_kind = "增值税专用发票"
    elif explicit_normal and not explicit_special:
        invoice_kind = "普通发票"
    elif explicit_special and not explicit_normal:
        invoice_kind = "增值税专用发票"
    elif "增值税专用发票" in compact and "增值税普通发票" not in compact and "普通发票" not in compact:
        invoice_kind = "增值税专用发票"

    if re.search(r"(纸质发票|纸票)", compact):
        invoice_medium = "纸质发票"

    if invoice_kind == "普通发票" and not explicit_normal:
        has_tax_id = bool(re.search(r"(税务登记号|税号|纳税人识别号|统一社会信用代码)", compact))
        has_address = bool(re.search(r"(单位地址|购买方地址|购方地址|地址)", compact))
        has_phone = bool(re.search(r"(电话号码|购买方电话|购方电话|电话)", compact))
        has_bank = bool(re.search(r"(开户行|开户银行)", compact))
        has_account = bool(re.search(r"(银行账号|账号)", compact))
        if has_tax_id and has_bank and has_account and (has_address or has_phone):
            invoice_kind = "增值税专用发票"

    if re.search(r"(机动车|车架号|车辆识别代号|VIN|合格证|厂牌型号|发动机号|发动机号码)", compact, re.IGNORECASE):
        special_business = "机动车"

    return {
        "invoice_kind": invoice_kind,
        "invoice_medium": invoice_medium,
        "special_business": special_business,
    }


def _enrich_buyer_from_sheet_context(company_name: str, buyer: BuyerInfo, parse_source: str) -> BuyerInfo:
    resolved = BuyerInfo(
        name=buyer.name,
        tax_id=buyer.tax_id,
        address=buyer.address,
        phone=buyer.phone,
        bank_name=buyer.bank_name,
        bank_account=buyer.bank_account,
    )
    current_company = company_name.strip()
    inside_billing_block = False

    for raw_line in parse_source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("需方") and not resolved.name:
            matched = re.search(r"需方\s+(.+?公司)", line)
            if matched:
                candidate = matched.group(1).strip()
                if candidate and candidate != current_company:
                    resolved.name = candidate
                    continue
        if "开票资料" in line:
            inside_billing_block = True
            continue
        if not inside_billing_block and not any(
            marker in line for marker in ("单位名称", "单位地址", "电话号码", "税务登记号", "开户行", "开户银行", "账号", "银行账户")
        ):
            continue

        key, value = _split_possible_key_value(line)
        if not key or not value:
            continue
        value = value.strip()
        if not value:
            continue

        if "单位名称" in key and not resolved.name and value != current_company:
            resolved.name = value
            continue
        if "税务登记号" in key and not resolved.tax_id:
            tax_id_match = re.search(r"([0-9A-Z]{15,20})", value.upper())
            resolved.tax_id = tax_id_match.group(1) if tax_id_match else value
            continue
        if "单位地址" in key and not resolved.address:
            resolved.address = value
            continue
        if "电话号码" in key and not resolved.phone:
            resolved.phone = value
            continue
        if ("开户行" in key or "开户银行" in key) and not resolved.bank_name:
            resolved.bank_name = value
            continue
        if key in {"账号", "银行账号", "银行账户"} and not resolved.bank_account:
            resolved.bank_account = value

    return resolved


def _split_possible_key_value(line: str) -> tuple[str, str]:
    if "：" in line:
        left, right = line.split("：", 1)
        return left.strip(), right.strip()
    if ":" in line:
        left, right = line.split(":", 1)
        return left.strip(), right.strip()
    return "", ""


def _build_draft_issues(
    *,
    company_name: str,
    raw_text: str,
    attachments: list[DraftAttachment],
    buyer: BuyerInfo,
    lines: list[InvoiceLine],
    special_business: str,
    document_status: str,
    document_note: str,
    ocr_status: str,
    ocr_note: str,
) -> list[str]:
    issues: list[str] = []
    has_image_attachments = any(
        Path(item.stored_name).suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
        for item in attachments
    )
    if not company_name.strip():
        issues.append("当前还没填写纳税主体名称；执行前请补充当前已登录企业。")
    if not raw_text.strip() and not attachments:
        issues.append("请输入原始开票信息，或至少上传一份材料。")
    if document_note and document_status not in {"not_requested", "success"}:
        issues.append(document_note)
    if has_image_attachments and ocr_note:
        issues.append(ocr_note)
    if not buyer.name:
        issues.append("当前还没自动识别出购买方名称，请在草稿页人工补充。")
    if not lines:
        if attachments and ocr_status in {"success", "partial"}:
            issues.append("图片文字已经提取，但当前还没稳定抽出明细行；请在草稿页人工补充。")
        else:
            issues.append("当前还没自动识别出开票明细，请在草稿页人工补充。")
    formal_library_size = len(load_formal_coding_library())
    if lines and formal_library_size:
        unresolved_indexes = [
            str(index)
            for index, line in enumerate(lines, start=1)
            if not line.tax_category or not line.tax_code
        ]
        if unresolved_indexes:
            issues.append(
                "第 "
                + "、".join(unresolved_indexes)
                + " 行还没命中正式赋码库，请人工确认赋码大类 / 税率 / 税收编码。"
            )
        special_tax_indexes = [
            str(index)
            for index, line in enumerate(lines, start=1)
            if line.normalized_tax_rate() in {"免税", "不征税", "免征增值税"}
        ]
        if special_tax_indexes:
            issues.append(
                "第 "
                + "、".join(special_tax_indexes)
                + " 行命中了免税/不征税口径，请在执行前再次确认客户场景与票面口径一致。"
            )
    if special_business == "机动车":
        issues.append("系统从材料中识别出机动车线索，建议在草稿里确认 `特定业务 = 机动车` 后再执行。")
    return issues


def _run_draft_ocr(draft_dir: Path, attachments: list[DraftAttachment]):
    image_paths = [
        draft_dir / item.stored_name
        for item in attachments
        if Path(item.stored_name).suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
    ]
    return run_optional_ocr(image_paths)


def _run_document_extraction(draft_dir: Path, attachments: list[DraftAttachment]):
    file_paths = [draft_dir / item.stored_name for item in attachments]
    result = extract_supported_documents(file_paths)
    (draft_dir / "source_doc_meta.json").write_text(serialize_document_results(result), encoding="utf-8")
    return result

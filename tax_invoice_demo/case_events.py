from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .models import BuyerInfo, DraftBatch, InvoiceDraft

EVENT_ROOT = Path(__file__).resolve().parent.parent / "output" / "workbench" / "tax_invoice_demo" / "_events"
EVENT_IO_LOCK = Lock()


def record_case_event(
    *,
    case_id: str,
    event_type: str,
    payload: dict,
    draft_id: str = "",
    batch_id: str = "",
) -> dict:
    EVENT_ROOT.mkdir(parents=True, exist_ok=True)
    event = {
        "event_id": uuid4().hex[:12],
        "case_id": case_id,
        "draft_id": draft_id,
        "batch_id": batch_id,
        "event_type": event_type,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "schema_version": "execution_event_v1",
        "runtime": _runtime_context(),
        "payload": payload,
    }
    append_jsonl(_pending_events_path(), event)
    append_jsonl(_case_events_path(case_id), event)
    try:
        from .sync_service import schedule_background_flush

        schedule_background_flush()
    except Exception:
        pass
    return event


def _runtime_context() -> dict:
    return {
        "app": "invoice-demo-batch-import",
        "app_version": os.getenv("TAX_INVOICE_APP_VERSION", "local-workbench"),
        "package_version": os.getenv("TAX_INVOICE_PACKAGE_VERSION", ""),
        "operator_alias": os.getenv("TAX_INVOICE_OPERATOR_ALIAS", ""),
        "device_alias": os.getenv("TAX_INVOICE_DEVICE_ALIAS", platform.node()),
        "os": platform.platform(),
        "python": platform.python_version(),
    }


def draft_snapshot(draft: InvoiceDraft) -> dict:
    return {
        "case_id": draft.case_id,
        "draft_id": draft.draft_id,
        "company_name": draft.company_name,
        "buyer": asdict(draft.buyer),
        "invoice_kind": draft.invoice_kind,
        "invoice_medium": draft.invoice_medium,
        "special_business": draft.special_business,
        "note": draft.note,
        "extract_strategy": draft.extract_strategy,
        "llm_provider": draft.llm_provider,
        "extract_warnings": list(draft.extract_warnings),
        "issues": list(draft.issues),
        "lines": [asdict(line) for line in draft.lines],
        "material_summary": _attachment_summary(draft.source_images),
    }


def batch_snapshot(batch: DraftBatch) -> dict:
    return {
        "case_id": batch.case_id,
        "batch_id": batch.batch_id,
        "company_name": batch.company_name,
        "invoice_kind": batch.invoice_kind,
        "invoice_medium": batch.invoice_medium,
        "special_business": batch.special_business,
        "extract_strategy": batch.extract_strategy,
        "llm_provider": batch.llm_provider,
        "extract_warnings": list(batch.extract_warnings),
        "issue_count": len(batch.issues),
        "item_count": len(batch.items),
        "items": [asdict(item) for item in batch.items],
        "material_summary": _attachment_summary(batch.source_images),
    }


def _attachment_summary(attachments: list) -> dict:
    suffixes: dict[str, int] = {}
    total_size = 0
    names: list[str] = []
    for item in attachments or []:
        original_name = str(getattr(item, "original_name", "") or "")
        stored_name = str(getattr(item, "stored_name", "") or original_name)
        suffix = Path(original_name or stored_name).suffix.lower() or "unknown"
        suffixes[suffix] = suffixes.get(suffix, 0) + 1
        total_size += int(getattr(item, "size_bytes", 0) or 0)
        if original_name:
            names.append(original_name)
    return {
        "file_count": len(attachments or []),
        "file_types": suffixes,
        "total_size_bytes": total_size,
        "file_names": names[:12],
    }


def diff_drafts(before: InvoiceDraft, after: InvoiceDraft) -> list[dict[str, str]]:
    diffs: list[dict[str, str]] = []
    _append_buyer_diff(diffs, "购买方名称", before.buyer.name, after.buyer.name)
    _append_buyer_diff(diffs, "购买方税号", before.buyer.tax_id, after.buyer.tax_id)
    _append_buyer_diff(diffs, "购买方地址", before.buyer.address, after.buyer.address)
    _append_buyer_diff(diffs, "购买方电话", before.buyer.phone, after.buyer.phone)
    _append_buyer_diff(diffs, "购买方开户行", before.buyer.bank_name, after.buyer.bank_name)
    _append_buyer_diff(diffs, "购买方银行账号", before.buyer.bank_account, after.buyer.bank_account)
    _append_buyer_diff(diffs, "发票类型", before.invoice_kind, after.invoice_kind)
    _append_buyer_diff(diffs, "特定业务", before.special_business, after.special_business)
    _append_buyer_diff(diffs, "备注", before.note, after.note)

    line_count = max(len(before.lines), len(after.lines))
    for index in range(line_count):
        before_line = before.lines[index] if index < len(before.lines) else None
        after_line = after.lines[index] if index < len(after.lines) else None
        if before_line is None and after_line is not None:
            diffs.append(
                {
                    "field_name": f"第 {index + 1} 行",
                    "before": "空",
                    "after": json.dumps(asdict(after_line), ensure_ascii=False),
                    "edit_source": "user",
                }
            )
            continue
        if before_line is not None and after_line is None:
            diffs.append(
                {
                    "field_name": f"第 {index + 1} 行",
                    "before": json.dumps(asdict(before_line), ensure_ascii=False),
                    "after": "已删除",
                    "edit_source": "user",
                }
            )
            continue
        if before_line is None or after_line is None:
            continue
        for field_name, label in (
            ("project_name", "项目名称"),
            ("tax_category", "赋码大类"),
            ("tax_code", "税收编码"),
            ("specification", "规格型号"),
            ("unit", "单位"),
            ("quantity", "数量"),
            ("unit_price", "单价"),
            ("amount_with_tax", "含税金额"),
            ("tax_rate", "税率"),
            ("coding_reference", "赋码说明"),
        ):
            before_value = getattr(before_line, field_name, "") or ""
            after_value = getattr(after_line, field_name, "") or ""
            if before_value == after_value:
                continue
            diffs.append(
                {
                    "field_name": f"第 {index + 1} 行{label}",
                    "before": str(before_value),
                    "after": str(after_value),
                    "edit_source": "user",
                }
            )
    return diffs


def _append_buyer_diff(diffs: list[dict[str, str]], label: str, before: str, after: str) -> None:
    if (before or "") == (after or ""):
        return
    diffs.append(
        {
            "field_name": label,
            "before": before or "",
            "after": after or "",
            "edit_source": "user",
        }
    )


def _pending_events_path() -> Path:
    return EVENT_ROOT / "pending_events.jsonl"


def _case_events_path(case_id: str) -> Path:
    return EVENT_ROOT / "cases" / f"{case_id}.jsonl"


def pending_events_path() -> Path:
    return _pending_events_path()


def last_sync_state_path() -> Path:
    return EVENT_ROOT / "last_sync_state.json"


def last_rule_sync_state_path() -> Path:
    return EVENT_ROOT / "last_rule_sync_state.json"


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_IO_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with EVENT_IO_LOCK:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_IO_LOCK:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_IO_LOCK:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_all_case_events() -> list[dict]:
    events: list[dict] = []
    cases_dir = EVENT_ROOT / "cases"
    if not cases_dir.exists():
        return []
    for path in sorted(cases_dir.glob("*.jsonl")):
        try:
            events.extend(read_jsonl(path))
        except Exception:
            continue
    return sorted(events, key=lambda item: item.get("created_at", ""), reverse=True)


def execution_record_summary(limit: int = 200) -> dict:
    events = read_all_case_events()
    by_case: dict[str, list[dict]] = {}
    for event in events:
        case_id = str(event.get("case_id") or "")
        if not case_id:
            continue
        by_case.setdefault(case_id, []).append(event)
    records = [_summarize_case_events(case_id, list(reversed(case_events))) for case_id, case_events in by_case.items()]
    records.sort(key=lambda item: item.get("last_at", ""), reverse=True)
    pending = read_jsonl(pending_events_path())
    metrics = {
        "case_count": len(records),
        "event_count": len(events),
        "pending_count": len(pending),
        "failed_count": sum(1 for record in records if record.get("status") == "tax_run_failed"),
        "preview_count": sum(1 for record in records if record.get("preview_reached")),
        "confirmed_count": sum(1 for record in records if record.get("assistant_confirmed")),
    }
    return {"records": records[:limit], "metrics": metrics}


def _summarize_case_events(case_id: str, events: list[dict]) -> dict:
    record = {
        "case_id": case_id,
        "draft_id": "",
        "batch_id": "",
        "created_at": events[0].get("created_at", "") if events else "",
        "last_at": events[-1].get("created_at", "") if events else "",
        "company_name": "",
        "buyer_name": "",
        "material_type": "未记录",
        "invoice_count": 1,
        "line_count": 0,
        "extract_strategy": "",
        "llm_provider": "",
        "manual_edit_count": 0,
        "export_error_count": 0,
        "export_warning_count": 0,
        "run_id": "",
        "run_status": "",
        "failure_count": 0,
        "failure_fields": [],
        "preview_reached": False,
        "assistant_confirmed": False,
        "status": "created",
        "status_label": "已创建",
        "last_event_type": events[-1].get("event_type", "") if events else "",
        "event_count": len(events),
        "events": events[-12:],
    }
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_type = str(event.get("event_type") or "")
        record["draft_id"] = str(event.get("draft_id") or record["draft_id"] or payload.get("draft_id") or "")
        record["batch_id"] = str(event.get("batch_id") or record["batch_id"] or payload.get("batch_id") or "")
        _merge_payload_identity(record, payload)
        _merge_material_summary(record, payload)
        if event_type in {"draft_created", "platform_screenshot_child_draft_created", "split_child_draft_created"}:
            record["status"] = "draft_generated"
            record["status_label"] = "草稿已生成"
        elif event_type in {"platform_screenshot_draft_batch_created", "draft_batch_created"}:
            record["status"] = "draft_generated"
            record["status_label"] = "批量草稿"
            record["invoice_count"] = int(payload.get("item_count") or len(payload.get("items") or []) or record["invoice_count"])
        elif event_type == "manual_edits_recorded":
            diffs = payload.get("diffs") if isinstance(payload.get("diffs"), list) else []
            record["manual_edit_count"] += len(diffs)
        elif event_type in {"template_exported", "batch_template_exported"}:
            record["status"] = "template_ready" if not payload.get("error_count") else "needs_review"
            record["status_label"] = "模板已生成" if not payload.get("error_count") else "待修正"
            record["export_error_count"] = int(payload.get("error_count") or 0)
            record["export_warning_count"] = int(payload.get("warning_count") or 0)
        elif event_type == "batch_run_queued":
            record["run_id"] = str(payload.get("run_id") or record["run_id"])
            record["status"] = "tax_run_queued"
            record["status_label"] = "税局执行中"
        elif event_type == "batch_run_finished":
            record["run_id"] = str(payload.get("run_id") or record["run_id"])
            record["run_status"] = str(payload.get("status") or "")
            record["failure_count"] = int(payload.get("failure_count") or 0)
            record["preview_reached"] = bool(payload.get("preview_clicked"))
            summary = payload.get("failure_summary") if isinstance(payload.get("failure_summary"), dict) else {}
            record["failure_fields"] = _extract_failure_fields(summary)
            if payload.get("status") == "done":
                record["status"] = "tax_preview_reached" if record["preview_reached"] else "tax_run_done"
                record["status_label"] = "已到预览" if record["preview_reached"] else "执行完成"
            else:
                record["status"] = "tax_run_failed"
                record["status_label"] = "税局失败"
        elif event_type in {"success_recorded", "batch_success_recorded"}:
            record["assistant_confirmed"] = True
            record["status"] = "assistant_confirmed"
            record["status_label"] = "已人工确认"
    return record


def _merge_payload_identity(record: dict, payload: dict) -> None:
    record["company_name"] = str(payload.get("company_name") or record.get("company_name") or "")
    buyer = payload.get("buyer") if isinstance(payload.get("buyer"), dict) else {}
    record["buyer_name"] = str(buyer.get("name") or payload.get("buyer_name") or record.get("buyer_name") or "")
    record["extract_strategy"] = str(payload.get("extract_strategy") or record.get("extract_strategy") or "")
    record["llm_provider"] = str(payload.get("llm_provider") or record.get("llm_provider") or "")
    lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
    if lines:
        record["line_count"] = len(lines)


def _merge_material_summary(record: dict, payload: dict) -> None:
    material_summary = payload.get("material_summary") if isinstance(payload.get("material_summary"), dict) else {}
    attachment_count = int(payload.get("attachment_count") or material_summary.get("file_count") or 0)
    if attachment_count:
        file_types = material_summary.get("file_types") if isinstance(material_summary.get("file_types"), dict) else {}
        type_text = "/".join(sorted(key.lstrip(".") for key in file_types.keys())) if file_types else "附件"
        record["material_type"] = f"{type_text} {attachment_count} 个"
    if payload.get("item_count"):
        record["material_type"] = "批量材料"
    if payload.get("source_doc_status") and payload.get("source_doc_status") != "not_requested":
        record["material_type"] = "文档材料"
    if payload.get("ocr_status") and payload.get("ocr_status") not in {"not_requested", "vision_deferred"}:
        record["material_type"] = "图片/OCR"
    if payload.get("extract_strategy") == "rules_plus_vision":
        record["material_type"] = "图片/视觉识别"


def _extract_failure_fields(summary: dict) -> list[str]:
    fields: list[str] = []
    for key in ["field_counts", "failure_fields", "fields"]:
        value = summary.get(key)
        if isinstance(value, dict):
            fields.extend(str(item) for item in value.keys())
        elif isinstance(value, list):
            fields.extend(str(item) for item in value)
    return fields[:6]

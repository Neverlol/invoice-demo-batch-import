from __future__ import annotations

import json
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

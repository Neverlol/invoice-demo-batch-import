from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .batch_template import TemplateInvoice, export_template_invoices, invoice_from_workbench_draft


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBENCH_ROOT = PACKAGE_ROOT / "output" / "workbench" / "tax_invoice_demo"
LEGACY_WORKBENCH_ROOT = PACKAGE_ROOT.parent / "output" / "workbench" / "tax_invoice_demo"


@dataclass(frozen=True)
class ExportCandidate:
    source_type: str
    identifier: str
    payload_path: Path
    draft_ids: tuple[str, ...]
    invoice_count: int


def export_saved_workbench_items(
    identifiers: list[str],
    output_path: str | Path,
    *,
    workbench_root: str | Path = DEFAULT_WORKBENCH_ROOT,
) -> Path:
    invoices: list[TemplateInvoice] = []
    for candidate in load_export_candidates(identifiers, workbench_root=workbench_root):
        for draft_id in candidate.draft_ids:
            payload = find_draft_payload(draft_id, workbench_root=workbench_root)
            draft_obj = _payload_to_namespace(payload)
            invoices.append(invoice_from_workbench_draft(draft_obj, serial_no=draft_id))
    return export_template_invoices(invoices, output_path)


def load_export_candidates(
    identifiers: list[str],
    *,
    workbench_root: str | Path = DEFAULT_WORKBENCH_ROOT,
) -> list[ExportCandidate]:
    root = Path(workbench_root)
    candidates: list[ExportCandidate] = []
    for identifier in identifiers:
        batch_payload = _safe_load_json(_resolve_payload_path(identifier, root, "batch.json"))
        if batch_payload is not None:
            draft_ids = tuple(item["draft_id"] for item in batch_payload.get("items", []))
            candidates.append(
                ExportCandidate(
                    source_type="draft_batch",
                    identifier=batch_payload.get("batch_id", identifier),
                    payload_path=_resolve_payload_path(identifier, root, "batch.json"),
                    draft_ids=draft_ids,
                    invoice_count=len(draft_ids),
                )
            )
            continue

        draft_payload = _safe_load_json(_resolve_payload_path(identifier, root, "draft.json"))
        if draft_payload is not None:
            draft_id = draft_payload.get("draft_id", identifier)
            candidates.append(
                ExportCandidate(
                    source_type="draft",
                    identifier=draft_id,
                    payload_path=_resolve_payload_path(identifier, root, "draft.json"),
                    draft_ids=(draft_id,),
                    invoice_count=1,
                )
            )
            continue

        raise FileNotFoundError(f"未找到草稿或批量草稿: {identifier}")
    return candidates


def find_draft_payload(draft_id: str, *, workbench_root: str | Path = DEFAULT_WORKBENCH_ROOT) -> dict[str, Any]:
    payload_path = _resolve_payload_path(draft_id, Path(workbench_root), "draft.json")
    payload = _safe_load_json(payload_path)
    if payload is None:
        raise FileNotFoundError(f"未找到草稿: {draft_id}")
    return payload


def find_draft_batch_payload(batch_id: str, *, workbench_root: str | Path = DEFAULT_WORKBENCH_ROOT) -> dict[str, Any]:
    payload_path = _resolve_payload_path(batch_id, Path(workbench_root), "batch.json")
    payload = _safe_load_json(payload_path)
    if payload is None:
        raise FileNotFoundError(f"未找到批量草稿: {batch_id}")
    return payload


def _resolve_payload_path(identifier: str, root: Path, filename: str) -> Path:
    candidate = Path(identifier)
    if candidate.is_file():
        return candidate
    if candidate.suffix == ".json":
        return candidate
    bundled_path = root / identifier / filename
    if bundled_path.exists():
        return bundled_path
    if root == DEFAULT_WORKBENCH_ROOT:
        legacy_path = LEGACY_WORKBENCH_ROOT / identifier / filename
        if legacy_path.exists():
            return legacy_path
    return bundled_path


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _payload_to_namespace(payload: dict[str, Any]) -> Any:
    buyer = SimpleNamespace(**payload.get("buyer", {}))
    lines = [SimpleNamespace(**line) for line in payload.get("lines", [])]
    return SimpleNamespace(
        draft_id=payload.get("draft_id", ""),
        company_name=payload.get("company_name", ""),
        buyer=buyer,
        lines=lines,
        note=payload.get("note", ""),
        invoice_kind=payload.get("invoice_kind", "普通发票"),
        invoice_medium=payload.get("invoice_medium", "电子发票"),
        special_business=payload.get("special_business", ""),
    )

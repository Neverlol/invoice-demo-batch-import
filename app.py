from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

from tax_invoice_batch_demo.batch_runner import (
    BatchImportRunner,
    BatchRunResult,
    inspect_tax_browser,
    open_tax_portal,
)
from tax_invoice_batch_demo.history_downloader import TaxHistoryDownloader
from tax_invoice_batch_demo.lean_workbench import (
    BATCH_OUTPUT_ROOT,
    SUCCESS_LEDGER_CSV,
    SUCCESS_LEDGER_XLSX,
    apply_failure_repairs_to_draft,
    create_lean_draft,
    default_form,
    draft_preview,
    enrich_failure_report_for_draft,
    export_batch_template,
    export_draft_template,
    line_form_rows,
    load_failure_report_for_draft,
    load_draft,
    load_draft_batch,
    parse_failure_file,
    record_batch_success_to_ledger,
    record_success_to_ledger,
    save_failure_report_for_draft,
    save_lean_draft_from_form,
)
from tax_invoice_demo import workbench as workbench_module
from tax_invoice_demo.case_events import execution_record_summary, record_case_event
from tax_invoice_demo.customer_profiles import PROFILE_CACHE_PATH, profile_cache_summary, profile_counts_for_seller
from tax_invoice_demo.models import BuyerInfo, DraftBatchItem, InvoiceLine
from tax_invoice_demo.sync_service import schedule_background_customer_profile_pull, schedule_background_rule_pull
from tax_invoice_demo.taxonomy_search import search_taxonomy
from tools.ingest_customer_profile_inbox import (
    DEFAULT_PROFILE_ROOT,
    ensure_dirs as ensure_profile_dirs,
    ingest_pending_files,
    rebuild_profiles,
    sync_profiles_to_cloud,
)


BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

RUNS: dict[str, dict] = {}
RUN_LOCK = Lock()


@app.get("/")
def index():
    schedule_background_rule_pull()
    schedule_background_customer_profile_pull()
    return render_template(
        "lean_index.html",
        form=default_form(),
        errors=[],
        profile_summary=profile_cache_summary(),
    )


@app.post("/drafts")
def create_draft():
    raw_text = request.form.get("raw_text", "")
    uploaded_files = request.files.getlist("source_files")
    if not raw_text.strip() and not any(file.filename for file in uploaded_files):
        return render_template(
            "lean_index.html",
            form=request.form,
            errors=["请粘贴开票信息，或上传客户提供的图片 / Excel / PDF。"],
            profile_summary=profile_cache_summary(),
        ), 400

    result = create_lean_draft(
        company_name=request.form.get("company_name", ""),
        raw_text=raw_text,
        note=request.form.get("note", ""),
        uploaded_files=uploaded_files,
        force_batch=request.form.get("batch_mode") == "on",
    )
    if hasattr(result, "batch_id"):
        return redirect(url_for("batch_detail", batch_id=result.batch_id))
    return redirect(url_for("draft_detail", draft_id=result.draft_id))


@app.post("/tax/open")
def tax_open():
    result = open_tax_portal(
        request.form.get("cdp_endpoint") or "http://127.0.0.1:9222",
        province=request.form.get("province") or "liaoning",
        url=request.form.get("url") or "",
    )
    return jsonify(result), 200 if result.get("status") == "ok" else 400


@app.get("/tax/status")
def tax_status():
    result = inspect_tax_browser(request.args.get("cdp_endpoint") or "http://127.0.0.1:9222")
    subject = str(result.get("subject") or "")
    seller_query = _seller_query_from_subject(subject)
    result["profile"] = profile_counts_for_seller(seller_query) if seller_query else {
        "matched": False,
        "seller_name": "",
        "seller_tax_id": "",
        "buyer_count": 0,
        "project_profile_count": 0,
    }
    return jsonify(result), 200 if result.get("status") == "ok" else 400


@app.get("/drafts/<draft_id>")
def draft_detail(draft_id: str):
    draft = load_draft(draft_id)
    if draft is None:
        abort(404)
    export = export_draft_template(draft)
    failure_report = load_failure_report_for_draft(draft_id, draft=draft)
    return render_template(
        "lean_draft.html",
        draft=draft,
        preview=draft_preview(draft),
        line_rows=line_form_rows(draft, failure_report=failure_report),
        export=export,
        failure_report=failure_report,
        saved=False,
        success_recorded=False,
        applied_failure_repairs=None,
        needs_rebuild=bool(failure_report and failure_report.get("needs_confirmation_rebuild")),
    )


@app.post("/drafts/<draft_id>/save")
def save_draft(draft_id: str):
    draft = save_lean_draft_from_form(draft_id, request.form, request.files.getlist("source_files"))
    export = export_draft_template(draft)
    failure_report = load_failure_report_for_draft(draft_id, draft=draft)
    if failure_report and failure_report.get("needs_confirmation_rebuild"):
        failure_report["needs_confirmation_rebuild"] = False
        failure_report["operator_confirmed_after_repair"] = True
        save_failure_report_for_draft(draft_id, failure_report)
    return render_template(
        "lean_draft.html",
        draft=draft,
        preview=draft_preview(draft),
        line_rows=line_form_rows(draft, failure_report=failure_report),
        export=export,
        failure_report=failure_report,
        saved=True,
        success_recorded=False,
        applied_failure_repairs=None,
        needs_rebuild=False,
    )


@app.post("/drafts/<draft_id>/failure")
def upload_failure(draft_id: str):
    draft = save_lean_draft_from_form(draft_id, request.form, [])
    failure_file = request.files.get("failure_file")
    failure_report = parse_failure_file(failure_file, draft=draft) if failure_file and failure_file.filename else None
    export = export_draft_template(draft)
    return render_template(
        "lean_draft.html",
        draft=draft,
        preview=draft_preview(draft),
        line_rows=line_form_rows(draft, failure_report=failure_report),
        export=export,
        failure_report=failure_report,
        saved=True,
        success_recorded=False,
        applied_failure_repairs=None,
        needs_rebuild=False,
    )


@app.post("/drafts/<draft_id>/apply-failure-repairs")
def apply_failure_repairs(draft_id: str):
    draft = save_lean_draft_from_form(draft_id, request.form, [])
    result = apply_failure_repairs_to_draft(draft)
    draft = result["draft"]
    failure_report = result["failure_report"] or load_failure_report_for_draft(draft_id, draft=draft)
    export = export_draft_template(draft)
    return render_template(
        "lean_draft.html",
        draft=draft,
        preview=draft_preview(draft),
        line_rows=line_form_rows(draft, failure_report=failure_report),
        export=export,
        failure_report=failure_report,
        saved=True,
        success_recorded=False,
        applied_failure_repairs=result,
        needs_rebuild=bool(result.get("applied_count")),
    )


@app.get("/profiles")
def profiles_page():
    return _render_profiles_page()


@app.post("/profiles/download-history")
def download_profile_history():
    months_raw = request.form.get("months") or "6"
    try:
        months = int(months_raw)
    except ValueError:
        months = 6
    downloader = TaxHistoryDownloader(
        cdp_endpoint=request.form.get("cdp_endpoint") or "http://127.0.0.1:9222",
        months=months,
    )
    download_result = downloader.run().as_dict()
    if download_result.get("status") == "no_data":
        return _render_profiles_page(download_result=download_result), 200
    if download_result.get("status") != "success":
        return _render_profiles_page(download_result=download_result), 500
    try:
        import_result = _import_profile_history_paths([Path(str(download_result.get("downloaded_path") or ""))])
        result = {**download_result, "import_result": import_result}
    except Exception as exc:  # noqa: BLE001
        result = {**download_result, "status": "warning", "error": f"下载成功，但导入档案失败：{type(exc).__name__}: {exc}"}
        return _render_profiles_page(download_result=result), 500
    return _render_profiles_page(download_result=result)


@app.post("/profiles/upload-history")
def upload_profile_history():
    result: dict[str, object]
    files = [file for file in request.files.getlist("history_files") if file and file.filename]
    if not files:
        result = {"status": "error", "message": "请先选择从税局下载的历史开票明细 Excel。"}
        return _render_profiles_page(upload_result=result), 400
    try:
        ensure_profile_dirs(DEFAULT_PROFILE_ROOT)
        bundle_dir = DEFAULT_PROFILE_ROOT / "_收件箱" / "待处理" / f"workbench_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        saved_files = []
        for file in files:
            filename = _safe_upload_name(file.filename or "history.xlsx")
            target = _unique_path(bundle_dir / filename)
            file.save(target)
            saved_files.append(target.name)
        import_result = _run_profile_ingest_pipeline()
        result = {
            "status": "success" if import_result.get("cloud_sync", {}).get("status") == "success" else "warning",
            "message": "历史开票明细已导入，本地客户档案已重建，并已尝试同步到阿里云。",
            "saved_files": saved_files,
            **import_result,
        }
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "message": f"档案导入失败：{type(exc).__name__}: {exc}"}
        return _render_profiles_page(upload_result=result), 500
    return _render_profiles_page(upload_result=result)


@app.get("/api/taxonomy/search")
def taxonomy_search_api():
    query = (request.args.get("q") or "").strip()
    return jsonify({"results": [item.to_dict() for item in search_taxonomy(query)]})


@app.get("/api/profiles/seller")
def seller_profile_api():
    query = (request.args.get("q") or "").strip()
    summary = profile_cache_summary()
    profile = profile_counts_for_seller(query) if query else {
        "matched": False,
        "seller_name": "",
        "seller_tax_id": "",
        "buyer_count": 0,
        "project_profile_count": 0,
    }
    return jsonify({"query": query, "summary": summary, "profile": profile})


@app.post("/drafts/<draft_id>/mark-success")
def mark_success(draft_id: str):
    draft = save_lean_draft_from_form(draft_id, request.form, [])
    record_success_to_ledger(draft)
    export = export_draft_template(draft)
    failure_report = load_failure_report_for_draft(draft_id, draft=draft)
    return render_template(
        "lean_draft.html",
        draft=draft,
        preview=draft_preview(draft),
        line_rows=line_form_rows(draft, failure_report=failure_report),
        export=export,
        failure_report=failure_report,
        saved=True,
        success_recorded=True,
        applied_failure_repairs=None,
        needs_rebuild=False,
    )


@app.get("/drafts/<draft_id>/download-template")
def download_template(draft_id: str):
    draft = load_draft(draft_id)
    if draft is None:
        abort(404)
    export = export_draft_template(draft)
    return send_file(export["output_path"], as_attachment=True)


@app.post("/drafts/<draft_id>/execute")
def execute_draft(draft_id: str):
    draft = save_lean_draft_from_form(draft_id, request.form, [])
    export = export_draft_template(draft)
    if export["error_count"]:
        failure_report = load_failure_report_for_draft(draft_id, draft=draft)
        return render_template(
            "lean_draft.html",
            draft=draft,
            preview=draft_preview(draft),
            line_rows=line_form_rows(draft, failure_report=failure_report),
            export=export,
            failure_report=failure_report,
            saved=True,
            success_recorded=False,
            run_blocked=True,
            applied_failure_repairs=None,
        ), 400
    run_id = _queue_batch_run(
        export["output_path"],
        request.form.get("cdp_endpoint", "http://127.0.0.1:9222"),
        draft_id=draft.draft_id,
    )
    record_case_event(
        case_id=draft.case_id,
        draft_id=draft.draft_id,
        event_type="batch_run_queued",
        payload={
            "run_id": run_id,
            "template_path": str(export["output_path"]),
            "cdp_endpoint": request.form.get("cdp_endpoint", "http://127.0.0.1:9222"),
        },
    )
    return redirect(url_for("run_detail", run_id=run_id))


@app.get("/batches/<batch_id>")
def batch_detail(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    export = export_batch_template(batch_id)
    return render_template("lean_batch.html", batch=batch, export=export, batch_rows=_batch_sheet_rows(batch))


@app.post("/batches/<batch_id>/save")
def save_batch_sheet(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    _save_batch_sheet_form(batch, request.form)
    export = export_batch_template(batch_id)
    return render_template("lean_batch.html", batch=batch, export=export, batch_rows=_batch_sheet_rows(batch), saved=True)


@app.get("/batches/<batch_id>/download-template")
def download_batch_template(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    export = export_batch_template(batch_id)
    return send_file(export["output_path"], as_attachment=True)


@app.post("/batches/<batch_id>/execute")
def execute_batch(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    export = export_batch_template(batch_id)
    if export["error_count"]:
        return render_template("lean_batch.html", batch=batch, export=export, batch_rows=_batch_sheet_rows(batch), run_blocked=True), 400
    run_id = _queue_batch_run(
        export["output_path"],
        request.form.get("cdp_endpoint", "http://127.0.0.1:9222"),
        draft_id=batch.batch_id,
    )
    record_case_event(
        case_id=batch.case_id,
        batch_id=batch.batch_id,
        event_type="batch_run_queued",
        payload={
            "run_id": run_id,
            "template_path": str(export["output_path"]),
            "cdp_endpoint": request.form.get("cdp_endpoint", "http://127.0.0.1:9222"),
            "invoice_count": len(batch.items),
        },
    )
    return redirect(url_for("run_detail", run_id=run_id))


def _batch_sheet_rows(batch):
    rows = []
    for index, item in enumerate(batch.items, start=1):
        draft = load_draft(item.draft_id)
        if draft is None:
            continue
        line = draft.lines[0] if draft.lines else InvoiceLine(project_name="", amount_with_tax="")
        issue_map = _batch_field_issue_map(draft, line)
        rows.append(
            {
                "index": index,
                "draft_id": draft.draft_id,
                "source_name": _source_name_from_note(draft.note),
                "buyer_name": draft.buyer.name,
                "buyer_tax_id": draft.buyer.tax_id,
                "invoice_kind": draft.invoice_kind or batch.invoice_kind or "普通发票",
                "project_name": line.project_name,
                "tax_category": line.tax_category,
                "tax_code": line.tax_code,
                "amount_with_tax": line.resolved_amount_with_tax() or line.amount_with_tax,
                "tax_rate": line.normalized_tax_rate() if line.tax_rate else "",
                "unit": line.unit,
                "quantity": line.quantity,
                "coding_reference": line.coding_reference,
                "issues": draft.issues,
                "issue_map": issue_map,
                "has_issues": bool(issue_map or draft.issues),
            }
        )
    return rows


def _source_name_from_note(note: str) -> str:
    matched = re.search(r"来源图片：([^；]+)", note or "")
    return matched.group(1).strip() if matched else ""


def _batch_field_issue_map(draft, line: InvoiceLine) -> dict[str, str]:
    issues: dict[str, str] = {}
    if not draft.buyer.name.strip():
        issues["buyer_name"] = "必填：请补全购买方名称"
    if not draft.buyer.tax_id.strip():
        issues["buyer_tax_id"] = "必填：请补全购买方税号"
    if not line.project_name.strip():
        issues["project_name"] = "必填：请补全项目名称"
    if not line.resolved_amount_with_tax():
        issues["amount_with_tax"] = "必填：请补全含税金额"
    if not line.tax_rate.strip():
        issues["tax_rate"] = "必填：请补全税率"
    if not line.tax_code.strip():
        issues["tax_code"] = "需复核：请确认税收编码"
    return issues


def _save_batch_sheet_form(batch, form):
    draft_ids = form.getlist("draft_id")
    batch_items: list[DraftBatchItem] = []
    batch_issues: list[str] = []
    for index, draft_id in enumerate(draft_ids):
        draft = load_draft(draft_id)
        if draft is None:
            continue
        draft.buyer = BuyerInfo(
            name=_form_list_value(form, "buyer_name", index),
            tax_id=_form_list_value(form, "buyer_tax_id", index),
            address=draft.buyer.address,
            phone=draft.buyer.phone,
            bank_name=draft.buyer.bank_name,
            bank_account=draft.buyer.bank_account,
        )
        draft.invoice_kind = _form_list_value(form, "invoice_kind", index) or draft.invoice_kind or "普通发票"
        line = draft.lines[0] if draft.lines else InvoiceLine(project_name="", amount_with_tax="")
        line.project_name = _form_list_value(form, "project_name", index)
        line.tax_category = _form_list_value(form, "tax_category", index)
        line.tax_code = _form_list_value(form, "tax_code", index)
        line.amount_with_tax = _form_list_value(form, "amount_with_tax", index)
        line.tax_rate = _form_list_value(form, "tax_rate", index) or line.tax_rate
        line.unit = _form_list_value(form, "unit", index) or line.unit
        line.quantity = _form_list_value(form, "quantity", index) or line.quantity
        if draft.lines:
            draft.lines[0] = line
        else:
            draft.lines = [line]
        issue_map = _batch_field_issue_map(draft, line)
        draft.issues = list(issue_map.values())
        workbench_module.save_draft(draft)
        issue_summary = next(iter(issue_map.values()), "")
        batch_items.append(
            DraftBatchItem(
                draft_id=draft.draft_id,
                buyer_name=draft.buyer.name or "待补全购买方名称",
                invoice_kind=draft.invoice_kind,
                amount_total=line.resolved_amount_with_tax(),
                project_summary=line.project_name,
                line_count=len(draft.lines),
                issue_summary=issue_summary,
            )
        )
        batch_issues.extend(issue_map.values())
    batch.items = batch_items
    batch.issues = batch_issues
    workbench_module.save_draft_batch(batch)
    record_case_event(
        case_id=batch.case_id,
        batch_id=batch.batch_id,
        event_type="batch_sheet_saved",
        payload={"invoice_count": len(batch.items), "issue_count": len(batch.issues)},
    )


def _form_list_value(form, name: str, index: int) -> str:
    values = form.getlist(name)
    if index >= len(values):
        return ""
    return (values[index] or "").strip()


@app.get("/ledger")
def ledger_page():
    execution_summary = execution_record_summary(limit=200)
    return render_template(
        "lean_ledger.html",
        ledger_exists=SUCCESS_LEDGER_XLSX.exists(),
        ledger_filename=SUCCESS_LEDGER_XLSX.name,
        ledger_path=str(SUCCESS_LEDGER_XLSX),
        row_count=_success_ledger_row_count(),
        execution_records=execution_summary["records"],
        execution_metrics=execution_summary["metrics"],
    )


@app.get("/ledger/success")
def success_ledger():
    if not SUCCESS_LEDGER_XLSX.exists():
        return redirect(url_for("ledger_page"))
    return send_file(SUCCESS_LEDGER_XLSX, as_attachment=True)


@app.get("/runs/<run_id>")
def run_detail(run_id: str):
    with RUN_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        abort(404)
    return render_template("lean_run.html", run=run)


@app.post("/runs/<run_id>/record-success")
def run_record_success(run_id: str):
    with RUN_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        abort(404)
    if run.get("status") != "done":
        return render_template("lean_run.html", run={**run, "error": "只有税局执行完成后，才能记录成功。"}), 400
    draft_or_batch_id = str(run.get("draft_id") or "")
    draft = load_draft(draft_or_batch_id) if draft_or_batch_id else None
    if draft is not None:
        record_success_to_ledger(draft)
    else:
        batch = load_draft_batch(draft_or_batch_id) if draft_or_batch_id else None
        if batch is None:
            abort(404)
        record_batch_success_to_ledger(batch)
    with RUN_LOCK:
        RUNS[run_id] = {**RUNS[run_id], "success_recorded": True}
        run = RUNS[run_id]
    return render_template("lean_run.html", run=run)


@app.get("/runs/<run_id>/failure-download")
def run_failure_download(run_id: str):
    with RUN_LOCK:
        run = RUNS.get(run_id)
    if run is None or not run.get("downloaded_failure_path"):
        abort(404)
    return send_file(run["downloaded_failure_path"], as_attachment=True)


@app.post("/runs/<run_id>/apply-failure-repairs")
def run_apply_failure_repairs(run_id: str):
    with RUN_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        abort(404)
    draft_id = str(run.get("draft_id") or "")
    draft = load_draft(draft_id) if draft_id else None
    if draft is None:
        abort(404)
    apply_failure_repairs_to_draft(draft)
    return redirect(url_for("draft_detail", draft_id=draft.draft_id))


def _render_profiles_page(*, upload_result: dict[str, object] | None = None, download_result: dict[str, object] | None = None):
    sellers = _cached_profile_sellers()
    summary = profile_cache_summary()
    return render_template(
        "lean_profiles.html",
        profile_summary=summary,
        sellers=sellers,
        upload_result=upload_result,
        download_result=download_result,
        profile_cache_path=str(PROFILE_CACHE_PATH),
        profile_root=str(DEFAULT_PROFILE_ROOT),
        pending_event_count=0,
    )


def _import_profile_history_paths(paths: list[Path]) -> dict[str, object]:
    ensure_profile_dirs(DEFAULT_PROFILE_ROOT)
    bundle_dir = DEFAULT_PROFILE_ROOT / "_收件箱" / "待处理" / f"tax_auto_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[str] = []
    for source in paths:
        if not source.exists() or not source.is_file():
            continue
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                for member in archive.infolist():
                    if member.is_dir() or not member.filename.lower().endswith(".xlsx"):
                        continue
                    target = _unique_path(bundle_dir / _safe_upload_name(Path(member.filename).name))
                    with archive.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    copied_files.append(target.name)
        else:
            target = _unique_path(bundle_dir / _safe_upload_name(source.name))
            shutil.copy2(source, target)
            copied_files.append(target.name)
    if not copied_files:
        raise RuntimeError("下载文件中未找到可导入的 .xlsx 历史明细。")
    return {"copied_files": copied_files, **_run_profile_ingest_pipeline()}


def _run_profile_ingest_pipeline() -> dict[str, object]:
    ingest_counts = ingest_pending_files(DEFAULT_PROFILE_ROOT)
    rebuild_counts = rebuild_profiles(DEFAULT_PROFILE_ROOT)
    cloud_sync = sync_profiles_to_cloud()
    return {"ingest": ingest_counts, "rebuild": rebuild_counts, "cloud_sync": cloud_sync}


def _cached_profile_sellers() -> list[dict[str, object]]:
    if not PROFILE_CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(PROFILE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    rows = []
    for seller in payload:
        if not isinstance(seller, dict):
            continue
        projects = [item for item in seller.get("project_profiles") or [] if isinstance(item, dict)]
        buyers = [item for item in seller.get("buyer_profiles") or [] if isinstance(item, dict)]
        top_project = projects[0] if projects else {}
        rows.append(
            {
                "seller_name": str(seller.get("seller_name") or ""),
                "seller_tax_id": str(seller.get("seller_tax_id") or ""),
                "buyer_count": len(buyers),
                "project_count": len(projects),
                "top_project": str(top_project.get("project_name") or ""),
                "top_tax_category": str(top_project.get("tax_category") or ""),
                "top_tax_code": str(top_project.get("tax_code") or ""),
                "top_tax_rate": str(top_project.get("tax_rate") or ""),
                "updated_at": str(seller.get("updated_at") or ""),
                "source_confidence": str(seller.get("source_confidence") or ""),
            }
        )
    return rows


def _safe_upload_name(filename: str) -> str:
    cleaned = Path(filename).name.strip().replace("\\", "_").replace("/", "_")
    cleaned = re.sub(r"[\x00-\x1f:*?\"<>|]+", "_", cleaned).strip("._ ")
    if not cleaned.lower().endswith(".xlsx"):
        cleaned = f"{cleaned or 'history'}.xlsx"
    return cleaned or "history.xlsx"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重名文件：{path}")


def _success_ledger_row_count() -> int:
    if not SUCCESS_LEDGER_CSV.exists():
        return 0
    try:
        with SUCCESS_LEDGER_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except Exception:
        return 0


def _queue_batch_run(template_path: Path, cdp_endpoint: str, *, draft_id: str = "") -> str:
    run_id = uuid4().hex[:10]
    with RUN_LOCK:
        RUNS[run_id] = {
            "run_id": run_id,
            "status": "queued",
            "current_step": "queued",
            "logs": [],
            "error": "",
            "template_path": str(template_path),
            "draft_id": draft_id or _draft_id_from_template_path(template_path),
            "downloaded_failure_path": "",
            "failure_report": None,
            "preview_clicked": False,
        }
    thread = Thread(target=_execute_batch_run, args=(run_id, template_path, cdp_endpoint), daemon=True)
    thread.start()
    return run_id


def _execute_batch_run(run_id: str, template_path: Path, cdp_endpoint: str) -> None:
    def status_hook(step: str, line: str) -> None:
        with RUN_LOCK:
            record = RUNS[run_id]
            record["status"] = "running"
            record["current_step"] = step
            record["logs"] = [*record["logs"], line]

    runner = BatchImportRunner(template_path=template_path, cdp_endpoint=cdp_endpoint, status_hook=status_hook)
    result = runner.run()
    with RUN_LOCK:
        draft_id = str(RUNS[run_id].get("draft_id") or "")
    failure_report = result.failure_report
    if failure_report and draft_id:
        draft = load_draft(draft_id)
        if draft is not None:
            failure_report = enrich_failure_report_for_draft(failure_report, draft)
            save_failure_report_for_draft(draft_id, failure_report)
    with RUN_LOCK:
        record = RUNS[run_id]
        record["status"] = result.status
        record["current_step"] = result.current_step
        record["logs"] = result.logs
        record["error"] = result.error
        record["downloaded_failure_path"] = result.downloaded_failure_path
        record["failure_report"] = failure_report
        record["preview_clicked"] = result.preview_clicked
    _record_batch_run_finished_event(run_id, result, template_path)


def _record_batch_run_finished_event(run_id: str, result: BatchRunResult, template_path: Path) -> None:
    with RUN_LOCK:
        run = dict(RUNS.get(run_id) or {})
    draft_id = str(run.get("draft_id") or _draft_id_from_template_path(template_path))
    draft = load_draft(draft_id) if draft_id else None
    case_id = draft.case_id if draft is not None else draft_id
    if not case_id:
        return
    failure_report = result.failure_report if isinstance(result.failure_report, dict) else None
    failure_summary = failure_report.get("summary") if isinstance(failure_report, dict) else None
    failure_records = failure_report.get("records") if isinstance(failure_report, dict) else []
    record_case_event(
        case_id=case_id,
        draft_id=draft_id,
        event_type="batch_run_finished",
        payload={
            "run_id": run_id,
            "status": result.status,
            "current_step": result.current_step,
            "error": result.error,
            "template_path": str(template_path),
            "downloaded_failure_path": result.downloaded_failure_path,
            "downloaded_failure_exists": bool(result.downloaded_failure_path),
            "failure_summary": failure_summary or {},
            "failure_count": len(failure_records) if isinstance(failure_records, list) else 0,
            "preview_clicked": bool(result.preview_clicked),
            "logs_tail": list(result.logs[-12:]),
        },
    )



def _seller_query_from_subject(subject: str) -> str:
    match = re.search(r"[0-9A-Z]{15,20}", subject.upper())
    if match:
        return match.group(0)
    return subject.split("/", 1)[0].strip()


def _draft_id_from_template_path(template_path: Path) -> str:
    stem = Path(template_path).stem
    suffix = "_batch_import"
    if stem.endswith(suffix):
        return stem[: -len(suffix)]
    return ""


@app.template_filter("json_pretty")
def json_pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    BATCH_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=5012, debug=True)

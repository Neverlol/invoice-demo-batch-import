from __future__ import annotations

import json
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from tax_invoice_batch_demo.batch_runner import BatchImportRunner
from tax_invoice_batch_demo.lean_workbench import (
    BATCH_OUTPUT_ROOT,
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
    record_success_to_ledger,
    save_failure_report_for_draft,
    save_lean_draft_from_form,
)
from tax_invoice_demo.case_events import record_case_event
from tax_invoice_demo.sync_service import schedule_background_rule_pull


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
    return render_template("lean_index.html", form=default_form(), errors=[])


@app.post("/drafts")
def create_draft():
    raw_text = request.form.get("raw_text", "")
    uploaded_files = request.files.getlist("source_files")
    if not raw_text.strip() and not any(file.filename for file in uploaded_files):
        return render_template(
            "lean_index.html",
            form=request.form,
            errors=["请粘贴开票信息，或上传客户提供的图片 / Excel / PDF。"],
        ), 400

    result = create_lean_draft(
        company_name=request.form.get("company_name", ""),
        raw_text=raw_text,
        note=request.form.get("note", ""),
        uploaded_files=uploaded_files,
    )
    if hasattr(result, "batch_id"):
        return redirect(url_for("batch_detail", batch_id=result.batch_id))
    return redirect(url_for("draft_detail", draft_id=result.draft_id))


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
    return render_template("lean_batch.html", batch=batch, export=export)


@app.get("/batches/<batch_id>/download-template")
def download_batch_template(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    export = export_batch_template(batch_id)
    return send_file(export["output_path"], as_attachment=True)


@app.get("/ledger/success")
def success_ledger():
    if not SUCCESS_LEDGER_XLSX.exists():
        abort(404)
    return send_file(SUCCESS_LEDGER_XLSX, as_attachment=True)


@app.get("/runs/<run_id>")
def run_detail(run_id: str):
    with RUN_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        abort(404)
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

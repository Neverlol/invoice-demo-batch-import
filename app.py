from __future__ import annotations

import csv
import json
import os
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
    focus_tax_window,
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
from tax_invoice_demo.customer_profiles import PROFILE_CACHE_PATH, profile_cache_summary, profile_counts_for_seller, seller_default_line_profile
from tax_invoice_demo.llm_adapter import diagnose_llm_config
from tax_invoice_demo.models import BuyerInfo, DraftBatchItem, InvoiceLine
from tax_invoice_demo.sync_service import schedule_background_customer_profile_pull, schedule_background_rule_pull
from tax_invoice_demo.taxonomy_search import search_taxonomy
from tax_invoice_demo.tax_rule_engine import smart_code_invoice_lines
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
        current_draft_id=draft.draft_id,
        parent_batch=_find_parent_batch_for_draft(draft.draft_id),
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
        current_draft_id=draft.draft_id,
        parent_batch=_find_parent_batch_for_draft(draft.draft_id),
    )


@app.post("/drafts/<draft_id>/smart-code")
def smart_code_draft(draft_id: str):
    draft = save_lean_draft_from_form(draft_id, request.form, [])
    scope = (request.form.get("smart_code_scope") or "missing").strip()
    target_lines: list[InvoiceLine] = []
    if scope.startswith("line:"):
        try:
            index = int(scope.split(":", 1)[1])
        except ValueError:
            index = -1
        if 0 <= index < len(draft.lines):
            target_lines = [draft.lines[index]]
    elif scope == "all":
        target_lines = list(draft.lines)
    else:
        target_lines = [line for line in draft.lines if not line.tax_category or not line.tax_code]
    before_refs = [line.coding_reference or "" for line in target_lines]
    before_codes = [(line.tax_category or "", line.tax_code or "") for line in target_lines]
    if target_lines:
        smart_code_invoice_lines(target_lines)
        workbench_module.save_draft(draft)
    smart_code_result = _smart_code_result_message(scope, target_lines, before_refs, before_codes)
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
        success_recorded=False,
        applied_failure_repairs=None,
        smart_code_result=smart_code_result,
        needs_rebuild=False,
        current_draft_id=draft.draft_id,
        parent_batch=_find_parent_batch_for_draft(draft.draft_id),
    )


def _coding_source_summary(refs: list[str]) -> str:
    counts = {
        "llm": sum(1 for ref in refs if ref.startswith("智能推荐") or "LLM" in ref),
        "engineering": sum(1 for ref in refs if "工程材料规则" in ref),
        "local": sum(1 for ref in refs if "本地" in ref),
        "tenant": sum(1 for ref in refs if "客户规则" in ref),
        "history": sum(1 for ref in refs if "历史" in ref or "档案" in ref),
        "official": sum(1 for ref in refs if "官方分类候选" in ref),
    }
    parts = []
    if counts["llm"]:
        parts.append(f"LLM 智能推荐 {counts['llm']} 行")
    if counts["engineering"]:
        parts.append(f"工程材料规则 {counts['engineering']} 行")
    if counts["local"]:
        parts.append(f"本地规则 {counts['local']} 行")
    if counts["tenant"]:
        parts.append(f"客户规则包 {counts['tenant']} 行")
    if counts["history"]:
        parts.append(f"历史/档案候选 {counts['history']} 行")
    if counts["official"]:
        parts.append(f"官方候选 {counts['official']} 行")
    if not parts:
        return "本次没有产生可归类的智能/规则来源。"
    llm_note = "；本次没有 LLM 可用推荐。" if counts["llm"] == 0 else "。"
    return "来源：" + "、".join(parts) + llm_note


def _smart_code_result_message(
    scope: str,
    target_lines: list[InvoiceLine],
    before_refs: list[str],
    before_codes: list[tuple[str, str]],
) -> dict[str, str | int]:
    total = len(target_lines)
    scope_label = "全部明细复核" if scope == "all" else "智能赋码"
    if scope.startswith("line:"):
        scope_label = "本行智能复核"
    if total == 0:
        return {
            "level": "ok",
            "title": "当前没有需要智能赋码的明细",
            "message": "所有明细已有税收分类和税收编码，请继续核对发票内容。",
            "total": 0,
            "smart": 0,
            "failed": 0,
            "changed": 0,
        }

    after_refs = [line.coding_reference or "" for line in target_lines]
    after_codes = [(line.tax_category or "", line.tax_code or "") for line in target_lines]
    source_summary = _coding_source_summary(after_refs)
    smart_count = sum(1 for ref in after_refs if ref.startswith("智能推荐"))
    failed_count = sum(
        1
        for ref in after_refs
        if ref.startswith("智能赋码调用失败")
        or ref.startswith("智能赋码返回结果未命中")
        or ref.startswith("待智能赋码")
    )
    changed_count = sum(
        1
        for before_ref, after_ref, before_code, after_code in zip(before_refs, after_refs, before_codes, after_codes)
        if before_ref != after_ref or before_code != after_code
    )
    if failed_count:
        return {
            "level": "warn",
            "title": f"{scope_label}已完成，{failed_count} 行需要人工确认",
            "message": f"本次处理 {total} 行，生成智能推荐 {smart_count} 行；仍有 {failed_count} 行未得到可用推荐，请查看明细中的状态。{source_summary}",
            "total": total,
            "smart": smart_count,
            "failed": failed_count,
            "changed": changed_count,
        }
    if smart_count:
        return {
            "level": "ok",
            "title": f"{scope_label}已完成",
            "message": f"本次处理 {total} 行，生成智能推荐 {smart_count} 行；请继续核对税收分类和税收编码。{source_summary}",
            "total": total,
            "smart": smart_count,
            "failed": failed_count,
            "changed": changed_count,
        }
    if changed_count:
        return {
            "level": "ok",
            "title": f"{scope_label}已完成",
            "message": f"本次处理 {total} 行，已更新 {changed_count} 行赋码信息；请继续核对发票内容。{source_summary}",
            "total": total,
            "smart": smart_count,
            "failed": failed_count,
            "changed": changed_count,
        }

    diagnostic = diagnose_llm_config()
    if not diagnostic.ready:
        return {
            "level": "warn",
            "title": f"{scope_label}未生成新的推荐",
            "message": "当前明细保留原有赋码结果；智能赋码配置未就绪，请检查大模型配置后再试。",
            "total": total,
            "smart": smart_count,
            "failed": failed_count,
            "changed": changed_count,
        }
    return {
        "level": "ok",
        "title": f"{scope_label}已完成",
        "message": f"本次复核 {total} 行，当前赋码结果未发生变化；请继续人工核对发票内容。{source_summary}",
        "total": total,
        "smart": smart_count,
        "failed": failed_count,
        "changed": changed_count,
    }


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
        current_draft_id=draft.draft_id,
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
        current_draft_id=draft.draft_id,
    )


@app.get("/profiles")
def profiles_page():
    return _render_profiles_page(current_draft_id=_valid_nav_draft_id(request.args.get("draft_id") or ""))


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
        current_draft_id=draft.draft_id,
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
    cdp_endpoint = request.form.get("cdp_endpoint", "http://127.0.0.1:9222")
    subject_check = _check_tax_subject_before_submit(
        expected_seller=draft.company_name,
        cdp_endpoint=cdp_endpoint,
        case_id=draft.case_id,
        draft_id=draft.draft_id,
    )
    if subject_check["blocked"]:
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
            run_block_reason=subject_check["message"],
            applied_failure_repairs=None,
        ), 400
    run_id = _queue_batch_run(
        export["output_path"],
        cdp_endpoint,
        draft_id=draft.draft_id,
    )
    record_case_event(
        case_id=draft.case_id,
        draft_id=draft.draft_id,
        event_type="batch_run_queued",
        payload={
            "run_id": run_id,
            "template_path": str(export["output_path"]),
            "cdp_endpoint": cdp_endpoint,
            "subject_match": subject_check,
        },
    )
    return redirect(url_for("run_detail", run_id=run_id))


@app.get("/batches/<batch_id>")
def batch_detail(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    export = export_batch_template(batch_id)
    return render_template(
        "lean_batch.html",
        batch=batch,
        export=export,
        batch_rows=_batch_sheet_rows(batch),
        line_recommendation=_batch_line_recommendation(batch),
    )


@app.post("/batches/<batch_id>/save")
def save_batch_sheet(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    _save_batch_sheet_form(batch, request.form)
    export = export_batch_template(batch_id)
    return render_template(
        "lean_batch.html",
        batch=batch,
        export=export,
        batch_rows=_batch_sheet_rows(batch),
        line_recommendation=_batch_line_recommendation(batch),
        saved=True,
    )


@app.post("/batches/<batch_id>/smart-code")
def smart_code_batch(batch_id: str):
    batch = load_draft_batch(batch_id)
    if batch is None:
        abort(404)
    _save_batch_sheet_form(batch, request.form)
    scope = (request.form.get("smart_code_scope") or "missing").strip()
    target_lines: list[InvoiceLine] = []
    target_drafts = []
    for item in batch.items:
        draft = load_draft(item.draft_id)
        if draft is None:
            continue
        selected = list(draft.lines) if scope == "all" else [line for line in draft.lines if not line.tax_category or not line.tax_code]
        if selected:
            target_drafts.append(draft)
            target_lines.extend(selected)
    before_refs = [line.coding_reference or "" for line in target_lines]
    before_codes = [(line.tax_category or "", line.tax_code or "") for line in target_lines]
    if target_lines:
        for draft in target_drafts:
            _apply_batch_context_coding(draft, replace_existing=(scope == "all"))
        smart_code_invoice_lines(target_lines)
        for draft in target_drafts:
            _apply_batch_context_coding(draft, replace_existing=(scope == "all"))
            workbench_module.save_draft(draft)
    smart_code_result = _smart_code_result_message(scope, target_lines, before_refs, before_codes)
    _rebuild_batch_items_from_drafts(batch)
    export = export_batch_template(batch_id)
    llm_diagnostic = diagnose_llm_config()
    record_case_event(
        case_id=batch.case_id,
        batch_id=batch.batch_id,
        event_type="batch_smart_code_completed",
        payload={
            "scope": scope,
            "total": smart_code_result.get("total", 0),
            "smart": smart_code_result.get("smart", 0),
            "failed": smart_code_result.get("failed", 0),
            "changed": smart_code_result.get("changed", 0),
            "llm_ready": llm_diagnostic.ready,
            "llm_provider": llm_diagnostic.provider,
            "llm_model": llm_diagnostic.model,
            "llm_attempted_or_ready_for_taxonomy": bool(target_lines and llm_diagnostic.ready),
            "llm_issues": llm_diagnostic.issues,
        },
    )
    return render_template(
        "lean_batch.html",
        batch=batch,
        export=export,
        batch_rows=_batch_sheet_rows(batch),
        line_recommendation=_batch_line_recommendation(batch),
        saved=True,
        smart_code_result=smart_code_result,
    )


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
        return render_template(
            "lean_batch.html",
            batch=batch,
            export=export,
            batch_rows=_batch_sheet_rows(batch),
            line_recommendation=_batch_line_recommendation(batch),
            run_blocked=True,
        ), 400
    cdp_endpoint = request.form.get("cdp_endpoint", "http://127.0.0.1:9222")
    subject_check = _check_tax_subject_before_submit(
        expected_seller=batch.company_name,
        cdp_endpoint=cdp_endpoint,
        case_id=batch.case_id,
        batch_id=batch.batch_id,
    )
    if subject_check["blocked"]:
        return render_template(
            "lean_batch.html",
            batch=batch,
            export=export,
            batch_rows=_batch_sheet_rows(batch),
            line_recommendation=_batch_line_recommendation(batch),
            run_blocked=True,
            run_block_reason=subject_check["message"],
        ), 400
    run_id = _queue_batch_run(
        export["output_path"],
        cdp_endpoint,
        draft_id=batch.batch_id,
    )
    record_case_event(
        case_id=batch.case_id,
        batch_id=batch.batch_id,
        event_type="batch_run_queued",
        payload={
            "run_id": run_id,
            "template_path": str(export["output_path"]),
            "cdp_endpoint": cdp_endpoint,
            "invoice_count": len(batch.items),
            "subject_match": subject_check,
        },
    )
    return redirect(url_for("run_detail", run_id=run_id))


def _check_tax_subject_before_submit(
    *,
    expected_seller: str,
    cdp_endpoint: str,
    case_id: str,
    draft_id: str = "",
    batch_id: str = "",
) -> dict:
    if os.getenv("TAX_INVOICE_SUBJECT_HARD_BLOCK", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"blocked": False, "status": "disabled", "expected_seller": expected_seller, "tax_subject": ""}
    result = inspect_tax_browser(cdp_endpoint)
    tax_subject = str(result.get("subject") or "")
    matched = _subject_matches_seller(tax_subject, expected_seller)
    check = {
        "blocked": not matched,
        "status": "matched" if matched else "blocked",
        "expected_seller": expected_seller,
        "tax_subject": tax_subject,
        "cdp_endpoint": cdp_endpoint,
        "inspect_status": result.get("status", ""),
        "message": "",
    }
    if matched:
        return check
    if not tax_subject:
        check["message"] = "提交前未能识别当前税局登录主体，已禁止提交。请确认已登录税局专用浏览器，并点击“识别当前税局主体 / 加载档案”后重试。"
    else:
        check["message"] = f"当前税局登录主体与草稿销售方不一致，已禁止提交。税局主体：{tax_subject}；草稿销售方：{expected_seller}。"
    record_case_event(
        case_id=case_id,
        draft_id=draft_id,
        batch_id=batch_id,
        event_type="tax_subject_mismatch_blocked",
        payload=check,
    )
    return check


def _subject_matches_seller(tax_subject: str, expected_seller: str) -> bool:
    subject_name = _normalize_subject_name(tax_subject)
    expected_name = _normalize_subject_name(expected_seller)
    if not subject_name or not expected_name:
        return False
    if subject_name == expected_name:
        return True
    return expected_name in subject_name or subject_name in expected_name


def _normalize_subject_name(value: str) -> str:
    text = (value or "").split("/", 1)[0]
    text = re.sub(r"[0-9A-Z]{15,20}", "", text.upper())
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _batch_line_recommendation(batch) -> dict[str, str] | None:
    """Return an optional seller-level line recommendation for operator-triggered batch import.

    This is deliberately not auto-applied: the operator must confirm the batch uses the same category before
    importing it into Sheet 2.
    """
    profile = seller_default_line_profile(batch.company_name or "")
    if profile is None:
        return None
    if not (profile.project_name or profile.tax_category or profile.tax_code or profile.tax_rate):
        return None
    return {
        "project_name": profile.project_name,
        "tax_category": profile.tax_category,
        "tax_code": profile.tax_code,
        "tax_rate": profile.tax_rate,
        "unit": profile.unit or "项",
        "quantity": profile.quantity or "1",
        "source": profile.matched_source,
    }



def _apply_batch_context_coding(draft, *, replace_existing: bool = False) -> int:
    """Apply high-confidence batch-context rules before/after smart coding.

    The batch page is the operator's main repair desk. When the uploaded workbook
    itself is a construction/steel material list, common engineering item names
    should not remain stuck as "待确认税收编码" just because the LLM call returns no
    usable candidate. These deterministic fills are still marked as requiring
    human review.
    """
    context = " ".join(
        part
        for part in [
            draft.workbook_name,
            draft.note,
            draft.raw_text,
            " ".join(draft.material_tags or []),
        ]
        if part
    )
    changed = 0
    for line in draft.lines:
        if _apply_engineering_material_code(line, context=context, replace_existing=replace_existing):
            changed += 1
    return changed


def _apply_engineering_material_code(line: InvoiceLine, *, context: str = "", replace_existing: bool = False) -> bool:
    text = f"{line.project_name} {line.specification} {context}".strip()
    item_text = f"{line.project_name} {line.specification}".strip()
    if not item_text:
        return False
    if line.tax_code.strip() and line.tax_category.strip() and not replace_existing:
        return False
    target: tuple[str, str, str] | None = None
    if re.search(r"(预埋钢板|止水钢板|镀锌板|不锈钢板)", item_text):
        target = ("黑色金属冶炼压延品", "1080207070000000000", "钢板")
    elif re.search(r"(钢爬梯|爬梯|伸缩缝.*不锈钢|不锈钢.*压舌|压舌)", item_text):
        target = ("金属制品", "1080401010000000000", "钢结构及其产品")
    elif re.search(r"(^|[^木])压板", item_text) and re.search(r"(压板\.xls|钢|金属|不锈钢|镀锌|预埋|工程|项目|中铁|施工)", text):
        target = ("金属制品", "1080401010000000000", "钢结构及其产品")
    if target is None:
        return False
    category, code, official_name = target
    before = (line.tax_category, line.tax_code, line.coding_reference)
    if replace_existing or not line.tax_category.strip():
        line.tax_category = category
    if replace_existing or not line.tax_code.strip():
        line.tax_code = code
    line.coding_reference = f"工程材料规则，需人工复核: {official_name} / {category} / {code}"
    return before != (line.tax_category, line.tax_code, line.coding_reference)


def _batch_sheet_rows(batch):
    rows = []
    for index, item in enumerate(batch.items, start=1):
        draft = load_draft(item.draft_id)
        if draft is None:
            continue
        first_line = draft.lines[0] if draft.lines else InvoiceLine(project_name="", amount_with_tax="")
        issue_map = _batch_field_issue_map(draft, first_line)
        note_issues = list((draft.field_review_reasons or {}).get("备注", []))
        buyer_tax_issues = list((draft.field_review_reasons or {}).get("购买方税号", []))
        if buyer_tax_issues and "buyer_tax_id" not in issue_map:
            issue_map["buyer_tax_id"] = buyer_tax_issues[0]
        if note_issues:
            issue_map["note"] = note_issues[0]
        line_rows = []
        for line_index, line in enumerate(draft.lines or [first_line]):
            line_issue_map = _batch_line_issue_map(line)
            line_rows.append(
                {
                    "line_index": line_index,
                    "display_index": line_index + 1,
                    "field_prefix": f"line_{draft.draft_id}_{line_index}",
                    "project_name": line.project_name,
                    "tax_category": line.tax_category,
                    "tax_code": line.tax_code,
                    "amount_with_tax": line.resolved_amount_with_tax() or line.amount_with_tax,
                    "tax_rate": line.normalized_tax_rate() if line.tax_rate else "",
                    "unit": line.unit,
                    "quantity": line.quantity,
                    "coding_reference": line.coding_reference,
                    "issue_map": line_issue_map,
                    "has_issues": bool(line_issue_map),
                }
            )
        row_issues = list(draft.issues or [])
        for reason in note_issues + buyer_tax_issues:
            if reason not in row_issues:
                row_issues.append(reason)
        rows.append(
            {
                "index": index,
                "draft_id": draft.draft_id,
                "source_name": _source_name_from_note(draft.note),
                "buyer_name": draft.buyer.name,
                "buyer_tax_id": draft.buyer.tax_id,
                "invoice_kind": draft.invoice_kind or batch.invoice_kind or "普通发票",
                "amount_with_tax": _draft_amount_total(draft),
                "note": draft.note,
                "note_preview": (draft.note or "").replace("\n", "；"),
                "line_count": len(draft.lines),
                "line_rows": line_rows,
                "issues": row_issues,
                "issue_map": issue_map,
                "has_issues": bool(issue_map or row_issues or any(line["has_issues"] for line in line_rows)),
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
    return issues


def _batch_line_issue_map(line: InvoiceLine) -> dict[str, str]:
    issues: dict[str, str] = {}
    if not line.project_name.strip():
        issues["project_name"] = "必填：请补全项目名称"
    if not line.resolved_amount_with_tax():
        issues["amount_with_tax"] = "必填：请补全含税金额"
    if not line.tax_rate.strip():
        issues["tax_rate"] = "必填：请补全税率"
    if not line.tax_code.strip():
        issues["tax_code"] = "需复核：请确认税收编码"
    return issues


def _draft_amount_total(draft) -> str:
    total = 0.0
    found = False
    for line in draft.lines:
        value = line.resolved_amount_with_tax()
        if not value:
            continue
        try:
            total += float(value.replace(",", ""))
            found = True
        except ValueError:
            continue
    return f"{total:.2f}" if found else ""


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
        draft.note = _form_list_value(form, "note", index) or draft.note
        if not draft.lines:
            draft.lines = [InvoiceLine(project_name="", amount_with_tax="")]
        legacy_first_line_values_present = any(_form_list_value(form, name, index) for name in ["project_name", "tax_category", "tax_code", "amount_with_tax", "tax_rate", "unit", "quantity"])
        for line_index, line in enumerate(draft.lines):
            prefix = f"line_{draft.draft_id}_{line_index}"
            if f"{prefix}_project_name" in form:
                line.project_name = (form.get(f"{prefix}_project_name") or "").strip()
                line.tax_category = (form.get(f"{prefix}_tax_category") or "").strip()
                line.tax_code = (form.get(f"{prefix}_tax_code") or "").strip()
                line.amount_with_tax = (form.get(f"{prefix}_amount_with_tax") or "").strip()
                line.tax_rate = (form.get(f"{prefix}_tax_rate") or "").strip() or line.tax_rate
                line.unit = (form.get(f"{prefix}_unit") or "").strip() or line.unit
                line.quantity = (form.get(f"{prefix}_quantity") or "").strip() or line.quantity
            elif line_index == 0 and legacy_first_line_values_present:
                line.project_name = _form_list_value(form, "project_name", index)
                line.tax_category = _form_list_value(form, "tax_category", index)
                line.tax_code = _form_list_value(form, "tax_code", index)
                line.amount_with_tax = _form_list_value(form, "amount_with_tax", index)
                line.tax_rate = _form_list_value(form, "tax_rate", index) or line.tax_rate
                line.unit = _form_list_value(form, "unit", index) or line.unit
                line.quantity = _form_list_value(form, "quantity", index) or line.quantity
            if form.get("batch_recommendation_applied") == "1" and (line.project_name or line.tax_category or line.tax_code):
                line.coding_reference = "批量页一键导入推荐，需人工复核"
        first_line = draft.lines[0]
        issue_map = _batch_field_issue_map(draft, first_line)
        line_issues = []
        for line_index, line in enumerate(draft.lines, start=1):
            for issue in _batch_line_issue_map(line).values():
                line_issues.append(f"第 {line_index} 行：{issue}")
        draft.issues = list(issue_map.values()) + line_issues
        workbench_module.save_draft(draft)
        issue_summary = next(iter(draft.issues), "")
        batch_items.append(
            DraftBatchItem(
                draft_id=draft.draft_id,
                buyer_name=draft.buyer.name or "待补全购买方名称",
                invoice_kind=draft.invoice_kind,
                amount_total=_draft_amount_total(draft),
                project_summary=first_line.project_name,
                line_count=len(draft.lines),
                issue_summary=issue_summary,
            )
        )
        batch_issues.extend(draft.issues)
    batch.items = batch_items
    batch.issues = batch_issues
    workbench_module.save_draft_batch(batch)
    record_case_event(
        case_id=batch.case_id,
        batch_id=batch.batch_id,
        event_type="batch_sheet_saved",
        payload={"invoice_count": len(batch.items), "issue_count": len(batch.issues)},
    )


def _rebuild_batch_items_from_drafts(batch) -> None:
    batch_items: list[DraftBatchItem] = []
    batch_issues: list[str] = []
    for item in batch.items:
        draft = load_draft(item.draft_id)
        if draft is None:
            continue
        line = draft.lines[0] if draft.lines else InvoiceLine(project_name="", amount_with_tax="")
        issue_map = _batch_field_issue_map(draft, line)
        line_issue_count = sum(1 for candidate in draft.lines if _line_needs_batch_review(candidate))
        issues = list(issue_map.values())
        if line_issue_count:
            issues.append(f"明细中仍有 {line_issue_count} 行缺少税收分类、税收编码、税率或金额，请在批量页智能赋码/修复后复核。")
        draft.issues = issues
        workbench_module.save_draft(draft)
        issue_summary = next(iter(issues), "")
        batch_items.append(
            DraftBatchItem(
                draft_id=draft.draft_id,
                buyer_name=draft.buyer.name or "待补全购买方名称",
                invoice_kind=draft.invoice_kind,
                amount_total=_draft_amount_total(draft),
                project_summary=line.project_name,
                line_count=len(draft.lines),
                issue_summary=issue_summary,
            )
        )
        batch_issues.extend(issues)
    batch.items = batch_items
    batch.issues = batch_issues
    workbench_module.save_draft_batch(batch)


def _line_needs_batch_review(line: InvoiceLine) -> bool:
    return not (line.project_name.strip() and line.resolved_amount_with_tax() and line.tax_rate.strip() and line.tax_code.strip())


def _find_parent_batch_for_draft(draft_id: str):
    draft_id = (draft_id or "").strip()
    if not draft_id:
        return None
    try:
        batch_paths = sorted(workbench_module.WORKBENCH_ROOT.glob("*/batch.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for batch_path in batch_paths:
        try:
            batch = load_draft_batch(batch_path.parent.name)
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            continue
        if batch and any(item.draft_id == draft_id for item in batch.items):
            return batch
    return None


def _form_list_value(form, name: str, index: int) -> str:
    values = form.getlist(name)
    if index >= len(values):
        return ""
    return (values[index] or "").strip()


def _valid_nav_draft_id(raw: str) -> str:
    draft_id = (raw or "").strip()
    if not draft_id:
        return ""
    return draft_id if load_draft(draft_id) is not None else ""


def _valid_nav_batch_id(raw: str) -> str:
    batch_id = (raw or "").strip()
    if not batch_id:
        return ""
    return batch_id if load_draft_batch(batch_id) is not None else ""


@app.get("/ledger")
def ledger_page():
    execution_summary = execution_record_summary(limit=200)
    current_draft_id = _valid_nav_draft_id(request.args.get("draft_id") or "")
    current_batch_id = _valid_nav_batch_id(request.args.get("batch_id") or "")
    return render_template(
        "lean_ledger.html",
        ledger_exists=SUCCESS_LEDGER_XLSX.exists(),
        ledger_filename=SUCCESS_LEDGER_XLSX.name,
        ledger_path=str(SUCCESS_LEDGER_XLSX),
        row_count=_success_ledger_row_count(),
        execution_records=execution_summary["records"],
        execution_metrics=execution_summary["metrics"],
        current_draft_id=current_draft_id,
        current_batch_id=current_batch_id,
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
    return render_template("lean_run.html", run=run, run_batch=_batch_for_run(run))


@app.post("/runs/<run_id>/focus-tax-window")
def run_focus_tax_window(run_id: str):
    with RUN_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        abort(404)
    cdp_endpoint = str(run.get("cdp_endpoint") or "http://127.0.0.1:9222")
    result = focus_tax_window(cdp_endpoint=cdp_endpoint)
    with RUN_LOCK:
        current = RUNS.get(run_id)
        if current is None:
            abort(404)
        if result.get("status") == "ok":
            notice = "已进入税局预览；请核对发票内容。"
            error = ""
        else:
            notice = ""
            error = result.get("error") or "未能进入税局预览。请确认 Edge 税局页面仍然打开。"
        RUNS[run_id] = {**current, "focus_notice": notice, "error": error}
        run = RUNS[run_id]
    status_code = 200 if result.get("status") == "ok" else 400
    return render_template("lean_run.html", run=run, run_batch=_batch_for_run(run)), status_code


@app.post("/runs/<run_id>/record-success")
def run_record_success(run_id: str):
    with RUN_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        abort(404)
    return render_template(
        "lean_run.html",
        run={**run, "error": "请进入税局预览，并在税局页面完成后续操作。"},
        run_batch=_batch_for_run(run),
    ), 400


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
    run_batch = _batch_for_run(run)
    if run_batch is not None:
        return redirect(url_for("batch_detail", batch_id=run_batch.batch_id))
    draft_id = str(run.get("draft_id") or "")
    draft = load_draft(draft_id) if draft_id else None
    if draft is None:
        abort(404)
    apply_failure_repairs_to_draft(draft)
    return redirect(url_for("draft_detail", draft_id=draft.draft_id))


def _batch_for_run(run: dict | None):
    if not run:
        return None
    draft_id = str(run.get("draft_id") or "")
    return load_draft_batch(draft_id) if draft_id else None


def _render_profiles_page(*, upload_result: dict[str, object] | None = None, download_result: dict[str, object] | None = None, current_draft_id: str = ""):
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
        current_draft_id=current_draft_id,
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
            "cdp_endpoint": cdp_endpoint,
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

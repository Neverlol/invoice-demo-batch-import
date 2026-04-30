from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, jsonify, request

from .store import (
    DEFAULT_DB_PATH,
    get_case_timeline,
    get_latest_rule_package,
    get_latest_customer_profiles,
    get_store_stats,
    import_customer_profiles,
    ingest_event_batch,
    initialize_store,
    list_rule_candidates,
    list_recent_events,
    publish_rule_package,
)


def create_app(*, db_path: Path | None = None) -> Flask:
    app = Flask(__name__)
    active_db_path = initialize_store(db_path or _configured_db_path())

    @app.get("/api/invoice/events/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "db_path": str(active_db_path),
                **get_store_stats(db_path=active_db_path),
            }
        )

    @app.post("/api/invoice/events")
    def ingest_events():
        _check_auth()
        payload = request.get_json(silent=True) or {}
        events = payload.get("events")
        if not isinstance(events, list):
            return jsonify({"error": "events must be an array"}), 400
        if not events:
            return jsonify({"accepted": 0, "duplicates": 0, "request_id": "", "tenant": payload.get("tenant") or "default"})

        tenant = str(payload.get("tenant") or "default").strip() or "default"
        source = str(payload.get("source") or "invoice-demo-batch-import").strip() or "invoice-demo-batch-import"
        validation_error = _validate_events(events)
        if validation_error:
            return jsonify({"error": validation_error}), 400

        result = ingest_event_batch(
            tenant=tenant,
            source=source,
            sent_at=str(payload.get("sent_at") or ""),
            events=events,
            db_path=active_db_path,
        )
        return jsonify(
            {
                "request_id": result.request_id,
                "accepted": result.accepted,
                "duplicates": result.duplicates,
                "tenant": result.tenant,
                "received_at": result.received_at,
            }
        )

    @app.get("/api/invoice/tenants/<tenant>/events")
    def recent_events(tenant: str):
        _check_auth()
        limit = max(1, min(int(request.args.get("limit", "50")), 500))
        return jsonify(
            {
                "tenant": tenant,
                "events": list_recent_events(tenant=tenant, limit=limit, db_path=active_db_path),
            }
        )

    @app.get("/api/invoice/tenants/<tenant>/cases/<case_id>")
    def case_timeline(tenant: str, case_id: str):
        _check_auth()
        events = get_case_timeline(tenant=tenant, case_id=case_id, db_path=active_db_path)
        if not events:
            abort(404)
        return jsonify(
            {
                "tenant": tenant,
                "case_id": case_id,
                "events": events,
            }
        )

    @app.post("/api/invoice/tenants/<tenant>/rules")
    def publish_rules(tenant: str):
        _check_auth()
        payload = request.get_json(silent=True) or {}
        rules = payload.get("rules")
        if not isinstance(rules, list):
            return jsonify({"error": "rules must be an array"}), 400
        validation_error = _validate_rules(rules)
        if validation_error:
            return jsonify({"error": validation_error}), 400
        result = publish_rule_package(
            tenant=tenant,
            version=str(payload.get("version") or ""),
            rules=rules,
            note=str(payload.get("note") or ""),
            db_path=active_db_path,
        )
        return jsonify(
            {
                "package_id": result.package_id,
                "tenant": result.tenant,
                "version": result.version,
                "rule_count": result.rule_count,
                "published_at": result.published_at,
            }
        )

    @app.get("/api/invoice/tenants/<tenant>/rules/latest")
    def latest_rules(tenant: str):
        _check_auth()
        package = get_latest_rule_package(tenant=tenant, db_path=active_db_path)
        if package is None:
            abort(404)
        return jsonify(package)

    @app.get("/api/invoice/tenants/<tenant>/rule-candidates")
    def rule_candidates(tenant: str):
        _check_auth()
        limit = max(1, min(int(request.args.get("limit", "5000")), 20000))
        return jsonify(
            {
                "tenant": tenant,
                "candidates": list_rule_candidates(tenant=tenant, limit=limit, db_path=active_db_path),
            }
        )

    @app.post("/api/invoice/profile-imports")
    def profile_imports():
        _check_auth()
        payload = request.get_json(silent=True) or {}
        tenant = str(payload.get("tenant") or "default").strip() or "default"
        sellers = payload.get("seller_profiles") or payload.get("sellers")
        if not isinstance(sellers, list):
            return jsonify({"error": "seller_profiles must be an array"}), 400
        validation_error = _validate_customer_profiles(sellers)
        if validation_error:
            return jsonify({"error": validation_error}), 400
        result = import_customer_profiles(
            tenant=tenant,
            source=str(payload.get("source") or "invoice-demo-batch-import"),
            sent_at=str(payload.get("sent_at") or ""),
            seller_profiles=sellers,
            source_confidence=str(payload.get("source_confidence") or "official_history_export"),
            summary=payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
            db_path=active_db_path,
        )
        return jsonify(
            {
                "batch_id": result.batch_id,
                "tenant": result.tenant,
                "seller_count": result.seller_count,
                "buyer_count": result.buyer_count,
                "line_profile_count": result.line_profile_count,
                "imported_at": result.imported_at,
            }
        )

    @app.get("/api/invoice/customer-profiles/latest")
    def latest_customer_profiles():
        _check_auth()
        tenant = str(request.args.get("tenant") or "default").strip() or "default"
        return jsonify(
            get_latest_customer_profiles(
                tenant=tenant,
                seller_tax_id=str(request.args.get("seller_tax_id") or ""),
                seller_name=str(request.args.get("seller_name") or ""),
                db_path=active_db_path,
            )
        )

    @app.get("/api/invoice/tenants/<tenant>/customer-profiles/latest")
    def latest_tenant_customer_profiles(tenant: str):
        _check_auth()
        return jsonify(
            get_latest_customer_profiles(
                tenant=tenant,
                seller_tax_id=str(request.args.get("seller_tax_id") or ""),
                seller_name=str(request.args.get("seller_name") or ""),
                db_path=active_db_path,
            )
        )

    return app


def _configured_db_path() -> Path:
    configured = (os.getenv("TAX_INVOICE_CENTER_DB") or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def _check_auth() -> None:
    expected_token = (os.getenv("TAX_INVOICE_CENTER_TOKEN") or "").strip()
    if not expected_token:
        return
    authorization = request.headers.get("Authorization", "")
    if authorization != f"Bearer {expected_token}":
        abort(401)


def _validate_events(events: list[dict]) -> str:
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            return f"event #{index} must be an object"
        for field in ("event_id", "case_id", "event_type", "created_at"):
            if not str(event.get(field) or "").strip():
                return f"event #{index} missing required field: {field}"
    return ""


def _validate_rules(rules: list[dict]) -> str:
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            return f"rule #{index} must be an object"
        raw_alias = str(rule.get("raw_alias") or rule.get("关键词") or "").strip()
        tax_category = str(rule.get("tax_category") or rule.get("标准分类") or "").strip()
        if not raw_alias:
            return f"rule #{index} missing required field: raw_alias"
        if not tax_category:
            return f"rule #{index} missing required field: tax_category"
    return ""


def _validate_customer_profiles(sellers: list[dict]) -> str:
    for index, seller in enumerate(sellers, start=1):
        if not isinstance(seller, dict):
            return f"seller_profile #{index} must be an object"
        seller_name = str(seller.get("seller_name") or "").strip()
        seller_tax_id = str(seller.get("seller_tax_id") or "").strip()
        if not seller_name:
            return f"seller_profile #{index} missing required field: seller_name"
        if not seller_tax_id:
            return f"seller_profile #{index} missing required field: seller_tax_id"
        project_profiles = seller.get("project_profiles") or seller.get("invoice_line_profiles") or []
        if not isinstance(project_profiles, list):
            return f"seller_profile #{index} project_profiles must be an array"
        buyer_profiles = seller.get("buyer_profiles") or []
        if not isinstance(buyer_profiles, list):
            return f"seller_profile #{index} buyer_profiles must be an array"
    return ""

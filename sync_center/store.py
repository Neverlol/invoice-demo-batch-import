from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4


SYNC_CENTER_ROOT = Path(__file__).resolve().parent.parent / "output" / "sync_center"
DEFAULT_DB_PATH = SYNC_CENTER_ROOT / "invoice_sync_center.sqlite3"


@dataclass(frozen=True)
class IngestResult:
    request_id: str
    accepted: int
    duplicates: int
    tenant: str
    received_at: str


@dataclass(frozen=True)
class RulePackageResult:
    package_id: str
    tenant: str
    version: str
    rule_count: int
    published_at: str


@dataclass(frozen=True)
class ProfileImportResult:
    batch_id: str
    tenant: str
    seller_count: int
    buyer_count: int
    line_profile_count: int
    imported_at: str


def initialize_store(db_path: Path | None = None) -> Path:
    target = db_path or DEFAULT_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with _connect(target) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ingest_requests (
                request_id TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                source TEXT NOT NULL,
                sent_at TEXT,
                received_at TEXT NOT NULL,
                event_count INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS case_events (
                event_id TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                case_id TEXT NOT NULL,
                draft_id TEXT,
                batch_id TEXT,
                event_type TEXT NOT NULL,
                event_created_at TEXT,
                received_at TEXT NOT NULL,
                request_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                raw_event_json TEXT NOT NULL,
                FOREIGN KEY(request_id) REFERENCES ingest_requests(request_id)
            );

            CREATE INDEX IF NOT EXISTS idx_case_events_tenant_case
                ON case_events (tenant, case_id, received_at);

            CREATE INDEX IF NOT EXISTS idx_case_events_tenant_event
                ON case_events (tenant, event_type, received_at);

            CREATE TABLE IF NOT EXISTS rule_packages (
                package_id TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL,
                published_at TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                note TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_rule_packages_tenant_latest
                ON rule_packages (tenant, status, published_at);

            CREATE TABLE IF NOT EXISTS profile_import_batches (
                batch_id TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                source TEXT NOT NULL,
                source_confidence TEXT NOT NULL,
                sent_at TEXT,
                imported_at TEXT NOT NULL,
                seller_count INTEGER NOT NULL,
                buyer_count INTEGER NOT NULL,
                line_profile_count INTEGER NOT NULL,
                summary_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS seller_profiles (
                tenant TEXT NOT NULL,
                seller_tax_id TEXT NOT NULL,
                seller_name TEXT NOT NULL,
                status TEXT NOT NULL,
                source_confidence TEXT NOT NULL,
                profile_batch_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant, seller_tax_id)
            );

            CREATE TABLE IF NOT EXISTS buyer_profiles (
                tenant TEXT NOT NULL,
                seller_tax_id TEXT NOT NULL,
                buyer_tax_id TEXT NOT NULL,
                buyer_name TEXT NOT NULL,
                status TEXT NOT NULL,
                source_confidence TEXT NOT NULL,
                line_count INTEGER NOT NULL,
                profile_batch_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant, seller_tax_id, buyer_tax_id, buyer_name)
            );

            CREATE TABLE IF NOT EXISTS invoice_line_profiles (
                tenant TEXT NOT NULL,
                seller_tax_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                tax_category TEXT NOT NULL,
                tax_code TEXT NOT NULL,
                tax_rate TEXT NOT NULL,
                unit TEXT NOT NULL,
                status TEXT NOT NULL,
                source_confidence TEXT NOT NULL,
                line_count INTEGER NOT NULL,
                profile_batch_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant, seller_tax_id, project_name, tax_category, tax_code, tax_rate, unit)
            );

            CREATE INDEX IF NOT EXISTS idx_customer_profiles_seller
                ON seller_profiles (tenant, seller_name, seller_tax_id, status);
            """
        )
    return target


def ingest_event_batch(
    *,
    tenant: str,
    source: str,
    sent_at: str,
    events: list[dict],
    db_path: Path | None = None,
) -> IngestResult:
    target = initialize_store(db_path)
    request_id = uuid4().hex[:12]
    received_at = datetime.now().isoformat(timespec="seconds")
    accepted = 0
    duplicates = 0
    with _connect(target) as connection:
        connection.execute(
            """
            INSERT INTO ingest_requests (request_id, tenant, source, sent_at, received_at, event_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (request_id, tenant, source, sent_at, received_at, len(events)),
        )
        for event in events:
            try:
                connection.execute(
                    """
                    INSERT INTO case_events (
                        event_id, tenant, case_id, draft_id, batch_id, event_type,
                        event_created_at, received_at, request_id, payload_json, raw_event_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.get("event_id") or ""),
                        tenant,
                        str(event.get("case_id") or ""),
                        str(event.get("draft_id") or ""),
                        str(event.get("batch_id") or ""),
                        str(event.get("event_type") or ""),
                        str(event.get("created_at") or ""),
                        received_at,
                        request_id,
                        json.dumps(event.get("payload") or {}, ensure_ascii=False),
                        json.dumps(event, ensure_ascii=False),
                    ),
                )
                accepted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
    return IngestResult(
        request_id=request_id,
        accepted=accepted,
        duplicates=duplicates,
        tenant=tenant,
        received_at=received_at,
    )


def list_recent_events(*, tenant: str, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    target = initialize_store(db_path)
    with _connect(target) as connection:
        rows = connection.execute(
            """
            SELECT event_id, tenant, case_id, draft_id, batch_id, event_type, event_created_at,
                   received_at, request_id, payload_json
            FROM case_events
            WHERE tenant = ?
            ORDER BY received_at DESC, rowid DESC
            LIMIT ?
            """,
            (tenant, limit),
        ).fetchall()
    return [_row_to_event(row) for row in rows]


def get_case_timeline(*, tenant: str, case_id: str, db_path: Path | None = None) -> list[dict]:
    target = initialize_store(db_path)
    with _connect(target) as connection:
        rows = connection.execute(
            """
            SELECT event_id, tenant, case_id, draft_id, batch_id, event_type, event_created_at,
                   received_at, request_id, payload_json
            FROM case_events
            WHERE tenant = ? AND case_id = ?
            ORDER BY received_at ASC, rowid ASC
            """,
            (tenant, case_id),
        ).fetchall()
    return [_row_to_event(row) for row in rows]


def get_store_stats(*, db_path: Path | None = None) -> dict:
    target = initialize_store(db_path)
    with _connect(target) as connection:
        total_events = connection.execute("SELECT COUNT(*) FROM case_events").fetchone()[0]
        total_cases = connection.execute("SELECT COUNT(DISTINCT tenant || '::' || case_id) FROM case_events").fetchone()[0]
        total_tenants = connection.execute("SELECT COUNT(DISTINCT tenant) FROM case_events").fetchone()[0]
        total_rule_packages = connection.execute("SELECT COUNT(*) FROM rule_packages").fetchone()[0]
        total_seller_profiles = connection.execute("SELECT COUNT(*) FROM seller_profiles WHERE status = 'active'").fetchone()[0]
        total_buyer_profiles = connection.execute("SELECT COUNT(*) FROM buyer_profiles WHERE status = 'active'").fetchone()[0]
        total_line_profiles = connection.execute("SELECT COUNT(*) FROM invoice_line_profiles WHERE status = 'active'").fetchone()[0]
    return {
        "db_path": str(target),
        "total_events": int(total_events),
        "total_cases": int(total_cases),
        "total_tenants": int(total_tenants),
        "total_rule_packages": int(total_rule_packages),
        "total_seller_profiles": int(total_seller_profiles),
        "total_buyer_profiles": int(total_buyer_profiles),
        "total_line_profiles": int(total_line_profiles),
    }


def publish_rule_package(
    *,
    tenant: str,
    version: str,
    rules: list[dict],
    note: str = "",
    db_path: Path | None = None,
) -> RulePackageResult:
    target = initialize_store(db_path)
    clean_tenant = tenant.strip() or "default"
    clean_version = version.strip() or datetime.now().strftime("%Y%m%d%H%M%S")
    published_at = datetime.now().isoformat(timespec="seconds")
    package_id = f"rules-{uuid4().hex[:12]}"
    with _connect(target) as connection:
        connection.execute(
            """
            INSERT INTO rule_packages (package_id, tenant, version, status, published_at, rules_json, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                package_id,
                clean_tenant,
                clean_version,
                "active",
                published_at,
                json.dumps(rules, ensure_ascii=False),
                note,
            ),
        )
    return RulePackageResult(
        package_id=package_id,
        tenant=clean_tenant,
        version=clean_version,
        rule_count=len(rules),
        published_at=published_at,
    )


def get_latest_rule_package(*, tenant: str, db_path: Path | None = None) -> dict | None:
    target = initialize_store(db_path)
    with _connect(target) as connection:
        row = connection.execute(
            """
            SELECT package_id, tenant, version, status, published_at, rules_json, note
            FROM rule_packages
            WHERE tenant = ? AND status = 'active'
            ORDER BY published_at DESC, rowid DESC
            LIMIT 1
            """,
            (tenant,),
        ).fetchone()
    if row is None:
        return None
    return {
        "package_id": row["package_id"],
        "tenant": row["tenant"],
        "version": row["version"],
        "status": row["status"],
        "published_at": row["published_at"],
        "note": row["note"] or "",
        "rules": json.loads(row["rules_json"] or "[]"),
    }


def import_customer_profiles(
    *,
    tenant: str,
    source: str,
    sent_at: str,
    seller_profiles: list[dict],
    source_confidence: str = "official_history_export",
    summary: dict | None = None,
    db_path: Path | None = None,
) -> ProfileImportResult:
    target = initialize_store(db_path)
    clean_tenant = tenant.strip() or "default"
    imported_at = datetime.now().isoformat(timespec="seconds")
    batch_id = f"profiles-{uuid4().hex[:12]}"
    clean_source_confidence = source_confidence.strip() or "official_history_export"
    seller_count = 0
    buyer_count = 0
    line_profile_count = 0

    with _connect(target) as connection:
        for seller in seller_profiles:
            if not isinstance(seller, dict):
                continue
            seller_name = str(seller.get("seller_name") or "").strip()
            seller_tax_id = str(seller.get("seller_tax_id") or "").strip()
            if not seller_name or not seller_tax_id:
                continue
            seller_count += 1
            payload = {
                **seller,
                "status": "active",
                "source_confidence": str(seller.get("source_confidence") or clean_source_confidence),
                "profile_batch_id": batch_id,
                "updated_at": imported_at,
            }
            connection.execute(
                """
                INSERT INTO seller_profiles (
                    tenant, seller_tax_id, seller_name, status, source_confidence,
                    profile_batch_id, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant, seller_tax_id) DO UPDATE SET
                    seller_name=excluded.seller_name,
                    status=excluded.status,
                    source_confidence=excluded.source_confidence,
                    profile_batch_id=excluded.profile_batch_id,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    clean_tenant,
                    seller_tax_id,
                    seller_name,
                    "active",
                    payload["source_confidence"],
                    batch_id,
                    imported_at,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

            for buyer in seller.get("buyer_profiles") or []:
                if not isinstance(buyer, dict):
                    continue
                buyer_name = str(buyer.get("buyer_name") or "").strip()
                buyer_tax_id = str(buyer.get("buyer_tax_id") or "").strip()
                if not buyer_name and not buyer_tax_id:
                    continue
                buyer_count += 1
                buyer_payload = {
                    **buyer,
                    "seller_name": seller_name,
                    "seller_tax_id": seller_tax_id,
                    "status": "active",
                    "source_confidence": str(buyer.get("source_confidence") or clean_source_confidence),
                    "profile_batch_id": batch_id,
                    "updated_at": imported_at,
                }
                connection.execute(
                    """
                    INSERT INTO buyer_profiles (
                        tenant, seller_tax_id, buyer_tax_id, buyer_name, status, source_confidence,
                        line_count, profile_batch_id, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant, seller_tax_id, buyer_tax_id, buyer_name) DO UPDATE SET
                        status=excluded.status,
                        source_confidence=excluded.source_confidence,
                        line_count=excluded.line_count,
                        profile_batch_id=excluded.profile_batch_id,
                        updated_at=excluded.updated_at,
                        payload_json=excluded.payload_json
                    """,
                    (
                        clean_tenant,
                        seller_tax_id,
                        buyer_tax_id,
                        buyer_name,
                        "active",
                        buyer_payload["source_confidence"],
                        int(buyer.get("line_count") or 0),
                        batch_id,
                        imported_at,
                        json.dumps(buyer_payload, ensure_ascii=False),
                    ),
                )

            for line in seller.get("project_profiles") or seller.get("invoice_line_profiles") or []:
                if not isinstance(line, dict):
                    continue
                project_name = str(line.get("project_name") or "").strip()
                tax_category = str(line.get("tax_category") or "").strip()
                tax_code = str(line.get("tax_code") or "").strip()
                tax_rate = str(line.get("tax_rate") or line.get("tax_treatment_or_rate") or "").strip()
                unit = str(line.get("unit") or "项").strip() or "项"
                if not project_name and not tax_code:
                    continue
                line_profile_count += 1
                line_payload = {
                    **line,
                    "seller_name": seller_name,
                    "seller_tax_id": seller_tax_id,
                    "status": "active",
                    "source_confidence": str(line.get("source_confidence") or clean_source_confidence),
                    "profile_batch_id": batch_id,
                    "updated_at": imported_at,
                }
                connection.execute(
                    """
                    INSERT INTO invoice_line_profiles (
                        tenant, seller_tax_id, project_name, tax_category, tax_code, tax_rate, unit,
                        status, source_confidence, line_count, profile_batch_id, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant, seller_tax_id, project_name, tax_category, tax_code, tax_rate, unit) DO UPDATE SET
                        status=excluded.status,
                        source_confidence=excluded.source_confidence,
                        line_count=excluded.line_count,
                        profile_batch_id=excluded.profile_batch_id,
                        updated_at=excluded.updated_at,
                        payload_json=excluded.payload_json
                    """,
                    (
                        clean_tenant,
                        seller_tax_id,
                        project_name,
                        tax_category,
                        tax_code,
                        tax_rate,
                        unit,
                        "active",
                        line_payload["source_confidence"],
                        int(line.get("line_count") or 0),
                        batch_id,
                        imported_at,
                        json.dumps(line_payload, ensure_ascii=False),
                    ),
                )

        import_summary = {
            **(summary or {}),
            "seller_count": seller_count,
            "buyer_count": buyer_count,
            "line_profile_count": line_profile_count,
        }
        connection.execute(
            """
            INSERT INTO profile_import_batches (
                batch_id, tenant, source, source_confidence, sent_at, imported_at,
                seller_count, buyer_count, line_profile_count, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                clean_tenant,
                source.strip() or "invoice-demo-batch-import",
                clean_source_confidence,
                sent_at,
                imported_at,
                seller_count,
                buyer_count,
                line_profile_count,
                json.dumps(import_summary, ensure_ascii=False),
            ),
        )

    return ProfileImportResult(
        batch_id=batch_id,
        tenant=clean_tenant,
        seller_count=seller_count,
        buyer_count=buyer_count,
        line_profile_count=line_profile_count,
        imported_at=imported_at,
    )


def get_latest_customer_profiles(
    *,
    tenant: str,
    seller_tax_id: str = "",
    seller_name: str = "",
    db_path: Path | None = None,
) -> dict:
    target = initialize_store(db_path)
    clean_tenant = tenant.strip() or "default"
    conditions = ["tenant = ?", "status = 'active'"]
    params: list[str] = [clean_tenant]
    if seller_tax_id.strip():
        conditions.append("seller_tax_id = ?")
        params.append(seller_tax_id.strip())
    if seller_name.strip():
        conditions.append("seller_name LIKE ?")
        params.append(f"%{seller_name.strip()}%")
    where_clause = " AND ".join(conditions)
    with _connect(target) as connection:
        seller_rows = connection.execute(
            f"""
            SELECT seller_tax_id, seller_name, updated_at, payload_json
            FROM seller_profiles
            WHERE {where_clause}
            ORDER BY updated_at DESC, seller_name ASC
            """,
            params,
        ).fetchall()
        sellers = []
        for seller_row in seller_rows:
            sid = seller_row["seller_tax_id"]
            seller_payload = json.loads(seller_row["payload_json"] or "{}")
            buyer_rows = connection.execute(
                """
                SELECT payload_json FROM buyer_profiles
                WHERE tenant = ? AND seller_tax_id = ? AND status = 'active'
                ORDER BY line_count DESC, buyer_name ASC
                """,
                (clean_tenant, sid),
            ).fetchall()
            line_rows = connection.execute(
                """
                SELECT payload_json FROM invoice_line_profiles
                WHERE tenant = ? AND seller_tax_id = ? AND status = 'active'
                ORDER BY line_count DESC, project_name ASC
                """,
                (clean_tenant, sid),
            ).fetchall()
            seller_payload["buyer_profiles"] = [json.loads(row["payload_json"] or "{}") for row in buyer_rows]
            seller_payload["project_profiles"] = [json.loads(row["payload_json"] or "{}") for row in line_rows]
            sellers.append(seller_payload)
    return {
        "tenant": clean_tenant,
        "seller_count": len(sellers),
        "sellers": sellers,
    }


def list_rule_candidates(*, tenant: str, db_path: Path | None = None, limit: int = 5000) -> list[dict]:
    target = initialize_store(db_path)
    with _connect(target) as connection:
        rows = connection.execute(
            """
            SELECT tenant, case_id, draft_id, event_created_at, received_at, payload_json
            FROM case_events
            WHERE tenant = ? AND event_type = 'local_learned_rules_saved'
            ORDER BY received_at ASC, rowid ASC
            LIMIT ?
            """,
            (tenant, limit),
        ).fetchall()

    grouped: dict[tuple[str, str, str, str], dict] = {}
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        rules = payload.get("rules") if isinstance(payload, dict) else None
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            raw_alias = str(rule.get("raw_alias") or "").strip()
            tax_category = str(rule.get("tax_category") or "").strip()
            tax_code = str(rule.get("tax_code") or "").strip()
            tax_rate = str(rule.get("tax_treatment_or_rate") or "").strip()
            if not raw_alias or not tax_category:
                continue
            key = (_normalize_candidate_key(raw_alias), tax_category, tax_code, tax_rate)
            candidate = grouped.setdefault(
                key,
                {
                    "candidate_id": f"cand-{len(grouped) + 1:04d}",
                    "tenant": row["tenant"],
                    "status": "pending_review",
                    "raw_alias": raw_alias,
                    "normalized_invoice_name": str(rule.get("normalized_invoice_name") or raw_alias.split("、")[0]).strip(),
                    "tax_category": tax_category,
                    "tax_code": tax_code,
                    "tax_treatment_or_rate": tax_rate,
                    "decision_basis": str(rule.get("decision_basis") or "本地人工修正回传").strip(),
                    "confidence": str(rule.get("confidence") or "candidate").strip(),
                    "company_names": [],
                    "case_ids": [],
                    "draft_ids": [],
                    "evidence_count": 0,
                    "first_seen_at": row["received_at"],
                    "last_seen_at": row["received_at"],
                },
            )
            candidate["raw_alias"] = _merge_text_list(candidate["raw_alias"], raw_alias)
            candidate["company_names"] = _append_unique(candidate["company_names"], str(rule.get("company_name") or "").strip())
            candidate["case_ids"] = _append_unique(candidate["case_ids"], str(row["case_id"] or "").strip())
            candidate["draft_ids"] = _append_unique(candidate["draft_ids"], str(row["draft_id"] or "").strip())
            candidate["evidence_count"] += 1
            candidate["last_seen_at"] = row["received_at"]

    candidates = []
    for candidate in grouped.values():
        candidates.append(
            {
                **candidate,
                "company_names": "、".join(candidate["company_names"]),
                "case_ids": "、".join(candidate["case_ids"]),
                "draft_ids": "、".join(candidate["draft_ids"]),
            }
        )
    return sorted(candidates, key=lambda item: (-int(item["evidence_count"]), item["raw_alias"]))


def _row_to_event(row: sqlite3.Row) -> dict:
    return {
        "event_id": row["event_id"],
        "tenant": row["tenant"],
        "case_id": row["case_id"],
        "draft_id": row["draft_id"],
        "batch_id": row["batch_id"],
        "event_type": row["event_type"],
        "event_created_at": row["event_created_at"],
        "received_at": row["received_at"],
        "request_id": row["request_id"],
        "payload": json.loads(row["payload_json"] or "{}"),
    }


def _normalize_candidate_key(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _merge_text_list(existing: str, new_value: str) -> str:
    values = []
    for part in f"{existing}、{new_value}".replace(",", "、").replace("，", "、").split("、"):
        stripped = part.strip()
        if stripped and stripped not in values:
            values.append(stripped)
    return "、".join(values)


def _append_unique(values: list[str], new_value: str) -> list[str]:
    if new_value and new_value not in values:
        values.append(new_value)
    return values


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()

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
    return {
        "db_path": str(target),
        "total_events": int(total_events),
        "total_cases": int(total_cases),
        "total_tenants": int(total_tenants),
        "total_rule_packages": int(total_rule_packages),
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

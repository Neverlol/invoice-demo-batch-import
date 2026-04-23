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
    return {
        "db_path": str(target),
        "total_events": int(total_events),
        "total_cases": int(total_cases),
        "total_tenants": int(total_tenants),
    }


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


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()

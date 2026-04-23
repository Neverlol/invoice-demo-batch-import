from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from threading import Lock, Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import case_events as case_events_module


@dataclass(frozen=True)
class SyncResult:
    status: str
    sent_count: int = 0
    pending_count: int = 0
    endpoint: str = ""
    error: str = ""


_FLUSH_LOCK = Lock()
_FLUSH_ACTIVE = False


def load_sync_config() -> dict[str, str]:
    return {
        "endpoint": (os.getenv("TAX_INVOICE_SYNC_ENDPOINT") or "").strip(),
        "token": (os.getenv("TAX_INVOICE_SYNC_TOKEN") or "").strip(),
        "tenant": (os.getenv("TAX_INVOICE_SYNC_TENANT") or "").strip(),
        "timeout_seconds": (os.getenv("TAX_INVOICE_SYNC_TIMEOUT") or "8").strip(),
    }


def schedule_background_flush(limit: int = 50) -> bool:
    config = load_sync_config()
    if not config["endpoint"]:
        return False

    global _FLUSH_ACTIVE
    with _FLUSH_LOCK:
        if _FLUSH_ACTIVE:
            return False
        _FLUSH_ACTIVE = True
    thread = Thread(target=_flush_in_background, args=(limit,), daemon=True)
    thread.start()
    return True


def flush_pending_events(limit: int = 50) -> SyncResult:
    config = load_sync_config()
    if not config["endpoint"]:
        pending = case_events_module.read_jsonl(case_events_module.pending_events_path())
        result = SyncResult(status="disabled", pending_count=len(pending))
        _write_last_sync_state(result)
        return result

    pending_events = case_events_module.read_jsonl(case_events_module.pending_events_path())
    if not pending_events:
        result = SyncResult(status="idle", endpoint=config["endpoint"])
        _write_last_sync_state(result)
        return result

    to_send = pending_events[:limit]
    remainder = pending_events[limit:]
    payload = {
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "source": "invoice-demo-batch-import",
        "tenant": config["tenant"],
        "events": to_send,
    }
    try:
        response_payload = _post_events(config["endpoint"], payload, token=config["token"], timeout_seconds=int(config["timeout_seconds"] or "8"))
    except Exception as exc:
        result = SyncResult(
            status="failed",
            sent_count=0,
            pending_count=len(pending_events),
            endpoint=config["endpoint"],
            error=str(exc),
        )
        _write_last_sync_state(result)
        return result

    accepted = int(response_payload.get("accepted", len(to_send))) if isinstance(response_payload, dict) else len(to_send)
    if accepted < len(to_send):
        unsent = to_send[accepted:] + remainder
    else:
        unsent = remainder
    case_events_module.write_jsonl(case_events_module.pending_events_path(), unsent)
    result = SyncResult(
        status="success",
        sent_count=min(accepted, len(to_send)),
        pending_count=len(unsent),
        endpoint=config["endpoint"],
    )
    _write_last_sync_state(result, extra={"response": response_payload if isinstance(response_payload, dict) else {}})
    return result


def _flush_in_background(limit: int) -> None:
    global _FLUSH_ACTIVE
    try:
        flush_pending_events(limit=limit)
    finally:
        with _FLUSH_LOCK:
            _FLUSH_ACTIVE = False


def _post_events(endpoint: str, payload: dict[str, Any], *, token: str, timeout_seconds: int) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("request timed out") from exc

    if not body.strip():
        return {"accepted": len(payload.get("events", []))}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {"accepted": len(payload.get("events", [])), "raw_body": body[:500]}
    return parsed if isinstance(parsed, dict) else {"accepted": len(payload.get("events", []))}


def _write_last_sync_state(result: SyncResult, *, extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "status": result.status,
        "sent_count": result.sent_count,
        "pending_count": result.pending_count,
        "endpoint": result.endpoint,
        "error": result.error,
    }
    if extra:
        payload.update(extra)
    case_events_module.write_json(case_events_module.last_sync_state_path(), payload)

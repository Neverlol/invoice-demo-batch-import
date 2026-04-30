from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import case_events as case_events_module
from .tax_rule_engine import write_tenant_rule_package


@dataclass(frozen=True)
class SyncResult:
    status: str
    sent_count: int = 0
    pending_count: int = 0
    endpoint: str = ""
    error: str = ""


@dataclass(frozen=True)
class RulePullResult:
    status: str
    rule_count: int = 0
    endpoint: str = ""
    package_id: str = ""
    version: str = ""
    error: str = ""


@dataclass(frozen=True)
class CustomerProfileSyncResult:
    status: str
    seller_count: int = 0
    buyer_count: int = 0
    line_profile_count: int = 0
    endpoint: str = ""
    batch_id: str = ""
    error: str = ""


_FLUSH_LOCK = Lock()
_FLUSH_ACTIVE = False
_RULE_PULL_LOCK = Lock()
_RULE_PULL_ACTIVE = False
_RULE_PULL_SCHEDULED = False


def load_sync_config() -> dict[str, str]:
    file_config = _load_sync_config_file()
    enabled = _coerce_enabled(
        env_value=os.getenv("TAX_INVOICE_SYNC_ENABLED"),
        file_value=file_config.get("enabled"),
    )
    return {
        "enabled": "1" if enabled else "0",
        "config_path": file_config.get("_config_path", ""),
        "endpoint": (os.getenv("TAX_INVOICE_SYNC_ENDPOINT") or file_config.get("endpoint") or "").strip(),
        "rules_endpoint": (os.getenv("TAX_INVOICE_RULES_ENDPOINT") or file_config.get("rules_endpoint") or "").strip(),
        "profile_import_endpoint": (os.getenv("TAX_INVOICE_PROFILE_IMPORT_ENDPOINT") or file_config.get("profile_import_endpoint") or "").strip(),
        "customer_profiles_endpoint": (os.getenv("TAX_INVOICE_CUSTOMER_PROFILES_ENDPOINT") or file_config.get("customer_profiles_endpoint") or "").strip(),
        "token": (os.getenv("TAX_INVOICE_SYNC_TOKEN") or file_config.get("token") or "").strip(),
        "tenant": (os.getenv("TAX_INVOICE_SYNC_TENANT") or file_config.get("tenant") or "").strip(),
        "timeout_seconds": (os.getenv("TAX_INVOICE_SYNC_TIMEOUT") or str(file_config.get("timeout_seconds") or "8")).strip(),
    }


def schedule_background_flush(limit: int = 50) -> bool:
    config = load_sync_config()
    if config["enabled"] != "1" or not config["endpoint"]:
        return False

    global _FLUSH_ACTIVE
    with _FLUSH_LOCK:
        if _FLUSH_ACTIVE:
            return False
        _FLUSH_ACTIVE = True
    thread = Thread(target=_flush_in_background, args=(limit,), daemon=True)
    thread.start()
    return True


def schedule_background_rule_pull(*, force: bool = False) -> bool:
    config = load_sync_config()
    if config["enabled"] != "1" or not _resolve_rules_endpoint(config):
        return False

    global _RULE_PULL_ACTIVE, _RULE_PULL_SCHEDULED
    with _RULE_PULL_LOCK:
        if _RULE_PULL_ACTIVE:
            return False
        if _RULE_PULL_SCHEDULED and not force:
            return False
        _RULE_PULL_ACTIVE = True
        _RULE_PULL_SCHEDULED = True
    thread = Thread(target=_pull_rules_in_background, daemon=True)
    thread.start()
    return True


def flush_pending_events(limit: int = 50) -> SyncResult:
    config = load_sync_config()
    if config["enabled"] != "1" or not config["endpoint"]:
        pending = case_events_module.read_jsonl(case_events_module.pending_events_path())
        result = SyncResult(status="disabled", pending_count=len(pending), endpoint=config.get("config_path") or config.get("endpoint") or "")
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


def sync_customer_profiles(profile_cache_path: Path | None = None) -> CustomerProfileSyncResult:
    config = load_sync_config()
    endpoint = _resolve_profile_import_endpoint(config)
    if config["enabled"] != "1" or not endpoint:
        return CustomerProfileSyncResult(status="disabled", endpoint=endpoint or config.get("config_path") or "")
    if not config["tenant"]:
        return CustomerProfileSyncResult(status="failed", endpoint=endpoint, error="missing tenant")

    profile_path = profile_cache_path or (_repo_root() / "output" / "workbench" / "tax_invoice_demo" / "客户档案缓存.json")
    try:
        sellers = json.loads(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return CustomerProfileSyncResult(status="failed", endpoint=endpoint, error=f"profile cache not found: {profile_path}")
    except json.JSONDecodeError as exc:
        return CustomerProfileSyncResult(status="failed", endpoint=endpoint, error=f"profile cache is not valid JSON: {exc}")
    if not isinstance(sellers, list):
        return CustomerProfileSyncResult(status="failed", endpoint=endpoint, error="profile cache root must be an array")

    buyer_count = sum(len(seller.get("buyer_profiles") or []) for seller in sellers if isinstance(seller, dict))
    line_count = sum(len(seller.get("project_profiles") or []) for seller in sellers if isinstance(seller, dict))
    payload = {
        "tenant": config["tenant"],
        "source": "invoice-demo-batch-import",
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "source_confidence": "official_history_export",
        "seller_profiles": sellers,
        "summary": {
            "profile_cache_path": str(profile_path),
            "seller_count": len(sellers),
            "buyer_count": buyer_count,
            "line_profile_count": line_count,
        },
    }
    try:
        response_payload = _post_json(endpoint, payload, token=config["token"], timeout_seconds=int(config["timeout_seconds"] or "8"))
    except Exception as exc:
        return CustomerProfileSyncResult(status="failed", endpoint=endpoint, error=str(exc))

    return CustomerProfileSyncResult(
        status="success",
        seller_count=int(response_payload.get("seller_count", len(sellers))) if isinstance(response_payload, dict) else len(sellers),
        buyer_count=int(response_payload.get("buyer_count", buyer_count)) if isinstance(response_payload, dict) else buyer_count,
        line_profile_count=int(response_payload.get("line_profile_count", line_count)) if isinstance(response_payload, dict) else line_count,
        endpoint=endpoint,
        batch_id=str(response_payload.get("batch_id") or "") if isinstance(response_payload, dict) else "",
    )


def pull_latest_customer_profiles(*, seller_tax_id: str = "", seller_name: str = "") -> CustomerProfileSyncResult:
    config = load_sync_config()
    endpoint = _resolve_customer_profiles_endpoint(config, seller_tax_id=seller_tax_id, seller_name=seller_name)
    if config["enabled"] != "1" or not endpoint:
        return CustomerProfileSyncResult(status="disabled", endpoint=endpoint or config.get("config_path") or "")
    try:
        payload = _get_json(endpoint, token=config["token"], timeout_seconds=int(config["timeout_seconds"] or "8"))
    except Exception as exc:
        return CustomerProfileSyncResult(status="failed", endpoint=endpoint, error=str(exc))
    sellers = payload.get("sellers") if isinstance(payload, dict) else None
    if not isinstance(sellers, list):
        return CustomerProfileSyncResult(status="failed", endpoint=endpoint, error="response missing sellers array")
    cache_path = _repo_root() / "output" / "workbench" / "tax_invoice_demo" / "客户档案缓存.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(sellers, ensure_ascii=False, indent=2), encoding="utf-8")
    return CustomerProfileSyncResult(
        status="success",
        seller_count=len(sellers),
        buyer_count=sum(len(seller.get("buyer_profiles") or []) for seller in sellers if isinstance(seller, dict)),
        line_profile_count=sum(len(seller.get("project_profiles") or []) for seller in sellers if isinstance(seller, dict)),
        endpoint=endpoint,
    )


def pull_latest_rule_package() -> RulePullResult:
    config = load_sync_config()
    endpoint = _resolve_rules_endpoint(config)
    if config["enabled"] != "1" or not endpoint:
        result = RulePullResult(status="disabled", endpoint=endpoint or config.get("config_path") or "")
        _write_last_rule_sync_state(result)
        return result
    if not config["tenant"]:
        result = RulePullResult(status="failed", endpoint=endpoint, error="missing tenant")
        _write_last_rule_sync_state(result)
        return result

    try:
        payload = _get_json(endpoint, token=config["token"], timeout_seconds=int(config["timeout_seconds"] or "8"))
    except Exception as exc:
        result = RulePullResult(status="failed", endpoint=endpoint, error=str(exc))
        _write_last_rule_sync_state(result)
        return result

    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        result = RulePullResult(status="failed", endpoint=endpoint, error="response missing rules array")
        _write_last_rule_sync_state(result)
        return result

    rule_count = write_tenant_rule_package(
        rules,
        package_id=str(payload.get("package_id") or ""),
        version=str(payload.get("version") or ""),
        tenant=str(payload.get("tenant") or config["tenant"]),
    )
    result = RulePullResult(
        status="success",
        rule_count=rule_count,
        endpoint=endpoint,
        package_id=str(payload.get("package_id") or ""),
        version=str(payload.get("version") or ""),
    )
    _write_last_rule_sync_state(result)
    return result


def _flush_in_background(limit: int) -> None:
    global _FLUSH_ACTIVE
    try:
        flush_pending_events(limit=limit)
    finally:
        with _FLUSH_LOCK:
            _FLUSH_ACTIVE = False


def _pull_rules_in_background() -> None:
    global _RULE_PULL_ACTIVE
    try:
        pull_latest_rule_package()
    finally:
        with _RULE_PULL_LOCK:
            _RULE_PULL_ACTIVE = False


def _post_events(endpoint: str, payload: dict[str, Any], *, token: str, timeout_seconds: int) -> dict[str, Any]:
    parsed = _post_json(endpoint, payload, token=token, timeout_seconds=timeout_seconds)
    if not parsed:
        return {"accepted": len(payload.get("events", []))}
    return parsed if isinstance(parsed, dict) else {"accepted": len(payload.get("events", []))}


def _post_json(endpoint: str, payload: dict[str, Any], *, token: str, timeout_seconds: int) -> dict[str, Any]:
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
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {"raw_body": body[:500]}
    return parsed if isinstance(parsed, dict) else {"raw_body": body[:500]}


def _get_json(endpoint: str, *, token: str, timeout_seconds: int) -> dict[str, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(endpoint, headers=headers, method="GET")
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
    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("response JSON must be an object")
    return parsed


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


def _write_last_rule_sync_state(result: RulePullResult) -> None:
    payload: dict[str, Any] = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "status": result.status,
        "rule_count": result.rule_count,
        "endpoint": result.endpoint,
        "package_id": result.package_id,
        "version": result.version,
        "error": result.error,
    }
    case_events_module.write_json(case_events_module.last_rule_sync_state_path(), payload)


def _resolve_rules_endpoint(config: dict[str, str]) -> str:
    if config.get("rules_endpoint"):
        return config["rules_endpoint"]
    endpoint = config.get("endpoint", "").strip()
    tenant = config.get("tenant", "").strip()
    if not endpoint or not tenant:
        return ""
    marker = "/api/invoice/events"
    if endpoint.endswith(marker):
        return endpoint[: -len(marker)] + f"/api/invoice/tenants/{quote(tenant)}/rules/latest"
    return ""


def _resolve_profile_import_endpoint(config: dict[str, str]) -> str:
    if config.get("profile_import_endpoint"):
        return config["profile_import_endpoint"]
    endpoint = config.get("endpoint", "").strip()
    marker = "/api/invoice/events"
    if endpoint.endswith(marker):
        return endpoint[: -len(marker)] + "/api/invoice/profile-imports"
    return ""


def _resolve_customer_profiles_endpoint(config: dict[str, str], *, seller_tax_id: str = "", seller_name: str = "") -> str:
    if config.get("customer_profiles_endpoint"):
        base = config["customer_profiles_endpoint"]
    else:
        endpoint = config.get("endpoint", "").strip()
        marker = "/api/invoice/events"
        tenant = config.get("tenant", "").strip()
        if not endpoint or not tenant or not endpoint.endswith(marker):
            return ""
        base = endpoint[: -len(marker)] + f"/api/invoice/tenants/{quote(tenant)}/customer-profiles/latest"
    params = []
    if seller_tax_id.strip():
        params.append(f"seller_tax_id={quote(seller_tax_id.strip())}")
    if seller_name.strip():
        params.append(f"seller_name={quote(seller_name.strip())}")
    if params:
        separator = "&" if "?" in base else "?"
        return base + separator + "&".join(params)
    return base


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _candidate_config_paths() -> list[Path]:
    explicit = (os.getenv("TAX_INVOICE_SYNC_CONFIG") or "").strip()
    repo_root = _repo_root()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(
        [
            repo_root / "sync_client.local.json",
            repo_root / "sync_client.json",
        ]
    )
    return candidates


def _load_sync_config_file() -> dict[str, Any]:
    for path in _candidate_config_paths():
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payload["_config_path"] = str(path)
        return payload
    return {}


def _coerce_enabled(*, env_value: str | None, file_value: Any) -> bool:
    if env_value is not None and env_value.strip():
        return env_value.strip().lower() not in {"0", "false", "off", "no"}
    if isinstance(file_value, bool):
        return file_value
    if isinstance(file_value, str) and file_value.strip():
        return file_value.strip().lower() not in {"0", "false", "off", "no"}
    return bool(file_value) if file_value is not None else True

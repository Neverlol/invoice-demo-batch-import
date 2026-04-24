from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


APPROVED_STATUSES = {"approved", "ready", "publish", "published", "通过", "发布"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish reviewed tax-code rules from a CSV to sync center.")
    parser.add_argument("--tenant", required=True, help="Tenant id, for example shenyang-seed-a")
    parser.add_argument("--csv", required=True, help="Reviewed candidate CSV path")
    parser.add_argument("--endpoint", default=os.getenv("TAX_INVOICE_RULE_PUBLISH_ENDPOINT") or "", help="Rule publish endpoint")
    parser.add_argument("--token", default=os.getenv("TAX_INVOICE_CENTER_TOKEN") or os.getenv("TAX_INVOICE_SYNC_TOKEN") or "", help="Bearer token")
    parser.add_argument("--version", default="", help="Rule package version")
    parser.add_argument("--note", default="", help="Publish note")
    parser.add_argument("--include-pending", action="store_true", help="Publish rows even if status is still pending_review")
    args = parser.parse_args()

    endpoint = args.endpoint.strip() or f"http://127.0.0.1:5021/api/invoice/tenants/{args.tenant}/rules"
    rules = _read_rules(Path(args.csv).expanduser(), include_pending=args.include_pending)
    if not rules:
        print(json.dumps({"status": "empty", "rule_count": 0, "endpoint": endpoint}, ensure_ascii=False, indent=2))
        return 1

    payload = {
        "version": args.version.strip() or datetime.now().strftime("%Y-%m-%d-%H%M%S"),
        "note": args.note.strip() or f"published from {Path(args.csv).name}",
        "rules": rules,
    }
    response = _post_json(endpoint, payload, token=args.token.strip())
    print(json.dumps({"status": "success", "endpoint": endpoint, "response": response}, ensure_ascii=False, indent=2))
    return 0


def _read_rules(path: Path, *, include_pending: bool) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rules: list[dict[str, str]] = []
    for row in rows:
        status = (row.get("status") or "").strip()
        if not include_pending and status not in APPROVED_STATUSES:
            continue
        raw_alias = (row.get("raw_alias") or "").strip()
        tax_category = (row.get("tax_category") or "").strip()
        if not raw_alias or not tax_category:
            continue
        rules.append(
            {
                "rule_id": (row.get("candidate_id") or "").strip(),
                "raw_alias": raw_alias,
                "normalized_invoice_name": (row.get("normalized_invoice_name") or raw_alias.split("、")[0]).strip(),
                "tax_category": tax_category,
                "tax_code": (row.get("tax_code") or "").strip(),
                "tax_treatment_or_rate": (row.get("tax_treatment_or_rate") or "").strip(),
                "decision_basis": (row.get("decision_basis") or "中心端候选审核通过").strip(),
                "confidence": "tenant_reviewed",
                "source_case_ids": (row.get("case_ids") or "").strip(),
                "company_name": (row.get("company_names") or "").strip(),
            }
        )
    return rules


def _post_json(endpoint: str, payload: dict, *, token: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from exc
    return json.loads(body or "{}")


if __name__ == "__main__":
    raise SystemExit(main())

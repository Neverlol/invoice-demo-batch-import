from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sync_center.store import DEFAULT_DB_PATH, list_rule_candidates  # noqa: E402


HEADERS = [
    "candidate_id",
    "tenant",
    "status",
    "raw_alias",
    "normalized_invoice_name",
    "tax_category",
    "tax_code",
    "tax_treatment_or_rate",
    "decision_basis",
    "confidence",
    "company_names",
    "case_ids",
    "draft_ids",
    "evidence_count",
    "first_seen_at",
    "last_seen_at",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export reviewed-rule candidates from sync center events.")
    parser.add_argument("--tenant", required=True, help="Tenant id, for example shenyang-seed-a")
    parser.add_argument("--db", default=os.getenv("TAX_INVOICE_CENTER_DB") or str(DEFAULT_DB_PATH), help="Sync center SQLite path")
    parser.add_argument("--output", default="", help="Output CSV path")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of CSV summary")
    args = parser.parse_args()

    candidates = list_rule_candidates(tenant=args.tenant, db_path=Path(args.db).expanduser())
    if args.json:
        print(json.dumps({"tenant": args.tenant, "candidates": candidates}, ensure_ascii=False, indent=2))
        return 0

    output_path = Path(args.output).expanduser() if args.output else _default_output_path(args.tenant)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({header: candidate.get(header, "") for header in HEADERS})

    print(
        json.dumps(
            {
                "status": "success",
                "tenant": args.tenant,
                "candidate_count": len(candidates),
                "output": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _default_output_path(tenant: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "output" / "sync_center" / "rule_candidates" / f"{tenant}_{stamp}_规则候选.csv"


if __name__ == "__main__":
    raise SystemExit(main())

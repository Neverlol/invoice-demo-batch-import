from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tax_invoice_demo.sync_service import pull_latest_rule_package  # noqa: E402


def main() -> int:
    result = pull_latest_rule_package()
    print(
        json.dumps(
            {
                "status": result.status,
                "rule_count": result.rule_count,
                "endpoint": result.endpoint,
                "package_id": result.package_id,
                "version": result.version,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.status in {"success", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

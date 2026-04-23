from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tax_invoice_demo.sync_service import flush_pending_events  # noqa: E402


def main() -> int:
    result = flush_pending_events()
    print(json.dumps(
        {
            "status": result.status,
            "sent_count": result.sent_count,
            "pending_count": result.pending_count,
            "endpoint": result.endpoint,
            "error": result.error,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if result.status in {"success", "idle", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

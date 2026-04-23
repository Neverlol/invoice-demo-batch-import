from __future__ import annotations

import os

from sync_center import create_app


def main() -> None:
    host = (os.getenv("TAX_INVOICE_CENTER_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int((os.getenv("TAX_INVOICE_CENTER_PORT") or "5021").strip() or "5021")
    debug = (os.getenv("TAX_INVOICE_CENTER_DEBUG") or "0").strip() == "1"
    app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$APP_DIR"

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

".venv/bin/python" -m pip install --upgrade pip
".venv/bin/pip" install -r requirements-sync-center.txt

mkdir -p output/sync_center

cat <<EOF
sync center runtime is ready.

App directory:
  $APP_DIR

Next:
  1. Copy deploy/sync-center.env.example to /etc/tax-invoice-sync-center.env and edit token/db path.
  2. Copy deploy/tax-invoice-sync-center.service to /etc/systemd/system/.
  3. Run: sudo systemctl daemon-reload && sudo systemctl enable --now tax-invoice-sync-center
EOF

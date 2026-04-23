from __future__ import annotations

from app import app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5012, debug=True)

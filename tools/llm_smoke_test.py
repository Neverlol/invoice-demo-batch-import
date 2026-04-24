from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tax_invoice_demo.llm_adapter import (  # noqa: E402
    LLMAdapterError,
    diagnose_llm_config,
    get_llm_adapter,
    validate_extract_invoice_payload,
)


SAMPLE_TEXT = """辽宁恒润电力科技有限公司
91210102MABWM3X12T
500
普票
代理记账和税务申报
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Check LLM config and optionally run invoice extraction.")
    parser.add_argument("--text", default="", help="Text to extract. Defaults to a small invoice sample.")
    parser.add_argument("--file", default="", help="Read extraction text from file.")
    parser.add_argument("--config-only", action="store_true", help="Only print config diagnostic, do not call model.")
    args = parser.parse_args()

    diagnostic = diagnose_llm_config()
    result: dict = {
        "config": asdict(diagnostic),
    }
    if args.config_only or not diagnostic.ready:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if diagnostic.ready or args.config_only else 1

    text = _load_text(args.file) if args.file else (args.text.strip() or SAMPLE_TEXT)
    adapter = get_llm_adapter()
    try:
        response = adapter.extract_invoice_info(text)
        validation_errors = validate_extract_invoice_payload(response.parsed_json)
    except LLMAdapterError as exc:
        result["call"] = {
            "status": "failed",
            "error": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result["call"] = {
        "status": "success" if not validation_errors else "invalid_payload",
        "provider": response.provider,
        "model": response.model,
        "validation_errors": validation_errors,
        "parsed_json": response.parsed_json,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not validation_errors else 1


def _load_text(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

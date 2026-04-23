from __future__ import annotations

import argparse
import json
from pathlib import Path

from tax_invoice_batch_demo.validation import build_validation_report


def main() -> int:
    parser = argparse.ArgumentParser(description="上传税局前预校验批量导入开票模板。")
    parser.add_argument("template_file", help="待上传的批量导入开票 xlsx 文件路径")
    parser.add_argument("-o", "--output", help="输出 JSON 报告路径")
    args = parser.parse_args()

    report = build_validation_report(args.template_file)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

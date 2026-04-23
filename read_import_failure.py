from __future__ import annotations

import argparse
import json
from pathlib import Path

from tax_invoice_batch_demo.failure_details import build_failure_report


def main() -> int:
    parser = argparse.ArgumentParser(description="读取税局批量导入开票失败明细。")
    parser.add_argument("failure_file", help="税局下载的失败明细 xlsx 文件路径")
    parser.add_argument("-o", "--output", help="输出 JSON 报告路径")
    args = parser.parse_args()

    report = build_failure_report(args.failure_file)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tax_invoice_batch_demo.workbench_bridge import (
    DEFAULT_WORKBENCH_ROOT,
    export_saved_workbench_items,
    load_export_candidates,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从现有 workbench draft.json / batch.json 导出税局官方批量开票模板。"
    )
    parser.add_argument(
        "identifiers",
        nargs="+",
        help="草稿 ID、批量草稿 ID，或直接传 draft.json/batch.json 路径。",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="输出 xlsx 路径。",
    )
    parser.add_argument(
        "--workbench-root",
        default=str(DEFAULT_WORKBENCH_ROOT),
        help="workbench 草稿根目录。",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    candidates = load_export_candidates(args.identifiers, workbench_root=args.workbench_root)
    output_path = export_saved_workbench_items(
        args.identifiers,
        args.output,
        workbench_root=args.workbench_root,
    )

    summary = {
        "output_path": str(Path(output_path).resolve()),
        "candidate_count": len(candidates),
        "invoice_count": sum(item.invoice_count for item in candidates),
        "sources": [
            {
                "source_type": item.source_type,
                "identifier": item.identifier,
                "payload_path": str(item.payload_path),
                "draft_ids": list(item.draft_ids),
                "invoice_count": item.invoice_count,
            }
            for item in candidates
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

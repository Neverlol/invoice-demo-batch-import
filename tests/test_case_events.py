import json
import os
import tempfile
import unittest
from pathlib import Path

import tax_invoice_demo.case_events as case_events_module
import tax_invoice_demo.ledger as ledger_module
import tax_invoice_demo.workbench as workbench_module
import tax_invoice_batch_demo.lean_workbench as lean_workbench_module


SIMPLE_TEXT_INPUT = """购买方名称：黑龙江芃领飞象网络科技有限公司
纳税人识别号：91230109MAK8RY0867

发票类型：普通发票
税率：3%

开票明细：
1. 放学乐大菠萝，规格型号：40支/箱，单位：箱，数量：59，含税金额：3540
"""


class CaseEventsTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)
        self.old_workbench_root = workbench_module.WORKBENCH_ROOT
        self.old_event_root = case_events_module.EVENT_ROOT
        self.old_ledger_paths = (
            ledger_module.LEDGER_ROOT,
            ledger_module.LEDGER_CSV_PATH,
            ledger_module.LEDGER_XLSX_PATH,
            ledger_module.FEEDBACK_CSV_PATH,
        )
        self.old_batch_output_root = lean_workbench_module.BATCH_OUTPUT_ROOT
        self.old_success_paths = (
            lean_workbench_module.SUCCESS_LEDGER_CSV,
            lean_workbench_module.SUCCESS_LEDGER_XLSX,
        )
        self.old_sync_endpoint = os.environ.get("TAX_INVOICE_SYNC_ENDPOINT")
        self.old_sync_token = os.environ.get("TAX_INVOICE_SYNC_TOKEN")
        self.old_sync_enabled = os.environ.get("TAX_INVOICE_SYNC_ENABLED")
        workbench_module.WORKBENCH_ROOT = self.temp_path / "workbench"
        case_events_module.EVENT_ROOT = self.temp_path / "events"
        ledger_module.LEDGER_ROOT = self.temp_path / "ledger"
        ledger_module.LEDGER_CSV_PATH = ledger_module.LEDGER_ROOT / "累计发票明细表.csv"
        ledger_module.LEDGER_XLSX_PATH = ledger_module.LEDGER_ROOT / "累计发票明细表.xlsx"
        ledger_module.FEEDBACK_CSV_PATH = ledger_module.LEDGER_ROOT / "赋码反馈候选池.csv"
        lean_workbench_module.BATCH_OUTPUT_ROOT = self.temp_path / "batch_import_preview"
        lean_workbench_module.SUCCESS_LEDGER_CSV = lean_workbench_module.BATCH_OUTPUT_ROOT / "批量导入成功明细.csv"
        lean_workbench_module.SUCCESS_LEDGER_XLSX = lean_workbench_module.BATCH_OUTPUT_ROOT / "批量导入成功明细.xlsx"
        os.environ.pop("TAX_INVOICE_SYNC_ENDPOINT", None)
        os.environ.pop("TAX_INVOICE_SYNC_TOKEN", None)
        os.environ["TAX_INVOICE_SYNC_ENABLED"] = "0"

    def tearDown(self):
        workbench_module.WORKBENCH_ROOT = self.old_workbench_root
        case_events_module.EVENT_ROOT = self.old_event_root
        (
            ledger_module.LEDGER_ROOT,
            ledger_module.LEDGER_CSV_PATH,
            ledger_module.LEDGER_XLSX_PATH,
            ledger_module.FEEDBACK_CSV_PATH,
        ) = self.old_ledger_paths
        lean_workbench_module.BATCH_OUTPUT_ROOT = self.old_batch_output_root
        (
            lean_workbench_module.SUCCESS_LEDGER_CSV,
            lean_workbench_module.SUCCESS_LEDGER_XLSX,
        ) = self.old_success_paths
        if self.old_sync_endpoint is None:
            os.environ.pop("TAX_INVOICE_SYNC_ENDPOINT", None)
        else:
            os.environ["TAX_INVOICE_SYNC_ENDPOINT"] = self.old_sync_endpoint
        if self.old_sync_token is None:
            os.environ.pop("TAX_INVOICE_SYNC_TOKEN", None)
        else:
            os.environ["TAX_INVOICE_SYNC_TOKEN"] = self.old_sync_token
        if self.old_sync_enabled is None:
            os.environ.pop("TAX_INVOICE_SYNC_ENABLED", None)
        else:
            os.environ["TAX_INVOICE_SYNC_ENABLED"] = self.old_sync_enabled
        self.tempdir.cleanup()

    def test_create_save_and_success_write_case_events(self):
        draft = workbench_module.create_draft_from_workbench("吉林省风生水起商贸有限公司", SIMPLE_TEXT_INPUT, "", [])
        updated = lean_workbench_module.save_lean_draft_from_form(
            draft.draft_id,
            {
                "company_name": draft.company_name,
                "raw_text": draft.raw_text,
                "note": "人工补充备注",
                "buyer_name": draft.buyer.name,
                "buyer_tax_id": draft.buyer.tax_id,
                "buyer_address": draft.buyer.address,
                "buyer_phone": draft.buyer.phone,
                "buyer_bank_name": draft.buyer.bank_name,
                "buyer_bank_account": draft.buyer.bank_account,
                "invoice_kind": draft.invoice_kind,
                "special_business": draft.special_business,
                "line_project_name": [draft.lines[0].project_name],
                "line_tax_category": [draft.lines[0].tax_category],
                "line_tax_code": [draft.lines[0].tax_code],
                "line_specification": [draft.lines[0].specification],
                "line_unit": [draft.lines[0].unit],
                "line_quantity": [draft.lines[0].quantity],
                "line_unit_price": [draft.lines[0].unit_price],
                "line_amount_with_tax": [draft.lines[0].amount_with_tax],
                "line_tax_rate": [draft.lines[0].tax_rate],
                "line_coding_reference": [draft.lines[0].coding_reference],
            },
            [],
        )
        lean_workbench_module.export_draft_template(updated)
        lean_workbench_module.record_success_to_ledger(updated)

        pending_path = case_events_module.EVENT_ROOT / "pending_events.jsonl"
        self.assertTrue(pending_path.exists())
        events = [json.loads(line) for line in pending_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        event_types = [event["event_type"] for event in events]
        self.assertIn("draft_created", event_types)
        self.assertIn("draft_updated", event_types)
        self.assertIn("manual_edits_recorded", event_types)
        self.assertIn("template_exported", event_types)
        self.assertIn("success_recorded", event_types)
        self.assertTrue(all(event["case_id"] == draft.case_id for event in events))
        created_payload = next(event["payload"] for event in events if event["event_type"] == "draft_created")
        self.assertIn("extract_strategy", created_payload)
        self.assertIn("llm_provider", created_payload)
        self.assertIn("extract_warnings", created_payload)


if __name__ == "__main__":
    unittest.main()

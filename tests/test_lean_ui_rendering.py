import os
import tempfile
import unittest
from pathlib import Path

from werkzeug.datastructures import MultiDict

import app as app_module
from app import app
import tax_invoice_batch_demo.lean_workbench as lean_workbench_module
import tax_invoice_demo.case_events as case_events_module
import tax_invoice_demo.ledger as ledger_module
import tax_invoice_demo.tax_rule_engine as tax_rule_engine_module
import tax_invoice_demo.workbench as workbench_module


MINIMAL_TEXT_INPUT = """辽宁恒润电力科技有限公司
91210102MABWM3X12T
500
普票
代理记账和税务申报
"""


class LeanUIRenderingTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)
        self.old_workbench_root = workbench_module.WORKBENCH_ROOT
        self.old_event_root = case_events_module.EVENT_ROOT
        self.old_learned_rules_path = tax_rule_engine_module.LEARNED_RULES_PATH
        self.old_tenant_rules_path = tax_rule_engine_module.TENANT_RULES_PATH
        self.old_ledger_paths = (
            ledger_module.LEDGER_ROOT,
            ledger_module.LEDGER_CSV_PATH,
            ledger_module.LEDGER_XLSX_PATH,
            ledger_module.FEEDBACK_CSV_PATH,
        )
        self.old_batch_output_root = lean_workbench_module.BATCH_OUTPUT_ROOT
        self.old_sync_endpoint = os.environ.get("TAX_INVOICE_SYNC_ENDPOINT")
        self.old_sync_token = os.environ.get("TAX_INVOICE_SYNC_TOKEN")
        self.old_sync_enabled = os.environ.get("TAX_INVOICE_SYNC_ENABLED")

        workbench_module.WORKBENCH_ROOT = self.temp_path / "workbench"
        case_events_module.EVENT_ROOT = self.temp_path / "events"
        tax_rule_engine_module.LEARNED_RULES_PATH = self.temp_path / "ledger" / "本地即时学习赋码规则.csv"
        tax_rule_engine_module.TENANT_RULES_PATH = self.temp_path / "ledger" / "客户同步赋码规则.csv"
        tax_rule_engine_module.load_tenant_coding_library.cache_clear()
        tax_rule_engine_module.load_learned_coding_library.cache_clear()
        ledger_module.LEDGER_ROOT = self.temp_path / "ledger"
        ledger_module.LEDGER_CSV_PATH = ledger_module.LEDGER_ROOT / "累计发票明细表.csv"
        ledger_module.LEDGER_XLSX_PATH = ledger_module.LEDGER_ROOT / "累计发票明细表.xlsx"
        ledger_module.FEEDBACK_CSV_PATH = ledger_module.LEDGER_ROOT / "赋码反馈候选池.csv"
        lean_workbench_module.BATCH_OUTPUT_ROOT = self.temp_path / "batch_import_preview"
        os.environ.pop("TAX_INVOICE_SYNC_ENDPOINT", None)
        os.environ.pop("TAX_INVOICE_SYNC_TOKEN", None)
        os.environ["TAX_INVOICE_SYNC_ENABLED"] = "0"

    def tearDown(self):
        workbench_module.WORKBENCH_ROOT = self.old_workbench_root
        case_events_module.EVENT_ROOT = self.old_event_root
        tax_rule_engine_module.LEARNED_RULES_PATH = self.old_learned_rules_path
        tax_rule_engine_module.TENANT_RULES_PATH = self.old_tenant_rules_path
        tax_rule_engine_module.load_tenant_coding_library.cache_clear()
        tax_rule_engine_module.load_learned_coding_library.cache_clear()
        (
            ledger_module.LEDGER_ROOT,
            ledger_module.LEDGER_CSV_PATH,
            ledger_module.LEDGER_XLSX_PATH,
            ledger_module.FEEDBACK_CSV_PATH,
        ) = self.old_ledger_paths
        lean_workbench_module.BATCH_OUTPUT_ROOT = self.old_batch_output_root
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

    def test_index_page_puts_service_flow_in_main_stage_not_bottom_rail(self):
        response = app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("智能开票服务流程", html)
        self.assertIn("Service Flow", html)
        self.assertIn("只到预览，不自动最终开具", html)
        self.assertIn("data-file-input", html)
        self.assertIn("data-file-status", html)
        self.assertIn("20260429-v22", html)
        self.assertIn("尚未选择材料", html)
        self.assertNotIn("税局操作步骤", html)
        self.assertNotIn("执行面板", html)

    def test_draft_page_shows_coding_reference_source(self):
        draft = workbench_module.create_draft_from_workbench("吉林省风生水起商贸有限公司", MINIMAL_TEXT_INPUT, "", [])
        lean_workbench_module.save_lean_draft_from_form(
            draft.draft_id,
            _form_from_draft(
                draft,
                tax_category="纳税申报代办",
                tax_code="3040802050000000000",
                tax_rate="3%",
            ),
            [],
        )
        next_draft = workbench_module.create_draft_from_workbench("吉林省风生水起商贸有限公司", MINIMAL_TEXT_INPUT, "", [])

        response = app.test_client().get(f"/drafts/{next_draft.draft_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("命中来源", html)
        self.assertIn("命中 本地即时规则", html)
        self.assertIn("data-coding-note", html)
        self.assertIn("智能开票服务流程", html)
        self.assertIn("Action Panel", html)
        self.assertNotIn("税局操作步骤", html)
        self.assertIn("下一步操作", html)
        self.assertIn("启动开票", html)
        self.assertIn("保存修改", html)
        self.assertNotIn("启动导入", html)
        self.assertNotIn("启动批量导入", html)
        self.assertNotIn("保存并重建模板", html)
        self.assertIn("税局失败明细", html)
        self.assertIn("浏览器连接设置", html)
        self.assertIn("下载税局文件", html)
        self.assertIn("查找税收编码", html)
        self.assertIn("data-taxonomy-query", html)
        self.assertIn("20260429-v21", html)
        self.assertNotIn("草稿摘要", html)
        self.assertNotIn("识别提醒", html)
        self.assertNotIn("CDP 端口", html)

    def test_taxonomy_search_api_returns_official_code_options(self):
        response = app.test_client().get("/api/taxonomy/search?q=医疗")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        labels = "\n".join(item["label"] for item in payload["results"])
        self.assertIn("医疗", labels)
        self.assertTrue(any(item["official_code"] for item in payload["results"]))
        self.assertTrue(any(item["category_short_name"] for item in payload["results"]))

    def test_failure_repair_button_applies_suggestion_and_rebuilds_template(self):
        draft = workbench_module.create_draft_from_workbench("吉林省风生水起商贸有限公司", MINIMAL_TEXT_INPUT, "", [])
        report = lean_workbench_module.enrich_failure_report_for_draft(
            {
                "records": [
                    {
                        "serial_no": draft.draft_id,
                        "source_sheet": "2-发票明细信息",
                        "field_name": "税率",
                        "reason": "第4行税率不合法，请使用如下税率：0.03、0.01。",
                        "failure_type": "seller_tax_rate_restriction",
                        "suggested_action": "请按税局返回的可用税率调整草稿后重建模板。",
                        "allowed_values": ["3%", "1%"],
                        "suggested_value": "3%",
                    }
                ]
            },
            draft,
        )
        lean_workbench_module.save_failure_report_for_draft(draft.draft_id, report)
        client = app.test_client()

        page = client.get(f"/drafts/{draft.draft_id}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("应用安全建议", html)
        self.assertIn("可一键修复", html)
        self.assertIn("需人工确认", html)
        self.assertIn("不可自动修复", html)
        self.assertIn("应用建议：3%", html)

        response = client.post(
            f"/drafts/{draft.draft_id}/apply-failure-repairs",
            data=_form_from_draft(draft, tax_category="现代服务", tax_code="3040802050000000000", tax_rate="13%"),
        )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("已应用 1 条税局建议", html)
        self.assertIn('data-initial-action="save"', html)
        self.assertIn('<button class="secondary" data-invoice-action', html)
        self.assertIn('<button class="primary" data-save-action', html)
        self.assertIn('name="line_tax_rate" value="3%"', html)
        self.assertIn("已应用：3%", html)
        self.assertIn("再次上传前必须人工确认", html)

    def test_failed_run_page_links_back_to_existing_draft_and_uses_clear_failure_wording(self):
        draft = workbench_module.create_draft_from_workbench("吉林省风生水起商贸有限公司", MINIMAL_TEXT_INPUT, "", [])
        report = lean_workbench_module.enrich_failure_report_for_draft(
            {
                "failure_count": 1,
                "records": [
                    {
                        "serial_no": draft.draft_id,
                        "source_sheet": "2-发票明细信息",
                        "field_name": "税率",
                        "reason": "第4行税率不合法，请使用如下税率：0.01。",
                        "failure_type": "seller_tax_rate_restriction",
                        "suggested_action": "请按税局返回的可用税率调整草稿后重建模板。",
                        "allowed_values": ["1%"],
                        "suggested_value": "1%",
                    }
                ],
            },
            draft,
        )
        app_module.RUNS["runfailed1"] = {
            "run_id": "runfailed1",
            "draft_id": draft.draft_id,
            "status": "failed",
            "current_step": "failed",
            "logs": ["failed: 税局导入失败，已下载并解析失败明细。"],
            "error": "",
            "template_path": str(self.temp_path / "batch_import_preview" / f"{draft.draft_id}_batch_import.xlsx"),
            "downloaded_failure_path": str(self.temp_path / "failure.xlsx"),
            "failure_report": report,
            "preview_clicked": False,
        }
        try:
            response = app.test_client().get("/runs/runfailed1")
        finally:
            app_module.RUNS.pop("runfailed1", None)

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("开票未通过；失败明细 Excel 已下载并解析", html)
        self.assertIn("返回草稿修改", html)
        self.assertIn(f"/drafts/{draft.draft_id}", html)
        self.assertIn("当前进度与下一步", html)
        self.assertIn("应用安全建议并回草稿", html)
        self.assertNotIn("本次模板", html)
        self.assertNotIn("执行步骤", html)
        self.assertNotIn("税局返回导入失败。<a", html)


def _form_from_draft(draft, *, tax_category: str, tax_code: str, tax_rate: str):
    form = MultiDict(
        [
            ("company_name", draft.company_name),
            ("raw_text", draft.raw_text),
            ("note", draft.note),
            ("invoice_kind", draft.invoice_kind),
            ("special_business", draft.special_business),
            ("buyer_name", draft.buyer.name),
            ("buyer_tax_id", draft.buyer.tax_id),
            ("buyer_address", draft.buyer.address),
            ("buyer_phone", draft.buyer.phone),
            ("buyer_bank_name", draft.buyer.bank_name),
            ("buyer_bank_account", draft.buyer.bank_account),
        ]
    )
    for line in draft.lines:
        form.add("line_project_name", line.project_name)
        form.add("line_tax_category", tax_category)
        form.add("line_tax_code", tax_code)
        form.add("line_specification", line.specification)
        form.add("line_unit", line.unit)
        form.add("line_quantity", line.quantity)
        form.add("line_unit_price", line.unit_price)
        form.add("line_amount_with_tax", line.resolved_amount_with_tax())
        form.add("line_tax_rate", tax_rate)
        form.add("line_coding_reference", line.coding_reference)
    return form


if __name__ == "__main__":
    unittest.main()

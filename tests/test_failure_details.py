import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from tax_invoice_batch_demo.failure_details import build_failure_report
from tax_invoice_batch_demo.lean_workbench import (
    apply_failure_repairs_to_draft,
    enrich_failure_report_for_draft,
    line_form_rows,
    load_failure_report_for_draft,
    save_failure_report_for_draft,
)
from tax_invoice_demo.models import BuyerInfo, InvoiceDraft, InvoiceLine
import tax_invoice_demo.case_events as case_events_module
import tax_invoice_demo.workbench as workbench_module


class FailureDetailsTest(unittest.TestCase):
    def test_seller_qualification_restriction_is_classified(self):
        reason = (
            "第4行您不属于涉税专业服务机构，商品和服务税收分类编码不允许填写"
            "3040802050000000000（纳税申报代办）、3040603010000000000（一般税务咨询）。"
        )
        with tempfile.TemporaryDirectory() as tempdir:
            workbook_path = Path(tempdir) / "failure.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["发票流水号", "发票类型", "购买方名称", "购买方纳税人识别号", "导入失败原因"])
            sheet.append(["909b942aca", "普通发票", "辽宁恒润电力科技有限公司", "91210102MABWM3X12T", reason])
            workbook.save(workbook_path)

            report = build_failure_report(workbook_path)

        self.assertEqual(report["failure_count"], 1)
        self.assertEqual(report["summary_by_type"], {"seller_qualification_restriction": 1})
        record = report["records"][0]
        self.assertEqual(record["serial_no"], "909b942aca")
        self.assertEqual(record["source_sheet"], "2-发票明细信息")
        self.assertEqual(record["field_name"], "商品和服务税收编码")
        self.assertEqual(record["failure_type"], "seller_qualification_restriction")
        self.assertIn("不是模板格式错误", record["suggested_action"])

    def test_tax_rate_restriction_extracts_allowed_values(self):
        reason = "第4行税率不合法，请使用如下税率：0.03、0.01、0。"
        with tempfile.TemporaryDirectory() as tempdir:
            workbook_path = Path(tempdir) / "failure.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["发票流水号", "发票类型", "购买方名称", "购买方纳税人识别号", "导入失败原因"])
            sheet.append(["draft001", "普通发票", "黑龙江式领飞象网络科技有限公司", "91230109MAK8RY0867", reason])
            workbook.save(workbook_path)

            report = build_failure_report(workbook_path)

        record = report["records"][0]
        self.assertEqual(record["field_name"], "税率")
        self.assertEqual(record["failure_type"], "seller_tax_rate_restriction")
        self.assertEqual(record["allowed_values"], ["3%", "1%", "0%"])
        self.assertEqual(record["suggested_value"], "3%")

    def test_failure_report_is_mapped_back_to_draft_line(self):
        reason = "第4行商品和服务税收编码为汇总商品编码，请使用下级具体商编。"
        report = {
            "records": [
                {
                    "serial_no": "draft001",
                    "source_sheet": "2-发票明细信息",
                    "field_name": "商品和服务税收编码",
                    "reason": reason,
                    "failure_type": "taxonomy_code_level_error",
                    "suggested_action": "当前编码层级过粗。",
                }
            ]
        }
        draft = InvoiceDraft(
            draft_id="draft001",
            case_id="case001",
            company_name="吉林省风生水起商贸有限公司",
            buyer=BuyerInfo(name="黑龙江式领飞象网络科技有限公司", tax_id="91230109MAK8RY0867"),
            lines=[
                InvoiceLine(project_name="放学乐大菠萝", amount_with_tax="100", tax_code="1030209990000000000"),
                InvoiceLine(project_name="大蜜瓜", amount_with_tax="200", tax_code="1030209990000000000"),
            ],
        )

        enriched = enrich_failure_report_for_draft(report, draft)
        record = enriched["records"][0]
        rows = line_form_rows(draft, failure_report=enriched)

        self.assertEqual(record["target_line_no"], "1")
        self.assertEqual(record["target_label"], "第 1 行：放学乐大菠萝")
        self.assertIn("检查税收编码", record["repair_focus"])
        self.assertEqual(rows[0]["failure_alerts"][0]["target_line_no"], "1")
        self.assertEqual(rows[1]["failure_alerts"], [])

    def test_failure_report_summary_splits_safe_manual_and_non_auto_items(self):
        report = {
            "records": [
                {
                    "serial_no": "draft001",
                    "source_sheet": "2-发票明细信息",
                    "field_name": "税率",
                    "reason": "第4行税率不合法，请使用如下税率：0.01。",
                    "failure_type": "seller_tax_rate_restriction",
                    "suggested_action": "请按税局返回的可用税率调整草稿后重建模板。",
                    "allowed_values": ["1%"],
                    "suggested_value": "1%",
                },
                {
                    "serial_no": "draft001",
                    "source_sheet": "2-发票明细信息",
                    "field_name": "商品和服务税收编码",
                    "reason": "第5行您不属于涉税专业服务机构，商品和服务税收分类编码不允许填写3040802050000000000。",
                    "failure_type": "seller_qualification_restriction",
                    "suggested_action": "主体资质限制。",
                },
                {
                    "serial_no": "draft001",
                    "source_sheet": "1-发票基本信息",
                    "field_name": "购买方纳税人识别号",
                    "reason": "购买方纳税人识别号格式不正确。",
                    "failure_type": "template_option_error",
                    "suggested_action": "请核对购买方税号。",
                },
            ]
        }
        draft = InvoiceDraft(
            draft_id="draft001",
            case_id="case001",
            company_name="吉林省风生水起商贸有限公司",
            buyer=BuyerInfo(name="辽宁恒润电力科技有限公司", tax_id="91210102MABWM3X12T"),
            lines=[
                InvoiceLine(project_name="办公用品", amount_with_tax="100", tax_rate="13%"),
                InvoiceLine(project_name="纳税申报代理", amount_with_tax="200", tax_code="3040802050000000000"),
            ],
        )

        enriched = enrich_failure_report_for_draft(report, draft)

        self.assertEqual(enriched["safe_actionable_count"], 1)
        self.assertEqual(enriched["manual_review_count"], 1)
        self.assertEqual(enriched["non_auto_count"], 1)
        self.assertEqual(enriched["records"][0]["repair_decision_label"], "可一键修复")
        self.assertEqual(enriched["records"][1]["repair_decision_label"], "不可自动修复")
        self.assertEqual(enriched["records"][2]["repair_decision_label"], "需人工确认")

    def test_tax_rate_failure_builds_line_repair_action(self):
        report = {
            "records": [
                {
                    "serial_no": "draft001",
                    "source_sheet": "2-发票明细信息",
                    "field_name": "税率",
                    "reason": "第4行税率不合法，请使用如下税率：0.03、0.01。",
                    "failure_type": "seller_tax_rate_restriction",
                    "suggested_action": "请按税局返回的可用税率调整草稿后重建模板。",
                    "allowed_values": ["3%", "1%"],
                    "suggested_value": "3%",
                }
            ]
        }
        draft = InvoiceDraft(
            draft_id="draft001",
            case_id="case001",
            company_name="吉林省风生水起商贸有限公司",
            buyer=BuyerInfo(name="黑龙江式领飞象网络科技有限公司", tax_id="91230109MAK8RY0867"),
            lines=[InvoiceLine(project_name="服务费", amount_with_tax="100", tax_rate="13%")],
        )

        enriched = enrich_failure_report_for_draft(report, draft)
        record = enriched["records"][0]

        self.assertEqual(record["target_line_no"], "1")
        self.assertEqual(record["repair_field"], "line_tax_rate")
        self.assertEqual(record["repair_value"], "3%")

    def test_apply_failure_repairs_updates_draft_and_report_status(self):
        with tempfile.TemporaryDirectory() as tempdir:
            old_root = workbench_module.WORKBENCH_ROOT
            old_event_root = case_events_module.EVENT_ROOT
            workbench_module.WORKBENCH_ROOT = Path(tempdir)
            case_events_module.EVENT_ROOT = Path(tempdir) / "events"
            try:
                draft = InvoiceDraft(
                    draft_id="draft001",
                    case_id="case001",
                    company_name="吉林省风生水起商贸有限公司",
                    buyer=BuyerInfo(name="黑龙江式领飞象网络科技有限公司", tax_id="91230109MAK8RY0867"),
                    lines=[InvoiceLine(project_name="服务费", amount_with_tax="100", tax_rate="13%")],
                    workbook_name="draft001.xlsx",
                )
                report = enrich_failure_report_for_draft(
                    {
                        "records": [
                            {
                                "serial_no": "draft001",
                                "source_sheet": "2-发票明细信息",
                                "field_name": "税率",
                                "reason": "第4行税率不合法，请使用如下税率：0.03。",
                                "failure_type": "seller_tax_rate_restriction",
                                "suggested_action": "请按税局返回的可用税率调整草稿后重建模板。",
                                "allowed_values": ["3%"],
                                "suggested_value": "3%",
                            }
                        ]
                    },
                    draft,
                )
                save_failure_report_for_draft("draft001", report)

                result = apply_failure_repairs_to_draft(draft)
                reloaded = load_failure_report_for_draft("draft001")
            finally:
                workbench_module.WORKBENCH_ROOT = old_root
                case_events_module.EVENT_ROOT = old_event_root

        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(draft.lines[0].tax_rate, "3%")
        self.assertEqual(reloaded["actionable_count"], 0)
        self.assertEqual(reloaded["applied_count"], 1)
        self.assertEqual(reloaded["records"][0]["repair_status"], "applied")

    def test_enriched_failure_report_can_be_reloaded_for_draft(self):
        report = {"records": [{"target_line_no": "1", "target_label": "第 1 行：服务费"}]}
        with tempfile.TemporaryDirectory() as tempdir:
            old_root = workbench_module.WORKBENCH_ROOT
            workbench_module.WORKBENCH_ROOT = Path(tempdir)
            try:
                save_failure_report_for_draft("draft001", report)
                reloaded = load_failure_report_for_draft("draft001")
            finally:
                workbench_module.WORKBENCH_ROOT = old_root

        self.assertEqual(reloaded, report)


if __name__ == "__main__":
    unittest.main()

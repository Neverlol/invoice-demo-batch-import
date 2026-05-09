import os
import tempfile
import unittest
from pathlib import Path

from werkzeug.datastructures import MultiDict

import app as app_module
from tax_invoice_batch_demo.batch_runner import BatchRunResult
from app import app
import tax_invoice_batch_demo.lean_workbench as lean_workbench_module
import tax_invoice_demo.case_events as case_events_module
import tax_invoice_demo.ledger as ledger_module
import tax_invoice_demo.tax_rule_engine as tax_rule_engine_module
import tax_invoice_demo.workbench as workbench_module
from tax_invoice_demo.models import BuyerInfo, DraftBatch, DraftBatchItem, InvoiceDraft, InvoiceLine


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
        self.assertIn("20260501-v26", html)
        self.assertIn("批量开具发票", html)
        self.assertIn('name="batch_mode"', html)
        self.assertIn("打开辽宁税局", html)
        self.assertIn("识别当前税局主体 / 加载档案", html)
        self.assertIn("客户档案缓存", html)
        self.assertIn("尚未选择材料", html)
        self.assertIn("正在生成草稿，请稍等", html)
        self.assertNotIn("placeholder-card", html)
        self.assertNotIn("生成后会在这里显示", html)
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
        self.assertIn("20260429-v23", html)
        self.assertNotIn("草稿摘要", html)
        self.assertNotIn("识别提醒", html)
        self.assertNotIn("CDP 端口", html)

    def test_batch_page_guides_operator_to_submit_whole_batch_not_single_draft(self):
        seller = "哈尔滨市道里区庆成记隆江猪脚饭店（个体工商户）"
        ledger_module.sync_draft_to_ledger(
            InvoiceDraft(
                draft_id="history-food-ui",
                case_id="history-food-ui",
                company_name=seller,
                buyer=BuyerInfo(name="历史购买方", tax_id="91230102MAEMEM2G2M"),
                lines=[
                    InvoiceLine(
                        project_name="餐费",
                        amount_with_tax="86.20",
                        tax_rate="1%",
                        tax_category="餐饮服务",
                        tax_code="3070401000000000000",
                        unit="项",
                        quantity="1",
                        coding_reference="税局历史明细导入，需人工复核",
                    )
                ],
                created_at="2026-04-30T10:00:00",
            )
        )
        batch = workbench_module.create_draft_from_workbench(
            seller,
            """[01.jpg]
发票详情
抬头 黑龙江源速商贸有限公司
税号 91230102MA1CDKE47Y
建议开票金额 13.80

[02.jpg]
发票详情
税号 91230102MAEMEM2G2M
建议开票金额 14.80
""",
            "平台截图批量测试",
            [],
            force_batch=True,
        )

        response = app.test_client().get(f"/batches/{batch.batch_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("批量开票工作表：2 张发票", html)
        self.assertIn("Sheet 1：发票基本信息", html)
        self.assertIn("Sheet 2：发票明细信息", html)
        self.assertIn("Sheet 3：待补全 / 异常项", html)
        self.assertIn("批量明细填充", html)
        self.assertIn("data-batch-recommendation-field", html)
        self.assertIn("一键导入品类明细及税收编码", html)
        self.assertIn("餐费", html)
        self.assertIn("这是本批检查清单，不是开票表", html)
        self.assertIn("下载本批税局 Excel", html)
        self.assertIn("发起本批开票 / 上传税局", html)
        self.assertIn("保存本批修改 / 重新校验", html)
        self.assertIn("高级编辑", html)
        self.assertIn("智能赋码本批未命中明细", html)
        self.assertIn("智能复核本批全部明细", html)

    def test_draft_page_surfaces_note_and_buyer_tax_id_review(self):
        draft = InvoiceDraft(
            draft_id="draft-note-tax-review",
            case_id="note-tax-review",
            company_name="沈阳市铁西区聚腾商贸商行（个体工商户）",
            buyer=BuyerInfo(name="中铁二局集团有限公司", tax_id="91210100BADTAXID"),
            lines=[InvoiceLine(project_name="压板", amount_with_tax="100.00", tax_rate="1%", tax_category="金属制品", tax_code="1080413010000000000")],
            raw_text="客户要求：发票对象和备注必须跟发票样张保持一致。",
            note="项目名称:中铁二局集团有限公司沈阳市王家湾项目经理部",
            material_tags=["图片材料", "样票"],
            created_at="2026-05-09T10:00:00",
            workbook_name="draft-note-tax-review.xlsx",
        )
        workbench_module.save_draft(draft)

        response = app.test_client().get(f"/drafts/{draft.draft_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("备注 / 发票对象", html)
        self.assertIn("项目名称:中铁二局集团有限公司沈阳市王家湾项目经理部", html)
        self.assertIn("购买方税号格式可疑", html)
        self.assertIn("对照原图逐位核对", html)

    def test_draft_inside_batch_links_back_and_hides_single_submit(self):
        draft = InvoiceDraft(
            draft_id="draft-in-batch-ui",
            case_id="batch-ui",
            company_name="吉林省风生水起商贸有限公司",
            buyer=BuyerInfo(name="中铁二局第四工程有限公司", tax_id="544554455445944554"),
            lines=[InvoiceLine(project_name="压板", amount_with_tax="126420.00", tax_rate="1%", tax_category="木制品", tax_code="1050101990000000000")],
            raw_text="批量中的单张草稿",
            created_at="2026-05-09T10:00:00",
            workbook_name="draft-in-batch-ui.xlsx",
        )
        workbench_module.save_draft(draft)
        batch = DraftBatch(
            batch_id="batch-return-ui",
            case_id="batch-ui",
            company_name=draft.company_name,
            created_at="2026-05-09T10:00:00",
            items=[DraftBatchItem(draft_id=draft.draft_id, buyer_name=draft.buyer.name, invoice_kind=draft.invoice_kind, amount_total="126420.00", project_summary="压板", line_count=1)],
        )
        workbench_module.save_draft_batch(batch)

        response = app.test_client().get(f"/drafts/{draft.draft_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("当前是批量中的单张高级编辑", html)
        self.assertIn("返回批量复核", html)
        self.assertIn(f"/batches/{batch.batch_id}", html)
        self.assertNotIn('formaction="/drafts/draft-in-batch-ui/execute"', html)

    def test_batch_smart_code_fills_missing_lines_and_returns_to_batch_page(self):
        draft = InvoiceDraft(
            draft_id="draft-batch-smart-code",
            case_id="batch-smart-code",
            company_name="吉林省风生水起商贸有限公司",
            buyer=BuyerInfo(name="中铁二局第四工程有限公司", tax_id="544554455445944554"),
            lines=[
                InvoiceLine(project_name="压板", amount_with_tax="100.00", tax_rate="1%", tax_category="", tax_code="", coding_reference="未命中本地规则"),
                InvoiceLine(project_name="钢爬梯", amount_with_tax="200.00", tax_rate="1%", tax_category="", tax_code="", coding_reference="未命中本地规则"),
            ],
            raw_text="批量智能赋码测试",
            created_at="2026-05-09T10:00:00",
            workbook_name="draft-batch-smart-code.xlsx",
        )
        workbench_module.save_draft(draft)
        batch = DraftBatch(
            batch_id="batch-smart-code-ui",
            case_id="batch-smart-code",
            company_name=draft.company_name,
            created_at="2026-05-09T10:00:00",
            items=[DraftBatchItem(draft_id=draft.draft_id, buyer_name=draft.buyer.name, invoice_kind=draft.invoice_kind, amount_total="100.00", project_summary="压板", line_count=2)],
        )
        workbench_module.save_draft_batch(batch)

        def fake_smart_code(lines):
            for line in lines:
                line.tax_category = "金属制品"
                line.tax_code = "1080413010000000000"
                line.coding_reference = "智能推荐，需人工复核"

        old_smart_code = app_module.smart_code_invoice_lines
        app_module.smart_code_invoice_lines = fake_smart_code
        try:
            response = app.test_client().post(
                f"/batches/{batch.batch_id}/smart-code",
                data={
                    "draft_id": draft.draft_id,
                    "buyer_name": draft.buyer.name,
                    "buyer_tax_id": draft.buyer.tax_id,
                    "invoice_kind": draft.invoice_kind,
                    "amount_with_tax": "100.00",
                    "project_name": "压板",
                    "tax_category": "",
                    "tax_code": "",
                    "tax_rate": "1%",
                    "unit": "项",
                    "quantity": "1",
                    "smart_code_scope": "missing",
                },
            )
        finally:
            app_module.smart_code_invoice_lines = old_smart_code

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("智能赋码已完成", html)
        self.assertIn("LLM 智能推荐 2 行", html)
        self.assertIn("LLM候选", html)
        self.assertIn("批量导入模板复核", html)
        updated = workbench_module.load_draft(draft.draft_id)
        self.assertEqual([line.tax_code for line in updated.lines], ["1080413010000000000", "1080413010000000000"])

    def test_batch_page_shows_all_lines_note_and_tax_id_warning(self):
        draft = InvoiceDraft(
            draft_id="draft-batch-all-lines",
            case_id="batch-all-lines",
            company_name="沈阳市铁西区聚腾商贸商行（个体工商户）",
            buyer=BuyerInfo(name="中铁二局集团有限公司", tax_id="91210100BADTAXID"),
            lines=[
                InvoiceLine(project_name="压板", amount_with_tax="100.00", tax_rate="1%", tax_category="金属制品", tax_code="1080413010000000000"),
                InvoiceLine(project_name="预埋钢板", amount_with_tax="200.00", tax_rate="1%", tax_category="", tax_code="", coding_reference="未命中本地规则"),
            ],
            raw_text="客户要求：发票对象和备注必须跟发票样张保持一致。",
            note="项目名称:中铁二局集团有限公司沈阳市王家湾项目经理部",
            material_tags=["图片材料", "样票"],
            created_at="2026-05-09T11:00:00",
            workbook_name="draft-batch-all-lines.xlsx",
        )
        workbench_module.save_draft(draft)
        batch = DraftBatch(
            batch_id="batch-all-lines-ui",
            case_id="batch-all-lines",
            company_name=draft.company_name,
            created_at="2026-05-09T11:00:00",
            items=[DraftBatchItem(draft_id=draft.draft_id, buyer_name=draft.buyer.name, invoice_kind=draft.invoice_kind, amount_total="300.00", project_summary="压板", line_count=2)],
        )
        workbench_module.save_draft_batch(batch)

        response = app.test_client().get(f"/batches/{batch.batch_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("全部明细可改", html)
        self.assertIn("1-2", html)
        self.assertIn("预埋钢板", html)
        self.assertIn("备注 / 发票对象", html)
        self.assertIn("项目名称:中铁二局集团有限公司沈阳市王家湾项目经理部", html)
        self.assertIn("对照原图逐位核对", html)

    def test_batch_page_saves_second_line_edits(self):
        draft = InvoiceDraft(
            draft_id="draft-batch-save-line2",
            case_id="batch-save-line2",
            company_name="沈阳市铁西区聚腾商贸商行（个体工商户）",
            buyer=BuyerInfo(name="中铁二局集团有限公司", tax_id="9151010073481642XK"),
            lines=[
                InvoiceLine(project_name="压板", amount_with_tax="100.00", tax_rate="1%", tax_category="金属制品", tax_code="1080413010000000000"),
                InvoiceLine(project_name="预埋钢板", amount_with_tax="200.00", tax_rate="1%", tax_category="", tax_code=""),
            ],
            note="项目地址:辽宁省沈阳市浑南区",
            created_at="2026-05-09T11:00:00",
            workbook_name="draft-batch-save-line2.xlsx",
        )
        workbench_module.save_draft(draft)
        batch = DraftBatch(
            batch_id="batch-save-line2-ui",
            case_id="batch-save-line2",
            company_name=draft.company_name,
            created_at="2026-05-09T11:00:00",
            items=[DraftBatchItem(draft_id=draft.draft_id, buyer_name=draft.buyer.name, invoice_kind=draft.invoice_kind, amount_total="300.00", project_summary="压板", line_count=2)],
        )
        workbench_module.save_draft_batch(batch)

        response = app.test_client().post(
            f"/batches/{batch.batch_id}/save",
            data={
                "draft_id": draft.draft_id,
                "buyer_name": draft.buyer.name,
                "buyer_tax_id": draft.buyer.tax_id,
                "invoice_kind": draft.invoice_kind,
                "note": "项目地址:辽宁省沈阳市浑南区长安桥南街",
                "line_draft-batch-save-line2_0_project_name": "压板",
                "line_draft-batch-save-line2_0_amount_with_tax": "100.00",
                "line_draft-batch-save-line2_0_tax_category": "金属制品",
                "line_draft-batch-save-line2_0_tax_code": "1080413010000000000",
                "line_draft-batch-save-line2_0_tax_rate": "1%",
                "line_draft-batch-save-line2_0_unit": "项",
                "line_draft-batch-save-line2_0_quantity": "1",
                "line_draft-batch-save-line2_1_project_name": "预埋钢板",
                "line_draft-batch-save-line2_1_amount_with_tax": "200.00",
                "line_draft-batch-save-line2_1_tax_category": "金属制品",
                "line_draft-batch-save-line2_1_tax_code": "1080413010000000000",
                "line_draft-batch-save-line2_1_tax_rate": "1%",
                "line_draft-batch-save-line2_1_unit": "项",
                "line_draft-batch-save-line2_1_quantity": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        updated = workbench_module.load_draft(draft.draft_id)
        self.assertEqual(updated.lines[1].tax_code, "1080413010000000000")
        self.assertEqual(updated.note, "项目地址:辽宁省沈阳市浑南区长安桥南街")

    def test_failed_batch_run_returns_to_batch_review_not_single_draft(self):
        batch = DraftBatch(
            batch_id="batch-run-failed-ui",
            case_id="batch-run-failed",
            company_name="沈阳市铁西区聚腾商贸商行（个体工商户）",
            created_at="2026-05-09T11:00:00",
            items=[DraftBatchItem(draft_id="child-1", buyer_name="中铁二局集团有限公司", invoice_kind="增值税专用发票", amount_total="300.00", project_summary="压板", line_count=2)],
        )
        workbench_module.save_draft_batch(batch)
        app_module.RUNS["run-batch-failed"] = {
            "run_id": "run-batch-failed",
            "draft_id": batch.batch_id,
            "status": "failed",
            "current_step": "failed",
            "logs": ["failed: 税局导入失败"],
            "error": "",
            "downloaded_failure_path": "",
            "failure_report": None,
            "preview_clicked": False,
        }
        try:
            response = app.test_client().get("/runs/run-batch-failed")
        finally:
            app_module.RUNS.pop("run-batch-failed", None)

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("本批整体退回", html)
        self.assertIn("回到批量复核修改", html)
        self.assertIn(f"/batches/{batch.batch_id}", html)
        self.assertNotIn("回到本次草稿修改", html)

    def test_batch_smart_code_fills_engineering_steel_lines_without_llm(self):
        draft = InvoiceDraft(
            draft_id="draft-batch-engineering-steel",
            case_id="batch-engineering-steel",
            company_name="沈阳市铁西区聚腾商贸商行（个体工商户）",
            buyer=BuyerInfo(name="中铁二局集团有限公司", tax_id="9151010073481642XK"),
            lines=[
                InvoiceLine(project_name="伸缩缝不锈钢压舌", amount_with_tax="45000.00", tax_rate="1%", tax_category="", tax_code="", unit="套", quantity="75", coding_reference="推荐"),
                InvoiceLine(project_name="预埋钢板", amount_with_tax="200200.00", tax_rate="1%", tax_category="", tax_code="", unit="块", quantity="91", coding_reference="推荐"),
                InvoiceLine(project_name="压板", amount_with_tax="41880.00", tax_rate="1%", tax_category="木制品", tax_code="1050101990000000000", unit="块", quantity="6980", coding_reference="官方分类候选"),
            ],
            note="项目名称:需求单位 全编码；来源 Excel：压板.xls",
            created_at="2026-05-09T12:00:00",
            workbook_name="压板.xls",
        )
        workbench_module.save_draft(draft)
        batch = DraftBatch(
            batch_id="batch-engineering-steel-ui",
            case_id="batch-engineering-steel",
            company_name=draft.company_name,
            created_at="2026-05-09T12:00:00",
            items=[DraftBatchItem(draft_id=draft.draft_id, buyer_name=draft.buyer.name, invoice_kind=draft.invoice_kind, amount_total="267080.00", project_summary="压板", line_count=3)],
        )
        workbench_module.save_draft_batch(batch)

        missing_response = app.test_client().post(
            f"/batches/{batch.batch_id}/smart-code",
            data={"draft_id": draft.draft_id, "buyer_name": draft.buyer.name, "buyer_tax_id": draft.buyer.tax_id, "invoice_kind": draft.invoice_kind, "note": draft.note, "smart_code_scope": "missing"},
        )

        self.assertEqual(missing_response.status_code, 200)
        missing_html = missing_response.get_data(as_text=True)
        self.assertIn("工程材料规则", missing_html)
        self.assertIn("本次没有 LLM 可用推荐", missing_html)
        self.assertIn("工程规则", missing_html)
        updated = workbench_module.load_draft(draft.draft_id)
        self.assertEqual(updated.lines[0].tax_code, "1080401010000000000")
        self.assertEqual(updated.lines[1].tax_code, "1080207070000000000")
        self.assertEqual(updated.lines[2].tax_code, "1050101990000000000")

        all_response = app.test_client().post(
            f"/batches/{batch.batch_id}/smart-code",
            data={"draft_id": draft.draft_id, "buyer_name": draft.buyer.name, "buyer_tax_id": draft.buyer.tax_id, "invoice_kind": draft.invoice_kind, "note": draft.note, "smart_code_scope": "all"},
        )

        self.assertEqual(all_response.status_code, 200)
        updated = workbench_module.load_draft(draft.draft_id)
        self.assertEqual(updated.lines[2].tax_category, "金属制品")
        self.assertEqual(updated.lines[2].tax_code, "1080401010000000000")
        self.assertIn("工程材料规则", updated.lines[2].coding_reference)

    def test_ledger_from_batch_keeps_return_to_batch_review_link(self):
        batch = DraftBatch(
            batch_id="batch-ledger-return-ui",
            case_id="batch-ledger-return",
            company_name="沈阳市铁西区聚腾商贸商行（个体工商户）",
            created_at="2026-05-09T12:00:00",
            items=[DraftBatchItem(draft_id="child-ledger", buyer_name="中铁二局集团有限公司", invoice_kind="增值税专用发票", amount_total="300.00", project_summary="压板", line_count=2)],
        )
        workbench_module.save_draft_batch(batch)

        response = app.test_client().get(f"/ledger?batch_id={batch.batch_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("返回当前批量复核", html)
        self.assertIn(f"/batches/{batch.batch_id}", html)

    def test_taxonomy_search_api_returns_official_code_options(self):
        response = app.test_client().get("/api/taxonomy/search?q=医疗")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        labels = "\n".join(item["label"] for item in payload["results"])
        self.assertIn("医疗", labels)
        self.assertTrue(any(item["official_code"] for item in payload["results"]))
        self.assertTrue(any(item["category_short_name"] for item in payload["results"]))
        self.assertTrue(any(item["official_code"] == "1090245030000000000" for item in payload["results"]))

        code_response = app.test_client().get("/api/taxonomy/search?q=1090245030000000000")
        code_payload = code_response.get_json()
        self.assertEqual(code_payload["results"][0]["official_code"], "1090245030000000000")
        self.assertEqual(code_payload["results"][0]["category_short_name"], "医疗仪器器械")

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

    def test_batch_run_finished_event_is_recorded_for_cloud_observability(self):
        draft = workbench_module.create_draft_from_workbench("吉林省风生水起商贸有限公司", MINIMAL_TEXT_INPUT, "", [])
        template_path = self.temp_path / "batch_import_preview" / f"{draft.draft_id}_batch_import.xlsx"
        run_id = "runfinish1"
        app_module.RUNS[run_id] = {
            "run_id": run_id,
            "draft_id": draft.draft_id,
            "status": "queued",
            "current_step": "queued",
            "logs": [],
            "error": "",
            "template_path": str(template_path),
            "downloaded_failure_path": "",
            "failure_report": None,
            "preview_clicked": False,
        }

        class FakeRunner:
            def __init__(self, **kwargs):
                pass

            def run(self):
                return BatchRunResult(
                    status="done",
                    current_step="done",
                    logs=["attach: ok", "preview: 已点击预览发票"],
                    preview_clicked=True,
                )

        old_runner = app_module.BatchImportRunner
        app_module.BatchImportRunner = FakeRunner
        try:
            app_module._execute_batch_run(run_id, template_path, "http://127.0.0.1:9222")
        finally:
            app_module.BatchImportRunner = old_runner
            app_module.RUNS.pop(run_id, None)

        events = case_events_module.read_jsonl(case_events_module.pending_events_path())
        finished_events = [event for event in events if event["event_type"] == "batch_run_finished"]
        self.assertEqual(len(finished_events), 1)
        payload = finished_events[0]["payload"]
        self.assertEqual(payload["run_id"], run_id)
        self.assertEqual(payload["status"], "done")
        self.assertTrue(payload["preview_clicked"])
        self.assertEqual(payload["logs_tail"][-1], "preview: 已点击预览发票")

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

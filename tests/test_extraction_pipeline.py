import os
import unittest

from tax_invoice_demo.extraction_pipeline import extract_invoice_structured_data


SIMPLE_TEXT_INPUT = """购买方名称：黑龙江芃领飞象网络科技有限公司
纳税人识别号：91230109MAK8RY0867

发票类型：普通发票
税率：3%

开票明细：
1. 放学乐大菠萝，规格型号：40支/箱，单位：箱，数量：59，含税金额：3540
2. 放学乐大蜜瓜，规格型号：40支/箱，单位：箱，数量：62，含税金额：3801.16
"""


class ExtractionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.old_provider = os.environ.get("TAX_INVOICE_LLM_PROVIDER")
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "off"

    def tearDown(self):
        if self.old_provider is None:
            os.environ.pop("TAX_INVOICE_LLM_PROVIDER", None)
        else:
            os.environ["TAX_INVOICE_LLM_PROVIDER"] = self.old_provider

    def test_rules_only_pipeline_keeps_existing_parsing_behavior(self):
        outcome = extract_invoice_structured_data(
            raw_text=SIMPLE_TEXT_INPUT,
            note="",
            document_text="",
            ocr_text="",
        )

        self.assertEqual(outcome.strategy, "rules_only")
        self.assertEqual(outcome.llm_provider, "")
        self.assertEqual(outcome.warnings, [])
        self.assertEqual(outcome.buyer.name, "黑龙江芃领飞象网络科技有限公司")
        self.assertEqual(outcome.buyer.tax_id, "91230109MAK8RY0867")
        self.assertEqual(len(outcome.lines), 2)
        self.assertEqual(outcome.lines[0].project_name, "放学乐大菠萝")
        self.assertEqual(outcome.lines[0].amount_with_tax, "3540")


if __name__ == "__main__":
    unittest.main()

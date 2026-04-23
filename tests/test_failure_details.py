import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from tax_invoice_batch_demo.failure_details import build_failure_report


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


if __name__ == "__main__":
    unittest.main()

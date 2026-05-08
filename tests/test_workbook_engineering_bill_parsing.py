from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from openpyxl import Workbook

from tax_invoice_demo.workbench import _generic_invoice_lines_from_workbook


class EngineeringBillWorkbookParsingTest(unittest.TestCase):
    def test_engineering_bill_headers_parse_lines_and_preserve_numbers(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([
            "序号",
            "清单编码",
            "清单名称",
            "规格/项目特征",
            "单位",
            "数量",
            "发票类型",
            "含税单价(元)",
            "含税总价(元)",
            "税率(%)",
        ])
        sheet.append(["1", "0115020700021", "压板", "110*50*10mm，防锈喷漆", "块", 6980, "增值税专用发票", 6, 41880, 1])
        sheet.append(["2", "0116240300011", "钢爬梯", "宽60cm,带护笼", "米", 10, "增值税专用发票", 1100, 11000, 1])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "engineering_bill.xlsx"
            workbook.save(path)
            lines = _generic_invoice_lines_from_workbook(path)

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].project_name, "压板")
        self.assertEqual(lines[0].specification, "110*50*10mm，防锈喷漆")
        self.assertEqual(lines[0].unit, "块")
        self.assertEqual(lines[0].quantity, "6980")
        self.assertEqual(lines[0].unit_price, "6.00")
        self.assertEqual(lines[0].amount_with_tax, "41880.00")
        self.assertEqual(lines[0].normalized_tax_rate(), "1%")
        self.assertEqual(lines[1].quantity, "10")
        self.assertEqual(lines[1].normalized_tax_rate(), "1%")


if __name__ == "__main__":
    unittest.main()

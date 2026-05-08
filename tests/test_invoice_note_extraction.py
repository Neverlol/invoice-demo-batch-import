from __future__ import annotations

import unittest

from tax_invoice_demo.workbench import _extract_invoice_note_from_context


class InvoiceNoteExtractionTest(unittest.TestCase):
    def test_extracts_project_remark_from_noisy_ocr(self) -> None:
        text = """
        项目名称      规格型号     单位      数量      单价      金额 税率/征收率
        项目名称:需求单位 全编码
        购方开户银行:建行成都铁道支行: 银行账号:******;
        项目名称: 中铁二局集团有限公司沈阳市王家湾〈冬运) 项目经理部
        注 |顺目地址: 辽宁省沈阳市浑南区长安桥南街中铁二局项目部
        """
        self.assertEqual(
            _extract_invoice_note_from_context(text),
            "项目名称:中铁二局集团有限公司沈阳市王家湾（冬运）项目经理部\n"
            "项目地址:辽宁省沈阳市浑南区长安桥南街中铁二局项目部",
        )

    def test_ignores_platform_project_selector_noise(self) -> None:
        text = """
        购买方信息(平台) 销售方信息(您公司) 开票信息
        项目名称(4选1) URS ARSE O)
        备注(账单ID) 202604302202361041
        """
        self.assertEqual(_extract_invoice_note_from_context(text), "")


if __name__ == "__main__":
    unittest.main()

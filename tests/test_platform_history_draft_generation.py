from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from tax_invoice_demo.models import DraftAttachment
from tax_invoice_demo.workbench import _extract_platform_history_draft_units


class PlatformHistoryDraftGenerationTest(unittest.TestCase):
    def test_platform_screenshots_match_latest_history_records_and_ignore_chat_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            draft_dir = Path(tmp)
            uploads = draft_dir / "uploads"
            uploads.mkdir()
            history_path = uploads / "history.xlsx"
            _write_history(history_path)
            ocr_text = """
[01_wechat_longscreenshot.png]
这个开一下
两个

[02_客户群聊图片1.jpg]
无结构化平台开票字段的普通截图

[03_客户群聊图片2.png]
购买方信息(平台) 销售方信息(您公司) 开票信息
名称 北京字跳网络技术有限公司 名称 沈阳市沈河区启运网络电子商务商行（个体工商户）
纳税人识别号 91110108MA01F2L25J
纳税人识别号 92210103MAEGN98R94
*现代服务*推广支持服务费
税率&发票类型 如您想开专票，请开6%/3%的增值税专票
备注(账单ID) 202604302202361041

[04_客户群聊图片3.png]
购买方信息(平台) 销售方信息(您公司) 开票信息
名称 北京字跳网络技术有限公司 名称 沈阳市沈河区启运网络电子商务商行（个体工商户）
纳税人识别号 91110108MA01F2L25J
纳税人识别号 92210103MAEGN98R94
*现代服务*营销支持服务费
税率&发票类型 如您想开专票，请开6%/3%的增值税专票
备注(账单ID) 2026043004023610420
¥14.63
"""
            units = _extract_platform_history_draft_units(
                draft_dir=draft_dir,
                attachments=[DraftAttachment(original_name="history.xlsx", stored_name="uploads/history.xlsx")],
                ocr_text=ocr_text,
                company_name="沈阳市沈河区启运网络电子商务商行（个体工商户）",
            )
        self.assertEqual(len(units), 2)
        self.assertEqual([unit.target_amount for unit in units], ["25.89", "14.63"])
        self.assertEqual([unit.buyer.name for unit in units], ["北京字跳网络技术有限公司", "北京字跳网络技术有限公司"])
        self.assertEqual([unit.note for unit in units], ["202604302202361041", "202604300402361042"])
        self.assertEqual(units[0].lines[0].project_name, "服务费")
        self.assertEqual(units[0].lines[0].tax_rate, "6%")
        self.assertEqual(units[0].lines[0].tax_code, "3049900000000000000")



def _write_history(path: Path) -> None:
    wb = Workbook()
    detail = wb.active
    detail.title = "信息汇总表"
    detail.append([
        "序号", "发票代码", "发票号码", "数电发票号码", "销方识别号", "销方名称", "购方识别号", "购买方名称", "开票日期",
        "税收分类编码", "特定业务类型", "货物或应税劳务名称", "规格型号", "单位", "数量", "单价", "金额", "税率", "税额", "价税合计",
    ])
    detail.append(_detail_row("26212000000652810921", "25.89"))
    detail.append(_detail_row("26212000000650427121", "14.63"))
    base = wb.create_sheet("发票基础信息")
    base.append([
        "序号", "发票代码", "发票号码", "数电发票号码", "销方识别号", "销方名称", "购方识别号", "购买方名称", "开票日期",
        "金额", "税额", "价税合计", "发票来源", "发票票种", "发票状态", "是否正数发票", "发票风险等级", "开票人", "备注",
    ])
    base.append(_base_row("26212000000652810921", "25.89", "2026-05-08 16:05:29"))
    base.append(_base_row("26212000000650427121", "14.63", "2026-05-08 16:04:59"))
    wb.save(path)


def _detail_row(invoice_no: str, total: str) -> list[str]:
    return [
        "1", "", "", invoice_no, "92210103MAEGN98R94", "沈阳市沈河区启运网络电子商务商行（个体工商户）",
        "91110108MA01F2L25J", "北京字跳网络技术有限公司", "2026-05-08 16:00:00", "3049900000000000000", "",
        "*现代服务*服务费", "", "", "", "", total, "6%", "0.00", total,
    ]


def _base_row(invoice_no: str, total: str, issued_at: str) -> list[str]:
    return [
        "1", "", "", invoice_no, "92210103MAEGN98R94", "沈阳市沈河区启运网络电子商务商行（个体工商户）",
        "91110108MA01F2L25J", "北京字跳网络技术有限公司", issued_at, total, "0.00", total, "电子发票服务平台",
        "数电发票（增值税专用发票）", "正常", "是", "正常", "测试员", "",
    ]


if __name__ == "__main__":
    unittest.main()

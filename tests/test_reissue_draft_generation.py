from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from werkzeug.datastructures import FileStorage

from tax_invoice_demo.models import DraftBatch
from tax_invoice_demo.workbench import create_draft_from_workbench, load_draft


BASE_HEADERS = [
    "序号",
    "发票代码",
    "发票号码",
    "数电发票号码",
    "销方识别号",
    "销方名称",
    "购方识别号",
    "购买方名称",
    "开票日期",
    "金额",
    "税额",
    "价税合计",
    "发票来源",
    "发票票种",
    "发票状态",
    "是否正数发票",
    "发票风险等级",
    "开票人",
    "备注",
]

LINE_HEADERS = [
    "序号",
    "发票代码",
    "发票号码",
    "数电发票号码",
    "销方识别号",
    "销方名称",
    "购方识别号",
    "购买方名称",
    "开票日期",
    "税收分类编码",
    "特定业务类型",
    "货物或应税劳务名称",
    "规格型号",
    "单位",
    "数量",
    "单价",
    "金额",
    "税率",
    "税额",
    "价税合计",
]


class ReissueDraftGenerationTest(unittest.TestCase):
    def test_generates_single_reissue_draft_from_original_invoice_and_new_amount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.xlsx"
            _write_history_workbook(
                history_path,
                base_rows=[
                    _base_row("26212000000646103446", "16886.30", "正常", "是", "数电发票（普通发票）"),
                    _base_row("26212000000641487751", "-17071.30", "正常", "否", "数电发票（普通发票）"),
                    _base_row("26212000000640589836", "17071.30", "已红冲-全额", "是", "数电发票（普通发票）"),
                ],
                line_rows=[
                    _line_row("26212000000646103446", "*修理修配服务*维修费", "16886.30", "2020000000000000000"),
                    _line_row("26212000000641487751", "*修理修配服务*维修费", "-17071.30", "2020000000000000000"),
                    _line_row("26212000000640589836", "*修理修配服务*维修费", "17071.30", "2020000000000000000"),
                ],
            )
            draft = _create_from_text(
                "沈阳市唐亮家电售后服务有限公司",
                "dzfp_26212000000640589836 昨天开的发票作废 数不对 重新开 开这个数16886.3",
                history_path,
            )
        self.assertEqual(draft.extract_strategy, "rules_plus_reissue_history")
        self.assertEqual(draft.buyer.name, "创维电器股份有限公司")
        self.assertEqual(draft.invoice_kind, "普通发票")
        self.assertEqual(draft.total_amount_with_tax, "16886.30")
        self.assertEqual(draft.lines[0].project_name, "维修费")
        self.assertEqual(draft.lines[0].tax_code, "2020000000000000000")

    def test_generates_split_reissue_batch_from_amount_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.xlsx"
            remark = "项目名称:测试项目\n项目地址:测试地址"
            _write_history_workbook(
                history_path,
                base_rows=[
                    _base_row("26212000000646117696", "47060.00", "正常", "是", "数电发票（增值税专用发票）", seller="沈阳聚腾商贸有限公司", remark=remark),
                    _base_row("26212000000648651946", "9750.00", "正常", "是", "数电发票（增值税专用发票）", seller="沈阳聚腾商贸有限公司", remark=remark),
                    _base_row("26212000000645672916", "16160.00", "正常", "是", "数电发票（增值税专用发票）", seller="沈阳聚腾商贸有限公司", remark=remark),
                    _base_row("26212000000636481081", "72970.00", "已红冲-全额", "是", "数电发票（增值税专用发票）", seller="沈阳聚腾商贸有限公司", remark=remark),
                ],
                line_rows=[
                    _line_row("26212000000646117696", "*非金属矿物制品*干混抹灰砂浆", "25200.00", "1080199010000000000", spec="M10", unit="吨", qty="70"),
                    _line_row("26212000000646117696", "*非金属矿物制品*干混砌筑砂浆", "21860.00", "1080199010000000000", spec="M7.5", unit="吨", qty="51"),
                    _line_row("26212000000648651946", "*化学试剂助剂*液体速凝剂", "6150.00", "1070214110000000000", unit="吨", qty="3"),
                    _line_row("26212000000648651946", "*化学试剂助剂*粉状速凝剂", "3600.00", "1070214110000000000", spec="袋装25kg", unit="吨", qty="3"),
                    _line_row("26212000000645672916", "*涂料*外墙抗裂腻子", "6400.00", "1070208010000000000", unit="吨", qty="8"),
                    _line_row("26212000000645672916", "*天然砂*河沙", "9760.00", "1020504040100000000", spec="精沙", unit="立方米", qty="78"),
                    _line_row("26212000000636481081", "*非金属矿物制品*干混抹灰砂浆", "72970.00", "1080199010000000000"),
                ],
            )
            batch = _create_from_text(
                "沈阳聚腾商贸有限公司",
                "dzfp_26212000000636481081 这张发票红冲了，这张单子得分三笔开，金额分别为 47060 9750 16160",
                history_path,
                force_batch=True,
            )
        self.assertIsInstance(batch, DraftBatch)
        self.assertEqual(batch.extract_strategy, "rules_plus_reissue_history_batch")
        self.assertEqual([item.amount_total for item in batch.items], ["47060.00", "9750.00", "16160.00"])
        first = load_draft(batch.items[0].draft_id)
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.buyer.name, "中铁二局集团有限公司")
        self.assertEqual(first.invoice_kind, "增值税专用发票")
        self.assertEqual(first.note, remark)
        self.assertEqual(len(first.lines), 2)


def _create_from_text(company_name: str, text: str, history_path: Path, *, force_batch: bool = False):
    with history_path.open("rb") as stream:
        file = FileStorage(stream=stream, filename=history_path.name)
        return create_draft_from_workbench(company_name, text, "", [file], force_batch=force_batch)


def _write_history_workbook(path: Path, *, base_rows: list[list[str]], line_rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "信息汇总表"
    ws.append(LINE_HEADERS)
    for row in line_rows:
        ws.append(row)
    base = wb.create_sheet("发票基础信息")
    base.append(BASE_HEADERS)
    for row in base_rows:
        base.append(row)
    wb.save(path)


def _base_row(invoice_no: str, total: str, status: str, positive: str, kind: str, *, seller: str = "沈阳测试销售方有限公司", remark: str = "") -> list[str]:
    return [
        "1",
        "",
        "",
        invoice_no,
        "912100000000000000",
        seller,
        "91320117062631908C" if "普通" in kind else "91510100MA61RKR7X3",
        "创维电器股份有限公司" if "普通" in kind else "中铁二局集团有限公司",
        "2026-05-08 10:00:00",
        total,
        "0.00",
        total,
        "电子发票服务平台",
        kind,
        status,
        positive,
        "正常",
        "测试员",
        remark,
    ]


def _line_row(
    invoice_no: str,
    name: str,
    total: str,
    tax_code: str,
    *,
    spec: str = "",
    unit: str = "",
    qty: str = "",
) -> list[str]:
    return [
        "1",
        "",
        "",
        invoice_no,
        "912100000000000000",
        "沈阳测试销售方有限公司",
        "91320117062631908C",
        "测试购买方",
        "2026-05-08 10:00:00",
        tax_code,
        "",
        name,
        spec,
        unit,
        qty,
        "",
        total,
        "1%",
        "0.00",
        total,
    ]


if __name__ == "__main__":
    unittest.main()

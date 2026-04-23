from __future__ import annotations

from pathlib import Path

from tax_invoice_batch_demo.batch_template import (
    TemplateBuyer,
    TemplateInvoice,
    TemplateLine,
    export_template_invoices,
)


def main() -> None:
    invoice = TemplateInvoice(
        serial_no="CASE5-DEMO-001",
        invoice_type="增值税专用发票",
        price_includes_tax="是",
        buyer=TemplateBuyer(
            name="黑龙江芃领飞象网络科技有限公司",
            tax_id="91230109MAK8RY0867",
        ),
        lines=[
            TemplateLine(
                project_name="放学乐大菠萝",
                tax_category="冷冻饮品",
                tax_rate="13%",
                specification="40支/箱",
                unit="箱",
                quantity="59",
                unit_price="60",
                amount="3540.00",
            ),
            TemplateLine(
                project_name="放学乐大蜜瓜",
                tax_category="冷冻饮品",
                tax_rate="13%",
                specification="40支/箱",
                unit="箱",
                quantity="52",
                unit_price="60",
                amount="3120.00",
            ),
            TemplateLine(
                project_name="放学乐葚是喜欢",
                tax_category="冷冻饮品",
                tax_rate="13%",
                specification="40支/箱",
                unit="箱",
                quantity="24",
                unit_price="63.798333",
                amount="1531.16",
            ),
        ],
        note="案例5多品类预览导出",
    )

    output_path = (
        Path(__file__).resolve().parents[1]
        / "output"
        / "batch_import_preview"
        / "case5_batch_import_preview.xlsx"
    )
    export_template_invoices([invoice], output_path)
    print(output_path)


if __name__ == "__main__":
    main()


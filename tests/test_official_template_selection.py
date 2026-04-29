import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from tax_invoice_batch_demo.batch_template import DEFAULT_TEMPLATE_PATH, latest_official_template_path


class OfficialTemplateSelectionTest(unittest.TestCase):
    def test_default_template_prefers_new_tax_bureau_version(self):
        self.assertEqual(DEFAULT_TEMPLATE_PATH.name, "(V260401版)批量开票-导入开票模板.xlsx")

    def test_latest_official_template_path_uses_highest_v_version(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            for name in (
                "(V251101版)批量开票-导入开票模板.xlsx",
                "(V260401版)批量开票-导入开票模板.xlsx",
                "readme.xlsx",
            ):
                workbook = Workbook()
                workbook.save(root / name)

            self.assertEqual(
                latest_official_template_path(root).name,
                "(V260401版)批量开票-导入开票模板.xlsx",
            )


if __name__ == "__main__":
    unittest.main()

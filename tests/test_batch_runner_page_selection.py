import unittest

from tax_invoice_batch_demo.batch_runner import _tax_page_score


class BatchRunnerPageSelectionTest(unittest.TestCase):
    def test_batch_invoice_window_scores_above_tax_portal_home(self):
        portal_score = _tax_page_score(
            "https://dppt.jilin.chinatax.gov.cn:8443/",
            "首页-全国统一规范电子税务局",
            "热门服务 发票业务 我的待办 吉林省风生水起商贸有限... 91220100MAK2QHBY1H",
        )
        invoice_score = _tax_page_score(
            "https://dppt.jilin.chinatax.gov.cn:8443/blue-invoice-makeout",
            "发票业务-全国统一规范电子税务局",
            "发票业务 蓝字发票开具 开票信息维护 发票查询统计",
        )
        batch_score = _tax_page_score(
            "https://dppt.jilin.chinatax.gov.cn:8443/blue-invoice-makeout/invoice-batch",
            "批量开票-全国统一规范电子税务局",
            "批量导入 选择文件 预览发票",
        )

        self.assertGreater(invoice_score, portal_score)
        self.assertGreater(batch_score, invoice_score)

    def test_login_page_is_deprioritized(self):
        login_score = _tax_page_score(
            "https://dppt.jilin.chinatax.gov.cn:8443/",
            "登录-全国统一规范电子税务局",
            "登录 密码 验证码",
        )
        portal_score = _tax_page_score(
            "https://dppt.jilin.chinatax.gov.cn:8443/",
            "首页-全国统一规范电子税务局",
            "热门服务 发票业务 我的待办",
        )

        self.assertLess(login_score, portal_score)


if __name__ == "__main__":
    unittest.main()

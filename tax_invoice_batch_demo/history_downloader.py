from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .batch_runner import (
    _click_first_visible_text,
    _extract_tax_subject,
    _origin_from_url,
    _page_label,
    _safe_body_text,
    _safe_title,
    _tax_page_score,
)

DOWNLOAD_ROOT = Path(__file__).resolve().parents[1] / "output" / "customer_profile_history_downloads"


@dataclass
class TaxHistoryDownloadResult:
    status: str
    current_step: str
    logs: list[str] = field(default_factory=list)
    error: str = ""
    subject: str = ""
    page_url: str = ""
    start_date: str = ""
    end_date: str = ""
    downloaded_path: str = ""
    suggested_filename: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "current_step": self.current_step,
            "logs": self.logs,
            "error": self.error,
            "subject": self.subject,
            "page_url": self.page_url,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "downloaded_path": self.downloaded_path,
            "suggested_filename": self.suggested_filename,
        }


class TaxHistoryDownloader:
    """Download official tax-bureau invoice history for customer-profile building.

    P0 target is the Jilin all-invoice query path provided by the onsite test:
    /third-menu/invoice-query/invoice-query -> /invoice-query/invoice-query.
    The implementation uses direct routing first, then visible text fallback, so it
    can be extended to Liaoning/Heilongjiang/Beijing after field testing.
    """

    def __init__(self, *, cdp_endpoint: str = "http://127.0.0.1:9222", months: int = 6) -> None:
        self.cdp_endpoint = cdp_endpoint
        self.months = months if months > 0 else 6
        self.logs: list[str] = []

    def run(self) -> TaxHistoryDownloadResult:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            return self._error("init", f"Playwright 不可用: {type(exc).__name__}: {exc}")

        start_date, end_date = _default_date_range(self.months)
        DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_endpoint)
            try:
                page = self._select_tax_page(browser)
                subject = _extract_tax_subject(page)
                if subject:
                    self._log("subject", f"当前税局主体: {subject}")
                page = self._open_invoice_query_page(page)
                self._set_query_dates(page, start_date, end_date)
                self._click_query(page)
                output_path, suggested = self._export_all_results(page, PlaywrightTimeoutError)
                return TaxHistoryDownloadResult(
                    status="success",
                    current_step="downloaded",
                    logs=self.logs,
                    subject=subject,
                    page_url=page.url,
                    start_date=start_date,
                    end_date=end_date,
                    downloaded_path=str(output_path),
                    suggested_filename=suggested,
                )
            except Exception as exc:  # noqa: BLE001
                self._log("error", f"{type(exc).__name__}: {exc}")
                return TaxHistoryDownloadResult(
                    status="error",
                    current_step="error",
                    logs=self.logs,
                    error=f"{type(exc).__name__}: {exc}",
                    start_date=start_date,
                    end_date=end_date,
                )
            finally:
                browser.close()

    def _select_tax_page(self, browser):
        pages = [page for context in browser.contexts for page in context.pages]
        if not pages:
            raise RuntimeError("未找到可附着的 Edge 标签页。请先用 CDP Edge 登录电子税务局。")
        scored = []
        for page in pages:
            title = _safe_title(page)
            text = _safe_body_text(page)
            score = _tax_page_score(page.url, title, text)
            if "invoice-query" in urlparse(page.url).path:
                score += 130
            if "发票查询统计" in text or "全量发票查询" in text:
                score += 80
            scored.append((score, page, title))
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, page, title = scored[0]
        if best_score <= 0 or "chinatax.gov.cn" not in page.url:
            raise RuntimeError("未找到已登录的电子税务局业务页。请先在 CDP Edge 登录税局并进入发票业务页，再自动下载历史记录。")
        self._log("attach", f"已发现 {len(scored)} 个浏览器页面，选择税局页面: score={best_score} title={title} url={page.url}")
        return page

    def _open_invoice_query_page(self, page):
        origin = _origin_from_url(page.url)
        target = f"{origin}/invoice-query/invoice-query"
        self._log("navigate", f"进入全量发票查询页面: {target}")
        page.goto(target, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        if _is_all_invoice_query_page(page):
            self._log("navigate", "已进入全量发票查询页面。")
            return page

        menu_url = f"{origin}/third-menu/invoice-query/invoice-query"
        self._log("navigate", f"直接进入未确认成功，回到发票查询统计页: {menu_url}")
        page.goto(menu_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        clicked = _click_first_visible_text(page, ("全量发票查询",), timeout=8000)
        if clicked:
            self._log("navigate", f"已点击入口: {clicked}")
            page.wait_for_timeout(2500)
        if _is_all_invoice_query_page(page):
            self._log("navigate", "已确认进入全量发票查询页面。")
            return page
        raise RuntimeError(f"未进入全量发票查询页面。当前地址: {page.url}；页面标题: {_safe_title(page)}")

    def _set_query_dates(self, page, start_date: str, end_date: str) -> None:
        self._log("query", f"设置开票日期区间：{start_date} 至 {end_date}。")
        ok = page.evaluate(
            """
            ({ startDate, endDate }) => {
              const norm = (value) => (value || '').replace(/\s+/g, '');
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const setValue = (input, value) => {
                input.scrollIntoView({ block: 'center', inline: 'center' });
                const proto = Object.getPrototypeOf(input);
                const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
                if (descriptor && descriptor.set) descriptor.set.call(input, value);
                else input.value = value;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('blur', { bubbles: true }));
              };
              const controls = Array.from(document.querySelectorAll('input'))
                .filter(visible)
                .filter((input) => {
                  const text = norm([
                    input.placeholder,
                    input.getAttribute('aria-label'),
                    input.name,
                    input.id,
                    input.closest('.el-form-item,.t-form__item,.ant-form-item,.form-item,div')?.innerText,
                  ].join(' '));
                  return /开票日期|日期|date|Date/.test(text) || /^\d{4}-\d{2}-\d{2}$/.test(input.value || '');
                });
              let startInput = controls.find((input) => /开票日期\(起\)|开票日期起|日期\(起\)|起/.test(norm(input.closest('.el-form-item,.t-form__item,.ant-form-item,.form-item,div')?.innerText || input.placeholder || '')));
              let endInput = controls.find((input) => /开票日期\(止\)|开票日期止|日期\(止\)|止/.test(norm(input.closest('.el-form-item,.t-form__item,.ant-form-item,.form-item,div')?.innerText || input.placeholder || '')));
              if ((!startInput || !endInput) && controls.length >= 2) {
                startInput = startInput || controls[controls.length - 2];
                endInput = endInput || controls[controls.length - 1];
              }
              if (!startInput || !endInput) {
                return { ok: false, count: controls.length };
              }
              setValue(startInput, startDate);
              setValue(endInput, endDate);
              return { ok: true, count: controls.length };
            }
            """,
            {"startDate": start_date, "endDate": end_date},
        )
        if not ok or not ok.get("ok"):
            raise RuntimeError(f"未能定位开票日期起止输入框，候选输入框数量: {ok.get('count') if ok else 0}")
        page.wait_for_timeout(800)
        self._log("query", "开票日期区间已写入页面。")

    def _click_query(self, page) -> None:
        clicked = _click_query_button_by_dom(page)
        if not clicked:
            clicked = bool(_click_first_visible_text(page, ("查询",), timeout=5000))
        if not clicked:
            raise RuntimeError("未找到右侧蓝色“查询”按钮。")
        self._log("query", "已点击查询按钮，等待结果表格。")
        page.wait_for_timeout(4000)
        for _ in range(20):
            text = _safe_body_text(page)
            if "共 0 条" in text or "共0条" in text:
                self._log("query", "查询完成：当前区间暂无发票记录。")
                raise RuntimeError("当前近半年区间查询结果为 0 条，无法下载历史明细。")
            if any(token in text for token in ("数电发票号码", "发票代码", "发票号码", "购/销方名称", "购/销方识别号")):
                self._log("query", "查询结果表格已出现。")
                return
            page.wait_for_timeout(1000)
        self._log("query", "未明确识别表格结果，继续尝试点击“导出”并选择“导出全部”。")

    def _export_all_results(self, page, timeout_error_cls) -> tuple[Path, str]:
        self._log("download", "准备按页面真实流程导出全部历史明细：点击“导出” → “导出全部”。")
        clicked_export = _click_export_dropdown_button(page) or bool(_click_first_visible_text(page, ("导出",), timeout=5000))
        if not clicked_export:
            raise RuntimeError("查询结果表格已出现，但未找到蓝色“导出”按钮。")
        self._log("download", "已点击“导出”按钮，等待下拉选项。")
        page.wait_for_timeout(800)
        try:
            with page.expect_download(timeout=20000) as download_info:
                clicked_all = _click_export_all_option(page) or bool(
                    _click_first_visible_text(page, ("导出全部", "全部导出", "导出全部发票"), timeout=6000)
                )
                if not clicked_all:
                    raise RuntimeError("export all option not found")
            download = download_info.value
            suggested = download.suggested_filename or "tax_invoice_history.xlsx"
            output_path = DOWNLOAD_ROOT / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_filename(suggested)}"
            download.save_as(str(output_path))
            self._log("download", f"已通过“导出全部”下载历史明细: {output_path}")
            return output_path, suggested
        except timeout_error_cls:
            raise RuntimeError("已点击“导出全部”，但未在 20 秒内捕获到浏览器下载。请确认税局页面是否弹出二次确认或下载被浏览器拦截。")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"未能点击下拉项“导出全部”：{type(exc).__name__}: {exc}") from exc

    def _log(self, step: str, message: str) -> None:
        self.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {step}: {message}")

    def _error(self, step: str, message: str) -> TaxHistoryDownloadResult:
        self._log(step, message)
        return TaxHistoryDownloadResult(status="error", current_step=step, logs=self.logs, error=message)


def _default_date_range(months: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=max(months, 1) * 31)
    return start.isoformat(), end.isoformat()


def _is_all_invoice_query_page(page) -> bool:
    path = urlparse(page.url).path.rstrip("/")
    if path.endswith("/invoice-query/invoice-query") and not path.endswith("/third-menu/invoice-query/invoice-query"):
        return True
    text = _safe_body_text(page)
    return "全量发票查询" in text and "开票日期" in text and "查询" in text


def _click_query_button_by_dom(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], .el-button, .t-button, .ant-btn'))
                .filter(visible)
                .filter((el) => (el.innerText || el.textContent || '').replace(/\s+/g, '') === '查询');
              const target = candidates.find((el) => {
                const cls = String(el.className || '');
                const style = window.getComputedStyle(el);
                return /primary|blue|main/.test(cls) || /rgb\(64, 158, 255\)|rgb\(22, 119, 255\)|rgb\(24, 144, 255\)/.test(style.backgroundColor);
              }) || candidates[candidates.length - 1];
              if (!target) return false;
              target.scrollIntoView({ block: 'center', inline: 'center' });
              target.click();
              return true;
            }
            """
        )
    )


def _click_export_dropdown_button(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, '').trim();
              const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], .el-button, .t-button, .ant-btn, .ivu-btn'))
                .filter(visible)
                .filter((el) => textOf(el) === '导出' || (textOf(el).includes('导出') && !textOf(el).includes('导出全部') && textOf(el).length <= 8));
              const target = candidates.find((el) => {
                const cls = String(el.className || '');
                const style = window.getComputedStyle(el);
                return /primary|blue|main/.test(cls) || /rgb\(64, 158, 255\)|rgb\(22, 119, 255\)|rgb\(24, 144, 255\)|rgb\(0, 82, 217\)/.test(style.backgroundColor);
              }) || candidates[0];
              if (!target) return false;
              target.scrollIntoView({ block: 'center', inline: 'center' });
              target.click();
              return true;
            }
            """
        )
    )


def _click_export_all_option(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, '').trim();
              const candidates = Array.from(document.querySelectorAll('li, button, a, [role="menuitem"], [role="option"], .el-dropdown-menu__item, .t-dropdown__item, .ant-dropdown-menu-item, .ivu-dropdown-item, div, span'))
                .filter(visible)
                .filter((el) => ['导出全部', '全部导出', '导出全部发票'].some((token) => textOf(el).includes(token)));
              const target = candidates.find((el) => /item|menu|dropdown|option/.test(String(el.className || '') + ' ' + String(el.getAttribute('role') || ''))) || candidates[0];
              if (!target) return false;
              target.scrollIntoView({ block: 'center', inline: 'center' });
              target.click();
              return true;
            }
            """
        )
    )


def _click_download_button_by_dom(page, texts: tuple[str, ...]) -> bool:
    pattern = "|".join(re.escape(text) for text in texts)
    return bool(
        page.evaluate(
            """
            (patternText) => {
              const pattern = new RegExp(patternText);
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], .el-button, .t-button, .ant-btn, .ivu-btn'))
                .filter(visible)
                .filter((el) => pattern.test((el.innerText || el.textContent || '').replace(/\s+/g, '')));
              const target = candidates[0];
              if (!target) return false;
              target.scrollIntoView({ block: 'center', inline: 'center' });
              target.click();
              return true;
            }
            """,
            pattern,
        )
    )


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip("._ ")
    return cleaned[:140] or "tax_invoice_history.xlsx"

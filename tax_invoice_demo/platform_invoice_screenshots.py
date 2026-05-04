from __future__ import annotations

import re
from dataclasses import dataclass

from .models import BuyerInfo


@dataclass(frozen=True)
class PlatformInvoiceRequest:
    source_name: str
    buyer: BuyerInfo
    amount_with_tax: str
    email: str = ""
    order_no: str = ""
    source_excerpt: str = ""
    project_name: str = ""
    tax_rate: str = ""
    tax_category: str = ""
    tax_code: str = ""
    specification: str = ""
    unit: str = ""
    quantity: str = ""


def extract_platform_invoice_requests(parse_source: str) -> list[PlatformInvoiceRequest]:
    blocks = _split_image_blocks(parse_source)
    if len(blocks) < 2:
        return []
    if not any(_looks_like_platform_invoice_block(text) for _source_name, text in blocks):
        return []
    requests: list[PlatformInvoiceRequest] = []
    for source_name, text in blocks:
        # 批量平台截图的业务单元是“图片”，不是“识别出的购买方”。
        # 即使某张图 OCR 没识别出税号/金额，也要生成待补全草稿，避免 19 张图只剩 4 张。
        buyer_name = _extract_buyer_name(text)
        requests.append(
            PlatformInvoiceRequest(
                source_name=source_name,
                buyer=BuyerInfo(name=buyer_name, tax_id=_extract_tax_id(text)),
                amount_with_tax=_extract_amount(text),
                email=_extract_email(text),
                order_no=_extract_order_no(text),
                source_excerpt=_compact_excerpt(text),
            )
        )
    return requests if len(requests) >= 2 else []


def _split_image_blocks(parse_source: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^\[(?P<name>[^\]]+\.(?:jpg|jpeg|png|webp|bmp))\]\s*$", parse_source, re.IGNORECASE))
    if not matches:
        return []
    blocks: list[tuple[str, str]] = []
    for index, matched in enumerate(matches):
        start = matched.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(parse_source)
        blocks.append((matched.group("name").strip(), parse_source[start:end].strip()))
    return blocks


def _looks_like_platform_invoice_block(text: str) -> bool:
    tokens = ("发票详情", "建议开票金额", "开票金额", "税号", "抬头", "订单号", "联系人邮箱", "邮箱")
    return sum(1 for token in tokens if token in text) >= 2


def _extract_amount(text: str) -> str:
    label_lines = [line for line in text.splitlines() if any(label in line for label in ["建议开票金额", "开票金额", "开要人金额"])]
    for line in reversed(label_lines):
        amount = _extract_amount_from_labeled_line(line)
        if amount:
            return amount
    patterns = [
        r"[¥￥Y]\s*(\d+(?:\.\d{1,2})?)",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for matched in re.finditer(pattern, text, re.IGNORECASE):
            amount = _normalize_amount_candidate(matched.group(1))
            if amount and _looks_like_small_invoice_amount(amount):
                candidates.append(amount)
        if candidates:
            return candidates[-1]
    return ""



def _extract_amount_from_labeled_line(line: str) -> str:
    right = re.split(r"建议开票金额|开票金额|开要人金额|金额", line, maxsplit=1)[-1]
    right = right.replace("¥", " ").replace("￥", " ").replace("Y", " ")
    chunks = re.findall(r"\d+(?:\.\d{1,2})?(?:\s+\d{1,2})?", right)
    for chunk in chunks:
        amount = _normalize_amount_candidate(chunk)
        if amount and _looks_like_small_invoice_amount(amount):
            return amount
    return ""



def _normalize_amount_candidate(value: str) -> str:
    compact = re.sub(r"\s+", "", value).strip(" ,，。;；:：Oo口")
    if not compact:
        return ""
    if "." in compact:
        try:
            return f"{float(compact):.2f}"
        except ValueError:
            return ""
    if not compact.isdigit():
        return ""
    # OCR 常把“15.80”识别成“15 80”或“1580”；把常见餐饮小额按分还原。
    if len(compact) == 3:
        compact = f"{compact[0]}.{compact[1:]}"
    elif len(compact) == 4:
        compact = f"{compact[:-2]}.{compact[-2:]}"
    elif len(compact) == 5 and compact.endswith("0"):
        trimmed = compact[:-1]
        compact = f"{trimmed[:-2]}.{trimmed[-2:]}"
    elif len(compact) > 5:
        return ""
    try:
        return f"{float(compact):.2f}"
    except ValueError:
        return ""


def _extract_tax_id(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    prioritized = [line for line in lines if re.search(r"税\s*[号写]|公司税号|纳税人", line)]
    # 平台截图里订单号也常是 18 位数字，不能把订单号误当税号。
    # P0 只从明确含“税号/纳税人”等标签的行提取税号；识别不到则进入待补全。
    for line in prioritized:
        compact = re.sub(r"\s+", "", line.upper())
        compact = compact.replace("Ｏ", "O").replace("Ｉ", "I")
        for matched in re.finditer(r"[0-9][0-9A-Z]{17}", compact):
            candidate = _normalize_tax_id_noise(matched.group(0))
            if candidate:
                return candidate
    return ""


def _normalize_tax_id_noise(value: str) -> str:
    candidate = value.strip().upper()
    if len(candidate) < 18:
        return ""
    candidate = candidate[:18]
    # 税号里常见 OCR 尾部把 0/1 识别成 O/I，只在数字占比较高的尾部做轻量纠正风险更小。
    candidate = candidate.replace(" ", "")
    if not re.fullmatch(r"[0-9A-Z]{18}", candidate):
        return ""
    return candidate


def _extract_buyer_name(text: str) -> str:
    lines = [line.strip(" |｜>《》\t") for line in text.splitlines() if line.strip()]
    for line in lines:
        cleaned = _cleanup_buyer_name_line(line)
        if _looks_like_company_name(cleaned):
            return cleaned
    # 部分平台 OCR 会把“抬头”识别丢失，回退到含公司/工作室/个体工商户的行。
    for line in lines:
        matched = re.search(r"([\u4e00-\u9fffA-Za-z0-9（）()·]{4,60}(?:有限公司|公司|工作室|个体工商户|商贸|学院|传媒|科技))", line)
        if matched:
            cleaned = _cleanup_buyer_name_line(matched.group(1))
            if _looks_like_company_name(cleaned):
                return cleaned
    return ""


def _cleanup_buyer_name_line(line: str) -> str:
    cleaned = re.sub(r"^(?:公司)?抬头[：:\s]*", "", line)
    cleaned = re.sub(r"^(?:SSS?|==|=|DP|ae|Me|fies|fat|票信息|发票信息|#\d+\.)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" ，,。；;：:|｜>《》\"'”oO器2")
    cleaned = cleaned.replace("...", "…")
    return cleaned.strip()


def _looks_like_company_name(value: str) -> bool:
    if not value or "税号" in value or "邮箱" in value or len(value) < 4:
        return False
    if any(marker in value for marker in ["...", "…", "截断"]):
        return False
    return bool(re.search(r"(有限公司|公司|工作室|个体工商户|学院|商贸|传媒|科技)", value))


def _extract_email(text: str) -> str:
    matched = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9._%+-]+", text)
    return matched.group(0).strip() if matched else ""


def _extract_order_no(text: str) -> str:
    patterns = [r"订单号[：:\s]*([0-9]{10,24})", r"WJ\s*#?\s*25[：:\s]*([0-9]{10,24})", r"WES[：:\s]*([0-9]{10,24})"]
    for pattern in patterns:
        matched = re.search(pattern, text, re.IGNORECASE)
        if matched:
            return matched.group(1)
    matched = re.search(r"\b(8\d{15,21}|18\d{15,21})\b", text.replace(" ", ""))
    return matched.group(1) if matched else ""


def _looks_like_small_invoice_amount(value: str) -> bool:
    try:
        number = float(value)
    except ValueError:
        return False
    return 0 < number < 100000


def _compact_excerpt(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:12])[:800]

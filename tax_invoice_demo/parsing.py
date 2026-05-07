from __future__ import annotations

import re

from .models import BuyerInfo, InvoiceLine

DETAIL_HEADERS = {
    "项目名称": "project_name",
    "开票内容": "project_name",
    "开票项目": "project_name",
    "发票项目": "project_name",
    "商品全名": "project_name",
    "商品名称": "project_name",
    "品名": "project_name",
    "品目": "project_name",
    "物料名称": "project_name",
    "物料描述": "project_name",
    "货物或应税劳务、服务名称": "project_name",
    "货物或应税劳务服务名称": "project_name",
    "名称": "project_name",
    "零件名": "project_name",
    "货品名称": "project_name",
    "服务名称": "project_name",
    "赋码大类": "tax_category",
    "税目大类": "tax_category",
    "分类大类": "tax_category",
    "税收分类": "tax_category",
    "税收分类简称": "tax_category",
    "商品和服务分类": "tax_category",
    "商品和服务分类简称": "tax_category",
    "商品和服务税收分类": "tax_category",
    "商品和服务税收分类简称": "tax_category",
    "税收分类名称": "tax_category",
    "大类": "tax_category",
    "规格": "specification",
    "规格型号": "specification",
    "实际尺寸": "specification",
    "零件编码": "source_item_code",
    "商品编码": "source_item_code",
    "单位": "unit",
    "销售数量": "quantity",
    "数量": "quantity",
    "出库数量": "quantity",
    "单价": "unit_price",
    "未税单价": "unit_price",
    "含税单价": "unit_price",
    "优惠后实售单价": "unit_price",
    "开票金额": "amount_with_tax",
    "金额": "amount_with_tax",
    "含税金额": "amount_with_tax",
    "含税总价": "amount_with_tax",
    "价税合计": "amount_with_tax",
    "合计金额": "amount_with_tax",
    "未税总价": "amount_with_tax",
    "优惠后实售金额": "amount_with_tax",
    "税率": "tax_rate",
    "税率/征收率": "tax_rate",
    "税收编码": "tax_code",
    "税收分类编码": "tax_code",
    "分类编码": "tax_code",
    "商品和服务税收编码": "tax_code",
    "商品和服务税收分类编码": "tax_code",
    "赋码说明": "coding_reference",
    "命中说明": "coding_reference",
    "赋码依据": "coding_reference",
}

BUYER_NAME_PATTERNS = [
    re.compile(r"(?:^|[\s\t])(?:购买方名称|购方名称|客户名称|公司名称|开票抬头|发票抬头|抬头|购货单位|购货方名称|业主单位名称|业主名称)[：:\t ]+\s*(.+)"),
    re.compile(r"(?:^|[\s\t])(?:单位名称|名称)[：:\t ]+\s*(.+)"),
]
BUYER_TAX_ID_PATTERNS = [
    re.compile(r"(?:^|[\s\t])(?:购买方税号|购方税号|单位税号|税号|统一社会信用代码|纳税人识别号|纳税识别号)[：:\t ]+\s*([0-9A-Z]{15,20})"),
]
BUYER_ADDRESS_PATTERNS = [
    re.compile(r"(?:购买方地址|地址)[：:]\s*(.+)"),
]
BUYER_PHONE_PATTERNS = [
    re.compile(r"(?:购买方电话|电话)[：:]\s*([0-9+\-() ]{6,})"),
]
BUYER_BANK_PATTERNS = [
    re.compile(r"(?:购买方开户行|购买方开户银行|开户行|开户银行)[：:]\s*(.+)"),
]
BUYER_ACCOUNT_PATTERNS = [
    re.compile(r"(?:购买方银行账号|银行账号|账号)[：:]\s*([0-9A-Za-z ]{6,})"),
]

LINE_FIELD_HEADERS = {
    **DETAIL_HEADERS,
    "项目": "project_name",
    "商品": "project_name",
    "服务": "project_name",
}

FREEFORM_LINE_RE = re.compile(
    r"^(?P<name>[^0-9:：]{2,}?)"
    r"(?:[\s,，|]+(?P<quantity>\d+(?:\.\d+)?))?"
    r"(?:[\s,，|]+(?P<unit_price>\d+(?:\.\d+)?))?"
    r"(?:[\s,，|]+(?P<amount>\d+(?:\.\d{1,2})?))"
    r"(?:[\s,，|]+(?P<tax>免税|不征税|免征增值税|\d+(?:\.\d+)?%?))?$"
)
INVOICE_PDF_LINE_RE = re.compile(
    r"^\*(?P<category>[^*]+)\*(?P<name>.+?)\s*"
    r"(?P<rate>\d+(?:\.\d+)?)%"
    r"(?P<unit>[^\d\s]+)\s+"
    r"(?P<amount>\d+(?:\.\d+)?)\s+"
    r"(?P<tax_amount>\d+(?:\.\d+)?)"
)
INVOICE_OCR_LINE_RE = re.compile(
    r"^(?P<name>.*?)\s+"
    r"(?P<unit>[^\d\s]{1,6})\s+"
    r"(?P<quantity>\d+(?:\.\d+)?)\s+"
    r"(?P<unit_price>\d+(?:\.\d+)?)\s+"
    r"(?P<amount>\d+(?:\.\s*\d+)?)\s+"
    r"(?P<tax>免税|不征税|免征增值税|\d+(?:\.\d+)?%?)"
)
DAILY_CHAT_ITEM_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<quantity>\d+(?:\.\d+)?)(?P<unit>[\u4e00-\u9fffA-Za-z]{1,8})\s+"
    r"[¥￥]?(?P<amount>\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*元?$"
)

NON_DETAIL_PREFIXES = (
    "税号",
    "统一社会信用代码",
    "纳税人识别号",
    "地址",
    "电话",
    "开户行",
    "银行账号",
    "账号",
    "日期",
    "备注",
    "业主单位名称",
    "业主开票要求",
    "证明材料",
    "发票申请联络函",
)


def normalize_header(value: str) -> str:
    return value.replace("（", "(").replace("）", ")").strip()


def is_header_row(parts: list[str]) -> bool:
    return sum(1 for part in parts if normalize_header(part) in DETAIL_HEADERS) >= 2


def parse_bulk_invoice_lines(raw_text: str) -> list[InvoiceLine]:
    # Keep leading delimiters intact. Many operator spreadsheets leave the
    # first column blank, and stripping the whole row shifts every field left.
    rows = [row.rstrip() for row in raw_text.splitlines() if row.strip()]
    if not rows:
        return []
    if not any("\t" in row for row in rows) and not any("|" in row for row in rows):
        return []

    delimiter = "\t" if any("\t" in row for row in rows) else "|"
    header_map: list[str] | None = None
    header_labels: list[str] | None = None
    parsed: list[InvoiceLine] = []

    for row in rows:
        parts = [part.strip() for part in row.split(delimiter)]
        if not any(parts):
            continue

        if header_map is None and is_header_row(parts):
            header_labels = [normalize_header(part) for part in parts]
            header_map = [DETAIL_HEADERS.get(label, "") for label in header_labels]
            continue

        data = {
            "project_name": "",
            "amount_with_tax": "",
            "tax_rate": "3%",
            "tax_category": "",
            "specification": "",
            "unit": "",
            "quantity": "",
            "unit_price": "",
            "tax_code": "",
            "source_item_code": "",
            "coding_reference": "",
        }
        repeated_block_selected = False

        if header_map:
            for index, value in enumerate(parts):
                if index >= len(header_map):
                    break
                field_name = header_map[index]
                if field_name and value and (not data[field_name] or field_name == "tax_rate" and data[field_name] == "3%"):
                    data[field_name] = value
            _fill_from_unmapped_columns(parts, header_map, data)
            if header_labels:
                repeated_block_selected = _apply_repeated_inventory_amount_blocks(parts, header_labels, data)
        else:
            if len(parts) > 8:
                continue
            if not _looks_like_unheaded_detail_row(parts):
                continue
            fallback_order = [
                "project_name",
                "specification",
                "unit",
                "quantity",
                "unit_price",
                "amount_with_tax",
                "tax_rate",
                "tax_code",
            ]
            if len(parts) == 3:
                fallback_order = ["project_name", "amount_with_tax", "tax_rate"]
            elif len(parts) == 4:
                fallback_order = ["project_name", "quantity", "amount_with_tax", "tax_rate"]
            elif len(parts) == 5:
                fallback_order = ["project_name", "unit", "quantity", "amount_with_tax", "tax_rate"]
            for field_name, value in zip(fallback_order, parts):
                data[field_name] = value

        if not data["project_name"]:
            continue
        if _looks_like_non_detail_label(data["project_name"]) or _looks_like_numeric_only_name(data["project_name"]):
            continue
        if _looks_like_summary_row(data):
            continue
        if header_labels and _has_repeated_inventory_layout(header_labels) and not repeated_block_selected:
            continue
        if header_map and not _looks_like_structured_detail(data):
            continue
        parsed.append(InvoiceLine(**data))

    return _apply_global_line_defaults(parsed, raw_text)


def _apply_global_line_defaults(lines: list[InvoiceLine], raw_text: str) -> list[InvoiceLine]:
    if not lines:
        return lines
    defaults = _extract_global_line_defaults(raw_text)
    if not defaults:
        return lines
    enriched: list[InvoiceLine] = []
    for line in lines:
        enriched.append(
            InvoiceLine(
                project_name=line.project_name,
                amount_with_tax=line.amount_with_tax,
                tax_rate=line.tax_rate or defaults.get("tax_rate", ""),
                tax_category=line.tax_category,
                specification=line.specification,
                unit=line.unit,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_code=line.tax_code or defaults.get("tax_code", ""),
                source_item_code=line.source_item_code,
                coding_reference=line.coding_reference,
            )
        )
    return enriched


def _extract_global_line_defaults(raw_text: str) -> dict[str, str]:
    defaults: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        parts = [part.strip() for part in re.split(r"[\t|]", raw_line) if part.strip()]
        if len(parts) < 2:
            key, value = _split_key_value(raw_line) if ("：" in raw_line or ":" in raw_line) else ("", "")
        else:
            key, value = parts[0], parts[1]
        key = normalize_header(key)
        value = value.strip()
        if not value:
            continue
        if key in {"税收编码", "税收分类编码", "商品和服务税收编码", "商品和服务税收分类编码"}:
            defaults["tax_code"] = value
        elif key in {"统一税率", "默认税率", "税率", "税率/征收率"} and "tax_rate" not in defaults:
            defaults["tax_rate"] = value
    return defaults


def serialize_invoice_lines(lines: list[InvoiceLine]) -> str:
    headers = [
        "项目名称",
        "赋码大类",
        "税收编码",
        "零件编码",
        "规格型号",
        "单位",
        "数量",
        "单价",
        "含税金额",
        "税率/征收率",
        "赋码说明",
    ]
    rows = ["\t".join(headers)]
    for line in lines:
        rows.append(
            "\t".join(
                [
                    line.project_name,
                    line.tax_category,
                    line.tax_code,
                    line.source_item_code,
                    line.specification,
                    line.unit,
                    line.quantity,
                    line.unit_price,
                    line.resolved_amount_with_tax(),
                    line.normalized_tax_rate(),
                    line.coding_reference,
                ]
            )
        )
    return "\n".join(rows)


def extract_buyer_info_from_text(raw_text: str) -> BuyerInfo:
    buyer = BuyerInfo(name="", tax_id="")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    tabular_buyer = _extract_buyer_info_from_tabular_text(lines)
    for line in lines:
        for pattern in BUYER_NAME_PATTERNS:
            matched = pattern.search(line)
            if matched and not buyer.name:
                candidate = _trim_inline_field_value(matched.group(1).strip())
                if _looks_like_placeholder_field_value(candidate):
                    continue
                buyer.name = candidate
        for pattern in BUYER_TAX_ID_PATTERNS:
            matched = pattern.search(line.upper())
            if matched and not buyer.tax_id:
                buyer.tax_id = _normalize_tax_id_ocr_noise(matched.group(1).strip())
        for pattern in BUYER_ADDRESS_PATTERNS:
            matched = pattern.search(line)
            if matched and not buyer.address:
                buyer.address = _trim_inline_field_value(matched.group(1).strip())
        for pattern in BUYER_PHONE_PATTERNS:
            matched = pattern.search(line)
            if matched and not buyer.phone:
                buyer.phone = _trim_inline_field_value(matched.group(1).strip())
        for pattern in BUYER_BANK_PATTERNS:
            matched = pattern.search(line)
            if matched and not buyer.bank_name:
                buyer.bank_name = _trim_inline_field_value(matched.group(1).strip())
        for pattern in BUYER_ACCOUNT_PATTERNS:
            matched = pattern.search(line)
            if matched and not buyer.bank_account:
                buyer.bank_account = _trim_inline_field_value(matched.group(1).strip())
    if tabular_buyer.name and not buyer.name:
        buyer.name = tabular_buyer.name
    if tabular_buyer.tax_id and not buyer.tax_id:
        buyer.tax_id = tabular_buyer.tax_id
    if tabular_buyer.address and not buyer.address:
        buyer.address = tabular_buyer.address
    if tabular_buyer.phone and not buyer.phone:
        buyer.phone = tabular_buyer.phone
    if tabular_buyer.bank_name and not buyer.bank_name:
        buyer.bank_name = tabular_buyer.bank_name
    if tabular_buyer.bank_account and not buyer.bank_account:
        buyer.bank_account = tabular_buyer.bank_account
    if not buyer.name or not buyer.tax_id:
        invoice_buyer = _extract_buyer_info_from_invoice_pdf_text(lines)
        if invoice_buyer.name and not buyer.name:
            buyer.name = invoice_buyer.name
        if invoice_buyer.tax_id and not buyer.tax_id:
            buyer.tax_id = invoice_buyer.tax_id
    if not buyer.name or not buyer.tax_id:
        invoice_ocr_buyer = _extract_buyer_info_from_invoice_ocr_text(lines)
        if invoice_ocr_buyer.name and (not buyer.name or buyer.name.count("名称") >= 1 or len(buyer.name) > 40):
            buyer.name = invoice_ocr_buyer.name
        if invoice_ocr_buyer.tax_id and not buyer.tax_id:
            buyer.tax_id = invoice_ocr_buyer.tax_id
    if not buyer.name or not buyer.tax_id:
        minimal_buyer = _extract_buyer_info_from_minimal_lines(lines)
        if minimal_buyer.name and not buyer.name:
            buyer.name = minimal_buyer.name
        if minimal_buyer.tax_id and not buyer.tax_id:
            buyer.tax_id = minimal_buyer.tax_id
    if not buyer.name or not buyer.tax_id:
        inline_buyer = _extract_buyer_info_from_inline_text(raw_text)
        if inline_buyer.name and not buyer.name:
            buyer.name = inline_buyer.name
        if inline_buyer.tax_id and not buyer.tax_id:
            buyer.tax_id = inline_buyer.tax_id
    return buyer


def extract_invoice_lines_from_text(raw_text: str) -> list[InvoiceLine]:
    parsed = parse_bulk_invoice_lines(raw_text)
    if parsed:
        return parsed

    labeled_detail_lines = _extract_labeled_detail_lines(raw_text)
    if labeled_detail_lines:
        return labeled_detail_lines

    key_value_lines = _extract_key_value_invoice_lines(raw_text)
    if key_value_lines:
        return key_value_lines

    invoice_pdf_lines = _extract_invoice_pdf_lines(raw_text)
    if invoice_pdf_lines:
        return invoice_pdf_lines

    invoice_ocr_lines = _extract_invoice_ocr_lines(raw_text)
    if invoice_ocr_lines:
        return invoice_ocr_lines

    contextual_chat_lines = _extract_contextual_chat_invoice_lines(raw_text)
    if contextual_chat_lines:
        return contextual_chat_lines

    daily_chat_item_lines = _extract_daily_chat_item_lines(raw_text)
    if daily_chat_item_lines:
        return daily_chat_item_lines

    minimal_request_lines = _extract_minimal_request_invoice_lines(raw_text)
    if minimal_request_lines:
        return minimal_request_lines

    inline_minimal_request_lines = _extract_inline_minimal_request_invoice_lines(raw_text)
    if inline_minimal_request_lines:
        return inline_minimal_request_lines

    return _extract_freeform_invoice_lines(raw_text)


def _extract_labeled_detail_lines(raw_text: str) -> list[InvoiceLine]:
    """Parse operator-pasted numbered detail lines.

    Example:
    1. 项目名，规格型号：40支/箱，单位：箱，数量：59，含税金额：3540，税收编码：...
    """
    default_tax_rate = _extract_default_tax_rate(raw_text)
    extracted: list[InvoiceLine] = []
    in_detail_block = False

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^(?:开票明细|发票明细|明细|项目明细)[：:]?$", line):
            in_detail_block = True
            continue
        block_header = re.match(r"^(?:开票明细|发票明细|明细|项目明细)[：:]\s*(.+)$", line)
        if block_header:
            in_detail_block = True
            line = block_header.group(1).strip()

        detail_text = _strip_numbered_detail_prefix(line)
        if not detail_text:
            if not in_detail_block:
                continue
            detail_text = line
        if not _looks_like_labeled_detail_text(detail_text):
            continue

        parsed = _parse_labeled_detail_text(detail_text, default_tax_rate=default_tax_rate)
        if parsed is not None:
            extracted.append(parsed)

    return extracted


def _strip_numbered_detail_prefix(line: str) -> str:
    matched = re.match(r"^\s*(?:\d+|[一二三四五六七八九十]+)\s*[\.、)）]\s*(.+)$", line)
    return matched.group(1).strip() if matched else ""


def _looks_like_labeled_detail_text(value: str) -> bool:
    if _looks_like_non_detail_label(value):
        return False
    if not re.search(r"[\u4e00-\u9fff]", value):
        return False
    key_count = 0
    for part in re.split(r"[，,；;]", value):
        key, _ = _split_key_value(part.strip()) if ("：" in part or ":" in part) else ("", "")
        if normalize_header(key) in LINE_FIELD_HEADERS:
            key_count += 1
    return key_count >= 2


def _parse_labeled_detail_text(value: str, *, default_tax_rate: str) -> InvoiceLine | None:
    value = _remove_thousands_commas(value)
    parts = [part.strip() for part in re.split(r"[，,；;]", value) if part.strip()]
    if not parts:
        return None

    data = _blank_line_payload()
    data["tax_rate"] = default_tax_rate or "3%"

    first_key, first_value = _split_key_value(parts[0]) if ("：" in parts[0] or ":" in parts[0]) else ("", "")
    if first_key and LINE_FIELD_HEADERS.get(normalize_header(first_key)) == "project_name":
        data["project_name"] = first_value.strip()
        remaining_parts = parts[1:]
    else:
        data["project_name"] = parts[0].strip(" -*")
        remaining_parts = parts[1:]

    for part in remaining_parts:
        if "：" not in part and ":" not in part:
            continue
        key, raw_value = _split_key_value(part)
        field_name = LINE_FIELD_HEADERS.get(normalize_header(key), "")
        if not field_name:
            continue
        cleaned_value = _cleanup_labeled_detail_value(raw_value)
        if cleaned_value:
            if field_name == "quantity":
                quantity, unit = _split_quantity_and_unit(cleaned_value)
                cleaned_value = quantity
                if unit and not data["unit"]:
                    data["unit"] = unit
            data[field_name] = cleaned_value

    if not data["project_name"] or not _looks_like_structured_detail(data):
        return None
    return InvoiceLine(**data)


def _cleanup_labeled_detail_value(value: str) -> str:
    cleaned = value.strip().strip("。；;,，")
    cleaned = cleaned.replace("￥", "").replace("¥", "").strip()
    if re.fullmatch(r"-?\d+(?:,\d{3})*(?:\.\d+)?\s*元?", cleaned):
        return cleaned.replace(",", "").rstrip("元").strip()
    return cleaned


def _remove_thousands_commas(value: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", value)


def _split_quantity_and_unit(value: str) -> tuple[str, str]:
    matched = re.fullmatch(r"(\d+(?:\.\d+)?)([\u4e00-\u9fffA-Za-z]+)", value.strip())
    if not matched:
        return value, ""
    return matched.group(1), matched.group(2)


def _extract_default_tax_rate(raw_text: str) -> str:
    for line in raw_text.splitlines():
        if "：" not in line and ":" not in line:
            continue
        key, value = _split_key_value(line.strip())
        if normalize_header(key) in {"税率", "税率/征收率"}:
            cleaned = _cleanup_labeled_detail_value(value)
            if cleaned:
                return cleaned
    return _extract_inline_tax_rate(raw_text) or "3%"


def _extract_key_value_invoice_lines(raw_text: str) -> list[InvoiceLine]:
    current = _blank_line_payload()
    extracted: list[InvoiceLine] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or "：" not in line and ":" not in line:
            continue
        key, value = _split_key_value(line)
        field_name = LINE_FIELD_HEADERS.get(normalize_header(key), "")
        if not field_name:
            continue
        if _looks_like_placeholder_field_value(value):
            continue
        if field_name == "project_name" and normalize_header(key) == "名称" and _looks_like_company_name(value):
            continue
        if field_name == "project_name" and current["project_name"]:
            extracted.append(InvoiceLine(**current))
            current = _blank_line_payload()
        current[field_name] = value.strip()

    if current["project_name"]:
        extracted.append(InvoiceLine(**current))
    return extracted


def _extract_invoice_pdf_lines(raw_text: str) -> list[InvoiceLine]:
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    merged_lines: list[str] = []
    buffer = ""
    for line in raw_lines:
        if line.startswith("*"):
            if buffer:
                merged_lines.append(buffer)
            buffer = line
            continue
        if buffer and not _looks_like_invoice_pdf_break(line):
            buffer += line
            continue
        if buffer:
            merged_lines.append(buffer)
            buffer = ""
        merged_lines.append(line)
    if buffer:
        merged_lines.append(buffer)

    extracted: list[InvoiceLine] = []
    for line in merged_lines:
        matched = INVOICE_PDF_LINE_RE.match(line)
        if not matched:
            continue
        amount = matched.group("amount").strip()
        tax_amount = matched.group("tax_amount").strip()
        amount_with_tax = amount
        try:
            amount_with_tax = f"{float(amount) + float(tax_amount):.2f}"
        except ValueError:
            amount_with_tax = amount
        extracted.append(
            InvoiceLine(
                project_name=matched.group("name").strip(),
                tax_category=matched.group("category").strip(),
                unit=matched.group("unit").strip(),
                amount_with_tax=amount_with_tax,
                tax_rate=f"{matched.group('rate').strip()}%",
            )
        )
    return extracted


def _extract_invoice_ocr_lines(raw_text: str) -> list[InvoiceLine]:
    extracted: list[InvoiceLine] = []
    for raw_line in raw_text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        matched = INVOICE_OCR_LINE_RE.match(line)
        if not matched:
            continue
        extracted.append(
            InvoiceLine(
                project_name=_cleanup_invoice_ocr_project_name(matched.group("name")),
                unit=matched.group("unit").strip(),
                quantity=matched.group("quantity").strip(),
                unit_price=matched.group("unit_price").strip(),
                amount_with_tax=matched.group("amount").replace(" ", "").strip(),
                tax_rate=matched.group("tax").strip(),
            )
        )
    return extracted


def _extract_contextual_chat_invoice_lines(raw_text: str) -> list[InvoiceLine]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    extracted: list[InvoiceLine] = []
    for index, line in enumerate(lines):
        if not any(delimiter in line for delimiter in ("，", ",", "、")):
            continue
        if any(marker in line for marker in ("公司名称", "单位地址", "开户地址", "开户银行", "税号", "账号", "电话")):
            continue
        left, right = _split_contextual_pair(line)
        if not left or not right:
            continue
        amount = _find_nearby_amount(lines, index)
        if not amount:
            continue
        tax_rate = _find_nearby_tax_rate(lines, index)
        extracted.append(
            InvoiceLine(
                project_name=right,
                tax_category=left,
                amount_with_tax=amount,
                tax_rate=tax_rate,
            )
        )
    return extracted


def _extract_daily_chat_item_lines(raw_text: str) -> list[InvoiceLine]:
    default_tax_rate = _extract_default_tax_rate(raw_text)
    extracted: list[InvoiceLine] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip(" -•\t，,。；;")
        if not line or _looks_like_daily_chat_non_detail_line(line):
            continue
        matched = DAILY_CHAT_ITEM_RE.match(line)
        if not matched:
            continue
        name = matched.group("name").strip(" -*，,。；;")
        if not name or _looks_like_daily_chat_non_detail_line(name) or _looks_like_company_name(name):
            continue
        extracted.append(
            InvoiceLine(
                project_name=name,
                quantity=matched.group("quantity").strip(),
                unit=matched.group("unit").strip(),
                amount_with_tax=_normalize_minimal_amount_line(matched.group("amount").strip()),
                tax_rate=default_tax_rate or "3%",
            )
        )
    return extracted



def _extract_minimal_request_invoice_lines(raw_text: str) -> list[InvoiceLine]:
    """Parse short operator inputs like: buyer, tax id, amount, invoice type, project."""

    lines = [line.strip(" -•\t") for line in raw_text.splitlines() if line.strip()]
    if len(lines) < 4:
        return []

    amount_candidates: list[tuple[int, str]] = []
    project_candidates: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        compact = line.replace(" ", "")
        if _looks_like_minimal_amount_line(compact):
            amount_candidates.append((index, _normalize_minimal_amount_line(compact)))
            continue
        if _should_ignore_minimal_request_line(line):
            continue
        if _looks_like_company_name(line):
            continue
        if not re.search(r"[\u4e00-\u9fff]", line):
            continue
        project_candidates.append((index, line))

    if len(amount_candidates) != 1 or not project_candidates:
        return []

    amount_index, amount = amount_candidates[0]
    after_amount = [candidate for candidate in project_candidates if candidate[0] > amount_index]
    project_name = (after_amount or project_candidates)[-1][1]
    if not project_name:
        return []

    return [
        InvoiceLine(
            project_name=project_name,
            amount_with_tax=amount,
            tax_rate=_extract_default_tax_rate(raw_text) or "3%",
            unit="项",
            quantity="1",
            unit_price=amount,
        )
    ]


def _extract_inline_minimal_request_invoice_lines(raw_text: str) -> list[InvoiceLine]:
    """Parse one-sentence invoice requests pasted directly from chat."""

    text = _normalize_inline_request_text(raw_text)
    if not text:
        return []

    amount = _extract_inline_amount(text)
    if not amount:
        return []

    project_name = _extract_inline_project_name(text, amount)
    if not project_name:
        return []

    return [
        InvoiceLine(
            project_name=project_name,
            amount_with_tax=amount,
            tax_rate=_extract_inline_tax_rate(text) or _extract_default_tax_rate(raw_text) or "3%",
            unit="项",
            quantity="1",
            unit_price=amount,
        )
    ]


def _extract_freeform_invoice_lines(raw_text: str) -> list[InvoiceLine]:
    extracted: list[InvoiceLine] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip(" -•\t")
        if not line:
            continue
        matched = FREEFORM_LINE_RE.match(line)
        if not matched:
            continue
        name = matched.group("name").strip()
        if (
            any(marker in name for marker in ["购买方", "销售方", "税号", "地址", "开户行"])
            or _looks_like_non_detail_label(name)
            or _looks_like_numeric_only_name(name)
        ):
            continue
        extracted.append(
            InvoiceLine(
                project_name=name,
                quantity=(matched.group("quantity") or "").strip(),
                unit_price=(matched.group("unit_price") or "").strip(),
                amount_with_tax=(matched.group("amount") or "").strip(),
                tax_rate=(matched.group("tax") or "3%").strip(),
            )
        )
    return extracted


def _looks_like_structured_detail(data: dict[str, str]) -> bool:
    return any(
        [
            bool(data["amount_with_tax"].strip()),
            bool(data["tax_code"].strip()),
            bool(data["source_item_code"].strip()),
            bool(data["quantity"].strip()) and bool(data["unit_price"].strip()),
        ]
    )


def _looks_like_non_detail_label(value: str) -> bool:
    normalized = value.strip().replace("：", "").replace(":", "")
    return any(normalized.startswith(prefix) for prefix in NON_DETAIL_PREFIXES)


def _looks_like_daily_chat_non_detail_line(value: str) -> bool:
    compact = value.strip().replace(" ", "")
    if not compact:
        return True
    if _looks_like_non_detail_label(value):
        return True
    if _looks_like_bare_tax_id(compact.upper()) or _looks_like_company_name(value):
        return True
    return bool(
        re.search(
            r"(麻烦|帮我|帮忙|开个|开票|普票|专票|发票|电子票|电子发票|微信|发我|备注|不用写|总共|合计|按[一二三四五六七八九十0-9]+个点|税率|这次是|大概这样)",
            compact,
        )
    )


def _looks_like_unheaded_detail_row(parts: list[str]) -> bool:
    if not parts or _looks_like_non_detail_label(parts[0]):
        return False
    tail = [part.strip() for part in parts[1:] if part.strip()]
    if len(tail) < 2:
        return False
    return any(_looks_like_measurement(part) for part in tail)


def _looks_like_measurement(value: str) -> bool:
    normalized = value.strip().replace(",", "").replace("，", "")
    if not normalized:
        return False
    if normalized in {"免税", "不征税", "免征增值税"}:
        return True
    return bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%?", normalized))


def _looks_like_numeric_only_name(value: str) -> bool:
    normalized = value.strip().replace(",", "").replace("，", "")
    return bool(normalized) and bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", normalized))


def _looks_like_placeholder_field_value(value: str) -> bool:
    normalized = value.strip().replace(" ", "")
    if not normalized:
        return True
    placeholder_values = {
        "名称",
        "名称：",
        "统一社会信用代码/纳税人识别号",
        "统一社会信用代码纳税人识别号",
        "请输入",
    }
    if normalized in placeholder_values:
        return True
    return normalized.endswith("：") and "公司" not in normalized


def _cleanup_invoice_ocr_project_name(value: str) -> str:
    candidate = re.sub(r"\s+", " ", value).strip(" -•\t|/=:_")
    if not candidate:
        return ""
    if not re.search(r"[\u4e00-\u9fff]", candidate):
        return ""
    return candidate


def _looks_like_company_name(value: str) -> bool:
    return bool(
        re.search(
            r"(?:公司|中心|医院|学校|大学|研究所|研究院|商店|经销店|配送中心|修理部|商行|门市部|超市|合作社)$",
            value.strip(),
        )
    )


def _normalize_tax_id_ocr_noise(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "")
    if not normalized:
        return normalized
    normalized = normalized.replace("O", "0")
    if len(normalized) > 18 and normalized[0].isdigit():
        normalized = normalized[:18]
    return normalized


def _looks_like_invoice_pdf_break(value: str) -> bool:
    return any(
        marker in value
        for marker in (
            "价税合计",
            "合计",
            "开票人",
            "备注",
            "名称：",
            "统一社会信用代码",
            "发票号码",
        )
    )


def _trim_inline_field_value(value: str) -> str:
    return re.split(
        r"\s+(?:纳税人识别号|纳税识别号|统一社会信用代码|税号|开户行|开户银行|账号|银行账号|电话|地址)[：:]",
        value,
        maxsplit=1,
    )[0].strip()



def _extract_buyer_info_from_tabular_text(lines: list[str]) -> BuyerInfo:
    buyer = BuyerInfo(name="", tax_id="")
    for index, line in enumerate(lines):
        parts = [part.strip() for part in re.split(r"[\t|]", line)]
        if len(parts) < 2:
            continue
        for column, label in enumerate(parts):
            normalized = normalize_header(label).replace("：", "").replace(":", "")
            value = _next_tabular_value(parts, column)
            if not value and index + 1 < len(lines):
                next_parts = [part.strip() for part in re.split(r"[\t|]", lines[index + 1])]
                value = _next_tabular_value(next_parts, column, include_same_column=True)
            if not value:
                continue
            if normalized in {"业主单位名称", "业主名称", "购买方名称", "购方名称", "客户名称", "开票抬头", "发票抬头", "单位名称"} and not buyer.name:
                buyer.name = value
            elif normalized in {"税号", "纳税人识别号", "纳税识别号", "统一社会信用代码", "购买方税号", "购方税号"} and not buyer.tax_id:
                matched = re.search(r"([0-9A-Z]{15,20})", value.upper().replace(" ", ""))
                if matched:
                    buyer.tax_id = _normalize_tax_id_ocr_noise(matched.group(1))
            elif normalized in {"地址", "购买方地址"} and not buyer.address:
                buyer.address = value
            elif normalized in {"电话", "购买方电话"} and not buyer.phone:
                buyer.phone = value
            elif normalized in {"开户行", "开户银行", "购买方开户行", "购买方开户银行"} and not buyer.bank_name:
                buyer.bank_name = value
            elif normalized in {"账号", "银行账号", "购买方银行账号"} and not buyer.bank_account:
                buyer.bank_account = value
    return buyer



def _next_tabular_value(parts: list[str], column: int, *, include_same_column: bool = False) -> str:
    start = column if include_same_column else column + 1
    for value in parts[start:]:
        value = value.strip()
        if not value:
            continue
        if _looks_like_tabular_label(value):
            return ""
        return _trim_inline_field_value(value)
    return ""



def _looks_like_tabular_label(value: str) -> bool:
    normalized = normalize_header(value).replace("：", "").replace(":", "").strip()
    return normalized in {
        "税号",
        "纳税人识别号",
        "纳税识别号",
        "统一社会信用代码",
        "开户行",
        "开户银行",
        "银行账号",
        "账号",
        "地址及电话",
        "地址",
        "电话",
        "证明材料",
    }



def _extract_buyer_info_from_invoice_pdf_text(lines: list[str]) -> BuyerInfo:
    buyer = BuyerInfo(name="", tax_id="")
    date_index = -1
    for index, line in enumerate(lines):
        if re.search(r"\d{4}年\d{2}月\d{2}日", line):
            date_index = index
            break
    if date_index < 0:
        return buyer

    tail = lines[date_index + 1 : date_index + 8]
    company_positions = [(index, line.strip()) for index, line in enumerate(tail) if "公司" in line]
    if not company_positions:
        return buyer

    buyer.name = company_positions[0][1]
    for index, line in enumerate(tail):
        if index <= company_positions[0][0]:
            continue
        matched = re.search(r"([0-9A-Z]{15,20})", line.upper())
        if matched:
            buyer.tax_id = matched.group(1)
            break
    return buyer


def _extract_buyer_info_from_invoice_ocr_text(lines: list[str]) -> BuyerInfo:
    buyer = BuyerInfo(name="", tax_id="")
    company_tail_pattern = r"(?:公司|中心|医院|学校|大学|研究所|研究院|商店|经销店|配送中心|修理部|商行|门市部|超市|合作社)"
    for line in lines:
        if not buyer.name and "名称" in line:
            matched = re.search(r"名称[：:]\s*(.+?)(?:\s{2,}.+?名称[：:]|$)", line)
            if matched:
                candidate = matched.group(1).strip()
                company_match = re.search(rf"([\u4e00-\u9fffA-Za-z0-9()（）·]+?{company_tail_pattern})", candidate)
                if company_match:
                    buyer.name = company_match.group(1).strip()
        if not buyer.tax_id and ("识别号" in line or "信用代码" in line):
            matches = re.findall(r"([0-9A-ZO]{15,20})", line.upper().replace(" ", ""))
            if matches:
                buyer.tax_id = _normalize_tax_id_ocr_noise(matches[0])
        if buyer.name and buyer.tax_id:
            break
    return buyer


def _extract_buyer_info_from_minimal_lines(lines: list[str]) -> BuyerInfo:
    buyer = BuyerInfo(name="", tax_id="")
    tax_id_index = -1
    for index, line in enumerate(lines):
        compact = line.strip().upper().replace(" ", "")
        if _looks_like_bare_tax_id(compact):
            buyer.tax_id = _normalize_tax_id_ocr_noise(compact)
            tax_id_index = index
            break

    if tax_id_index < 0:
        return buyer

    for candidate in reversed(lines[:tax_id_index]):
        cleaned = candidate.strip()
        if _looks_like_company_name(cleaned):
            buyer.name = cleaned
            break
    if not buyer.name:
        for candidate in lines:
            cleaned = candidate.strip()
            if _looks_like_company_name(cleaned):
                buyer.name = cleaned
                break
    return buyer


def _extract_buyer_info_from_inline_text(raw_text: str) -> BuyerInfo:
    buyer = BuyerInfo(name="", tax_id="")
    text = _normalize_inline_request_text(raw_text)
    if not text:
        return buyer

    tax_id_match = _find_inline_tax_id_match(text)
    if tax_id_match:
        buyer.tax_id = _normalize_tax_id_ocr_noise(tax_id_match.group(1))

    company_matches = list(
        re.finditer(
            r"([\u4e00-\u9fffA-Za-z0-9()（）·]{2,}(?:公司|中心|医院|学校|大学|研究所|研究院|商店|经销店|配送中心|修理部|商行|门市部|超市|合作社))",
            text,
        )
    )
    if not company_matches:
        return buyer

    if tax_id_match:
        before_tax_id = [match for match in company_matches if match.end() <= tax_id_match.start()]
        chosen = (before_tax_id or company_matches)[-1]
    else:
        chosen = company_matches[0]
    buyer.name = _cleanup_inline_company_name(chosen.group(1))
    return buyer


def _find_inline_tax_id_match(text: str):
    compact_text = text.upper().replace(" ", "")
    for matched in re.finditer(r"([0-9A-Z]{15,20})", compact_text):
        value = matched.group(1)
        window = compact_text[max(0, matched.start() - 8): min(len(compact_text), matched.end() + 8)]
        if "车架号" in window or "VIN" in window:
            continue
        if len(value) == 17 and not value[0].isdigit():
            continue
        return matched
    return None



def _normalize_inline_request_text(raw_text: str) -> str:
    return re.sub(r"\s+", " ", raw_text.replace("\u3000", " ")).strip()


def _cleanup_inline_company_name(value: str) -> str:
    cleaned = value.strip(" ，,。；;：:")
    cleaned = re.sub(r"^(?:请|麻烦|帮忙|帮我|给|开给|需要给|客户是|客户|购买方|购方)", "", cleaned)
    cleaned = re.sub(r"(?:开|申请|要|需要|来一张|出一张).*$", "", cleaned)
    return cleaned.strip(" ，,。；;：:")


def _extract_inline_amount(text: str) -> str:
    labeled_match = re.search(
        r"(?:价税合计|含税金额|开票金额|金额|合计|总共|总计)[：:]?\s*[¥￥]?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*元?",
        text,
    )
    if labeled_match:
        return _normalize_minimal_amount_line(labeled_match.group(1))
    labeled_words_match = re.search(
        r"(?:价税合计|含税金额|开票金额|金额|合计|总共|总计)[：:]?\s*([零〇一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟两]+)\s*(?:元|块)?",
        text,
    )
    if labeled_words_match:
        amount = _normalize_chinese_amount(labeled_words_match.group(1))
        if amount:
            return amount

    scrubbed = re.sub(r"[0-9A-Z]{15,20}", " ", text.upper())
    scrubbed = re.sub(r"\d+(?:\.\d+)?\s*%", " ", scrubbed)
    amount_matches = list(re.finditer(r"[¥￥]?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*元?", scrubbed))
    candidates = []
    for matched in amount_matches:
        amount = _normalize_minimal_amount_line(matched.group(1))
        if _looks_like_minimal_amount_line(amount):
            candidates.append(amount)
    if candidates:
        return candidates[-1]
    word_amount_matches = list(
        re.finditer(r"([零〇一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟两]{1,12})\s*(?:元|块)?", scrubbed)
    )
    word_candidates = []
    for matched in word_amount_matches:
        amount = _normalize_chinese_amount(matched.group(1))
        if amount:
            word_candidates.append(amount)
    return word_candidates[-1] if word_candidates else ""


def _extract_inline_tax_rate(text: str) -> str:
    matched = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if matched:
        return f"{matched.group(1)}%"
    matched = re.search(r"([一二三四五六七八九十0-9]+)个点", text)
    if matched:
        return f"{_normalize_chinese_number(matched.group(1))}%"
    return ""


def _extract_inline_project_name(text: str, amount: str) -> str:
    labeled_match = re.search(
        r"(?:项目名称|开票项目|项目|服务名称|开票内容|品名)[：:]?\s*(.+?)(?:[，,；;。]|价税合计|含税金额|开票金额|金额|合计|税率|$)",
        text,
    )
    if labeled_match:
        candidate = _cleanup_inline_project_name(labeled_match.group(1))
        if candidate:
            return candidate

    scrubbed = text
    scrubbed = re.sub(r"[0-9A-Z]{15,20}", " ", scrubbed.upper())
    scrubbed = re.sub(rf"[¥￥]?\s*{re.escape(amount)}\s*(?:元|块)?", " ", scrubbed)
    scrubbed = re.sub(r"[零〇一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟两]+\s*(?:元|块)?", " ", scrubbed)
    scrubbed = re.sub(
        r"[\d.]+%|[一二三四五六七八九十0-9]+个点|增值税专用发票|增值税普通发票|普通发票|专用发票|普票|专票|电子发票|发票",
        " ",
        scrubbed,
    )
    for match in re.finditer(
        r"[\u4e00-\u9fffA-Za-z0-9()（）·]{2,}(?:公司|中心|商店|经销店|配送中心|修理部|商行|门市部|超市|合作社)",
        scrubbed,
    ):
        scrubbed = scrubbed.replace(match.group(0), " ")
    scrubbed = re.sub(r"(?:税号|统一社会信用代码|纳税人识别号|客户名称|购买方名称|给|请|麻烦|帮忙|帮我|开个票|开票|开|开具|需要|客户|那个公司|那个|这个公司|这个)", " ", scrubbed)
    candidates = [
        _cleanup_inline_project_name(part)
        for part in re.split(r"[，,；;。\s]+", scrubbed)
        if _cleanup_inline_project_name(part)
    ]
    return candidates[-1] if candidates else ""


def _cleanup_inline_project_name(value: str) -> str:
    cleaned = value.strip(" -*，,。；;：:")
    cleaned = re.sub(r"^(?:开|开具|需要|项目|服务|品名|为|是)", "", cleaned)
    cleaned = re.sub(r"(?:金额|价税合计|含税金额|税率).*$", "", cleaned)
    if (
        not cleaned
        or _looks_like_non_detail_label(cleaned)
        or _looks_like_daily_chat_non_detail_line(cleaned)
        or _looks_like_company_name(cleaned)
        or _looks_like_amount_in_words(cleaned)
    ):
        return ""
    if not re.search(r"[\u4e00-\u9fff]", cleaned):
        return ""
    return cleaned.strip(" -*，,。；;：:")


def _split_contextual_pair(value: str) -> tuple[str, str]:
    for delimiter in ("，", ",", "、"):
        if delimiter not in value:
            continue
        left, right = value.split(delimiter, 1)
        left = left.strip(" -*")
        right = right.strip(" -*")
        if left and right:
            return left, right
    return "", ""


def _find_nearby_amount(lines: list[str], anchor_index: int) -> str:
    for candidate in lines[anchor_index + 1 : anchor_index + 4]:
        normalized = candidate.replace(",", "").replace("，", "").strip()
        if re.fullmatch(r"\d+(?:\.\d{1,2})?", normalized):
            return normalized
    return ""


def _find_nearby_tax_rate(lines: list[str], anchor_index: int) -> str:
    window = lines[max(0, anchor_index - 4) : min(len(lines), anchor_index + 5)]
    for candidate in window:
        matched = re.search(r"(\d+(?:\.\d+)?)\s*%", candidate)
        if matched:
            return f"{matched.group(1)}%"
        matched = re.search(r"([一二三四五六七八九十0-9]+)个点", candidate)
        if matched:
            return f"{_normalize_chinese_number(matched.group(1))}%"
    return "3%"


def _normalize_chinese_number(value: str) -> str:
    if value.isdigit():
        return value
    mapping = {
        "一": "1",
        "二": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
        "十": "10",
    }
    return mapping.get(value, value)



def _normalize_chinese_amount(value: str) -> str:
    compact = value.strip().replace("两", "二")
    compact = compact.replace("壹", "一").replace("贰", "二").replace("叁", "三").replace("肆", "四").replace("伍", "五")
    compact = compact.replace("陆", "六").replace("柒", "七").replace("捌", "八").replace("玖", "九")
    compact = compact.replace("拾", "十").replace("佰", "百").replace("仟", "千").replace("〇", "零")
    if not compact or not re.fullmatch(r"[零一二三四五六七八九十百千万亿]+", compact):
        return ""
    digit_map = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if all(char in digit_map for char in compact):
        return str(int("".join(str(digit_map[char]) for char in compact)))
    total = 0
    section = 0
    number = 0
    last_unit = 1
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
    for char in compact:
        if char in digit_map:
            number = digit_map[char]
            continue
        unit = unit_map.get(char)
        if not unit:
            return ""
        if unit in {10000, 100000000}:
            section = (section + number) * unit
            total += section
            section = 0
            number = 0
            last_unit = unit
            continue
        section += (number or 1) * unit
        number = 0
        last_unit = unit
    # 口语“一千二”通常表示 1200，“一万三”表示 13000。
    if number and last_unit in {1000, 10000, 100000000}:
        section += number * (last_unit // 10)
    else:
        section += number
    amount = total + section
    return str(amount) if amount > 0 else ""



def _looks_like_order_code(value: str) -> bool:
    normalized = value.strip().replace(" ", "")
    return bool(normalized) and bool(re.fullmatch(r"[A-Z]?\d{4,}(?:[-_][A-Z0-9]+)+", normalized, re.IGNORECASE))


def _looks_like_amount_in_words(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    return bool(re.fullmatch(r"[零〇一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟元角分整]+", normalized))


def _looks_like_bare_tax_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9][0-9A-Z]{14,19}", value)) and bool(re.search(r"[A-Z]", value))


def _looks_like_minimal_amount_line(value: str) -> bool:
    cleaned = value.replace(",", "").replace("，", "").replace("￥", "").replace("¥", "").rstrip("元")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
        return False
    if len(cleaned.split(".", 1)[0]) > 10:
        return False
    return True


def _normalize_minimal_amount_line(value: str) -> str:
    return value.replace(",", "").replace("，", "").replace("￥", "").replace("¥", "").rstrip("元")


def _should_ignore_minimal_request_line(value: str) -> bool:
    compact = value.strip().replace(" ", "").upper()
    if not compact:
        return True
    if _looks_like_bare_tax_id(compact):
        return True
    if _looks_like_minimal_amount_line(compact):
        return True
    if compact in {
        "普票",
        "普通发票",
        "增值税普通发票",
        "专票",
        "专用发票",
        "增值税专用发票",
        "电子发票",
        "纸票",
        "纸质发票",
    }:
        return True
    if re.fullmatch(r"(?:税率)?\d+(?:\.\d+)?%?", compact):
        return True
    return _looks_like_non_detail_label(value)


def _looks_like_summary_row(data: dict[str, str]) -> bool:
    project_name = data["project_name"].strip()
    if not project_name:
        return False
    if project_name in {"合计", "小计", "总计"}:
        return True
    if _looks_like_amount_in_words(project_name):
        return True
    summary_markers = [data["tax_category"].strip(), data["unit_price"].strip(), data["specification"].strip()]
    return any(value in {"大写", "小写", "未税", "含税", "合计"} for value in summary_markers if value)


def _fill_from_unmapped_columns(parts: list[str], header_map: list[str], data: dict[str, str]) -> None:
    try:
        project_index = header_map.index("project_name")
    except ValueError:
        project_index = -1

    if project_index > 0 and not data["tax_category"]:
        # Some operator spreadsheets leave the tax-category column header blank
        # but still place a stable category value immediately before the item name.
        for index in range(project_index - 1, -1, -1):
            if header_map[index]:
                continue
            candidate = parts[index].strip() if index < len(parts) else ""
            if not candidate:
                continue
            if _looks_like_numeric_only_name(candidate):
                break
            if _looks_like_order_code(candidate):
                continue
            if _looks_like_non_detail_label(candidate):
                continue
            data["tax_category"] = candidate
            break


def _has_repeated_inventory_layout(header_labels: list[str]) -> bool:
    return sum(1 for label in header_labels if label == "库存") >= 2


def _apply_repeated_inventory_amount_blocks(parts: list[str], header_labels: list[str], data: dict[str, str]) -> bool:
    repeated_candidates: list[tuple[str, str, str]] = []
    for index, label in enumerate(header_labels):
        if label != "库存":
            continue
        if index + 2 >= len(parts) or index + 2 >= len(header_labels):
            continue
        if header_labels[index + 1] != "单价" or header_labels[index + 2] != "金额":
            continue
        quantity = parts[index].strip()
        unit_price = parts[index + 1].strip()
        amount = parts[index + 2].strip()
        if not quantity or not unit_price or not amount:
            continue
        if not _looks_like_measurement(quantity) or not _looks_like_measurement(unit_price) or not _looks_like_measurement(amount):
            continue
        repeated_candidates.append((quantity, unit_price, amount))

    if repeated_candidates:
        quantity, unit_price, amount = repeated_candidates[-1]
        data["quantity"] = quantity
        data["unit_price"] = unit_price
        data["amount_with_tax"] = amount
        return True
    return False


def _blank_line_payload() -> dict[str, str]:
    return {
        "project_name": "",
        "amount_with_tax": "",
        "tax_rate": "3%",
        "tax_category": "",
        "specification": "",
        "unit": "",
        "quantity": "",
        "unit_price": "",
        "tax_code": "",
        "source_item_code": "",
        "coding_reference": "",
    }


def _split_key_value(line: str) -> tuple[str, str]:
    if "：" in line:
        key, value = line.split("：", 1)
        return key.strip(), value.strip()
    key, value = line.split(":", 1)
    return key.strip(), value.strip()

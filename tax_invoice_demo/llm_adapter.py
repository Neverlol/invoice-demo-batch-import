from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MINIMAX_ENDPOINT = "https://api.minimax.io/v1/chat/completions"
DEFAULT_MINIMAX_MODEL = "MiniMax-M2.7"

EXTRACT_INVOICE_INFO_SCHEMA = {
    "type": "object",
    "required": ["客户名称", "纳税人识别号", "地址电话", "开户行及账号", "项目列表", "价税合计", "备注"],
    "line_required": ["项目名称", "规格型号", "单位", "数量", "单价", "金额", "税率"],
}


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    raw_payload: dict[str, Any]
    parsed_json: dict[str, Any]


class LLMAdapterError(RuntimeError):
    pass


class BaseLLMAdapter:
    provider_name = "disabled"

    @property
    def is_enabled(self) -> bool:
        return False

    def extract_invoice_info(self, text: str) -> LLMResponse:
        raise LLMAdapterError("LLM adapter is disabled.")

    def classify_tax_code(self, item_name: str, candidates: list[str]) -> LLMResponse:
        raise LLMAdapterError("Tax code classification adapter is disabled.")


class NullLLMAdapter(BaseLLMAdapter):
    pass


class MiniMaxOpenAICompatibleAdapter(BaseLLMAdapter):
    provider_name = "minimax_openai"

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("TAX_INVOICE_LLM_API_KEY")
            or os.getenv("TAX_INVOICE_MINIMAX_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.endpoint = os.getenv("TAX_INVOICE_LLM_ENDPOINT") or DEFAULT_MINIMAX_ENDPOINT
        self.model = os.getenv("TAX_INVOICE_LLM_MODEL") or DEFAULT_MINIMAX_MODEL

    @property
    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def extract_invoice_info(self, text: str) -> LLMResponse:
        prompt = (
            "请从以下开票材料中提取结构化开票信息。\n"
            "必须只返回 JSON，不要输出解释。\n"
            "若字段缺失，请返回空字符串。\n"
            "税率统一返回百分比字符串，例如 3%、13%、免税。\n"
            "项目列表至少包含：项目名称、规格型号、单位、数量、单价、金额、税率。\n"
            "JSON 顶层字段必须包含：客户名称、纳税人识别号、地址电话、开户行及账号、项目列表、价税合计、备注。\n"
            "材料如下：\n"
            f"{text}"
        )
        return self._chat_json(prompt)

    def classify_tax_code(self, item_name: str, candidates: list[str]) -> LLMResponse:
        prompt = (
            "你只做税收分类候选推荐，不做最终决定。\n"
            "请根据项目名称，从给定候选中返回 JSON。\n"
            "JSON 顶层字段必须包含：项目名称、候选分类。\n"
            "候选分类必须是数组，元素包含：分类名称、税收编码、置信度。\n"
            f"项目名称：{item_name}\n"
            f"候选：{json.dumps(candidates, ensure_ascii=False)}"
        )
        return self._chat_json(prompt)

    def _chat_json(self, prompt: str) -> LLMResponse:
        if not self.api_key:
            raise LLMAdapterError("MiniMax API key is not configured.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a careful invoice extraction assistant. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=45) as response:
                raw_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise LLMAdapterError(f"MiniMax HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise LLMAdapterError(f"MiniMax network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMAdapterError("MiniMax request timed out.") from exc

        content = _extract_openai_content(raw_payload)
        try:
            parsed_json = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMAdapterError(f"MiniMax returned non-JSON content: {content[:200]}") from exc
        return LLMResponse(
            provider=self.provider_name,
            model=self.model,
            raw_payload=raw_payload,
            parsed_json=parsed_json,
        )


def get_llm_adapter() -> BaseLLMAdapter:
    provider = (os.getenv("TAX_INVOICE_LLM_PROVIDER") or "").strip().lower()
    if provider in {"", "off", "disabled", "none"}:
        return NullLLMAdapter()
    if provider in {"minimax", "minimax_openai", "minimax-coding-plan"}:
        return MiniMaxOpenAICompatibleAdapter()
    return NullLLMAdapter()


def validate_extract_invoice_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in EXTRACT_INVOICE_INFO_SCHEMA["required"]:
        if field not in payload:
            errors.append(f"缺少字段: {field}")
    lines = payload.get("项目列表")
    if not isinstance(lines, list):
        errors.append("项目列表必须是数组。")
        return errors
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            errors.append(f"项目列表第 {index} 项不是对象。")
            continue
        for field in EXTRACT_INVOICE_INFO_SCHEMA["line_required"]:
            if field not in line:
                errors.append(f"项目列表第 {index} 项缺少字段: {field}")
    return errors


def _extract_openai_content(payload: dict[str, Any]) -> str:
    try:
        return str(payload["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMAdapterError(f"Unexpected MiniMax response shape: {payload}") from exc

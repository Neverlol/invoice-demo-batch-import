from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MINIMAX_GLOBAL_ENDPOINT = "https://api.minimax.io/v1/chat/completions"
DEFAULT_MINIMAX_CHINA_ENDPOINT = "https://api.minimaxi.com/v1/chat/completions"
DEFAULT_MINIMAX_ENDPOINT = DEFAULT_MINIMAX_GLOBAL_ENDPOINT
DEFAULT_MINIMAX_MODEL = "MiniMax-M2.7"
DEFAULT_MIMO_ENDPOINT = "https://api.xiaomimimo.com/v1/chat/completions"
DEFAULT_MIMO_MODEL = "mimo-v2-omni"
SUPPORTED_MINIMAX_PROVIDERS = {"minimax", "minimax_openai", "minimax_m27"}
SUPPORTED_MIMO_PROVIDERS = {"mimo", "mimo_openai", "xiaomi_mimo"}
SUPPORTED_DIRECT_PROVIDERS = SUPPORTED_MINIMAX_PROVIDERS | SUPPORTED_MIMO_PROVIDERS
AGENT_ORCHESTRATOR_PROVIDERS = {"openclaw", "hermes", "openclaw_minimax", "hermes_minimax"}

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


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    provider: str
    region: str
    endpoint: str
    model: str
    api_key: str
    timeout_seconds: int
    max_retries: int
    config_path: str = ""


@dataclass(frozen=True)
class LLMConfigDiagnostic:
    enabled: bool
    provider: str
    region: str
    endpoint: str
    model: str
    api_key_configured: bool
    api_key_preview: str
    timeout_seconds: int
    max_retries: int
    config_path: str
    ready: bool
    issues: list[str]


class LLMAdapterError(RuntimeError):
    pass


class BaseLLMAdapter:
    provider_name = "disabled"
    max_retries = 2

    @property
    def is_enabled(self) -> bool:
        return False

    def extract_invoice_info(self, text: str) -> LLMResponse:
        raise LLMAdapterError("LLM adapter is disabled.")

    def extract_invoice_info_from_images(self, text: str, image_paths: list[Path]) -> LLMResponse:
        raise LLMAdapterError("Vision invoice extraction adapter is disabled.")

    def classify_tax_code(self, item_name: str, candidates: list[str]) -> LLMResponse:
        raise LLMAdapterError("Tax code classification adapter is disabled.")

    def extract_text_from_image(self, image_path: Path) -> LLMResponse:
        raise LLMAdapterError("Image OCR adapter is disabled.")

    def ping_json(self) -> LLMResponse:
        raise LLMAdapterError("LLM adapter is disabled.")


class NullLLMAdapter(BaseLLMAdapter):
    pass


class MiniMaxOpenAICompatibleAdapter(BaseLLMAdapter):
    provider_name = "minimax_openai"
    provider_label = "MiniMax"
    default_endpoint = DEFAULT_MINIMAX_ENDPOINT
    default_model = DEFAULT_MINIMAX_MODEL

    def __init__(self, config: LLMConfig) -> None:
        self.api_key = config.api_key
        self.endpoint = config.endpoint or self.default_endpoint
        self.model = config.model or self.default_model
        # P0 现场链路不能被旧 local 配置中的 45s 长等待拖住；
        # 但 MiniMax-M2.7 是 reasoning 模型，12s 对结构化开票 JSON 容易过短。
        self.timeout_seconds = min(config.timeout_seconds, 25)
        self.max_retries = config.max_retries

    @property
    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def extract_invoice_info(self, text: str) -> LLMResponse:
        prompt = (
            "请从以下开票材料中提取结构化开票信息。\n"
            "必须只返回 JSON，不要输出解释。\n"
            "若字段缺失，请返回空字符串。\n"
            "税率统一返回百分比字符串，例如 3%、13%、免税。\n"
            "项目列表至少包含：项目名称、规格型号、单位、数量、单价、金额、税率；如果材料里有税收编码，也放入每一行的税收编码字段。\n"
            "JSON 顶层字段必须包含：客户名称、纳税人识别号、地址电话、开户行及账号、项目列表、价税合计、备注；若能识别发票类型，也返回发票类型。\n"
            "材料如下：\n"
            f"{text}"
        )
        return self._chat_json(prompt, timeout_seconds=_task_timeout_seconds("TAX_INVOICE_LLM_EXTRACT_TIMEOUT", self.timeout_seconds, 8))

    def extract_invoice_info_from_images(self, text: str, image_paths: list[Path]) -> LLMResponse:
        if not image_paths:
            raise LLMAdapterError("No images provided for vision invoice extraction.")
        prompt = (
            "请直接阅读图片中的开票材料，并结合补充文字提取结构化开票信息。\n"
            "必须只返回 JSON，不要输出解释。\n"
            "若字段缺失，请返回空字符串；不要臆造税号、金额或购买方。\n"
            "税率统一返回百分比字符串，例如 1%、3%、13%、免税。\n"
            "项目列表至少包含：项目名称、规格型号、单位、数量、单价、金额、税率；如果图片里有税收编码，也放入每一行的税收编码字段。\n"
            "金额必须填写含税开票金额；餐饮/外卖/平台截图请优先查找‘建议开票金额’、‘开票金额’、‘实付’、‘合计’、‘价税合计’等字段，并同时填入项目列表[0].金额和顶层价税合计。\n"
            "若图片是餐饮平台发票申请截图，项目名称可填‘餐费’，税率按图片或补充说明填写；不要把其它主体的历史项目当成图片内容。\n"
            "如果图片里同时出现多条待开票卡片，请优先提取画面中最完整、最清晰的一条；不要把上方或下方被截断的卡片混入同一张发票。\n"
            "餐饮平台卡片中，‘公司抬头/公司税号’就是购买方名称和纳税人识别号；‘开票金额’就是本张发票含税金额；订单号可放入备注。\n"
            "JSON 顶层字段必须包含：客户名称、纳税人识别号、地址电话、开户行及账号、项目列表、价税合计、备注；若能识别发票类型，也返回发票类型。\n"
            "补充文字如下：\n"
            f"{text or '无'}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}})
        return self._chat_json_messages(
            [
                {"role": "system", "content": "You are a careful invoice vision extraction assistant. Output JSON only."},
                {"role": "user", "content": content},
            ],
            timeout_seconds=_task_timeout_seconds("TAX_INVOICE_LLM_VISION_EXTRACT_TIMEOUT", self.timeout_seconds, 18),
        )

    def classify_tax_code(self, item_name: str, candidates: list[str]) -> LLMResponse:
        prompt = (
            "你只做税收分类候选推荐，不做最终决定。\n"
            "请根据项目名称，从给定候选中返回 JSON。\n"
            "JSON 顶层字段必须包含：项目名称、候选分类。\n"
            "候选分类必须是数组，元素包含：分类名称、税收编码、置信度。\n"
            f"项目名称：{item_name}\n"
            f"候选：{json.dumps(candidates, ensure_ascii=False)}"
        )
        return self._chat_json(prompt, timeout_seconds=_task_timeout_seconds("TAX_INVOICE_LLM_TAX_CODE_TIMEOUT", self.timeout_seconds, 20))

    def extract_text_from_image(self, image_path: Path) -> LLMResponse:
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "请对这张图片做 OCR，只提取图片中的开票文字。"
            "必须只返回 JSON，格式为 {\"文字\": \"...\"}。"
            "请保留换行、公司名称、税号、发票类型、税率、明细、规格型号、数量、金额、地址电话、开户行账号。"
        )
        return self._chat_json_messages(
            [
                {"role": "system", "content": "You are a careful invoice OCR assistant. Output JSON only."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                    ],
                },
            ],
            timeout_seconds=_task_timeout_seconds("TAX_INVOICE_LLM_IMAGE_OCR_TIMEOUT", self.timeout_seconds, 12),
        )

    def ping_json(self) -> LLMResponse:
        return self._chat_json("只返回 JSON：{\"ok\": true}", timeout_seconds=min(self.timeout_seconds, 15))

    def _chat_json(self, prompt: str, *, timeout_seconds: int | None = None) -> LLMResponse:
        return self._chat_json_messages(
            [
                {"role": "system", "content": "You are a careful invoice extraction assistant. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            timeout_seconds=timeout_seconds,
        )

    def _chat_json_messages(self, messages: list[dict[str, Any]], *, timeout_seconds: int | None = None) -> LLMResponse:
        if not self.api_key:
            raise LLMAdapterError(f"{self.provider_label} API key is not configured.")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds or self.timeout_seconds) as response:
                raw_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise LLMAdapterError(f"{self.provider_label} HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise LLMAdapterError(f"{self.provider_label} network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMAdapterError(f"{self.provider_label} request timed out.") from exc

        content = _extract_openai_content(raw_payload)
        parsed_json = _parse_json_content(content)
        return LLMResponse(
            provider=self.provider_name,
            model=self.model,
            raw_payload=raw_payload,
            parsed_json=parsed_json,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


class MiMoOpenAICompatibleAdapter(MiniMaxOpenAICompatibleAdapter):
    provider_name = "mimo_openai"
    provider_label = "MiMo"
    default_endpoint = DEFAULT_MIMO_ENDPOINT
    default_model = DEFAULT_MIMO_MODEL

    def _headers(self) -> dict[str, str]:
        # Xiaomi MiMo OpenAI-compatible API uses `api-key` instead of Bearer auth.
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }


def _task_timeout_seconds(env_name: str, configured_timeout: int, default_cap: int) -> int:
    raw = os.environ.get(env_name, "").strip()
    try:
        cap = int(raw) if raw else default_cap
    except ValueError:
        cap = default_cap
    cap = max(1, cap)
    return min(configured_timeout, cap)



def get_llm_adapter() -> BaseLLMAdapter:
    config = load_llm_config()
    provider = config.provider.strip().lower()
    if not config.enabled or provider in {"", "off", "disabled", "none"}:
        return NullLLMAdapter()
    if provider in SUPPORTED_MINIMAX_PROVIDERS:
        return MiniMaxOpenAICompatibleAdapter(config)
    if provider in SUPPORTED_MIMO_PROVIDERS:
        return MiMoOpenAICompatibleAdapter(config)
    return NullLLMAdapter()


def diagnose_llm_config() -> LLMConfigDiagnostic:
    config = load_llm_config()
    issues: list[str] = []
    provider = config.provider.strip()
    enabled = bool(config.enabled and provider.lower() not in {"", "off", "disabled", "none"})
    if not enabled:
        issues.append("LLM is disabled.")
    if enabled and provider.lower() in AGENT_ORCHESTRATOR_PROVIDERS:
        issues.append(
            "OpenClaw/Hermes is a later orchestration layer, not the phase-1 LLM provider. "
            "Use provider=minimax_openai, mimo_openai, or another direct model API provider."
        )
    elif enabled and provider.lower() not in SUPPORTED_DIRECT_PROVIDERS:
        issues.append(f"Unsupported provider: {provider}")
    if enabled and not config.api_key:
        issues.append("API key is missing.")
    if enabled and not config.endpoint:
        issues.append("Endpoint is missing.")
    if enabled and not config.model:
        issues.append("Model is missing.")
    return LLMConfigDiagnostic(
        enabled=enabled,
        provider=provider,
        region=config.region,
        endpoint=config.endpoint,
        model=config.model,
        api_key_configured=bool(config.api_key),
        api_key_preview=_redact_key(config.api_key),
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        config_path=config.config_path,
        ready=enabled and not issues,
        issues=issues,
    )


def validate_extract_invoice_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["LLM 返回值必须是 JSON 对象。"]
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
        amount = str(line.get("金额", "") or "").strip()
        if amount and not _is_amount_like(amount):
            errors.append(f"项目列表第 {index} 项金额不是可识别数字: {amount}")
        tax_rate = str(line.get("税率", "") or "").strip()
        if tax_rate and not _is_tax_rate_like(tax_rate):
            errors.append(f"项目列表第 {index} 项税率格式不可识别: {tax_rate}")
    return errors


def load_llm_config() -> LLMConfig:
    file_config = _load_llm_config_file()
    env_provider = (os.getenv("TAX_INVOICE_LLM_PROVIDER") or "").strip()
    provider = env_provider or str(file_config.get("provider") or "").strip()
    enabled = _coerce_enabled(
        env_value=os.getenv("TAX_INVOICE_LLM_ENABLED"),
        file_value=file_config.get("enabled"),
        provider=provider,
        provider_from_env=bool(env_provider),
    )
    api_key_env_name = (os.getenv("TAX_INVOICE_LLM_API_KEY_ENV") or str(file_config.get("api_key_env") or "")).strip()
    api_key_from_named_env = os.getenv(api_key_env_name) if api_key_env_name else ""
    api_key = (
        os.getenv("TAX_INVOICE_LLM_API_KEY")
        or api_key_from_named_env
        or os.getenv("TAX_INVOICE_MIMO_API_KEY")
        or os.getenv("MIMO_API_KEY")
        or os.getenv("TAX_INVOICE_MINIMAX_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or str(file_config.get("api_key") or "")
    ).strip()
    region = (os.getenv("TAX_INVOICE_LLM_REGION") or str(file_config.get("region") or "")).strip().lower()
    explicit_endpoint = (
        os.getenv("TAX_INVOICE_LLM_ENDPOINT")
        or str(file_config.get("endpoint") or "")
    ).strip()
    provider_key = provider.strip().lower()
    endpoint = explicit_endpoint or _default_endpoint_for_provider(provider_key, region)
    model = (
        os.getenv("TAX_INVOICE_LLM_MODEL")
        or str(file_config.get("model") or "")
        or _default_model_for_provider(provider_key)
    ).strip()
    return LLMConfig(
        enabled=enabled,
        provider=provider,
        region=region,
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout_seconds=_safe_int(os.getenv("TAX_INVOICE_LLM_TIMEOUT") or file_config.get("timeout_seconds"), default=45, minimum=3),
        max_retries=_safe_int(os.getenv("TAX_INVOICE_LLM_MAX_RETRIES") or file_config.get("max_retries"), default=2, minimum=1),
        config_path=str(file_config.get("_config_path") or ""),
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _candidate_config_paths() -> list[Path]:
    explicit = (os.getenv("TAX_INVOICE_LLM_CONFIG") or "").strip()
    repo_root = _repo_root()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(
        [
            repo_root / "llm_client.local.json",
            repo_root / "llm_client.json",
        ]
    )
    return candidates


def _default_endpoint_for_provider(provider: str, region: str) -> str:
    if provider in SUPPORTED_MIMO_PROVIDERS:
        return DEFAULT_MIMO_ENDPOINT
    return _default_minimax_endpoint_for_region(region)


def _default_model_for_provider(provider: str) -> str:
    if provider in SUPPORTED_MIMO_PROVIDERS:
        return DEFAULT_MIMO_MODEL
    return DEFAULT_MINIMAX_MODEL


def _default_minimax_endpoint_for_region(region: str) -> str:
    if region.strip().lower() in {"cn", "china", "mainland", "zh-cn", "domestic", "国内", "中国"}:
        return DEFAULT_MINIMAX_CHINA_ENDPOINT
    return DEFAULT_MINIMAX_GLOBAL_ENDPOINT


def _load_llm_config_file() -> dict[str, Any]:
    for path in _candidate_config_paths():
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payload["_config_path"] = str(path)
        return payload
    return {}


def _coerce_enabled(*, env_value: Optional[str], file_value: Any, provider: str, provider_from_env: bool) -> bool:
    if env_value is not None and env_value.strip():
        return env_value.strip().lower() not in {"0", "false", "off", "no"}
    if provider_from_env:
        return provider.strip().lower() not in {"", "off", "disabled", "none"}
    if isinstance(file_value, bool):
        return file_value
    if isinstance(file_value, str) and file_value.strip():
        return file_value.strip().lower() not in {"0", "false", "off", "no"}
    return False


def _safe_int(value: Any, *, default: int, minimum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _is_amount_like(value: str) -> bool:
    text = value.strip().replace(",", "").replace("，", "").replace("￥", "").replace("¥", "").replace("元", "")
    try:
        float(text)
        return True
    except ValueError:
        return False


def _is_tax_rate_like(value: str) -> bool:
    text = value.strip().replace("％", "%")
    if text in {"免税", "不征税", "免征增值税"}:
        return True
    if text.endswith("%"):
        text = text[:-1]
    try:
        float(text)
        return True
    except ValueError:
        return False


def _extract_openai_content(payload: dict[str, Any]) -> str:
    try:
        return str(payload["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMAdapterError(f"Unexpected OpenAI-compatible response shape: {payload}") from exc


def _parse_json_content(content: str) -> dict[str, Any]:
    text = _strip_reasoning_blocks(content).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LLMAdapterError(f"MiniMax returned non-JSON content: {content[:200]}")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMAdapterError(f"MiniMax returned non-JSON content: {content[:200]}") from exc
    if not isinstance(parsed, dict):
        raise LLMAdapterError("MiniMax returned JSON but it is not an object.")
    return parsed


def _strip_reasoning_blocks(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL | re.IGNORECASE)


def _redact_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"

import os
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from tax_invoice_demo.extraction_pipeline import extract_invoice_structured_data
import tax_invoice_demo.llm_adapter as llm_adapter_module


SIMPLE_TEXT_INPUT = """购买方名称：黑龙江芃领飞象网络科技有限公司
纳税人识别号：91230109MAK8RY0867

发票类型：普通发票
税率：3%

开票明细：
1. 放学乐大菠萝，规格型号：40支/箱，单位：箱，数量：59，含税金额：3540
2. 放学乐大蜜瓜，规格型号：40支/箱，单位：箱，数量：62，含税金额：3801.16
"""


class ExtractionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)
        self.old_repo_root = llm_adapter_module._repo_root
        self.old_provider = os.environ.get("TAX_INVOICE_LLM_PROVIDER")
        self.old_enabled = os.environ.get("TAX_INVOICE_LLM_ENABLED")
        self.old_endpoint = os.environ.get("TAX_INVOICE_LLM_ENDPOINT")
        self.old_region = os.environ.get("TAX_INVOICE_LLM_REGION")
        self.old_model = os.environ.get("TAX_INVOICE_LLM_MODEL")
        self.old_api_key = os.environ.get("TAX_INVOICE_LLM_API_KEY")
        self.old_mimo_api_key = os.environ.get("TAX_INVOICE_MIMO_API_KEY")
        self.old_mimo_api_key_alias = os.environ.get("MIMO_API_KEY")
        self.old_api_key_env = os.environ.get("TAX_INVOICE_LLM_API_KEY_ENV")
        self.old_timeout = os.environ.get("TAX_INVOICE_LLM_TIMEOUT")
        self.old_max_retries = os.environ.get("TAX_INVOICE_LLM_MAX_RETRIES")
        self.old_config = os.environ.get("TAX_INVOICE_LLM_CONFIG")
        llm_adapter_module._repo_root = lambda: self.temp_path
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "off"
        os.environ.pop("TAX_INVOICE_LLM_ENABLED", None)
        os.environ.pop("TAX_INVOICE_LLM_ENDPOINT", None)
        os.environ.pop("TAX_INVOICE_LLM_REGION", None)
        os.environ.pop("TAX_INVOICE_LLM_MODEL", None)
        os.environ.pop("TAX_INVOICE_LLM_API_KEY", None)
        os.environ.pop("TAX_INVOICE_MIMO_API_KEY", None)
        os.environ.pop("MIMO_API_KEY", None)
        os.environ.pop("TAX_INVOICE_LLM_API_KEY_ENV", None)
        os.environ.pop("TAX_INVOICE_LLM_TIMEOUT", None)
        os.environ.pop("TAX_INVOICE_LLM_MAX_RETRIES", None)
        os.environ.pop("TAX_INVOICE_LLM_CONFIG", None)

    def tearDown(self):
        llm_adapter_module._repo_root = self.old_repo_root
        self._restore_env("TAX_INVOICE_LLM_PROVIDER", self.old_provider)
        self._restore_env("TAX_INVOICE_LLM_ENABLED", self.old_enabled)
        self._restore_env("TAX_INVOICE_LLM_ENDPOINT", self.old_endpoint)
        self._restore_env("TAX_INVOICE_LLM_REGION", self.old_region)
        self._restore_env("TAX_INVOICE_LLM_MODEL", self.old_model)
        self._restore_env("TAX_INVOICE_LLM_API_KEY", self.old_api_key)
        self._restore_env("TAX_INVOICE_MIMO_API_KEY", self.old_mimo_api_key)
        self._restore_env("MIMO_API_KEY", self.old_mimo_api_key_alias)
        self._restore_env("TAX_INVOICE_LLM_API_KEY_ENV", self.old_api_key_env)
        self._restore_env("TAX_INVOICE_LLM_TIMEOUT", self.old_timeout)
        self._restore_env("TAX_INVOICE_LLM_MAX_RETRIES", self.old_max_retries)
        self._restore_env("TAX_INVOICE_LLM_CONFIG", self.old_config)
        self.tempdir.cleanup()

    def _restore_env(self, name: str, value: Optional[str]) -> None:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def test_rules_only_pipeline_keeps_existing_parsing_behavior(self):
        outcome = extract_invoice_structured_data(
            raw_text=SIMPLE_TEXT_INPUT,
            note="",
            document_text="",
            ocr_text="",
        )

        self.assertEqual(outcome.strategy, "rules_only")
        self.assertEqual(outcome.llm_provider, "")
        self.assertEqual(outcome.warnings, [])
        self.assertEqual(outcome.buyer.name, "黑龙江芃领飞象网络科技有限公司")
        self.assertEqual(outcome.buyer.tax_id, "91230109MAK8RY0867")
        self.assertEqual(len(outcome.lines), 2)
        self.assertEqual(outcome.lines[0].project_name, "放学乐大菠萝")
        self.assertEqual(outcome.lines[0].amount_with_tax, "3540")

    def test_load_llm_config_from_local_file(self):
        os.environ.pop("TAX_INVOICE_LLM_PROVIDER", None)
        os.environ["TAX_INVOICE_MINIMAX_API_KEY"] = "file-env-key"
        (self.temp_path / "llm_client.local.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "provider": "minimax_openai",
                    "endpoint": "https://example.com/v1/chat/completions",
                    "model": "MiniMax-Test",
                    "api_key_env": "TAX_INVOICE_MINIMAX_API_KEY",
                    "timeout_seconds": 9,
                    "max_retries": 3,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        config = llm_adapter_module.load_llm_config()

        self.assertTrue(config.enabled)
        self.assertEqual(config.provider, "minimax_openai")
        self.assertEqual(config.endpoint, "https://example.com/v1/chat/completions")
        self.assertEqual(config.model, "MiniMax-Test")
        self.assertEqual(config.api_key, "file-env-key")
        self.assertEqual(config.timeout_seconds, 9)
        self.assertEqual(config.max_retries, 3)
        self.assertTrue(config.config_path.endswith("llm_client.local.json"))

    def test_environment_variables_override_llm_config_file(self):
        (self.temp_path / "llm_client.local.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "provider": "minimax_openai",
                    "endpoint": "https://file.example.com/v1/chat/completions",
                    "model": "FileModel",
                    "api_key": "file-key",
                    "timeout_seconds": 9,
                    "max_retries": 3,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_ENDPOINT"] = "https://env.example.com/v1/chat/completions"
        os.environ["TAX_INVOICE_LLM_MODEL"] = "EnvModel"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "env-key"
        os.environ["TAX_INVOICE_LLM_TIMEOUT"] = "7"
        os.environ["TAX_INVOICE_LLM_MAX_RETRIES"] = "4"

        config = llm_adapter_module.load_llm_config()

        self.assertTrue(config.enabled)
        self.assertEqual(config.provider, "minimax")
        self.assertEqual(config.endpoint, "https://env.example.com/v1/chat/completions")
        self.assertEqual(config.model, "EnvModel")
        self.assertEqual(config.api_key, "env-key")
        self.assertEqual(config.timeout_seconds, 7)
        self.assertEqual(config.max_retries, 4)

    def test_cn_region_uses_minimaxi_endpoint_when_endpoint_not_explicit(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax_m27"
        os.environ["TAX_INVOICE_LLM_REGION"] = "cn"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"
        os.environ.pop("TAX_INVOICE_LLM_ENDPOINT", None)

        config = llm_adapter_module.load_llm_config()
        diagnostic = llm_adapter_module.diagnose_llm_config()

        self.assertTrue(config.enabled)
        self.assertEqual(config.region, "cn")
        self.assertEqual(config.endpoint, "https://api.minimaxi.com/v1/chat/completions")
        self.assertEqual(diagnostic.region, "cn")
        self.assertTrue(diagnostic.ready)

    def test_mimo_provider_uses_xiaomi_defaults_and_api_key_header(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "mimo_openai"
        os.environ["TAX_INVOICE_MIMO_API_KEY"] = "mimo-key"
        os.environ.pop("TAX_INVOICE_LLM_ENDPOINT", None)
        os.environ.pop("TAX_INVOICE_LLM_MODEL", None)
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["url"] = request.full_url
            return _FakeHTTPResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

        config = llm_adapter_module.load_llm_config()
        diagnostic = llm_adapter_module.diagnose_llm_config()
        self.assertEqual(config.endpoint, "https://api.xiaomimimo.com/v1/chat/completions")
        self.assertEqual(config.model, "mimo-v2-omni")
        self.assertTrue(diagnostic.ready)

        with patch.object(llm_adapter_module, "urlopen", side_effect=fake_urlopen):
            response = llm_adapter_module.get_llm_adapter().ping_json()

        self.assertEqual(response.provider, "mimo_openai")
        self.assertEqual(response.parsed_json["ok"], True)
        self.assertEqual(captured["url"], "https://api.xiaomimimo.com/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "mimo-v2-omni")
        self.assertEqual(captured["headers"].get("Api-key"), "mimo-key")
        self.assertNotIn("Authorization", captured["headers"])

    def test_llm_extracts_when_rules_are_weak(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "客户名称": "辽宁恒润电力科技有限公司",
                                "纳税人识别号": "91210102MABWM3X12T",
                                "地址电话": "",
                                "开户行及账号": "",
                                "项目列表": [
                                    {
                                        "项目名称": "代理记账和税务申报",
                                        "规格型号": "",
                                        "单位": "项",
                                        "数量": "1",
                                        "单价": "500",
                                        "金额": "500",
                                        "税率": "3%",
                                        "税收编码": "3040802050000000000",
                                    }
                                ],
                                "价税合计": "500",
                                "备注": "",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

        with patch.object(llm_adapter_module, "urlopen", return_value=_FakeHTTPResponse(response_payload)):
            outcome = extract_invoice_structured_data(
                raw_text="帮忙给辽宁恒润开代理记账和税务申报，金额500，普票。税号91210102MABWM3X12T",
                note="",
                document_text="",
                ocr_text="",
            )

        self.assertEqual(outcome.strategy, "rules_plus_llm")
        self.assertEqual(outcome.llm_provider, "minimax_openai")
        self.assertEqual(outcome.buyer.name, "辽宁恒润电力科技有限公司")
        self.assertEqual(outcome.lines[0].project_name, "代理记账和税务申报")
        self.assertEqual(outcome.lines[0].amount_with_tax, "500")
        self.assertEqual(outcome.lines[0].tax_code, "3040802050000000000")

    def test_document_extraction_uses_llm_as_reviewer_and_flags_conflicts(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"
        document_text = """物料名称\t规格型号\t数量\t开票金额\t税率
一次性使用微针电极\tJ25BM\t3282\t1061785.36\t0.13
公司名称\t河北雅之颜医药有限公司
税号\t91130101MA7MB4FA89
税收编码\t1090245030000000000
"""
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "客户名称": "河北雅之颜医药有限公司",
                                "纳税人识别号": "91130101MA7MB4FA89",
                                "地址电话": "",
                                "开户行及账号": "",
                                "项目列表": [
                                    {
                                        "项目名称": "一次性使用微针电极",
                                        "规格型号": "J25BM",
                                        "单位": "",
                                        "数量": "3282",
                                        "单价": "",
                                        "金额": "1061785.36",
                                        "税率": "3%",
                                        "税收编码": "1090245030000000000",
                                    }
                                ],
                                "价税合计": "1061785.36",
                                "备注": "",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

        with patch.object(llm_adapter_module, "urlopen", return_value=_FakeHTTPResponse(response_payload)):
            outcome = extract_invoice_structured_data(raw_text="", note="", document_text=document_text, ocr_text="")

        self.assertEqual(outcome.strategy, "rules_plus_llm")
        self.assertEqual(outcome.lines[0].normalized_tax_rate(), "13%")
        self.assertTrue(any("识别差异需确认：第 1 行税率" in warning for warning in outcome.warnings))

    def test_invalid_llm_payload_falls_back_to_rules(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"
        response_payload = {"choices": [{"message": {"content": json.dumps({"项目列表": []}, ensure_ascii=False)}}]}

        with patch.object(llm_adapter_module, "urlopen", return_value=_FakeHTTPResponse(response_payload)):
            outcome = extract_invoice_structured_data(
                raw_text="客户：测试公司，税号91230100MA00000000，金额500",
                note="",
                document_text="",
                ocr_text="",
            )

        self.assertEqual(outcome.strategy, "rules_only")
        self.assertTrue(outcome.warnings)
        self.assertIn("LLM 返回结构无效", outcome.warnings[0])

    def test_llm_adapter_accepts_json_inside_markdown_fence(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"
        content = """```json
{
  "客户名称": "辽宁恒润电力科技有限公司",
  "纳税人识别号": "91210102MABWM3X12T",
  "地址电话": "",
  "开户行及账号": "",
  "项目列表": [
    {
      "项目名称": "代理记账和税务申报",
      "规格型号": "",
      "单位": "项",
      "数量": "1",
      "单价": "500",
      "金额": "500",
      "税率": "3%"
    }
  ],
  "价税合计": "500",
  "备注": ""
}
```"""
        response_payload = {"choices": [{"message": {"content": content}}]}

        with patch.object(llm_adapter_module, "urlopen", return_value=_FakeHTTPResponse(response_payload)):
            outcome = extract_invoice_structured_data(
                raw_text="给辽宁恒润开代理记账和税务申报500元",
                note="",
                document_text="",
                ocr_text="",
            )

        self.assertEqual(outcome.strategy, "rules_plus_llm")
        self.assertEqual(outcome.buyer.name, "辽宁恒润电力科技有限公司")
        self.assertEqual(outcome.lines[0].project_name, "代理记账和税务申报")

    def test_minimax_payload_omits_response_format_and_accepts_think_json(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"
        captured_payload = {}
        content = """<think>先理解字段，不要把这里当 JSON。</think>
{
  "客户名称": "测试有限公司",
  "纳税人识别号": "91210103MAC7R8K26X",
  "地址电话": "",
  "开户行及账号": "",
  "项目列表": [
    {"项目名称": "医用检查手套", "规格型号": "", "单位": "盒", "数量": "1", "单价": "100", "金额": "100", "税率": "13%"}
  ],
  "价税合计": "100",
  "备注": ""
}
"""

        def fake_urlopen(request, timeout=None):
            captured_payload.update(json.loads(request.data.decode("utf-8")))
            return _FakeHTTPResponse({"choices": [{"message": {"content": content}}]})

        with patch.object(llm_adapter_module, "urlopen", side_effect=fake_urlopen):
            response = llm_adapter_module.get_llm_adapter().extract_invoice_info("测试")

        self.assertNotIn("response_format", captured_payload)
        self.assertEqual(response.parsed_json["客户名称"], "测试有限公司")
        self.assertEqual(response.parsed_json["项目列表"][0]["项目名称"], "医用检查手套")

    def test_minimax_uses_slow_model_compatible_timeout_cap(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"
        os.environ["TAX_INVOICE_LLM_TIMEOUT"] = "45"

        adapter = llm_adapter_module.get_llm_adapter()

        self.assertEqual(adapter.timeout_seconds, 25)

    def test_llm_config_diagnostic_redacts_key(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "minimax"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "sk-test-123456"

        diagnostic = llm_adapter_module.diagnose_llm_config()

        self.assertTrue(diagnostic.ready)
        self.assertTrue(diagnostic.api_key_configured)
        self.assertEqual(diagnostic.api_key_preview, "sk-t...3456")
        self.assertEqual(diagnostic.issues, [])

    def test_openclaw_is_reported_as_orchestration_layer_not_phase1_provider(self):
        os.environ["TAX_INVOICE_LLM_PROVIDER"] = "openclaw"
        os.environ["TAX_INVOICE_LLM_API_KEY"] = "fake-key"

        diagnostic = llm_adapter_module.diagnose_llm_config()

        self.assertFalse(diagnostic.ready)
        self.assertTrue(any("OpenClaw/Hermes" in issue for issue in diagnostic.issues))


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


if __name__ == "__main__":
    unittest.main()

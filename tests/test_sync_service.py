import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tax_invoice_demo.case_events as case_events_module
import tax_invoice_demo.sync_service as sync_service_module
import tax_invoice_demo.tax_rule_engine as tax_rule_engine_module
from tax_invoice_demo.models import InvoiceLine


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class SyncServiceTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)
        self.old_event_root = case_events_module.EVENT_ROOT
        self.old_repo_root = sync_service_module._repo_root
        self.old_endpoint = os.environ.get("TAX_INVOICE_SYNC_ENDPOINT")
        self.old_token = os.environ.get("TAX_INVOICE_SYNC_TOKEN")
        self.old_tenant = os.environ.get("TAX_INVOICE_SYNC_TENANT")
        self.old_enabled = os.environ.get("TAX_INVOICE_SYNC_ENABLED")
        self.old_config = os.environ.get("TAX_INVOICE_SYNC_CONFIG")
        self.old_timeout = os.environ.get("TAX_INVOICE_SYNC_TIMEOUT")
        self.old_rules_endpoint = os.environ.get("TAX_INVOICE_RULES_ENDPOINT")
        self.old_tenant_rules_path = tax_rule_engine_module.TENANT_RULES_PATH
        self.old_learned_rules_path = tax_rule_engine_module.LEARNED_RULES_PATH
        case_events_module.EVENT_ROOT = self.temp_path / "events"
        sync_service_module._repo_root = lambda: self.temp_path
        tax_rule_engine_module.TENANT_RULES_PATH = self.temp_path / "客户同步赋码规则.csv"
        tax_rule_engine_module.LEARNED_RULES_PATH = self.temp_path / "本地即时学习赋码规则.csv"
        tax_rule_engine_module.load_tenant_coding_library.cache_clear()
        tax_rule_engine_module.load_learned_coding_library.cache_clear()
        os.environ["TAX_INVOICE_SYNC_ENDPOINT"] = "https://example.com/api/invoice/events"
        os.environ["TAX_INVOICE_SYNC_TOKEN"] = "demo-token"
        os.environ.pop("TAX_INVOICE_SYNC_TENANT", None)
        os.environ.pop("TAX_INVOICE_SYNC_ENABLED", None)
        os.environ.pop("TAX_INVOICE_SYNC_CONFIG", None)
        os.environ.pop("TAX_INVOICE_SYNC_TIMEOUT", None)
        os.environ.pop("TAX_INVOICE_RULES_ENDPOINT", None)

    def tearDown(self):
        case_events_module.EVENT_ROOT = self.old_event_root
        sync_service_module._repo_root = self.old_repo_root
        if self.old_endpoint is None:
            os.environ.pop("TAX_INVOICE_SYNC_ENDPOINT", None)
        else:
            os.environ["TAX_INVOICE_SYNC_ENDPOINT"] = self.old_endpoint
        if self.old_token is None:
            os.environ.pop("TAX_INVOICE_SYNC_TOKEN", None)
        else:
            os.environ["TAX_INVOICE_SYNC_TOKEN"] = self.old_token
        if self.old_tenant is None:
            os.environ.pop("TAX_INVOICE_SYNC_TENANT", None)
        else:
            os.environ["TAX_INVOICE_SYNC_TENANT"] = self.old_tenant
        if self.old_enabled is None:
            os.environ.pop("TAX_INVOICE_SYNC_ENABLED", None)
        else:
            os.environ["TAX_INVOICE_SYNC_ENABLED"] = self.old_enabled
        if self.old_config is None:
            os.environ.pop("TAX_INVOICE_SYNC_CONFIG", None)
        else:
            os.environ["TAX_INVOICE_SYNC_CONFIG"] = self.old_config
        if self.old_timeout is None:
            os.environ.pop("TAX_INVOICE_SYNC_TIMEOUT", None)
        else:
            os.environ["TAX_INVOICE_SYNC_TIMEOUT"] = self.old_timeout
        if self.old_rules_endpoint is None:
            os.environ.pop("TAX_INVOICE_RULES_ENDPOINT", None)
        else:
            os.environ["TAX_INVOICE_RULES_ENDPOINT"] = self.old_rules_endpoint
        tax_rule_engine_module.TENANT_RULES_PATH = self.old_tenant_rules_path
        tax_rule_engine_module.LEARNED_RULES_PATH = self.old_learned_rules_path
        tax_rule_engine_module.load_tenant_coding_library.cache_clear()
        tax_rule_engine_module.load_learned_coding_library.cache_clear()
        self.tempdir.cleanup()

    def test_flush_pending_events_posts_and_clears_queue(self):
        with patch.object(sync_service_module, "schedule_background_flush", lambda *args, **kwargs: False):
            case_events_module.record_case_event(
                case_id="case-1",
                draft_id="draft-1",
                event_type="draft_created",
                payload={"foo": "bar"},
            )

        with patch.object(sync_service_module, "urlopen", return_value=_FakeHTTPResponse({"accepted": 1})) as mocked:
            result = sync_service_module.flush_pending_events(limit=20)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.sent_count, 1)
        self.assertEqual(result.pending_count, 0)
        self.assertTrue(mocked.called)
        pending_path = case_events_module.pending_events_path()
        self.assertTrue(pending_path.exists())
        self.assertEqual(pending_path.read_text(encoding="utf-8").strip(), "")
        sync_state = json.loads(case_events_module.last_sync_state_path().read_text(encoding="utf-8"))
        self.assertEqual(sync_state["status"], "success")
        self.assertEqual(sync_state["sent_count"], 1)

    def test_load_sync_config_prefers_local_file_when_env_absent(self):
        os.environ.pop("TAX_INVOICE_SYNC_ENDPOINT", None)
        os.environ.pop("TAX_INVOICE_SYNC_TOKEN", None)
        (self.temp_path / "sync_client.local.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "endpoint": "http://seed-host:5021/api/invoice/events",
                    "token": "seed-token",
                    "tenant": "shenyang-seed-a",
                    "timeout_seconds": 11,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        config = sync_service_module.load_sync_config()

        self.assertEqual(config["enabled"], "1")
        self.assertEqual(config["endpoint"], "http://seed-host:5021/api/invoice/events")
        self.assertEqual(config["token"], "seed-token")
        self.assertEqual(config["tenant"], "shenyang-seed-a")
        self.assertEqual(config["timeout_seconds"], "11")
        self.assertTrue(config["config_path"].endswith("sync_client.local.json"))

    def test_environment_variables_override_local_file(self):
        (self.temp_path / "sync_client.local.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "endpoint": "http://seed-host:5021/api/invoice/events",
                    "token": "seed-token",
                    "tenant": "shenyang-seed-a",
                    "timeout_seconds": 11,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.environ["TAX_INVOICE_SYNC_ENDPOINT"] = "https://example.com/api/invoice/events"
        os.environ["TAX_INVOICE_SYNC_TOKEN"] = "env-token"
        os.environ["TAX_INVOICE_SYNC_TENANT"] = "env-tenant"
        os.environ["TAX_INVOICE_SYNC_TIMEOUT"] = "5"

        config = sync_service_module.load_sync_config()

        self.assertEqual(config["endpoint"], "https://example.com/api/invoice/events")
        self.assertEqual(config["token"], "env-token")
        self.assertEqual(config["tenant"], "env-tenant")
        self.assertEqual(config["timeout_seconds"], "5")

    def test_pull_latest_rule_package_writes_tenant_rules(self):
        os.environ["TAX_INVOICE_SYNC_TENANT"] = "seed-tenant"
        payload = {
            "package_id": "rules-001",
            "tenant": "seed-tenant",
            "version": "2026-04-24-a",
            "rules": [
                {
                    "raw_alias": "代理记账和税务申报",
                    "normalized_invoice_name": "代理记账和税务申报",
                    "tax_category": "纳税申报代理",
                    "tax_code": "3040802050000000000",
                    "tax_treatment_or_rate": "0.03",
                }
            ],
        }

        with patch.object(sync_service_module, "urlopen", return_value=_FakeHTTPResponse(payload)) as mocked:
            result = sync_service_module.pull_latest_rule_package()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.rule_count, 1)
        self.assertIn("/api/invoice/tenants/seed-tenant/rules/latest", result.endpoint)
        self.assertTrue(mocked.called)
        suggestion = tax_rule_engine_module.suggest_line(InvoiceLine(project_name="代理记账和税务申报", amount_with_tax="500"))
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion.entry.tax_category, "纳税申报代理")
        self.assertEqual(suggestion.entry.tax_code, "3040802050000000000")
        state = json.loads(case_events_module.last_rule_sync_state_path().read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "success")
        self.assertEqual(state["package_id"], "rules-001")


if __name__ == "__main__":
    unittest.main()

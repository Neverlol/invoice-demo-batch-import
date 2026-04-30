import os
import tempfile
import unittest
from pathlib import Path

from sync_center import create_app


class SyncCenterAPITest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "sync-center.sqlite3"
        self.old_token = os.environ.get("TAX_INVOICE_CENTER_TOKEN")
        os.environ["TAX_INVOICE_CENTER_TOKEN"] = "center-secret"
        self.app = create_app(db_path=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        if self.old_token is None:
            os.environ.pop("TAX_INVOICE_CENTER_TOKEN", None)
        else:
            os.environ["TAX_INVOICE_CENTER_TOKEN"] = self.old_token
        self.tempdir.cleanup()

    def test_ingest_and_query_case_events(self):
        payload = {
            "tenant": "shenyang-seed",
            "source": "invoice-demo-batch-import",
            "sent_at": "2026-04-23T10:00:00",
            "events": [
                {
                    "event_id": "evt-001",
                    "case_id": "case-001",
                    "draft_id": "draft-001",
                    "batch_id": "",
                    "event_type": "draft_created",
                    "created_at": "2026-04-23T10:00:01",
                    "payload": {"foo": "bar"},
                },
                {
                    "event_id": "evt-002",
                    "case_id": "case-001",
                    "draft_id": "draft-001",
                    "batch_id": "",
                    "event_type": "template_exported",
                    "created_at": "2026-04-23T10:00:03",
                    "payload": {"output_path": "/tmp/demo.xlsx"},
                },
            ],
        }
        headers = {"Authorization": "Bearer center-secret"}

        response = self.client.post("/api/invoice/events", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["accepted"], 2)

        duplicate = self.client.post("/api/invoice/events", json=payload, headers=headers)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.get_json()["accepted"], 0)
        self.assertEqual(duplicate.get_json()["duplicates"], 2)

        timeline = self.client.get("/api/invoice/tenants/shenyang-seed/cases/case-001", headers=headers)
        self.assertEqual(timeline.status_code, 200)
        body = timeline.get_json()
        self.assertEqual(body["case_id"], "case-001")
        self.assertEqual(len(body["events"]), 2)
        self.assertEqual(body["events"][0]["event_type"], "draft_created")

        recent = self.client.get("/api/invoice/tenants/shenyang-seed/events?limit=5", headers=headers)
        self.assertEqual(recent.status_code, 200)
        self.assertEqual(len(recent.get_json()["events"]), 2)

    def test_auth_is_required_when_center_token_is_set(self):
        response = self.client.post(
            "/api/invoice/events",
            json={"tenant": "t", "events": []},
        )
        self.assertEqual(response.status_code, 401)

    def test_publish_and_fetch_latest_rule_package(self):
        headers = {"Authorization": "Bearer center-secret"}
        rules = [
            {
                "raw_alias": "代理记账和税务申报",
                "normalized_invoice_name": "代理记账和税务申报",
                "tax_category": "纳税申报代理",
                "tax_code": "3040802050000000000",
                "tax_treatment_or_rate": "0.03",
            }
        ]

        response = self.client.post(
            "/api/invoice/tenants/shenyang-seed/rules",
            json={"version": "2026-04-24-a", "rules": rules, "note": "reviewed"},
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["rule_count"], 1)
        self.assertEqual(body["version"], "2026-04-24-a")

        latest = self.client.get("/api/invoice/tenants/shenyang-seed/rules/latest", headers=headers)
        self.assertEqual(latest.status_code, 200)
        latest_body = latest.get_json()
        self.assertEqual(latest_body["package_id"], body["package_id"])
        self.assertEqual(latest_body["rules"][0]["tax_code"], "3040802050000000000")

    def test_rule_candidates_are_extracted_from_learned_rule_events(self):
        headers = {"Authorization": "Bearer center-secret"}
        payload = {
            "tenant": "shenyang-seed",
            "source": "invoice-demo-batch-import",
            "events": [
                {
                    "event_id": "learned-001",
                    "case_id": "case-001",
                    "draft_id": "draft-001",
                    "batch_id": "",
                    "event_type": "local_learned_rules_saved",
                    "created_at": "2026-04-24T10:00:00",
                    "payload": {
                        "rule_count": 1,
                        "rules": [
                            {
                                "raw_alias": "代理记账和税务申报",
                                "normalized_invoice_name": "代理记账和税务申报",
                                "tax_category": "纳税申报代理",
                                "tax_code": "3040802050000000000",
                                "tax_treatment_or_rate": "0.03",
                                "company_name": "吉林省风生水起商贸有限公司",
                            }
                        ],
                    },
                },
                {
                    "event_id": "learned-002",
                    "case_id": "case-002",
                    "draft_id": "draft-002",
                    "batch_id": "",
                    "event_type": "local_learned_rules_saved",
                    "created_at": "2026-04-24T10:05:00",
                    "payload": {
                        "rule_count": 1,
                        "rules": [
                            {
                                "raw_alias": "代理记账和税务申报",
                                "normalized_invoice_name": "代理记账和税务申报",
                                "tax_category": "纳税申报代理",
                                "tax_code": "3040802050000000000",
                                "tax_treatment_or_rate": "0.03",
                                "company_name": "吉林省风生水起商贸有限公司",
                            }
                        ],
                    },
                },
            ],
        }

        ingest = self.client.post("/api/invoice/events", json=payload, headers=headers)
        self.assertEqual(ingest.status_code, 200)

        response = self.client.get("/api/invoice/tenants/shenyang-seed/rule-candidates", headers=headers)
        self.assertEqual(response.status_code, 200)
        candidates = response.get_json()["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["raw_alias"], "代理记账和税务申报")
        self.assertEqual(candidates[0]["tax_code"], "3040802050000000000")
        self.assertEqual(candidates[0]["evidence_count"], 2)
        self.assertIn("case-001", candidates[0]["case_ids"])

    def test_import_and_fetch_customer_profiles(self):
        headers = {"Authorization": "Bearer center-secret"}
        sellers = [
            {
                "seller_name": "哈尔滨市道里区庆成记隆江猪脚饭店（个体工商户）",
                "seller_tax_id": "92230102MAECWNQX6M",
                "source_confidence": "official_history_export",
                "project_profiles": [
                    {
                        "project_name": "餐费",
                        "tax_category": "餐饮服务",
                        "tax_code": "3070401000000000000",
                        "tax_rate": "1%",
                        "unit": "项",
                        "line_count": 2,
                    }
                ],
                "buyer_profiles": [
                    {"buyer_name": "北京测试有限公司", "buyer_tax_id": "91110101TEST000001", "line_count": 2}
                ],
            }
        ]

        response = self.client.post(
            "/api/invoice/profile-imports",
            json={
                "tenant": "shenyang-seed",
                "source": "invoice-demo-batch-import",
                "source_confidence": "official_history_export",
                "seller_profiles": sellers,
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["seller_count"], 1)
        self.assertEqual(body["buyer_count"], 1)
        self.assertEqual(body["line_profile_count"], 1)

        latest = self.client.get(
            "/api/invoice/tenants/shenyang-seed/customer-profiles/latest?seller_tax_id=92230102MAECWNQX6M",
            headers=headers,
        )
        self.assertEqual(latest.status_code, 200)
        latest_body = latest.get_json()
        self.assertEqual(latest_body["seller_count"], 1)
        seller = latest_body["sellers"][0]
        self.assertEqual(seller["seller_tax_id"], "92230102MAECWNQX6M")
        self.assertEqual(seller["project_profiles"][0]["tax_code"], "3070401000000000000")
        self.assertEqual(seller["buyer_profiles"][0]["buyer_name"], "北京测试有限公司")

        health = self.client.get("/api/invoice/events/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json()["total_seller_profiles"], 1)



if __name__ == "__main__":
    unittest.main()

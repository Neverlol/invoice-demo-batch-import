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


if __name__ == "__main__":
    unittest.main()

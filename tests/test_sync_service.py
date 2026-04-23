import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tax_invoice_demo.case_events as case_events_module
import tax_invoice_demo.sync_service as sync_service_module


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
        self.old_endpoint = os.environ.get("TAX_INVOICE_SYNC_ENDPOINT")
        self.old_token = os.environ.get("TAX_INVOICE_SYNC_TOKEN")
        case_events_module.EVENT_ROOT = self.temp_path / "events"
        os.environ["TAX_INVOICE_SYNC_ENDPOINT"] = "https://example.com/api/invoice/events"
        os.environ["TAX_INVOICE_SYNC_TOKEN"] = "demo-token"

    def tearDown(self):
        case_events_module.EVENT_ROOT = self.old_event_root
        if self.old_endpoint is None:
            os.environ.pop("TAX_INVOICE_SYNC_ENDPOINT", None)
        else:
            os.environ["TAX_INVOICE_SYNC_ENDPOINT"] = self.old_endpoint
        if self.old_token is None:
            os.environ.pop("TAX_INVOICE_SYNC_TOKEN", None)
        else:
            os.environ["TAX_INVOICE_SYNC_TOKEN"] = self.old_token
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


if __name__ == "__main__":
    unittest.main()

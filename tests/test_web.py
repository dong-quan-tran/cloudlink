import tempfile
import unittest
import os
import json
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from cloudlink.probe import Node
from cloudlink.web import create_app
from cloudlink.worker import process_message


class FakeSession:
    def client(self, name):
        return object()


NODES = [
    Node("i-a", "A", "10.10.1.1", "203.0.113.1", "vpc-1", "subnet-a", "us-east-1a", ("sg-a",)),
    Node("i-b", "B", "10.10.2.1", "203.0.113.2", "vpc-1", "subnet-b", "us-east-1b", ("sg-b",)),
]


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(FakeSession(), Path(self.temp.name) / "history.sqlite3")
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_lab_form_uses_private_addresses_only(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Private IP (same VPC)", html)
        self.assertNotIn('id="address-type"', html)
        self.assertNotIn('<option value="public">', html)

    @patch("cloudlink.web.discover_nodes", return_value=NODES)
    def test_instance_list(self, _discover):
        response = self.client.get("/api/instances")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["instances"]), 2)

    @patch("cloudlink.web.discover_nodes", return_value=NODES)
    def test_rejects_missing_token(self, _discover):
        response = self.client.post("/api/tests", json={"source_id": "i-a", "destination_id": "i-b"})
        self.assertEqual(response.status_code, 403)

    @patch("cloudlink.web.run_probe")
    @patch("cloudlink.web.discover_nodes", return_value=NODES)
    def test_records_result(self, _discover, probe):
        probe.return_value = {
            "timestamp": "2026-10-14T12:00:00+00:00", "source_id": "i-a", "destination_id": "i-b",
            "source_name": "A", "destination_name": "B", "address_type": "private",
            "tested_address": "10.10.2.1", "test_type": "https", "port": 443,
            "check": {"ok": True, "detail": "HTTP 200 OK", "status_code": 200},
            "summary": "HTTPS responded", "recommendation": "No action needed.",
        }
        with self.client.get("/") as response:
            html = response.get_data(as_text=True)
        token = html.split('name="cloudlink-token" content="')[1].split('"')[0]
        response = self.client.post(
            "/api/tests", json={"source_id": "i-a", "destination_id": "i-b", "test_type": "https"},
            headers={"X-CloudLink-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["summary"], "HTTPS responded")
        self.assertEqual(probe.call_args.kwargs["test_type"], "https")
        self.assertIsNone(probe.call_args.kwargs["port"])
        self.assertEqual(len(self.client.get("/api/history").json["tests"]), 1)

    @patch("cloudlink.web.discover_nodes", return_value=NODES)
    def test_rejects_invalid_mode_and_port(self, _discover):
        html = self.client.get("/").get_data(as_text=True)
        token = html.split('name="cloudlink-token" content="')[1].split('"')[0]
        headers = {"X-CloudLink-Token": token}
        base = {"source_id": "i-a", "destination_id": "i-b"}
        for extra in ({"test_type": "udp"}, {"test_type": "tcp", "port": 0},
                      {"test_type": "tcp", "port": True}, {"test_type": "ping", "port": 8080}):
            with self.subTest(extra=extra):
                response = self.client.post("/api/tests", json={**base, **extra}, headers=headers)
                self.assertEqual(response.status_code, 400)

    def test_hosted_inventory_needs_no_aws_session(self):
        inventory = Path(self.temp.name) / "nodes.json"
        inventory.write_text('[{"instance_id":"node-a","name":"A","private_ip":"10.10.1.10"}]')
        with patch.dict(os.environ, {"CLOUDLINK_INVENTORY_PATH": str(inventory)}):
            hosted = create_app(data_path=Path(self.temp.name) / "hosted.sqlite3")
        response = hosted.test_client().get("/api/instances")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["instances"][0]["instance_id"], "node-a")

    @patch("cloudlink.web.run_probe")
    @patch("cloudlink.web.discover_nodes", return_value=NODES)
    def test_queued_submission_works_across_app_replicas(self, _discover, probe):
        key = Path(self.temp.name) / "shared-key"
        key.write_text("local fixture only")
        jobs = MagicMock()
        job_id = "9d3276f0-fd3c-4377-aa6d-72f263f75561"
        jobs.submit.return_value = {"id": job_id, "status": "queued"}
        jobs.get.return_value = {"id": job_id}
        jobs.view.return_value = {"id": job_id, "status": "completed", "summary": "ICMP reply received"}
        with patch.dict(os.environ, {"CLOUDLINK_KEY_PATH": str(key)}):
            first = create_app(FakeSession(), job_store=jobs).test_client()
            second = create_app(FakeSession(), job_store=jobs).test_client()
        html = first.get("/").get_data(as_text=True)
        token = html.split('name="cloudlink-token" content="')[1].split('"')[0]
        second.set_cookie("session", first.get_cookie("session").value)
        response = second.post("/api/tests", json={"source_id": "i-a", "destination_id": "i-b"},
                               headers={"X-CloudLink-Token": token})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(first.get(response.json["status_url"]).json["status"], "completed")
        probe.assert_not_called()

    @patch("cloudlink.worker.run_probe")
    def test_worker_does_not_repeat_completed_or_leased_work(self, probe):
        store = MagicMock()
        message = {"Body": '{"id":"job-1"}', "ReceiptHandle": "receipt"}
        store.get.return_value = {"status": "completed"}
        process_message(store, FakeSession(), message)
        store.queue.delete_message.assert_called_once()
        store.reset_mock()
        store.get.return_value = {"status": "running", "deadline": int(time.time()) + 900}
        store.claim.return_value = False
        process_message(store, FakeSession(), message)
        store.queue.delete_message.assert_not_called()
        probe.assert_not_called()

    @patch("cloudlink.worker.run_probe", return_value={"check": {"ok": True}})
    @patch("cloudlink.worker.discover_nodes", return_value=NODES)
    def test_worker_saves_before_acknowledging(self, _discover, probe):
        store = MagicMock()
        store.get.return_value = {"status": "queued", "deadline": int(time.time()) + 900,
                                  "source_id": "i-a", "destination_id": "i-b",
                                  "request": {"address_type": "private", "test_type": "tcp", "port": Decimal(8080)}}
        store.claim.return_value = True
        store.complete.return_value = True
        with patch.dict(os.environ, {"CLOUDLINK_KEY_PATH": "/local-fixture"}):
            process_message(store, FakeSession(), {"Body": json.dumps({"id": "job-1"}), "ReceiptHandle": "receipt"})
        store.complete.assert_called_once_with("job-1", store.claim.call_args.args[1], probe.return_value)
        self.assertIs(type(probe.call_args.kwargs["port"]), int)
        self.assertEqual(probe.call_args.kwargs["port"], 8080)
        names = [call[0] for call in store.mock_calls]
        self.assertLess(names.index("complete"), names.index("queue.delete_message"))


if __name__ == "__main__":
    unittest.main()

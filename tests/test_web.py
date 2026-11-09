import tempfile
import unittest
import os
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from cloudlink.jobs import JobStore
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
        analysis = patch("cloudlink.web.analyze_network", return_value={"status": "unknown", "summary": "Local fixture", "checks": []})
        self.analysis = analysis.start()
        self.addCleanup(analysis.stop)
        self.app = create_app(FakeSession(), Path(self.temp.name) / "history.sqlite3")
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_lab_form_uses_private_addresses_only(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="fixed-address">Private IP</div>', html)
        self.assertIn('data-result="network-findings"', html)
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
        self.assertNotIn("network_analysis", response.json)
        self.analysis.assert_not_called()
        self.assertEqual(probe.call_args.kwargs["test_type"], "https")
        self.assertIsNone(probe.call_args.kwargs["port"])
        self.assertEqual(len(self.client.get("/api/history").json["tests"]), 1)
        other = self.app.test_client()
        other.get("/")
        self.assertEqual(other.get("/api/history").json["tests"], [])
        self.client.get("/")
        self.assertEqual(len(self.client.get("/api/history").json["tests"]), 1)

    @patch("cloudlink.web.discover_nodes", return_value=NODES)
    def test_rejects_invalid_mode_and_port(self, _discover):
        html = self.client.get("/").get_data(as_text=True)
        token = html.split('name="cloudlink-token" content="')[1].split('"')[0]
        headers = {"X-CloudLink-Token": token}
        base = {"source_id": "i-a", "destination_id": "i-b"}
        for extra in ({"mode": "invalid"}, {"test_type": "overview"}, {"test_type": "udp"}, {"test_type": "tcp", "port": 0},
                      {"test_type": "tcp", "port": True}, {"test_type": "ping", "port": 8080}):
            with self.subTest(extra=extra):
                response = self.client.post("/api/tests", json={**base, **extra}, headers=headers)
                self.assertEqual(response.status_code, 400)

    @patch("cloudlink.network.analyze_network", return_value={"status": "review", "summary": "Rules listed", "checks": []})
    @patch("cloudlink.web.run_probe")
    @patch("cloudlink.web.discover_nodes", return_value=NODES)
    def test_configuration_review_saves_without_running_a_probe(self, _discover, probe, analyze):
        html = self.client.get("/").get_data(as_text=True)
        token = html.split('name="cloudlink-token" content="')[1].split('"')[0]
        response = self.client.post("/api/tests", json={"source_id": "i-a", "destination_id": "i-b", "mode": "configuration"},
                                    headers={"X-CloudLink-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["test_type"], "overview")
        probe.assert_not_called()
        analyze.assert_called_once()
        self.assertEqual(self.client.get("/api/history").json["tests"][0], response.json)

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
        storage = MagicMock()
        jobs = JobStore(storage, "tests", "queue")
        items = {}
        jobs.table.put_item.side_effect = lambda Item, **_: items.update({Item["id"]: Item})
        jobs.table.get_item.side_effect = lambda Key, **_: {"Item": items[Key["id"]]} if Key["id"] in items else {}
        jobs.table.query.side_effect = lambda ExpressionAttributeValues, **_: {
            "Items": [job for job in items.values() if job["history_partition"] == ExpressionAttributeValues[":p"]],
        }
        with patch.dict(os.environ, {"CLOUDLINK_KEY_PATH": str(key)}):
            first = create_app(FakeSession(), job_store=jobs).test_client()
            replica = create_app(FakeSession(), job_store=jobs)
            second = replica.test_client()
            other = replica.test_client()
        html = first.get("/").get_data(as_text=True)
        token = html.split('name="cloudlink-token" content="')[1].split('"')[0]
        second.set_cookie("session", first.get_cookie("session").value)
        response = second.post("/api/tests", json={"source_id": "i-a", "destination_id": "i-b"},
                               headers={"X-CloudLink-Token": token})
        self.assertEqual(response.status_code, 202)
        result_url = response.json["status_url"]
        job_id = response.json["id"]
        self.assertEqual(first.get(result_url).json["status"], "queued")
        items[job_id].update(status="completed", result_json=json.dumps({"summary": "ICMP reply received"}))
        self.assertEqual(first.get(result_url).json["status"], "completed")
        self.assertEqual(first.get("/api/history").json["tests"][0]["id"], job_id)
        self.assertEqual(other.get(result_url).status_code, 404)
        other.get("/")
        self.assertEqual(other.get(result_url).status_code, 404)
        self.assertEqual(other.get("/api/history").json["tests"], [])
        items[job_id]["history_partition"] = "tests"  # Legacy, shared record.
        self.assertEqual(first.get(result_url).status_code, 404)
        self.assertEqual(first.get("/api/history").json["tests"], [])
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

    @patch("cloudlink.worker.analyze_network", return_value={"status": "pass", "checks": []})
    @patch("cloudlink.worker.run_probe", return_value={"check": {"ok": False}})
    @patch("cloudlink.worker.discover_nodes", return_value=NODES)
    def test_worker_saves_before_acknowledging(self, discover, probe, analysis):
        store = MagicMock()
        store.get.return_value = {"status": "queued", "deadline": int(time.time()) + 900,
                                  "created_at": "2026-11-09T12:00:00+00:00",
                                  "source_id": "i-a", "destination_id": "i-b",
                                  "request": {"address_type": "private", "test_type": "tcp", "port": Decimal(8080)}}
        store.claim.return_value = True
        store.complete.return_value = True
        with (
            patch.dict(os.environ, {"CLOUDLINK_KEY_PATH": "/local-fixture"}),
            patch("cloudlink.worker.datetime", wraps=datetime) as clock,
            self.assertLogs("cloudlink.worker", level="INFO") as logs,
        ):
            clock.now.return_value = datetime(2026, 11, 9, 12, 0, 2, tzinfo=timezone.utc)
            process_message(store, FakeSession(), {"Body": json.dumps({"id": "job-1"}), "ReceiptHandle": "receipt"})
        self.assertEqual(discover.call_args.kwargs["instance_ids"], ("i-a", "i-b"))
        event, = (json.loads(record.getMessage()) for record in logs.records)
        self.assertEqual(event["event"], "diagnostic_completed")
        self.assertEqual(event["test_type"], "tcp")
        self.assertEqual(event["outcome"], "unreachable")
        self.assertGreaterEqual(event["duration_ms"], 0)
        self.assertEqual(event["queue_wait_ms"], 2000)
        self.assertEqual(event["total_ms"], 2000 + event["duration_ms"])
        store.complete.assert_called_once_with("job-1", store.claim.call_args.args[1], probe.return_value)
        self.assertEqual(store.complete.call_args.args[2]["network_analysis"], analysis.return_value)
        self.assertEqual(analysis.call_args.kwargs["port"], 8080)
        self.assertIs(type(probe.call_args.kwargs["port"]), int)
        self.assertEqual(probe.call_args.kwargs["port"], 8080)
        names = [call[0] for call in store.mock_calls]
        self.assertLess(names.index("complete"), names.index("queue.delete_message"))


if __name__ == "__main__":
    unittest.main()

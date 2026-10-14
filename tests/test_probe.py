import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from cloudlink.probe import Node, REMOTE_PROBE, discover_nodes, load_inventory, run_probe, summarize


class FakePaginator:
    def paginate(self, **kwargs):
        assert {item["Name"] for item in kwargs["Filters"]} == {
            "instance-state-name", "tag:Project", "tag:CloudLinkRole"
        }
        yield {"Reservations": [{"Instances": [{
            "InstanceId": "i-123", "PrivateIpAddress": "10.10.1.5",
            "PublicIpAddress": "203.0.113.5", "VpcId": "vpc-123", "SubnetId": "subnet-123",
            "Placement": {"AvailabilityZone": "us-east-1a"},
            "SecurityGroups": [{"GroupId": "sg-123"}],
            "Tags": [{"Key": "Name", "Value": "Node A"}],
        }]}]}


class FakeEC2:
    def get_paginator(self, name):
        assert name == "describe_instances"
        return FakePaginator()


class ProbeTests(unittest.TestCase):
    source = Node("node-a", "A", "10.10.1.10", None, "vpc-1", "subnet-a", "", ())
    destination = Node("node-b", "B", "10.10.2.10", None, "vpc-1", "subnet-b", "", ())

    def test_discovery(self):
        node = discover_nodes(FakeEC2())[0]
        self.assertEqual(node.name, "Node A")
        self.assertEqual(node.private_ip, "10.10.1.5")
        self.assertEqual(node.security_group_ids, ("sg-123",))

    def test_http_response_is_success_even_for_error_status(self):
        summary, advice = summarize("http", {"ok": True, "detail": "HTTP 404 Not Found", "status_code": 404}, 80)
        self.assertEqual(summary, "HTTP responded")
        self.assertIn("application error", advice)

    def test_failed_tcp_does_not_claim_a_missing_route(self):
        summary, advice = summarize("tcp", {"ok": False, "detail": "Connection refused"}, 8080)
        self.assertEqual(summary, "TCP connection failed")
        self.assertIn("does not prove a missing route", advice)

    def test_source_failure(self):
        summary, advice = summarize("ping", {"ok": False, "management_error": True}, None)
        self.assertEqual(summary, "Source unavailable")
        self.assertIn("nothing about A-to-B", advice)

    def test_file_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.json"
            path.write_text('[{"instance_id":"node-a","name":"Node A","private_ip":"10.10.1.10"}]')
            self.assertEqual(load_inventory(path)[0].private_ip, "10.10.1.10")

    def test_ping_uses_private_management_path_and_one_remote_command(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "probe-key"
            key.write_text("test key")
            with patch("cloudlink.probe.shutil.which", return_value="/usr/bin/ssh"):
                with patch("cloudlink.probe._run_ssh", return_value={"ok": True, "exit_code": 0, "stdout": "2 received", "stderr": ""}) as command:
                    result = run_probe(
                        None, self.source, self.destination, existing_key_path=str(key),
                        source_address_type="private", test_type="ping",
                    )
        self.assertEqual(result["summary"], "ICMP reply received")
        self.assertIsNone(result["port"])
        command.assert_called_once()
        self.assertEqual(command.call_args.args[0], "10.10.1.10")
        self.assertEqual(command.call_args.args[2], ["ping", "-c", "2", "-W", "2", "10.10.2.10"])

    def test_protocol_modes_dispatch_to_correct_ports(self):
        for test_type, port in (("http", 80), ("https", 443), ("ssh", 22), ("tcp", 8080)):
            with self.subTest(test_type=test_type), tempfile.TemporaryDirectory() as directory:
                key = Path(directory) / "probe-key"
                key.write_text("test key")
                response = {"ok": True, "exit_code": 0, "stdout": json.dumps({"ok": True, "detail": "Service answered"}), "stderr": ""}
                with patch("cloudlink.probe.shutil.which", return_value="/usr/bin/ssh"):
                    with patch("cloudlink.probe._run_ssh", return_value=response) as command:
                        result = run_probe(
                            None, self.source, self.destination, existing_key_path=str(key),
                            source_address_type="private", test_type=test_type,
                            port=8080 if test_type == "tcp" else None,
                        )
                self.assertEqual(result["port"], port)
                self.assertTrue(result["check"]["ok"])
                self.assertEqual(command.call_args.args[2], ["python3", "-", "10.10.2.10", test_type, str(port)])
                self.assertEqual(command.call_args.kwargs["input_text"], REMOTE_PROBE)

    def test_rejects_invalid_custom_port_before_remote_access(self):
        with self.assertRaisesRegex(ValueError, "Custom TCP port"):
            run_probe(None, self.source, self.destination, test_type="tcp", port=True)

    def test_remote_probe_reports_closed_tcp_port(self):
        output = StringIO()
        with patch.object(sys, "argv", ["-", "127.0.0.1", "tcp", "8080"]):
            with patch("socket.create_connection", side_effect=ConnectionRefusedError("blocked")):
                with redirect_stdout(output):
                    exec(REMOTE_PROBE, {"__name__": "__main__"})
        result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("ConnectionRefusedError", result["detail"])

    def test_remote_http_accepts_an_error_status_as_a_response(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 404
        connection.getresponse.return_value.reason = "Not Found"
        output = StringIO()
        with patch.object(sys, "argv", ["-", "127.0.0.1", "http", "80"]):
            with patch("http.client.HTTPConnection", return_value=connection):
                with redirect_stdout(output):
                    exec(REMOTE_PROBE, {"__name__": "__main__"})
        result = json.loads(output.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 404)
        connection.request.assert_called_once_with("GET", "/", headers={"Connection": "close"})

    def test_remote_https_reports_unverified_certificate(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.reason = "OK"
        output = StringIO()
        with patch.object(sys, "argv", ["-", "127.0.0.1", "https", "443"]):
            with patch("http.client.HTTPSConnection", return_value=connection):
                with redirect_stdout(output):
                    exec(REMOTE_PROBE, {"__name__": "__main__"})
        result = json.loads(output.getvalue())
        self.assertTrue(result["ok"])
        self.assertIn("certificate not verified", result["detail"])

    def test_remote_ssh_checks_banner_without_login(self):
        connection = MagicMock()
        connection.__enter__.return_value.recv.return_value = b"SSH-2.0-OpenSSH_9.0\r\n"
        output = StringIO()
        with patch.object(sys, "argv", ["-", "127.0.0.1", "ssh", "22"]):
            with patch("socket.create_connection", return_value=connection):
                with redirect_stdout(output):
                    exec(REMOTE_PROBE, {"__name__": "__main__"})
        result = json.loads(output.getvalue())
        self.assertTrue(result["ok"])
        self.assertIn("login not attempted", result["detail"])


if __name__ == "__main__":
    unittest.main()

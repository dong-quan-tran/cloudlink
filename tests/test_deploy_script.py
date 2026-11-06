"""Exercise deployment orchestration with a fake AWS CLI, never a live account."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "123456789012"

FAKE_AWS = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["MOCK_AWS_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
service, operation = args[:2]
if (service, operation) == ("sts", "get-caller-identity"):
    print(json.dumps({"Account": "123456789012", "Arn": os.environ.get("MOCK_CALLER", "arn:aws:iam::123456789012:user/joel")}))
elif (service, operation) == ("cloudformation", "describe-stacks"):
    if "--query" in args:
        query = args[args.index("--query") + 1]
        print("http://127.0.0.1/" if "WebUrl" in query else "i-node-a" if "NodeAInstanceId" in query else "i-node-b")
    elif os.environ.get("MOCK_UNOWNED"):
        print(json.dumps({"Stacks": [{"StackName": args[args.index("--stack-name") + 1], "Tags": [], "StackStatus": "CREATE_COMPLETE"}]}))
    else:
        print("An error occurred (ValidationError): Stack does not exist", file=sys.stderr)
        sys.exit(1)
elif (service, operation) == ("ec2", "describe-instance-type-offerings"):
    print(os.environ.get("MOCK_OFFERED", "1"))
elif (service, operation) == ("ec2", "describe-instances"):
    print(os.environ.get("MOCK_PUBLIC_IPS", ""))
elif (service, operation) == ("cloudformation", "validate-template") and os.environ.get("MOCK_INVALID_TEMPLATE"):
    print("Template validation failed", file=sys.stderr)
    sys.exit(1)
'''


class DeployScriptTests(unittest.TestCase):
    def run_script(self, *args: str, mock_env=None, manifest=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("scripts", "infra"):
                shutil.copytree(ROOT / name, root / name)
            if manifest:
                (root / ".cloudlink-deployment.json").write_text(json.dumps(manifest))
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log_path = root / "aws.log"
            aws_path = bin_dir / "aws"
            aws_path.write_text(f"#!{sys.executable}\n" + FAKE_AWS)
            aws_path.chmod(0o755)
            curl_path = bin_dir / "curl"
            curl_path.write_text("#!/bin/sh\nexit 0\n")
            curl_path.chmod(0o755)
            (bin_dir / "python3").symlink_to(sys.executable)
            environment = {**os.environ, "MOCK_AWS_LOG": str(log_path), **(mock_env or {})}
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            result = subprocess.run(
                ["bash", str(root / "scripts" / "deploy.sh"), *args],
                cwd=root, env=environment, capture_output=True, text=True,
                timeout=15, check=False,
            )
            calls = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
            saved = root / ".cloudlink-deployment.json"
            return result, calls, json.loads(saved.read_text()) if saved.exists() else None

    def deploy(self, *args, **kwargs):
        return self.run_script("--management-cidr", "203.0.113.10/32", "--apply",
                               "--confirm-account", ACCOUNT, *args, **kwargs)

    def test_preview_performs_no_deployment_or_local_record(self):
        result, calls, saved = self.run_script("--management-cidr", "203.0.113.10/32")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preview only", result.stdout)
        self.assertFalse(any(call[:2] == ["cloudformation", "deploy"] for call in calls))
        self.assertEqual(sum(call[:2] == ["cloudformation", "validate-template"] for call in calls), 3)
        self.assertIsNone(saved)

    def test_deploys_in_dependency_order_without_academy_key(self):
        result, calls, saved = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        deploys = [call for call in calls if call[:2] == ["cloudformation", "deploy"]]
        self.assertEqual([call[call.index("--stack-name") + 1] for call in deploys],
                         ["cloudlink-network", "cloudlink-web", "cloudlink-probes"])
        self.assertIn("EnablePeerSsh=false", deploys[0])
        self.assertIn("ManagementCidr=203.0.113.10/32", deploys[0])
        self.assertIn("AvailabilityZone=us-east-1a", deploys[0])
        self.assertIn("RepositoryRef=personal-account-deploy", deploys[1])
        self.assertIn("SshKeyName=", deploys[1])
        self.assertFalse(any(call[:2] == ["ec2", "describe-key-pairs"] for call in calls))
        for call in deploys:
            self.assertIn("ManagedBy=cloudlink-personal", call)
            self.assertIn(f"OwnerAccount={ACCOUNT}", call)
            self.assertEqual(call[call.index("--region") + 1], "us-east-1")
        self.assertEqual(saved["account"], ACCOUNT)
        self.assertIn("http://127.0.0.1/", result.stdout)

    def test_explicit_administrator_key_and_peer_ssh(self):
        result, calls, _ = self.deploy("--key-name", "joel-key", "--enable-peer-ssh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("joel-key" in call and "describe-key-pairs" in call for call in calls))
        self.assertTrue(any("EnablePeerSsh=true" in call for call in calls))
        self.assertEqual(sum("SshKeyName=joel-key" in call for call in calls), 2)

    def test_bad_confirmation_prevents_writes(self):
        result, calls, saved = self.run_script("--management-cidr", "203.0.113.10/32",
                                               "--apply", "--confirm-account", "999999999999")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("deploy" in call for call in calls))
        self.assertIsNone(saved)

    def test_noninteractive_deployment_requires_confirmation(self):
        result, calls, saved = self.run_script("--management-cidr", "203.0.113.10/32", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirm-account", result.stderr)
        self.assertFalse(any("deploy" in call for call in calls))
        self.assertIsNone(saved)

    def test_invalid_input_stops_before_aws(self):
        result, calls, _ = self.run_script("--management-cidr", "0.0.0.0/0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_absent_instance_offering_prevents_deployment(self):
        result, calls, saved = self.deploy(mock_env={"MOCK_OFFERED": "0"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("t3.micro is not offered", result.stderr)
        self.assertFalse(any("deploy" in call for call in calls))
        self.assertIsNone(saved)

    def test_invalid_template_prevents_any_deployment(self):
        result, calls, _ = self.deploy(mock_env={"MOCK_INVALID_TEMPLATE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("deploy" in call for call in calls))

    def test_foreign_same_name_stack_is_not_adopted(self):
        result, calls, _ = self.deploy(mock_env={"MOCK_UNOWNED": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ownership tags", result.stderr)
        self.assertFalse(any("deploy" in call for call in calls))

    def test_academy_session_is_rejected(self):
        result, calls, _ = self.deploy(mock_env={"MOCK_CALLER": f"arn:aws:sts::{ACCOUNT}:assumed-role/voclabs/user"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not the Academy", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_recorded_other_account_blocks_deployment(self):
        result, calls, _ = self.deploy(manifest={"account": "999999999999", "region": "us-east-1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another account", result.stderr)
        self.assertFalse(any("deploy" in call for call in calls))

    def test_warns_about_legacy_public_probe_ips(self):
        result, _, _ = self.deploy(mock_env={"MOCK_PUBLIC_IPS": "198.51.100.10"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("still have public IP(s)", result.stderr)


if __name__ == "__main__":
    unittest.main()

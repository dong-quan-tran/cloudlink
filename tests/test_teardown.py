"""Deletion/account guards are tested without making AWS requests."""

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cloudlink_stacks.py"
spec = importlib.util.spec_from_file_location("cloudlink_stacks", MODULE_PATH)
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)
ACCOUNT = "123456789012"


class TeardownTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manifest = Path(self.temp.name) / "deployment.json"
        manifest_patch = patch.object(deployment, "MANIFEST", self.manifest)
        manifest_patch.start()
        self.addCleanup(manifest_patch.stop)
        self.calls = []
        self.deleted = set()
        self.stacks = [
            {"StackName": name, "StackId": f"arn:aws:cloudformation:us-east-1:{ACCOUNT}:stack/{name}/id",
             "StackStatus": "CREATE_COMPLETE", "Tags": [
                 {"Key": key, "Value": value} for key, value in
                 {**deployment.TAGS, "OwnerAccount": ACCOUNT}.items()]}
            for name in deployment.STACKS
        ]
        self.outside_import = False
        self.retained = False
        self.fail_delete = False

    def fake_aws(self, *args, **kwargs):
        self.calls.append(args)
        operation = args[:2]
        if operation == ("sts", "get-caller-identity"):
            return {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/joel"}
        if operation == ("cloudformation", "describe-stacks"):
            matches = [s for s in self.stacks if s["StackName"] == args[3]]
            return {"Stacks": matches} if matches else None
        if operation == ("cloudformation", "list-exports"):
            return {"Exports": [{"Name": "cloudlink-network-VpcId", "ExportingStackId": self.stacks[0]["StackId"]}]} if self.stacks else {"Exports": []}
        if operation == ("cloudformation", "list-imports"):
            return {"Imports": ["unrelated-app"] if self.outside_import else [s["StackName"] for s in self.stacks[1:]]}
        if operation == ("cloudformation", "list-stack-resources"):
            stack_id = args[3]
            if stack_id in self.deleted:
                return {"StackResourceSummaries": [{"LogicalResourceId": "Disk", "PhysicalResourceId": "vol-a", "ResourceStatus": "DELETE_SKIPPED"}]} if self.retained else {"StackResourceSummaries": []}
            resource = {"ResourceType": "AWS::EC2::VPC", "PhysicalResourceId": "vpc-a"} if "network/" in stack_id else {"ResourceType": "AWS::EC2::Instance", "PhysicalResourceId": "i-a"}
            return {"StackResourceSummaries": [resource]}
        if operation == ("ec2", "describe-instances"):
            if self.deleted:
                return {"Reservations": [{"Instances": [{"State": {"Name": "terminated"}}]}]}
            return {"Reservations": [{"Instances": [{"BlockDeviceMappings": [{"Ebs": {"VolumeId": "vol-a"}}]}]}]}
        if operation in (("ec2", "describe-volumes"), ("ec2", "describe-vpcs")):
            return None
        if operation == ("cloudformation", "delete-stack"):
            if self.fail_delete:
                raise deployment.SafetyError("Access denied")
            self.deleted.add(args[3])
            return None
        if args[:3] == ("cloudformation", "wait", "stack-delete-complete"):
            return None
        self.fail(f"Unexpected AWS request: {args}")

    def destroy(self, apply=False, confirmation=None):
        with patch.object(deployment, "aws", side_effect=self.fake_aws), contextlib.redirect_stdout(io.StringIO()) as out:
            deployment.destroy(apply, confirmation)
        return out.getvalue()

    def test_preview_never_sends_delete(self):
        self.assertIn("Preview only", self.destroy())
        self.assertFalse(self.deleted)

    def test_confirmation_deletes_in_reverse_order_and_waits(self):
        self.manifest.write_text(json.dumps({"account": ACCOUNT, "region": "us-east-1"}))
        self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        mutations = [call for call in self.calls if call[1] in ("delete-stack", "wait")]
        self.assertEqual([call[1] for call in mutations], ["delete-stack", "wait"] * 3)
        self.assertEqual([call[3] for call in mutations[::2]], [s["StackId"] for s in reversed(self.stacks)])
        self.assertTrue(any(call[:2] == ("ec2", "describe-volumes") for call in self.calls))
        self.assertTrue(any(call[:2] == ("ec2", "describe-vpcs") for call in self.calls))
        self.assertFalse(self.manifest.exists())

    def test_wrong_confirmation_never_deletes(self):
        with self.assertRaisesRegex(deployment.SafetyError, "Confirmation did not match"):
            self.destroy(True, "yes")
        self.assertFalse(self.deleted)

    def test_foreign_stack_is_never_deleted(self):
        self.stacks[0]["Tags"] = []
        with self.assertRaisesRegex(deployment.SafetyError, "ownership tags"):
            self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        self.assertFalse(self.deleted)

    def test_external_import_prevents_partial_teardown(self):
        self.outside_import = True
        with self.assertRaisesRegex(deployment.SafetyError, "unrelated-app"):
            self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        self.assertFalse(self.deleted)

    def test_busy_stack_prevents_deletion(self):
        self.stacks[1]["StackStatus"] = "UPDATE_IN_PROGRESS"
        with self.assertRaisesRegex(deployment.SafetyError, "is busy"):
            self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        self.assertFalse(self.deleted)

    def test_termination_protection_is_respected(self):
        self.stacks[1]["EnableTerminationProtection"] = True
        with self.assertRaisesRegex(deployment.SafetyError, "termination protection"):
            self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        self.assertFalse(self.deleted)

    def test_failed_delete_stops_before_next_stack(self):
        self.fail_delete = True
        with self.assertRaisesRegex(deployment.SafetyError, "Access denied"):
            self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        deletes = [call for call in self.calls if call[:2] == ("cloudformation", "delete-stack")]
        self.assertEqual(len(deletes), 1)

    def test_retained_resource_is_reported(self):
        self.retained = True
        with self.assertRaisesRegex(deployment.SafetyError, "vol-a"):
            self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        self.assertEqual(len(self.deleted), 1)

    def test_no_stacks_is_safe_to_repeat(self):
        self.stacks = []
        self.assertIn("No delete requests", self.destroy(True))
        self.assertFalse(self.deleted)

    def test_partially_created_deployment_can_be_removed(self):
        self.stacks = self.stacks[:1]
        self.stacks[0]["StackStatus"] = "ROLLBACK_COMPLETE"
        self.destroy(True, f"DESTROY {ACCOUNT} us-east-1")
        self.assertEqual(self.deleted, {self.stacks[0]["StackId"]})

    def test_cli_access_denial_is_not_treated_as_missing_stack(self):
        result = subprocess.CompletedProcess([], 1, "", "An error occurred (AccessDenied): denied")
        with patch.object(deployment.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(deployment.SafetyError, "AccessDenied"):
                deployment.aws("cloudformation", "describe-stacks", "--stack-name", "cloudlink-web")

    def test_cli_absence_is_recognized(self):
        result = subprocess.CompletedProcess([], 1, "", "An error occurred (ValidationError): Stack does not exist")
        with patch.object(deployment.subprocess, "run", return_value=result):
            self.assertIsNone(deployment.aws("cloudformation", "describe-stacks", "--stack-name", "cloudlink-web"))

    def test_remaining_disk_is_reported_instead_of_silently_ignored(self):
        with patch.object(deployment, "aws", return_value={"Volumes": [{"VolumeId": "vol-a"}]}), patch.object(deployment.time, "sleep"):
            with self.assertRaisesRegex(deployment.SafetyError, "may incur charges: vol-a"):
                deployment.verify_deleted([], ["vol-a"], [])


if __name__ == "__main__":
    unittest.main()

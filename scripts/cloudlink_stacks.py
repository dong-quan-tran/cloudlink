"""Account/ownership guards and teardown for the current three-stack deployment.

Uses the AWS CLI's current CloudShell identity. No API keys or account settings
are stored in the repository. This module never makes requests at import time.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REGION = "us-east-1"
STACKS = ("cloudlink-network", "cloudlink-web", "cloudlink-probes")
TAGS = {"Project": "CloudLink", "ManagedBy": "cloudlink-personal"}
MANIFEST = Path(__file__).resolve().parents[1] / ".cloudlink-deployment.json"


class SafetyError(RuntimeError):
    pass


def aws(*args: str, absent_codes: tuple[str, ...] = ()) -> Any:
    """An authorization/network failure must never be mistaken for absence."""
    command = ["aws", *args, "--region", REGION, "--no-cli-pager", "--output", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        error = result.stderr.strip()
        if any(f"({code})" in error for code in absent_codes):
            return None
        if (
            args[:2] == ("cloudformation", "describe-stacks")
            and "(ValidationError)" in error
            and "does not exist" in error
        ):
            return None
        raise SafetyError(error or f"AWS CLI failed: {' '.join(args[:2])}")
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SafetyError("AWS CLI returned invalid JSON; stopping.") from error


def identity() -> str:
    caller = aws("sts", "get-caller-identity")
    account = caller.get("Account", "")
    if not re.fullmatch(r"\d{12}", account):
        raise SafetyError("Could not verify the current AWS account.")
    if re.search(r":assumed-role/(?:voclabs|vocareum)/", caller.get("Arn", "")):
        raise SafetyError("This script is for your personal account, not the Academy sandbox.")
    if MANIFEST.exists():
        saved = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if saved.get("account") != account or saved.get("region") != REGION:
            raise SafetyError("This checkout records a deployment in another account/Region. Stop and review it.")
    return account


def stacks(account: str) -> list[dict[str, Any]]:
    found = []
    for name in STACKS:
        response = aws("cloudformation", "describe-stacks", "--stack-name", name)
        if response is None:
            continue
        if len(response.get("Stacks", [])) != 1:
            raise SafetyError(f"Unexpected stack response for {name}.")
        stack = response["Stacks"][0]
        tags = {tag["Key"]: tag["Value"] for tag in stack.get("Tags", [])}
        if any(tags.get(key) != value for key, value in {**TAGS, "OwnerAccount": account}.items()):
            raise SafetyError(f"Refusing to use {name}: its ownership tags do not match this deployment.")
        if "_IN_PROGRESS" in stack["StackStatus"]:
            raise SafetyError(f"{name} is busy ({stack['StackStatus']}); wait before running this script.")
        found.append(stack)
    return found


def record(account: str) -> None:
    if identity() != account:
        raise SafetyError("AWS account changed before deployment.")
    with MANIFEST.open("w", encoding="utf-8") as stream:
        json.dump({"account": account, "region": REGION, "stacks": list(STACKS)}, stream, indent=2)
        stream.write("\n")
    MANIFEST.chmod(0o600)


def check_external_imports(found: list[dict[str, Any]]) -> None:
    """Don't partially tear down a network another stack still imports."""
    allowed_names = {stack["StackName"] for stack in found}
    allowed_ids = {stack["StackId"] for stack in found}
    exports = aws("cloudformation", "list-exports").get("Exports", [])
    for export in exports:
        if export["ExportingStackId"] not in allowed_ids:
            continue
        imports = aws("cloudformation", "list-imports", "--export-name", export["Name"])
        outside = set(imports.get("Imports", [])) - allowed_names
        if outside:
            raise SafetyError(f"{export['Name']} is used by other stacks: {', '.join(sorted(outside))}.")


def inventory(found: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    instances, volumes, vpcs = [], [], []
    for stack in found:
        if stack.get("EnableTerminationProtection"):
            raise SafetyError(f"{stack['StackName']} has termination protection; review it manually.")
        resources = aws("cloudformation", "list-stack-resources", "--stack-name", stack["StackId"])
        for resource in resources.get("StackResourceSummaries", []):
            resource_id = resource.get("PhysicalResourceId", "")
            if resource.get("ResourceStatus") == "DELETE_COMPLETE":
                continue
            if resource["ResourceType"] == "AWS::EC2::VPC" and resource_id.startswith("vpc-"):
                vpcs.append(resource_id)
            if resource["ResourceType"] != "AWS::EC2::Instance" or not resource_id.startswith("i-"):
                continue
            instances.append(resource_id)
            result = aws("ec2", "describe-instances", "--instance-ids", resource_id,
                         absent_codes=("InvalidInstanceID.NotFound",))
            for reservation in (result or {}).get("Reservations", []):
                for instance in reservation["Instances"]:
                    volumes.extend(mapping["Ebs"]["VolumeId"] for mapping in instance.get("BlockDeviceMappings", [])
                                   if "Ebs" in mapping)
    return sorted(set(instances)), sorted(set(volumes)), sorted(set(vpcs))


def verify_deleted(instance_ids: list[str], volume_ids: list[str], vpc_ids: list[str]) -> None:
    for instance_id in instance_ids:
        result = aws("ec2", "describe-instances", "--instance-ids", instance_id,
                     absent_codes=("InvalidInstanceID.NotFound",))
        for reservation in (result or {}).get("Reservations", []):
            for instance in reservation["Instances"]:
                if instance["State"]["Name"] != "terminated":
                    raise SafetyError(f"Instance still exists: {instance_id}.")
    # EBS deletion can trail instance termination briefly. Never delete an
    # arbitrary volume by tag; only verify IDs collected from the owned stacks.
    for volume_id in volume_ids:
        for attempt in range(10):
            result = aws("ec2", "describe-volumes", "--volume-ids", volume_id,
                         absent_codes=("InvalidVolume.NotFound",))
            if result is None or not result.get("Volumes"):
                break
            if attempt == 9:
                raise SafetyError(f"Volume remains and may incur charges: {volume_id}.")
            time.sleep(2)
    for vpc_id in vpc_ids:
        result = aws("ec2", "describe-vpcs", "--vpc-ids", vpc_id,
                     absent_codes=("InvalidVpcID.NotFound",))
        if result and result.get("Vpcs"):
            raise SafetyError(f"VPC remains: {vpc_id}.")


def destroy(apply: bool, confirmation: str | None) -> None:
    account = identity()
    found = stacks(account)
    print(f"AWS account: {account}; Region: {REGION}")
    print("Targets: cloudlink-probes -> cloudlink-web -> cloudlink-network")
    if not found:
        print("None of these stacks exist. No delete requests sent.")
        return
    check_external_imports(found)
    instance_ids, volume_ids, vpc_ids = inventory(found)
    for stack in reversed(found):
        print(f"  {stack['StackName']}: {stack['StackStatus']}")
    print(f"Tracked resources: {len(instance_ids)} EC2 instances, {len(volume_ids)} volumes, {len(vpc_ids)} VPCs.")
    print("This permanently deletes the application, local test history, and the listed stacks' resources.")
    if not apply:
        print("Preview only. Run bash scripts/teardown.sh --apply to request deletion.")
        return
    phrase = f"DESTROY {account} {REGION}"
    if confirmation is None:
        if not sys.stdin.isatty():
            raise SafetyError(f'Interactive confirmation required, or pass --confirm "{phrase}".')
        confirmation = input(f"Type {phrase} to continue: ").strip()
    if confirmation != phrase:
        raise SafetyError("Confirmation did not match. Nothing deleted.")
    # Re-check identity and ownership immediately before the first deletion.
    if identity() != account:
        raise SafetyError("AWS account changed. Nothing deleted.")
    current = stacks(account)
    if {s["StackId"] for s in current} != {s["StackId"] for s in found}:
        raise SafetyError("Stack inventory changed. Run the preview again.")
    for stack in reversed(current):
        print(f"Deleting {stack['StackName']}...", flush=True)
        aws("cloudformation", "delete-stack", "--stack-name", stack["StackId"])
        aws("cloudformation", "wait", "stack-delete-complete", "--stack-name", stack["StackId"])
        result = aws("cloudformation", "list-stack-resources", "--stack-name", stack["StackId"])
        retained = [r.get("PhysicalResourceId") or r["LogicalResourceId"]
                    for r in result.get("StackResourceSummaries", []) if r["ResourceStatus"] == "DELETE_SKIPPED"]
        if retained:
            raise SafetyError(f"Resources retained by {stack['StackName']}: {', '.join(retained)}.")
    verify_deleted(instance_ids, volume_ids, vpc_ids)
    MANIFEST.unlink(missing_ok=True)
    print("Target stacks deleted; tracked instances, disks, and VPCs were checked.")
    print("Unrelated AWS resources were not touched. This is not an account-wide billing audit.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("account", "record", "destroy"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--account")
    args = parser.parse_args()
    try:
        if args.action == "account":
            account = identity()
            stacks(account)
            print(account)
        elif args.action == "record":
            if not args.account:
                raise SafetyError("The verified account is required.")
            record(args.account)
        else:
            destroy(args.apply, args.confirm)
    except (SafetyError, OSError, ValueError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

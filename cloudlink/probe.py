"""Discover lab nodes and run bounded network checks from a selected source."""

from __future__ import annotations

import ipaddress
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEST_PORTS = {"http": 80, "https": 443, "ssh": 22}
TEST_TYPES = frozenset(("ping", "tcp", *TEST_PORTS))

# Runs on the selected source instance. Only validated IP addresses, a fixed test type,
# and a validated port are passed as arguments; no user-provided command is executed.
REMOTE_PROBE = """import http.client
import json
import socket
import ssl
import sys

address, test_type, port_text = sys.argv[1:4]
port = int(port_text)
try:
    if test_type in ("http", "https"):
        if test_type == "https":
            # This is a connectivity test against an IP, not certificate verification.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            connection = http.client.HTTPSConnection(address, port, timeout=5, context=context)
        else:
            connection = http.client.HTTPConnection(address, port, timeout=5)
        try:
            connection.request("GET", "/", headers={"Connection": "close"})
            response = connection.getresponse()
            result = {"ok": True, "detail": "HTTP %s %s" % (response.status, response.reason),
                      "status_code": response.status}
            if test_type == "https":
                result["detail"] += " (TLS certificate not verified)"
        finally:
            connection.close()
    elif test_type == "ssh":
        with socket.create_connection((address, port), timeout=5) as connection:
            connection.settimeout(5)
            banner = connection.recv(256).decode("ascii", "replace").splitlines()
        if banner and banner[0].startswith("SSH-"):
            result = {"ok": True, "detail": "SSH server banner received; login not attempted"}
        else:
            result = {"ok": False, "detail": "Port 22 answered, but no SSH banner was received"}
    elif test_type == "tcp":
        with socket.create_connection((address, port), timeout=5):
            pass
        result = {"ok": True, "detail": "TCP connection established on port %s" % port}
    else:
        result = {"ok": False, "detail": "Unsupported test type"}
except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as error:
    result = {"ok": False, "detail": "%s: %s" % (type(error).__name__, error)}
print(json.dumps(result))
"""


@dataclass(frozen=True)
class Node:
    instance_id: str
    name: str
    private_ip: str | None
    public_ip: str | None
    vpc_id: str
    subnet_id: str
    availability_zone: str
    security_group_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_nodes(ec2_client: Any) -> list[Node]:
    """List running CloudLink probe nodes, not unrelated sandbox instances."""
    filters = [
        {"Name": "instance-state-name", "Values": ["running"]},
        {"Name": "tag:Project", "Values": ["CloudLink"]},
        {"Name": "tag:CloudLinkRole", "Values": ["Probe"]},
    ]
    nodes: list[Node] = []
    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate(Filters=filters):
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                nodes.append(
                    Node(
                        instance_id=instance["InstanceId"],
                        name=tags.get("Name", instance["InstanceId"]),
                        private_ip=instance.get("PrivateIpAddress"),
                        public_ip=instance.get("PublicIpAddress"),
                        vpc_id=instance.get("VpcId", ""),
                        subnet_id=instance.get("SubnetId", ""),
                        availability_zone=instance["Placement"]["AvailabilityZone"],
                        security_group_ids=tuple(
                            group["GroupId"] for group in instance.get("SecurityGroups", [])
                        ),
                    )
                )
    return sorted(nodes, key=lambda node: (node.name, node.instance_id))


def load_inventory(path: Path) -> list[Node]:
    """Read the CloudFormation lab inventory without requiring AWS API credentials."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("The CloudLink inventory must contain a list of nodes.")
    nodes = []
    for item in data:
        nodes.append(
            Node(
                instance_id=item["instance_id"],
                name=item["name"],
                private_ip=item.get("private_ip"),
                public_ip=item.get("public_ip"),
                vpc_id=item.get("vpc_id", ""),
                subnet_id=item.get("subnet_id", ""),
                availability_zone=item.get("availability_zone", ""),
                security_group_ids=tuple(item.get("security_group_ids", [])),
            )
        )
    return sorted(nodes, key=lambda node: (node.name, node.instance_id))


def _run_ssh(source_host: str, key_path: Path, remote_command: list[str], input_text: str | None = None) -> dict[str, Any]:
    host = str(ipaddress.ip_address(source_host))
    command = [
        "ssh",
        "-i",
        str(key_path),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "NumberOfPasswordPrompts=0",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"ec2-user@{host}",
        *remote_command,
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, input=input_text, capture_output=True, text=True, timeout=16, check=False
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-1500:],
            "stderr": completed.stderr[-1500:],
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "SSH or the remote test timed out.",
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }


def summarize(test_type: str, check: dict[str, Any], port: int | None) -> tuple[str, str]:
    """Describe this test only; a failed probe does not prove the route is missing."""
    if check.get("management_error"):
        return (
            "Source unavailable",
            "CloudLink could not run a test on the source. Check its separate management SSH path, "
            "authorized key, and instance health. This says nothing about A-to-B reachability.",
        )
    if check.get("incomplete"):
        return ("Test incomplete", "The source did not return a usable result. Check its Python installation and retry.")
    if check["ok"]:
        if test_type == "ping":
            return ("ICMP reply received", "Ping worked. This does not establish that any TCP service is reachable.")
        if test_type == "tcp":
            return ("TCP connected", f"A TCP connection to port {port} worked. This does not verify an application protocol.")
        if test_type == "ssh":
            return ("SSH service responded", "An SSH banner was received; authentication was not attempted.")
        if test_type == "https":
            return ("HTTPS responded", "The server answered an HTTPS GET. Its TLS certificate was not validated in this connectivity test.")
        return ("HTTP responded", "The server answered an HTTP GET, even if its status code indicates an application error.")
    if test_type == "ping":
        return ("No ICMP reply", "ICMP may be blocked even when a TCP service works. Check ICMP rules, host firewall, and routing.")
    if test_type == "ssh":
        return ("SSH check failed", "Check port 22 rules and whether an SSH server is listening on the destination.")
    if test_type in ("http", "https"):
        return (f"{test_type.upper()} check failed", f"Check port {port} rules, the web service, and its host firewall. A failed service check alone does not prove a missing route.")
    return ("TCP connection failed", f"Check port {port} rules, the listening service, and the host firewall. A failed port check alone does not prove a missing route.")


def run_probe(
    session: Any,
    source: Node,
    destination: Node,
    address_type: str = "private",
    existing_key_path: str | None = None,
    source_address_type: str = "public",
    test_type: str = "ping",
    port: int | None = None,
) -> dict[str, Any]:
    """Connect to the source over a separate management path, then run one chosen test."""
    if source.instance_id == destination.instance_id:
        raise ValueError("Choose two different instances.")
    if address_type not in ("private", "public"):
        raise ValueError("Address type must be private or public.")
    if source_address_type not in ("private", "public"):
        raise ValueError("Source address type must be private or public.")
    if test_type not in TEST_TYPES:
        raise ValueError("Choose ping, HTTP, HTTPS, SSH, or a custom TCP port.")
    if test_type == "tcp":
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Custom TCP port must be between 1 and 65535.")
    elif port is not None:
        raise ValueError("A custom port is only used for the TCP test.")
    else:
        port = TEST_PORTS.get(test_type)
    destination_address = (
        destination.private_ip if address_type == "private" else destination.public_ip
    )
    if not destination_address:
        raise ValueError(f"The destination has no {address_type} IP address.")
    destination_address = str(ipaddress.ip_address(destination_address))
    source_address = source.private_ip if source_address_type == "private" else source.public_ip
    if not source_address:
        raise ValueError(f"The selected source has no {source_address_type} IP address.")
    source_address = str(ipaddress.ip_address(source_address))
    if not shutil.which("ssh"):
        raise RuntimeError("OpenSSH is required on the CloudLink host.")

    def test_with_key(key_path: Path) -> dict[str, Any]:
        if test_type == "ping":
            response = _run_ssh(source_address, key_path, ["ping", "-c", "2", "-W", "2", destination_address])
            if response["exit_code"] == 255:
                return {"ok": False, "detail": response["stderr"] or "Management SSH failed", "management_error": True}
            if response["exit_code"] is None or response["exit_code"] not in (0, 1):
                return {"ok": False, "detail": response["stderr"] or "Ping could not run", "incomplete": True}
            return {
                "ok": response["ok"],
                "detail": "At least one ICMP reply received" if response["ok"] else "No ICMP reply received",
                "output": response["stdout"],
            }
        response = _run_ssh(
            source_address, key_path,
            ["python3", "-", destination_address, test_type, str(port)],
            input_text=REMOTE_PROBE,
        )
        if response["exit_code"] == 255:
            return {"ok": False, "detail": response["stderr"] or "Management SSH failed", "management_error": True}
        if not response["ok"]:
            return {"ok": False, "detail": response["stderr"] or "Remote check could not run", "incomplete": True}
        try:
            result = json.loads(response["stdout"].strip().splitlines()[-1])
            if type(result.get("ok")) is not bool or not isinstance(result.get("detail"), str):
                raise ValueError("Missing test result fields")
            return result
        except (IndexError, ValueError, AttributeError) as error:
            return {"ok": False, "detail": f"Invalid response from source: {error}", "incomplete": True}

    if existing_key_path:
        key_path = Path(existing_key_path).expanduser()
        if not key_path.is_file():
            raise ValueError("The configured SSH key file does not exist.")
        check = test_with_key(key_path)
    else:
        if session is None:
            raise ValueError("AWS credentials or a configured management SSH key are required.")
        if not shutil.which("ssh-keygen"):
            raise RuntimeError("OpenSSH key generation is required on the CloudLink host.")
        with tempfile.TemporaryDirectory(prefix="cloudlink-key-") as key_dir:
            key_path = Path(key_dir) / "id_ed25519"
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            public_key = key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()
            response = session.client("ec2-instance-connect").send_ssh_public_key(
                InstanceId=source.instance_id,
                InstanceOSUser="ec2-user",
                SSHPublicKey=public_key,
                AvailabilityZone=source.availability_zone,
            )
            if not response.get("Success"):
                raise RuntimeError("AWS did not accept the temporary SSH key.")
            check = test_with_key(key_path)

    summary, recommendation = summarize(test_type, check, port)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_id": source.instance_id,
        "source_name": source.name,
        "destination_id": destination.instance_id,
        "destination_name": destination.name,
        "address_type": address_type,
        "tested_address": destination_address,
        "test_type": test_type,
        "port": port,
        "check": check,
        "summary": summary,
        "recommendation": recommendation,
    }

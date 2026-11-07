"""Inspect security groups and subnet ACLs for a direct private IPv4 path."""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .probe import Node

POLICY_LABELS = (
    ("source_sg", "Source security groups · outbound"),
    ("destination_sg", "Destination security groups · inbound"),
    ("source_acl", "Source subnet ACL"),
    ("destination_acl", "Destination subnet ACL"),
)
EPHEMERAL_PORTS = (1024, 65535)


def finding(key: str, label: str, status: str, detail: str, **evidence: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "detail": detail, **evidence}


def describe(ec2: Any, operation: str, field: str, filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    request: dict[str, Any] = {"Filters": filters}
    while True:
        page = getattr(ec2, operation)(**request)
        result.extend(page.get(field, []))
        if not page.get("NextToken"):
            return result
        request["NextToken"] = page["NextToken"]


def api_error(error: Exception) -> str:
    if isinstance(error, ClientError):
        code = error.response["Error"]["Code"]
        return f"AWS returned {code}. Check the app's EC2 read permissions and retry."
    return "AWS network information is temporarily unavailable. Retry this check."


def contains(cidr: str, address: str) -> bool:
    return ip_address(address) in ip_network(cidr)


def protocol(value: str) -> str:
    return {"tcp": "6", "udp": "17", "icmp": "1"}.get(value, value)


def rule_label(proto: str, low: int, high: int) -> str:
    if proto == "-1":
        return "All traffic"
    if proto in ("6", "17"):
        ports = str(low) if low == high else f"{low}–{high}"
        return f"{'TCP' if proto == '6' else 'UDP'} {ports}"
    if proto == "1":
        return "ICMP (all types)" if low == -1 else f"ICMP type {low}, code {'any' if high == -1 else high}"
    return f"Protocol {proto}"


def group_check(key: str, label: str, groups: dict[str, Any], node: Node, peer: Node,
                outbound: bool, test_type: str, port: int | None, group_refs: bool) -> dict[str, Any]:
    evidence = {"resources": list(node.security_group_ids)}
    if not node.security_group_ids or any(group not in groups for group in node.security_group_ids):
        return finding(key, label, "unknown", "Could not read all security groups attached to this instance.", **evidence)
    rules, unresolved = [], False
    for group_id in node.security_group_ids:
        for rule in groups[group_id].get("IpPermissionsEgress" if outbound else "IpPermissions", []):
            proto = protocol(rule["IpProtocol"])
            low, high = rule.get("FromPort", -1), rule.get("ToPort", -1)
            if test_type == "ping" and proto != "-1" and not (proto == "1" and low in (-1, 8) and high in (-1, 0)):
                continue
            if port is not None and proto != "-1" and not (proto == "6" and low <= port <= high):
                continue
            matches = [item["CidrIp"] for item in rule.get("IpRanges", []) if contains(item["CidrIp"], peer.private_ip)]
            refs = [item["GroupId"] for item in rule.get("UserIdGroupPairs", [])
                    if item.get("GroupId") in peer.security_group_ids]
            if group_refs:
                matches.extend(refs)
            elif refs:
                unresolved = True
            prefixes = [item["PrefixListId"] for item in rule.get("PrefixListIds", [])]
            if prefixes:
                unresolved = True
            if matches or refs or prefixes:
                targets = matches + [f"{ref} (unverified)" for ref in refs if not group_refs]
                targets += [f"{prefix} (unresolved)" for prefix in prefixes]
                rules.append((bool(matches), f"{group_id} · {rule_label(proto, low, high)} · {', '.join(targets)}"))
    evidence["rules"] = [description for _, description in rules]
    if any(matched for matched, _ in rules):
        if test_type == "overview":
            return finding(key, label, "review", "These allow rules match the peer. Select a traffic type to check whether a particular flow is allowed.", **evidence)
        return finding(key, label, "pass", "At least one attached group allows the request. Security groups allow its reply automatically.", **evidence)
    if unresolved:
        return finding(key, label, "unknown", "A prefix list or security group reference could not be verified for this path.", **evidence)
    return finding(key, label, "fail", "No attached group has an allow rule matching the peer and selected traffic." if test_type != "overview"
                   else "No attached group has an allow rule matching the peer’s private address or security groups.", **evidence)


def acl_check(key: str, label: str, acl: dict[str, Any], peer_ip: str, source: bool,
              test_type: str, port: int | None) -> dict[str, Any]:
    entries = sorted((entry for entry in acl.get("Entries", [])
                      if entry.get("CidrBlock") and contains(entry["CidrBlock"], peer_ip)),
                     key=lambda entry: entry["RuleNumber"])
    evidence: dict[str, Any] = {"resources": [acl["NetworkAclId"]]}
    outcomes, lines = [], []
    for reply in (False, True):
        outbound = source != reply
        direction = f"{'Reply' if reply else 'Request'} {'outbound' if outbound else 'inbound'}"
        rules = [entry for entry in entries if entry["Egress"] == outbound]
        if test_type == "overview":
            # An all-protocol match shadows every later entry for this peer.
            applicable = []
            for entry in rules:
                proto = entry["Protocol"]
                bounds = entry.get("PortRange", {})
                icmp = entry.get("IcmpTypeCode", {})
                low, high = (icmp.get("Type", -1), icmp.get("Code", -1)) if proto == "1" else (bounds.get("From", 0), bounds.get("To", 65535))
                lines.append(f"{direction} · #{entry['RuleNumber']} {entry['RuleAction']} · {rule_label(proto, low, high)} · {entry['CidrBlock']}")
                applicable.append(entry)
                if proto == "-1":
                    break
            if not any(entry["RuleAction"] == "allow" for entry in applicable):
                outcomes.append("fail")
            continue

        if test_type == "ping":
            icmp_type = 0 if reply else 8
            matches = [entry for entry in rules if entry["Protocol"] == "-1" or (
                entry["Protocol"] == "1" and entry.get("IcmpTypeCode", {}).get("Type", -1) in (-1, icmp_type)
                and entry.get("IcmpTypeCode", {}).get("Code", -1) in (-1, 0))]
            winners = [matches[0]] if matches else [None]
        else:
            # Only rule boundaries can change which ordered rule wins. Sample each interval.
            low, high = EPHEMERAL_PORTS if reply else (port, port)
            matches = [entry for entry in rules if entry["Protocol"] in ("-1", "6")]
            ranges = [(entry, entry.get("PortRange", {}).get("From", 0), entry.get("PortRange", {}).get("To", 65535))
                      if entry["Protocol"] == "6" else (entry, 0, 65535) for entry in matches]
            starts = {low} | {point for _, first, last in ranges for point in (first, last + 1) if low < point <= high}
            winners = [next((entry for entry, first, last in ranges if first <= point <= last), None)
                       for point in sorted(starts)]
        allowed = [entry is not None and entry["RuleAction"] == "allow" for entry in winners]
        outcome = "pass" if all(allowed) else "unknown" if any(allowed) else "fail"
        outcomes.append(outcome)
        matched = dict.fromkeys(f"#{entry['RuleNumber']} {entry['RuleAction']}" if entry else "implicit deny" for entry in winners)
        lines.append(f"{direction} · {', '.join(matched)}")

    evidence["rules"] = lines
    if test_type == "overview":
        if "fail" in outcomes:
            return finding(key, label, "fail", "No applicable allow rule for this peer in at least one direction. Review the request and reply rules below.", **evidence)
        return finding(key, label, "review", "These IPv4 rules match the peer address. The lowest matching rule number wins in each direction.", **evidence)
    status = "fail" if "fail" in outcomes else "unknown" if "unknown" in outcomes else "pass"
    detail = {"pass": "Matching rules allow the request and reply through this subnet.",
              "fail": "The request or reply is denied by this subnet’s ACL.",
              "unknown": "Only part of the possible TCP reply port range (1024–65535) is allowed. The result depends on the client port."}[status]
    return finding(key, label, status, detail, **evidence)


def inspect_policy(ec2: Any, source: Node, destination: Node, test_type: str, port: int | None,
                   group_refs: bool) -> list[dict[str, Any]]:
    try:
        ids = sorted(set(source.security_group_ids) | set(destination.security_group_ids))
        groups = describe(ec2, "describe_security_groups", "SecurityGroups", [{"Name": "group-id", "Values": ids}]) if ids else []
        by_id = {group["GroupId"]: group for group in groups}
        checks = [group_check(*POLICY_LABELS[0], by_id, source, destination, True, test_type, port, group_refs),
                  group_check(*POLICY_LABELS[1], by_id, destination, source, False, test_type, port, group_refs)]
    except (ClientError, BotoCoreError) as error:
        checks = [finding(*item, "unknown", api_error(error)) for item in POLICY_LABELS[:2]]

    if source.subnet_id == destination.subnet_id:
        return checks + [finding(*item, "not_required", "Traffic within the same subnet does not cross a subnet ACL.")
                         for item in POLICY_LABELS[2:]]
    try:
        acls = describe(ec2, "describe_network_acls", "NetworkAcls", [
            {"Name": "association.subnet-id", "Values": [source.subnet_id, destination.subnet_id]},
        ])
        for item, node, peer, is_source in ((POLICY_LABELS[2], source, destination, True),
                                            (POLICY_LABELS[3], destination, source, False)):
            matches = [acl for acl in acls if any(link.get("SubnetId") == node.subnet_id for link in acl.get("Associations", []))]
            checks.append(acl_check(*item, matches[0], peer.private_ip, is_source, test_type, port) if len(matches) == 1
                          else finding(*item, "unknown", "Could not identify the ACL associated with this subnet."))
    except (ClientError, BotoCoreError) as error:
        checks.extend(finding(*item, "unknown", api_error(error)) for item in POLICY_LABELS[2:])
    return checks

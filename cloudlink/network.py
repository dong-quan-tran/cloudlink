"""Read-only IPv4 configuration inspection for local and directly peered VPC paths."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Any

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .policy import POLICY_LABELS, api_error, describe, finding, inspect_policy, resource_name
from .probe import TEST_PORTS, Node

SCOPE = "Private IPv4 in one AWS Region, within a VPC or through direct VPC peering. Configuration cannot confirm that the destination service is listening or that its host firewall allows traffic."
TARGETS = ("GatewayId", "VpcPeeringConnectionId", "TransitGatewayId", "NatGatewayId",
           "NetworkInterfaceId", "InstanceId", "VpcEndpointId", "LocalGatewayId",
           "CarrierGatewayId", "CoreNetworkArn", "OdbNetworkArn")
TARGET_NAMES = {"pcx-": "VPC peering connection", "igw-": "Internet gateway", "tgw-": "Transit gateway",
                "nat-": "NAT gateway", "eni-": "Network interface", "vgw-": "Virtual private gateway",
                "vpce-": "VPC endpoint"}


def route_snapshot(ec2: Any, node: Node, address: str) -> dict[str, Any]:
    """Use the explicit subnet association first; otherwise use the VPC main table."""
    try:
        tables = describe(ec2, "describe_route_tables", "RouteTables", [
            {"Name": "vpc-id", "Values": [node.vpc_id]},
            {"Name": "association.subnet-id", "Values": [node.subnet_id]},
        ])
        association = "explicit subnet association"
        if not tables:
            tables = describe(ec2, "describe_route_tables", "RouteTables", [
                {"Name": "vpc-id", "Values": [node.vpc_id]},
                {"Name": "association.main", "Values": ["true"]},
            ])
            association = "VPC main table"
        if len(tables) != 1:
            return {"error": "Could not identify a single effective route table for this subnet."}
        table = tables[0]
        name = resource_name(table, "VPC main route table" if association == "VPC main table" else "Subnet route table")
        evidence = {"table_id": table["RouteTableId"], "table_name": name, "association": association,
                    "subnet_id": node.subnet_id, "destination_ip": address}
        for item in table.get("Associations", []):
            if item.get("SubnetId") == node.subnet_id and item.get("AssociationState", {}).get("State", "associated") != "associated":
                return {**evidence, "error": "The subnet's route-table association is changing. Retry when it is stable."}
        routes = table.get("Routes", [])
        if any(route.get("DestinationPrefixListId") for route in routes):
            return {**evidence, "error": "This table includes prefix-list destinations, which this version cannot resolve. The winning route could not be verified."}
        matches = []
        for route in routes:
            cidr = route.get("DestinationCidrBlock")
            if cidr and ipaddress.ip_address(address) in ipaddress.ip_network(cidr):
                # A static route wins over a propagated route with the same CIDR.
                priority = (ipaddress.ip_network(cidr).prefixlen, route.get("Origin") != "EnableVgwRoutePropagation")
                matches.append((priority, route))
        if not matches:
            return {**evidence, "route": None}
        priority = max(item[0] for item in matches)
        winners = [route for rank, route in matches if rank == priority]
        if len(winners) != 1:
            return {**evidence, "error": "Several routes have the same priority; this version cannot determine the selected target."}
        route = winners[0]
        target = next((route[key] for key in TARGETS if route.get(key)), "unknown")
        return {**evidence, "route": route, "cidr": route["DestinationCidrBlock"],
                "target": target, "route_state": route.get("State", "unknown")}
    except (ClientError, BotoCoreError) as error:
        return {"error": api_error(error)}


def peering_check(ec2: Any, source: Node, destination: Node, snapshots: list[dict[str, Any]]) -> tuple[dict[str, Any], set[str] | None]:
    if source.vpc_id == destination.vpc_id:
        return finding("peering", "VPC peering", "not_required", "Both instances are in the same VPC; no peering connection is needed.",
                       source_vpc=source.vpc_id, destination_vpc=destination.vpc_id), set()
    try:
        vpcs = [source.vpc_id, destination.vpc_id]
        peers = describe(ec2, "describe_vpc_peering_connections", "VpcPeeringConnections", [
            {"Name": "requester-vpc-info.vpc-id", "Values": vpcs},
            {"Name": "accepter-vpc-info.vpc-id", "Values": vpcs},
        ])
        peers = [peer for peer in peers if {
            peer.get("RequesterVpcInfo", {}).get("VpcId"), peer.get("AccepterVpcInfo", {}).get("VpcId")
        } == set(vpcs)]
        active = {peer["VpcPeeringConnectionId"] for peer in peers if peer.get("Status", {}).get("Code") == "active"}
        evidence = {"source_vpc": source.vpc_id, "destination_vpc": destination.vpc_id,
                    "connections": [{"id": peer["VpcPeeringConnectionId"],
                                     "name": resource_name(peer, "VPC peering connection"),
                                     "state": peer.get("Status", {}).get("Code", "unknown")} for peer in peers]}
        if active:
            return finding("peering", "VPC peering", "pass", "An active direct peering connection links the two VPCs. Routes still need to use it.", **evidence), active
        # An appliance/TGW/prefix-list path might work without direct peering.
        unsupported = any(snapshot.get("error") or (snapshot.get("route") and
                          snapshot.get("target") not in ("local", "unknown") and
                          not snapshot.get("route", {}).get("VpcPeeringConnectionId") and
                          not str(snapshot.get("target", "")).startswith("igw-")) for snapshot in snapshots)
        status = "unknown" if unsupported else "fail"
        detail = ("No active direct peering was found. An alternative routing path could not be assessed by this version."
                  if unsupported else "No active direct peering links these VPCs. Establish or accept their direct peering connection; peering through a third VPC is not transitive.")
        return finding("peering", "VPC peering", status, detail, **evidence), active
    except (ClientError, BotoCoreError) as error:
        return finding("peering", "VPC peering", "unknown", api_error(error)), None


def route_check(key: str, label: str, snapshot: dict[str, Any], same_vpc: bool,
                active_peers: set[str] | None, peer_names: dict[str, str]) -> dict[str, Any]:
    evidence = {key: value for key, value in snapshot.items() if key not in ("error", "route")}
    if snapshot.get("error"):
        return finding(key, label, "unknown", snapshot["error"], **evidence)
    route = snapshot.get("route")
    if route is None:
        return finding(key, label, "fail", f"No IPv4 route in {snapshot['table_name']} matches {snapshot['destination_ip']}. Add the required route for this direction.", **evidence)
    target = snapshot["target"]
    target_name = peer_names.get(target) or next((name for prefix, name in TARGET_NAMES.items()
                                                if target.startswith(prefix)), "Local VPC" if target == "local" else "Other route target")
    evidence["target_name"] = target_name
    if route.get("State") == "blackhole":
        return finding(key, label, "fail", f"The most-specific route ({snapshot['cidr']} → {target_name}) is a blackhole. Restore its target or replace the route; a less-specific route will not take over.", **evidence)
    if route.get("State") != "active":
        return finding(key, label, "unknown", "The selected route is not reported as active. Retry after its state is stable.", **evidence)
    if target == "local":
        status = "pass" if same_vpc else "fail"
        detail = ("The selected active local route covers the destination inside this VPC." if same_vpc else
                  "The selected local route stays inside this VPC and cannot reach the other VPC. Check overlapping addresses and the route to the peer.")
    elif route.get("VpcPeeringConnectionId"):
        if active_peers is None:
            status, detail = "unknown", "The route is active, but access to peering information was unavailable, so its target could not be verified."
        elif not same_vpc and target in active_peers:
            status, detail = "pass", "The selected active route uses a direct peering connection between these VPCs."
        else:
            status, detail = "fail", "The selected route does not use an active direct peering connection for these two VPCs. Correct its peering target."
    elif str(target).startswith("igw-"):
        status, detail = "fail", "The selected route points to an internet gateway, which does not provide this private-IP path. Add the required local or direct-peering route."
    else:
        status, detail = "unknown", f"The selected route uses this target: {target_name}. Appliance, NAT, VPN, and transit-gateway paths are outside this version's analysis."
    return finding(key, label, status, detail, **evidence)


def analyze_network(session: Any, source: Node, destination: Node, address_type: str = "private",
                    test_type: str | None = None, port: int | None = None) -> dict[str, Any]:
    labels = (("peering", "VPC peering"), ("forward_route", "Source → destination route"),
              ("return_route", "Destination → source route"))
    all_labels = labels + POLICY_LABELS if test_type else labels
    reason = None
    if address_type != "private":
        reason = "Configuration analysis currently supports private IPv4 destinations only."
    elif not session:
        reason = "AWS access is required to read network configuration."
    elif not all((source.vpc_id, destination.vpc_id, source.subnet_id, destination.subnet_id)):
        reason = "VPC and subnet metadata are required for both instances."
    try:
        if not source.private_ip or not destination.private_ip or any(
            ipaddress.ip_address(address).version != 4 for address in (source.private_ip, destination.private_ip)
        ):
            reason = "Both instances need valid private IPv4 addresses for configuration analysis."
    except ValueError:
        reason = "Both instances need valid private IPv4 addresses for configuration analysis."
    if reason:
        checks = [finding(key, label, "unknown", reason) for key, label in all_labels]
    else:
        try:
            ec2 = session.client("ec2", config=Config(connect_timeout=3, read_timeout=5,
                                                     retries={"mode": "standard", "total_max_attempts": 2}))
        except (ClientError, BotoCoreError) as error:
            return {"status": "unknown", "summary": api_error(error), "scope": SCOPE,
                    "checks": [finding(key, label, "unknown", api_error(error)) for key, label in all_labels]}
        same_vpc = source.vpc_id == destination.vpc_id
        group_refs = True
        if same_vpc and source.subnet_id == destination.subnet_id:
            checks = [finding("peering", "VPC peering", "not_required", "Both instances are in the same VPC; no peering is needed.")]
            checks += [finding(key, label, "not_required", "Both instances share a subnet. A route-table lookup does not establish whether their within-subnet traffic can pass.") for key, label in labels[1:]]
        else:
            snapshots = [route_snapshot(ec2, source, destination.private_ip), route_snapshot(ec2, destination, source.private_ip)]
            peer, active = peering_check(ec2, source, destination, snapshots)
            peer_names = {connection["id"]: connection["name"] for connection in peer.get("connections", [])}
            checks = [peer, route_check(*labels[1], snapshots[0], same_vpc, active, peer_names),
                      route_check(*labels[2], snapshots[1], same_vpc, active, peer_names)]
            group_refs = all(check["status"] == "pass" for check in checks[1:])
        if test_type:
            checks.extend(inspect_policy(ec2, source, destination, test_type, TEST_PORTS.get(test_type, port), group_refs))
    status = "fail" if any(check["status"] == "fail" for check in checks) else (
        "unknown" if any(check["status"] == "unknown" for check in checks) else
        "review" if any(check["status"] == "review" for check in checks) else "pass")
    summary = {"pass": "The inspected AWS configuration allows the selected traffic." if test_type else "The inspected routing configuration looks correct.",
               "fail": "The inspected configuration has a blocker for this path.",
               "review": "Routing and firewall rules are shown below. Select a traffic type for a rule-by-rule verdict.",
               "unknown": "The inspected configuration did not establish whether the path allows this traffic."}[status]
    if all(check["status"] == "not_required" for check in checks):
        summary = "Both instances share a subnet; direct peering and route-table checks are not needed for this path."
    return {"status": status, "summary": summary, "scope": SCOPE, "checks": checks}


def configuration_result(session: Any, source: Node, destination: Node, address_type: str,
                         test_type: str, port: int | None) -> dict[str, Any]:
    analysis = analyze_network(session, source, destination, address_type, test_type, port)
    return {
        "mode": "configuration", "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_id": source.instance_id, "source_name": source.name,
        "destination_id": destination.instance_id, "destination_name": destination.name,
        "address_type": address_type, "tested_address": destination.private_ip,
        "test_type": test_type, "port": TEST_PORTS.get(test_type, port),
        "summary": analysis["summary"], "network_analysis": analysis,
    }

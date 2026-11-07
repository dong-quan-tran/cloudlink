"""Small offline cases for the routing decisions exposed by the dashboard."""

from dataclasses import replace
import unittest

from botocore.exceptions import ClientError

from cloudlink.network import analyze_network
from cloudlink.probe import Node


def route(cidr, target="local", state="active"):
    key = "VpcPeeringConnectionId" if target.startswith("pcx-") else "TransitGatewayId" if target.startswith("tgw-") else "GatewayId"
    return {"DestinationCidrBlock": cidr, key: target, "State": state, "Origin": "CreateRoute"}


class FakeEc2:
    def __init__(self):
        self.explicit = {"subnet-a": {"RouteTableId": "rtb-a", "Routes": [route("10.10.0.0/16")]}}
        self.main = {"vpc-a": {"RouteTableId": "rtb-main", "Routes": [route("10.10.0.0/16")]}}
        self.peers = []
        self.calls = []
        self.denied = False

    def describe_route_tables(self, Filters):
        self.calls.append(("routes", Filters))
        if self.denied:
            raise ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": "Denied"}}, "DescribeRouteTables")
        filters = {entry["Name"]: entry["Values"][0] for entry in Filters}
        table = (self.explicit.get(filters["association.subnet-id"]) if "association.subnet-id" in filters
                 else self.main.get(filters["vpc-id"]))
        return {"RouteTables": [table] if table else []}

    def describe_vpc_peering_connections(self, Filters):
        self.calls.append(("peering", Filters))
        if self.denied:
            raise ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": "Denied"}}, "DescribeVpcPeeringConnections")
        return {"VpcPeeringConnections": self.peers}


class Session:
    def __init__(self, ec2):
        self.ec2 = ec2

    def client(self, name, **kwargs):
        assert name == "ec2"
        return self.ec2


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.ec2 = FakeEc2()
        self.session = Session(self.ec2)
        self.a = Node("i-a", "A", "10.10.1.10", None, "vpc-a", "subnet-a", "us-east-1a", ())
        self.b = Node("i-b", "B", "10.10.2.10", None, "vpc-a", "subnet-b", "us-east-1b", ())

    def cross_vpc(self):
        self.b = replace(self.b, private_ip="10.30.1.10", vpc_id="vpc-b")
        self.ec2.explicit["subnet-a"]["Routes"].append(route("10.30.0.0/16", "pcx-ab"))
        self.ec2.explicit["subnet-b"] = {"RouteTableId": "rtb-b", "Routes": [
            route("10.30.0.0/16"), route("10.10.0.0/16", "pcx-ab")]}
        self.ec2.peers = [{"VpcPeeringConnectionId": "pcx-ab", "Status": {"Code": "active"},
                           "RequesterVpcInfo": {"VpcId": "vpc-a"}, "AccepterVpcInfo": {"VpcId": "vpc-b"}}]

    def inspect(self):
        return analyze_network(self.session, self.a, self.b)

    def test_main_table_fallback_and_more_specific_blackhole(self):
        result = self.inspect()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checks"][0]["status"], "not_required")
        self.assertEqual(result["checks"][1]["table_id"], "rtb-a")
        self.assertEqual(result["checks"][2]["table_id"], "rtb-main")
        self.assertEqual(result["checks"][2]["association"], "VPC main table")
        self.assertFalse(any(call[0] == "peering" for call in self.ec2.calls))
        self.ec2.explicit["subnet-a"]["Routes"].append(route("10.10.2.10/32", "pcx-dead", "blackhole"))
        broken = self.inspect()["checks"][1]
        self.assertEqual(broken["status"], "fail")
        self.assertEqual(broken["cidr"], "10.10.2.10/32")
        self.assertIn("blackhole", broken["detail"])

    def test_active_peering_requires_a_valid_return_route(self):
        self.cross_vpc()
        self.assertEqual(self.inspect()["status"], "pass")
        self.ec2.explicit["subnet-b"]["Routes"].pop()
        result = self.inspect()
        self.assertEqual([check["status"] for check in result["checks"]], ["pass", "pass", "fail"])
        self.assertIn("No IPv4 route", result["checks"][2]["detail"])
        self.ec2.explicit["subnet-b"]["Routes"].append(route("0.0.0.0/0", "igw-example"))
        self.assertIn("internet gateway", self.inspect()["checks"][2]["detail"])

    def test_inactive_or_wrong_peering_target_is_reported(self):
        self.cross_vpc()
        self.ec2.peers[0]["Status"]["Code"] = "pending-acceptance"
        self.assertEqual(self.inspect()["checks"][0]["status"], "fail")
        self.ec2.peers[0]["Status"]["Code"] = "active"
        self.ec2.explicit["subnet-a"]["Routes"][-1] = route("10.30.0.0/16", "pcx-other")
        result = self.inspect()
        self.assertEqual(result["checks"][0]["status"], "pass")
        self.assertEqual(result["checks"][1]["status"], "fail")

    def test_unsupported_paths_and_denied_reads_do_not_claim_success(self):
        self.cross_vpc()
        self.ec2.peers = []
        self.ec2.explicit["subnet-a"]["Routes"][-1] = route("10.30.0.0/16", "tgw-example")
        self.ec2.explicit["subnet-b"]["Routes"][-1] = route("10.10.0.0/16", "tgw-example")
        self.assertEqual(self.inspect()["status"], "unknown")
        self.ec2.explicit["subnet-a"]["Routes"].append({"DestinationPrefixListId": "pl-example", "GatewayId": "vpce-example", "State": "active"})
        self.assertIn("prefix-list", self.inspect()["checks"][1]["detail"])
        self.ec2.denied = True
        result = self.inspect()
        self.assertEqual([check["status"] for check in result["checks"]], ["unknown"] * 3)
        self.assertIn("UnauthorizedOperation", result["checks"][1]["detail"])

    def test_policy_checks_group_references_and_ordered_acl_reply_rules(self):
        self.a = replace(self.a, security_group_ids=("sg-a",))
        self.b = replace(self.b, security_group_ids=("sg-b",))
        self.ec2.describe_security_groups = lambda **_: {"SecurityGroups": [
            {"GroupId": "sg-a", "IpPermissionsEgress": [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]},
            {"GroupId": "sg-b", "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 8080, "ToPort": 8080,
                                                    "UserIdGroupPairs": [{"GroupId": "sg-a"}]}]},
        ]}
        entries = [{"RuleNumber": 100, "Egress": outbound, "Protocol": "-1", "RuleAction": "allow", "CidrBlock": "0.0.0.0/0"}
                   for outbound in (True, False)]
        self.ec2.describe_network_acls = lambda **_: {"NetworkAcls": [
            {"NetworkAclId": "acl-a", "Associations": [{"SubnetId": "subnet-a"}], "Entries": entries},
            {"NetworkAclId": "acl-b", "Associations": [{"SubnetId": "subnet-b"}], "Entries": entries[:2]},
        ]}
        overview = analyze_network(self.session, self.a, self.b, test_type="overview")
        self.assertEqual(overview["status"], "review")
        self.assertEqual(analyze_network(self.session, self.a, self.b, test_type="tcp", port=8080)["status"], "pass")
        https = analyze_network(self.session, self.a, self.b, test_type="https")
        self.assertEqual(next(check for check in https["checks"] if check["key"] == "destination_sg")["status"], "fail")

        deny = {"RuleNumber": 90, "Egress": False, "Protocol": "6", "RuleAction": "deny",
                "CidrBlock": "10.10.2.0/24", "PortRange": {"From": 1024, "To": 65000}}
        entries.append(deny)
        self.assertEqual(analyze_network(self.session, self.a, self.b, test_type="tcp", port=8080)["status"], "unknown")
        deny["PortRange"]["To"] = 65535
        blocked = analyze_network(self.session, self.a, self.b, test_type="tcp", port=8080)
        source_acl = next(check for check in blocked["checks"] if check["key"] == "source_acl")
        self.assertEqual(blocked["status"], "fail")
        self.assertIn("Reply inbound · #90 deny", source_acl["rules"])


if __name__ == "__main__":
    unittest.main()

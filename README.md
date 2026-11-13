# CloudLink

CloudLink is a guided network troubleshooting tool for AWS. Pick two EC2 instances to see whether they can communicate and which network settings could explain a failure. CloudLink brings the live test and the AWS configuration into one dashboard so cloud administrators and developers can decide what to check next.

## How it works

Choose a source, a destination, and the traffic you want to check.

| Mode | What it shows |
| --- | --- |
| **Connectivity Test** | Runs a live probe from the selected source using ping, HTTP, HTTPS, an SSH banner check, or a custom TCP port. |
| **Configuration Review** | Inspects direct VPC peering, forward and return routes, security groups, and network ACLs for the selected private IPv4 path. |

CloudLink leaves network settings untouched. Results apply to the selected direction, protocol, and port. Configuration findings show whether AWS settings permit the traffic. A live test also depends on the destination service responding.

## Architecture

The browser reaches the dashboard over HTTPS through Amazon CloudFront. An Application Load Balancer distributes requests to EC2 web hosts in an Auto Scaling group across two Availability Zones. The API queues diagnostics in Amazon SQS, and workers on the EC2 hosts run the checks and save job status and results in Amazon DynamoDB. The dashboard polls for updates, and recent results are scoped to each browser session.

The application runs in its own VPC and uses private peering connections to reach the lab nodes in two shared lab VPCs. Workers run live probes from the selected source over a management SSH connection. CloudWatch tracks application logs and queue activity, and the SQS backlog helps drive scaling.

## Demo scenarios

Use **TCP port 8080** in the direction shown to reproduce the baseline scenarios. Choose any two different lab nodes and either mode to explore other supported protocols or ports.

| Node pair | What Configuration Review should report |
| --- | --- |
| A → B | Same-VPC traffic is allowed. |
| C → D | The destination security group blocks traffic. |
| E → F | The destination subnet’s network ACL blocks traffic. |
| G → H | Traffic is allowed across VPC peering. |
| I → J | The source subnet’s route table lacks a forward route. |
| K → L | The destination subnet’s route table lacks a return route. |
| M → N | The associated route table lacks the forward route. |
| O → P | A missing return route, a security group rule, and a network ACL rule block traffic. |

## Future work

As more teams run diagnostics concurrently, CloudLink could scale diagnostic workers with the SQS backlog and scale web hosts with dashboard traffic. Adding AWS region selection would let teams discover EC2 instances and diagnose connections between peered VPCs in different regions.

## Team

Built for CSE 4333 Cloud Computing by **Joel Beauregard** (application and AWS deployment) and **Johnny Tran** (network scenarios and lab design).

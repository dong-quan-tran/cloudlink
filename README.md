# CloudLink

CloudLink is a guided network troubleshooting tool for cloud-hosted applications. It tests connectivity **from one cloud instance to another** and turns the result into a clear next step. A service that cannot be reached might have a routing, firewall, port, or application problem; CloudLink helps narrow down what to check without changing the network for you.

## What it does

- Lets you choose a source and destination from the configured lab instances.
- Runs a test from the source using ICMP ping, HTTP, HTTPS, an SSH server-banner check, or a custom TCP port.
- Shows the result, a likely area to investigate, and a suggested next check.
- Saves recent results so you can compare before and after a configuration change.

CloudLink's tests are read-only. A failed check is specific to the protocol and port selected; it does not, by itself, prove that all traffic between the instances is blocked.

## Who it is for

CloudLink is intended for junior cloud administrators, application developers, and small technical teams that need a straightforward way to investigate connectivity between services. It brings the first checks and their results into one place without requiring users to work through several cloud dashboards for every test.

## Current project scope

The current version has a public CloudLink web instance and two private test instances in separate subnets of the same VPC. The web instance reaches the selected source over a private management connection; the source runs the chosen test against the destination's private IP. The interface currently lists these two configured lab nodes, not every instance in an AWS account. Testing arbitrary private networks, peered VPCs, and additional instances is future work.

TCP port 8080 is available on each probe node; HTTP and HTTPS on ports 80 and 443 are not. Peer-to-peer SSH is blocked by default so CloudLink can demonstrate a protocol-specific failure even while ping works. The lab is disposable: the dashboard uses unauthenticated HTTP on a web port that is public by default. Administrative SSH to the web instance remains limited to a specified `/32` address.

CloudFormation and CloudShell scripts set up and tear down this environment in a personal AWS account. See [the deployment guide](infra/README.md).

# CloudLink

CloudLink is a guided network troubleshooting tool for cloud-hosted applications. It tests connectivity **from one cloud instance to another** and turns the result into a clear next step. A service that cannot be reached might have a routing, firewall, port, or application problem; CloudLink helps narrow down what to check without changing the network for you.

## What it does

- Lets you choose a source and destination from the configured lab instances.
- Runs a test from the source using ICMP ping, HTTP, HTTPS, an SSH server-banner check, or a custom TCP port.
- Shows the result, a likely area to investigate, and a suggested next check.
- Saves recent results so you can compare before and after a configuration change.
- Queues hosted requests and shows their progress while background workers run the checks.

CloudLink's tests are read-only. A failed check is specific to the protocol and port selected; it does not, by itself, prove that all traffic between the instances is blocked.

## Who it is for

CloudLink is intended for junior cloud administrators, application developers, and small technical teams that need a straightforward way to investigate connectivity between services. It brings the first checks and their results into one place without requiring users to work through several cloud dashboards for every test.

## Current project scope

CloudLink's application runs in its own VPC, with a load balancer and an Auto Scaling Group spanning two Availability Zones. Classmates access the dashboard through a CloudFront HTTPS URL. SQS queues connectivity requests, and DynamoDB shares job progress, results, and history between application servers. Failed app instances can be replaced without losing the shared history.

The two private probe instances live in a separate lab VPC, reached through VPC peering. CloudLink discovers running instances tagged as its probes and connects to the selected source over private SSH. The source then runs the selected check against the destination. TCP 8080 and ICMP are allowed between the probes; peer-to-peer SSH is blocked to demonstrate a protocol-specific failure. The probes do not serve HTTP/HTTPS on ports 80/443.

The dashboard is a shared class demo without user accounts. Individual probe nodes remain single instances. Route-table, ACL, security-group, and peering configuration analysis, along with additional network scenarios, are planned for phase two. Local development can still use the synchronous API and SQLite history.

CloudFormation and CloudShell scripts set up and tear down this environment in a personal AWS account. See [the deployment guide](infra/README.md).

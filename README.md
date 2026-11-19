# CloudLink

CloudLink is a guided network troubleshooting tool for AWS. Pick two EC2 instances to see whether they can communicate and which network settings could explain a failure. CloudLink brings the live test and the AWS configuration into one dashboard so cloud administrators and developers can decide what to check next.

## Table of contents

- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Demo scenarios](#demo-scenarios)
- [Deploy in your own AWS account and test scenarios](#deploy-in-your-own-aws-account-and-test-scenarios)
- [Future work](#future-work)
- [Team](#team)

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

## Deploy in your own AWS account and test scenarios

Sign in to your AWS account, select **US East (N. Virginia), `us-east-1`**, and open **AWS CloudShell**. Deployment uses that account’s signed-in CloudShell identity. The templates create the application role, instance profile, and probe SSH key automatically.

Before deploying, confirm the account has the following available in `us-east-1`.

- Permissions to provision the CloudFormation resources, including IAM roles and instance profiles and `iam:PassRole`.
- Room for **three new VPCs**, covering the application and two lab networks.
- Enough **Running On-Demand Standard instances** vCPU quota for the fleet. The 16 `t2.micro` probes and four initial `t3.small` web hosts use **24 vCPUs**. Allow **28 vCPUs** for the web fleet to scale to six hosts, plus any existing usage.

### Deploy

Run these commands in CloudShell.

```bash
git clone --branch main https://github.com/dong-quan-tran/cloudlink.git
cd cloudlink
bash scripts/deploy.sh
```

The script displays the destination AWS account and deploys the network, shared services, all eight node-pair scenarios, and the web application in dependency order. Each web host installs the app from the checked-out branch. Keep CloudShell open until the script finishes and prints the **CloudLink HTTPS URL**, then open that URL to use the dashboard. The same URL is available under **CloudFormation → cloudlink-web → Outputs → WebUrl**.

### Test the scenarios

Open the HTTPS dashboard and select a source and destination from the [demo scenarios](#demo-scenarios) table. Choose TCP port **8080** to reproduce the listed outcomes.

Run **Configuration Review** to inspect peering, forward and return routes, security groups, and network ACLs for the selected traffic. Run **Connectivity Test** to send a live probe from the source instance and see whether it reaches the destination.

You can also choose any two different lab nodes and explore other supported protocols or ports in either mode. Change the direction or traffic selection and compare the results in your browser session’s history.

### Clean up

These resources incur AWS charges while deployed. When you finish testing, run the teardown from the same repository folder.

```bash
bash scripts/teardown.sh
```

Review the account shown and type `delete` when prompted. The script waits for each stack to be deleted in dependency order. Teardown removes the deployed app and lab infrastructure, including saved history, queued jobs, and the managed probe key.

## Future work

As more teams run diagnostics concurrently, CloudLink could scale diagnostic workers with the SQS backlog and scale web hosts with dashboard traffic. Adding AWS region selection would let teams discover EC2 instances and diagnose connections between peered VPCs in different regions.

## Team

Built for CSE 4333 Cloud Computing by **Joel Beauregard** (application and AWS deployment) and **Johnny Tran** (network scenarios and lab design).

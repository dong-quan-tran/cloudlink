# CloudLink

CloudLink will test connections between AWS servers, explain likely
problems, and save results for before/after comparisons.

It provides guidance only. It will not automatically change AWS settings.

## Current status

Johnny's test environment is working:
- VPC, two subnets, internet routing, and security groups created.
- Two Amazon Linux EC2 servers launched.
- SSH access verified for both.
- Destination test service running on TCP port 8000.
- Source-to-destination HTTP test passed.

Controlled failure tests have not started.
The actual CloudLink app and dashboard have not been integrated.
The new automated setup still needs testing in a teammate's sandbox.

These results describe the last verified session, not a live status check.

## Team

- Johnny: AWS infrastructure, test servers, failure tests, and setup docs.
- Joel: application, dashboard, probes, diagnostic rules, and result storage.

## Set up your own AWS environment

These instructions are for Windows PowerShell.

### 1. Clone the repository

    git clone https://github.com/dong-quan-tran/cloudlink.git
    cd cloudlink

If you already cloned it:

    git pull

### 2. Check AWS CLI

    aws --version

If AWS CLI is missing, install it:

    Start-Process msiexec.exe -ArgumentList '/i https://awscli.amazonaws.com/AWSCLIV2.msi' -Wait

Follow the installer, then close and reopen your terminal.
Run aws --version again.

### 3. Start your sandbox

- Open AWS Academy Canvas.
- Open Sandbox environment.
- Click Start Lab and wait for the AWS indicator to turn green.
- Open Details > Show to find your AWS CLI credentials.
- Check the current region in the AWS console. Do not change it.

### 4. Create your test environment

From the repository's PowerShell terminal:

    .\scripts\setup-aws.ps1

The script asks for:
- Your AWS access key ID.
- Your AWS secret access key.
- Your AWS session token.
- Your sandbox region.

Enter values only, without labels or quotes.
Confirm the displayed AWS account is yours.
Type SETUP when prompted to create the resources.

If Windows blocks the script, run this for the current terminal only:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

Then run the script again.

### 5. Check your local resource details

    Get-Content infrastructure/network.local.json

The setup creates:
- VPC: 10.20.0.0/16.
- Source subnet: 10.20.1.0/24.
- Destination subnet: 10.20.2.0/24.
- Internet gateway and public routing.
- Separate source and destination security groups.
- SSH access from your public IP.
- Destination port 8000 access from the source security group.
- Two Amazon Linux 2023 t3.micro servers with 8 GB gp2 disks.
- A Python test service on the destination.

This creates the test environment, not the CloudLink app.

### 6. Verify the setup

Download your own sandbox PEM key from Details > Show.
Keep it outside the repository.

Use your own addresses from network.local.json to connect over SSH.
From the source server, request the destination's private IP on port 8000.

Expected response:

    CloudLink destination is healthy

The automated setup is not considered verified until this test passes.
See docs/recreate-setup.md for more details.

## Connect without rebuilding

To connect a new PowerShell terminal to your sandbox:

    .\scripts\connect-aws.ps1

This only sets credentials and checks AWS access.
It does not create infrastructure.

Credentials apply to the current terminal and its child processes.
Run it again in a new terminal or when credentials expire.

## Separate sandboxes

Each teammate uses their own sandbox and credentials.
The network layout matches, but AWS IDs and IPs differ.

- infrastructure/network.json contains Johnny's original resource IDs.
- infrastructure/network.local.json contains your own setup's IDs.
- Do not use Johnny's resource IDs in your separate sandbox.
- Do not commit your local settings file.

## Setup limits

- The script requires the sandbox's existing vockey key pair.
- It needs room for two instances under the sandbox's nine-instance limit.
- Repeat runs update the same cloudlink-dev CloudFormation stack.
- They do not fully reset server files or manual changes.
- The script stops if it finds an existing manual CloudLink VPC.
- If setup fails, inspect CloudFormation stack events before retrying.
- The selected Amazon Linux version may differ from Johnny's original image.
- Sandbox resource persistence between sessions is not confirmed.

## Next project tasks

1. Verify the automated setup in Joel's sandbox.
2. Stop the destination service and test failure/recovery.
3. Test blocked port and wrong source range.
4. Test a stopped destination instance.
5. Save results and restoration steps.
6. Add cleanup instructions.
7. Integrate and test Joel's CloudLink app.

## Repository files

- scripts/connect-aws.ps1: prompts for credentials and checks access.
- scripts/setup-aws.ps1: creates or updates the development environment.
- infrastructure/cloudlink.yaml: CloudFormation resource template.
- infrastructure/setup-destination.sh: standalone test-service setup.
- infrastructure/network.json: Johnny's original resource IDs.
- infrastructure/README.md: original infrastructure status.
- docs/recreate-setup.md: teammate setup guide.
- docs/aws-connection.md: connection-only guide.
- docs/baseline-result.md: Johnny's successful baseline test.
- docs/test-scenarios.md: controlled test checklist.
- docs/joel-update.md: team handoff details.

## Safety

Never commit AWS credentials, SSH keys, or passwords.
Do not share Canvas logins or private keys.
Create and modify only dedicated CloudLink test resources.

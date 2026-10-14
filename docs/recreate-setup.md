# Recreate the CloudLink Development Environment

## Requirements
- Windows PowerShell and AWS CLI v2.
- Your own running AWS Academy Sandbox.
- Sandbox permissions for EC2, VPC networking, and CloudFormation.
- Existing sandbox key pair: vockey.
- Room for two t3.micro instances with 8 GB gp2 disks.

## Run from the repository
    .\scripts\setup-aws.ps1

The script:
1. Prompts for your sandbox credentials and region.
2. Shows the target account and asks for confirmation.
3. Creates the network, security groups, and two EC2 servers.
4. Starts the destination test service on port 8000.
5. Saves your IDs and IPs to infrastructure/network.local.json.

## What matches Johnny's setup
- VPC: 10.20.0.0/16.
- Source subnet: 10.20.1.0/24.
- Destination subnet: 10.20.2.0/24.
- Public internet routing.
- SSH allowed from your public IP only.
- Destination port 8000 allowed from the source security group.
- Amazon Linux 2023 servers and Python test service.

## What differs
AWS assigns new resource IDs and IPs.
A fresh setup selects the latest matching Amazon Linux image.
This creates the test environment, not the CloudLink app.

## After setup
Download your own sandbox PEM key.
Use network.local.json for your server addresses.
Verify SSH and run an HTTP request from source to destination.
Expected response: CloudLink destination is healthy.

## Important
Do not use Johnny's tracked network.json for your sandbox.
Do not commit credentials, private keys, or network.local.json.
Do not run this to duplicate Johnny's existing manual setup.
Repeat runs update the same cloudlink-dev stack.
Existing instance files and manually changed settings are not fully reset.
If setup fails, inspect CloudFormation stack events before retrying.
Sandbox persistence between sessions is still unconfirmed.

## PowerShell execution policy
If Windows blocks the script, run for this terminal only:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

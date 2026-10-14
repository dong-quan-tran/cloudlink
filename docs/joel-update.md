# Handoff for Joel — October 14, 2026

## What Johnny actually verified

On October 13, Johnny created the AWS network manually, launched source and destination instances, verified SSH, started the destination Python HTTP service and successfully requested it from the source over private TCP port 8000.

Original source: i-0e4cb59f00340b267 / 10.20.1.33.
Original destination: i-0f32c4732129523c5 / 10.20.2.151.
Region: us-east-1.
Response: CloudLink destination is healthy.

These are historical results, not today's live status. Do not use these IDs in your sandbox.

## What the repo now provides

- Credential prompt and AWS identity check.
- CloudFormation template and setup driver for a separate sandbox.
- SSH-key preparation instructions.
- Verification helper for API access, both servers and private HTTP connectivity.
- Manual checks, logs, service control, service-failure/recovery procedure and stack cleanup commands.
- The original service setup script and baseline result.

Inspection found that setup referenced a missing connect-aws.ps1. This handoff adds it. It also restores missing security-group and instance IDs to Johnny's historical network record.

The new helper scripts and automated recreation have not yet been run against a teammate's AWS sandbox. Code inspection is not an AWS test result.

## Your next steps

1. Pull the repo and follow the main README.
2. Start your sandbox and run scripts/setup-aws.ps1 with your credentials.
3. Prepare your own sandbox PEM key.
4. Run scripts/verify-aws.ps1 and save the actual result.
5. Build the CloudLink backend and dashboard. Send Johnny the app setup/run commands when ready.

## App boundary

The Python HTTP service is only a target. No CloudLink app is installed yet.

Proposed probe location: your source EC2 instance.
Target: your destination private IP on TCP port 8000.
Read your own settings from ignored infrastructure/network.local.json.
AWS API authentication for the app is not configured; EC2 SSH access does not grant API access. Agree on an approved temporary-credential or existing-role approach before implementing real AWS checks.

## Remaining work

Johnny: controlled failures, evidence, safe recovery, manual-environment cleanup.
Joel: app, probes, AWS checks, explanations, dashboard, result storage.
Together: verify recreation, integrate the app, agree on interface and demo steps.
Professor: confirm sandbox persistence and whether any shared project environment is available.

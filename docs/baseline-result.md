# Healthy Baseline - T01

## Summary

Two healthy baseline results are recorded below:

- Original manual environment: source-to-destination HTTP passed.
- October 14, 2026 CloudFormation deployment: automated verification passed.

These are recorded test results, not a live AWS status check.
The destination Python HTTP service is a test target, not the CloudLink application.

## Original manual environment

### Result

PASS: The source server reached the destination test service.

### Environment

- Region: us-east-1
- Source instance: i-0e4cb59f00340b267
- Source private IP: 10.20.1.33
- Destination instance: i-0f32c4732129523c5
- Destination private IP: 10.20.2.151
- Protocol: HTTP over TCP
- Destination port: 8000

### Test

Executed on the source server:

```bash
curl --fail --connect-timeout 5 --max-time 10 http://10.20.2.151:8000/
```

### Actual response

```text
CloudLink destination is healthy
```

### What this confirms

- The tested source-to-destination connection worked.
- The destination HTTP service responded on port 8000.

## October 14, 2026 - CloudFormation deployment

### Result

PASS: The verification helper confirmed SSH access and a successful
source-to-destination HTTP request over private TCP port 8000.

### Environment

- Account: 259282837093
- Region: us-east-1
- Stack: cloudlink-dev
- VPC: vpc-0534a8c8c0cde39bb
- Source instance: i-06e17c86edd59a3d9
- Source private IP: 10.20.1.226
- Destination instance: i-06aaa5a1822ac14d5
- Destination private IP: 10.20.2.21
- Protocol: HTTP over TCP
- Destination port: 8000

This deployment is separate from the original manual environment above.

### Test

Executed from the repository root in Windows PowerShell:

```powershell
.\scripts\verify-aws.ps1
```

The helper checked AWS API access, instance details, destination SSH,
destination startup and service health, source SSH, and the private
source-to-destination HTTP connection.

### Recorded output

Relevant output from the successful run:

```text
API access OK: account 259282837093, region us-east-1

Checking destination SSH, startup and local service (up to 180 seconds).

status: done
ip-10-20-2-21.ec2.internal
Python 3.9.25
active
CloudLink destination is healthy
Checking source SSH and source-to-destination HTTP.
CloudLink destination is healthy
PASS: source reached destination on private TCP port 8000.
```

SSH host-trust prompts and the instance table are omitted from this excerpt.

### Setup issue resolved

Initial destination SSH authentication failed.

The local SSH key was replaced with the downloaded sandbox PEM.
The existing local key needed temporary write permission before it could
be replaced. After replacement, SSH and the complete verification passed.

No server rebuild was needed to resolve this authentication issue.

### What this confirms

- AWS API access worked in the recorded account and region.
- Both servers accepted SSH connections.
- Destination startup completed.
- The destination test service reported active.
- The destination service responded locally.
- The source reached the destination through its private IP on port 8000.
- Setup and verification succeeded for this CloudFormation deployment
  in Johnny's sandbox.

### What this does not confirm

- A successful deployment in a teammate's separate sandbox.
- Successful reconnect-helper testing in a later session.
- Controlled failure detection or recovery.
- CloudLink application or dashboard integration.
- Latency measurements, automated diagnosis, recommendations, or saved history.
- Resource persistence after the sandbox session ends.

## Destination test service

- Service name: `cloudlink-test`
- Standalone setup script: `infrastructure/setup-destination.sh`
- The CloudFormation template includes equivalent startup commands.
- This is a Python test HTTP service, not the CloudLink application.

Run these commands on the intended destination server:

```bash
sudo systemctl start cloudlink-test
sudo systemctl stop cloudlink-test
sudo systemctl status cloudlink-test
```

## Next test - T04

The service-stopped failure and recovery scenario has not yet been run.

1. Verify the healthy baseline.
2. Stop only the destination test service.
3. Confirm that the source HTTP request fails.
4. Restart the destination test service.
5. Verify that the healthy baseline returns.
6. Save the failure output and restored-success output in a separate result document.

Follow `docs/operations.md` for the procedure.

Do not mark T04 passed until both the expected failure and successful
recovery are recorded.
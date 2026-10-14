# CloudLink

CloudLink will test connections between AWS servers, explain likely problems, and save results. It gives guidance; it will not automatically change cloud settings.

## Status - October 14, 2026

| Work | Status |
|---|---|
| Johnny's VPC, subnets, internet routing, security groups | Created |
| Two EC2 servers and SSH access | Verified October 13 |
| Destination Python test service on port 8000 | Verified October 13 |
| Source-to-destination HTTP baseline | Passed October 13 |
| Automated CloudFormation recreation | Added; not yet verified in a teammate's sandbox |
| Connection and verification helper scripts | Added; runtime testing pending |
| Controlled failure scenarios | Planned; not run |
| CloudLink app, dashboard, diagnostics, saved history | Not yet integrated |

These are recorded results, not a live AWS status check. The Python HTTP server is a test target, not the CloudLink app.

## Team

- Johnny: AWS network, servers, failure scenarios, setup and test evidence.
- Joel: app, dashboard, connection probes, AWS configuration checks and result storage.

## What we built

```text
Laptop -- AWS CLI credentials --> sandbox AWS APIs
Laptop -- SSH key / port 22 --> source and destination public IPs
Source -- private IP / TCP 8000 --> destination test HTTP service
```

- VPC: `10.20.0.0/16`.
- Source subnet: `10.20.1.0/24`.
- Destination subnet: `10.20.2.0/24`.
- Internet gateway and a public route table serving both subnets.
- SSH permitted only from the developer's public IPv4 address at setup time.
- Destination port 8000 permitted from the source security group.
- Two Amazon Linux 2023 `t3.micro` instances, each with an 8 GB `gp2` root disk.
- Sandbox key pair: `vockey`. No new IAM user or role is created.

## Recreate the setup in your sandbox - Windows PowerShell

### 1. Get the code

```powershell
git clone [https://github.com/dong-quan-tran/cloudlink.git](https://github.com/dong-quan-tran/cloudlink.git)
cd cloudlink
```

If already cloned, run `git pull --ff-only` inside the repository. Stop if Git reports local changes or a conflict.

### 2. Check requirements

```powershell
git --version
aws --version
ssh -V
Get-Command scp
```

Install Git, Windows OpenSSH Client, or AWS CLI if its check fails. To install AWS CLI:

```powershell
Start-Process msiexec.exe -ArgumentList '/i [https://awscli.amazonaws.com/AWSCLIV2.msi](https://awscli.amazonaws.com/AWSCLIV2.msi)' -Wait
```

Complete the installer and reopen your terminal in the repository. Then run `aws --version` again.

### 3. Open your sandbox

In AWS Academy Canvas, open Sandbox environment. Click Start Lab and wait for the green AWS indicator. Open Details > Show to find your temporary CLI credentials. Check the current region in the AWS console; do not switch it.

Confirm your sandbox allows CloudFormation, EC2 and VPC networking, `t3.micro`, and 8 GB `gp2` disks. Our listed sandbox limit is nine instances, including existing instances. IAM is read-only. Session timer is three hours; persistence after a session is still unconfirmed.

### 4. Create your resources

```powershell
.\scripts\setup-aws.ps1
```

It prompts for your credentials and region, shows the target account, then asks you to type `SETUP`. It creates or updates the `cloudlink-dev` CloudFormation stack. It saves your resource IDs to ignored file `infrastructure/network.local.json`. No credentials are written to disk by our script.

If PowerShell blocks our scripts, review the script first, then use this terminal-only setting if permitted by your organization:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Do not run setup to duplicate Johnny's manual environment. It stops if it finds an existing manual CloudLink VPC. Existing manual resources are not imported into CloudFormation.

### 5. Check AWS API access

Run in the same terminal after setup or connection:

```powershell
aws sts get-caller-identity --no-cli-pager
aws ec2 describe-instances --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name,PrivateIP:PrivateIpAddress}" --output table --no-cli-pager
Get-Content infrastructure/network.local.json
```

Expected: your sandbox identity and your two running instances. These checks confirm API access, not server-to-server connectivity.

### 6. Download and prepare your SSH key

Download PEM from your sandbox's Details > Show. Save it outside the repository. Paste this block and enter its actual downloaded path:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $download = (Read-Host 'Full path to your downloaded sandbox PEM').Trim('"')
    if (-not (Test-Path -LiteralPath $download -PathType Leaf)) { throw 'PEM file not found.' }
    $key = Join-Path $env:USERPROFILE '.ssh/cloudlink.pem'
    New-Item -ItemType Directory -Force (Split-Path $key -Parent) | Out-Null
    if (Test-Path $key) {
        if ((Read-Host 'Replace the existing local cloudlink.pem? Type REPLACE') -cne 'REPLACE') { throw 'Cancelled.' }
    }
    Copy-Item -LiteralPath $download -Destination $key -Force
    icacls.exe $key /reset
    if ($LASTEXITCODE -ne 0) { throw 'Permission reset failed.' }
    $me = whoami
    icacls.exe $key /grant:r "${me}:(R)"
    if ($LASTEXITCODE -ne 0) { throw 'Permission update failed.' }
    icacls.exe $key /inheritance:r
    if ($LASTEXITCODE -ne 0) { throw 'Permission update failed.' }
}
```

The key must belong to your sandbox's `vockey`, not another teammate's sandbox.

### 7. Verify both servers and the private connection

```powershell
.\scripts\verify-aws.ps1
```

The helper checks account/region, refreshes instance addresses from EC2, checks both servers are running, waits for destination startup, checks its service, and sends a request from source to destination. It does not create resources or modify security rules. First-time SSH connections may ask you to trust the host. Check the address against your EC2 console; never disable host-key checking to bypass a warning.

Expected final output:

```text
PASS: source reached destination on private TCP port 8000.
```

Expected HTTP body:

```text
CloudLink destination is healthy
```

Record your own result before marking setup verified. Johnny's earlier result does not verify a fresh teammate deployment.

## Reconnect next time - no rebuild

Start the sandbox and enter fresh credentials in your repo terminal:

```powershell
.\scripts\connect-aws.ps1
aws sts get-caller-identity --no-cli-pager
.\scripts\verify-aws.ps1
```

Connection credentials apply to this terminal and child processes only. New terminal or expired credentials means reconnect. SSH keys are separate from CLI credentials. Public IPs can change; the verification helper refreshes them from EC2. If instances are stopped, inspect their state and start only your own project instances; see [operations](docs/operations.md).

## Separate sandboxes and settings

GitHub access shares code, not AWS access. Each teammate creates a separate copy using their own credentials. IDs, IPs and the selected latest Amazon Linux image can differ.

- `infrastructure/network.json`: Johnny's original resource record; do not use it in another account.
- `infrastructure/network.local.json`: your own ignored settings.
- For Johnny's existing environment only, follow the local-file instructions in [operations](docs/operations.md). Do not rebuild it just to get a local file.

Repeat setup runs update the named stack; they do not fully reset files or manually changed settings. No app or AWS-read role for the app is configured yet.

## Continue the project

1. Joel verifies his recreated environment.
2. Johnny runs one controlled failure at a time, restores the baseline and saves evidence.
3. Joel builds the app using the source server as the probe location.
4. Agree on app run commands and how it will read AWS settings with approved temporary access.
5. Test app findings against actual controlled failures.

Do not commit credentials or assume an EC2 instance automatically has AWS API permissions. IAM is read-only in our sandbox; app API access remains an integration task.

## Guides and files

- [AWS connection](docs/aws-connection.md): sign-in and checks.
- [Operations](docs/operations.md): manual checks, service controls, failures, troubleshooting and cleanup.
- [Joel handoff](docs/joel-update.md).
- [Scenario checklist](docs/test-scenarios.md).
- [Original baseline evidence](docs/baseline-result.md).
- `scripts/setup-aws.ps1`: deployment driver.
- `scripts/connect-aws.ps1`: interactive temporary credentials.
- `scripts/verify-aws.ps1`: current AWS/SSH/HTTP checks.
- `infrastructure/cloudlink.yaml`: complete development resource template.
- `infrastructure/setup-destination.sh`: standalone destination service setup, already used in Johnny's manual environment. The template includes equivalent startup commands.

## Safety and cleanup

Never commit keys, tokens, passwords, or local settings. Keep the test HTTP service limited to its dedicated directory; it is not a production server. Use only dedicated project resources. See [operations](docs/operations.md) before deleting anything. CloudFormation cleanup does not remove Johnny's separately created manual environment.
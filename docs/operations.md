# CloudLink Operations — PowerShell

Run from the repository root after connecting to the correct sandbox. These are procedures, not evidence that the tests have been run. Do not run destructive or failure steps on unrelated resources.

## Settings and existing manual environment

Fresh teammate deployments use ignored `infrastructure/network.local.json` automatically.

Johnny's original environment was created manually, not by CloudFormation. Johnny only can create a local record without creating resources:

```powershell
Copy-Item infrastructure/network.json infrastructure/network.local.json
```

Do not do this in Joel's sandbox. The tracked file contains Johnny's resource IDs. Check credentials match that file's AccountId before further commands.

## Read current settings and refresh addresses

```powershell
$n = Get-Content infrastructure/network.local.json -Raw | ConvertFrom-Json
$env:AWS_DEFAULT_REGION = $n.Region
$env:AWS_REGION = $n.Region
$key = Join-Path $env:USERPROFILE '.ssh/cloudlink.pem'
aws sts get-caller-identity --no-cli-pager
aws ec2 describe-instances --instance-ids $n.SourceInstanceId $n.DestinationInstanceId --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name,PrivateIP:PrivateIpAddress,PublicIP:PublicIpAddress}" --output table --no-cli-pager
```

Stop if the displayed account differs from `$n.AccountId`.

```powershell
.\scripts\verify-aws.ps1
$n = Get-Content infrastructure/network.local.json -Raw | ConvertFrom-Json
```

The helper refreshes the saved addresses before its SSH checks. If an HTTP failure is expected during a scenario, the helper will fail; inspect that failure rather than treating it as a pass.

## Manual checks

After loading settings and refreshing addresses:

```powershell
ssh -i $key "ec2-user@$($n.SourcePublicIP)" 'hostname; python3 --version'
ssh -i $key "ec2-user@$($n.DestinationPublicIP)" 'hostname; python3 --version'
ssh -i $key "ec2-user@$($n.DestinationPublicIP)" 'sudo systemctl is-active cloudlink-test'
ssh -i $key "ec2-user@$($n.DestinationPublicIP)" 'curl --silent --show-error --fail http://127.0.0.1:8000/'
ssh -i $key "ec2-user@$($n.SourcePublicIP)" "curl --silent --show-error --fail --connect-timeout 5 --max-time 10 http://$($n.DestinationPrivateIP):8000/"
```

Expected: service `active`, then body `CloudLink destination is healthy`. The last request runs on the source, not on your laptop. A source probe must run from the intended source network location.

## Repair the destination test service

Use only on your dedicated destination. First inspect errors below. To apply the existing setup script:

```powershell
scp -i $key infrastructure/setup-destination.sh "ec2-user@$($n.DestinationPublicIP):/home/ec2-user/setup-destination.sh"
if ($LASTEXITCODE -ne 0) { throw 'Upload failed.' }
ssh -i $key "ec2-user@$($n.DestinationPublicIP)" "sed -i 's/\r$//' /home/ec2-user/setup-destination.sh && bash /home/ec2-user/setup-destination.sh"
if ($LASTEXITCODE -ne 0) { throw 'Destination setup failed.' }
```

The service is a Python test server, not the CloudLink application. Its files are under `/opt/cloudlink-test`.

## T04: service-stopped failure and recovery — not yet run

First confirm the healthy baseline. Load `$n` and `$key` as above. This intentionally interrupts only the test service.

```powershell
& {
    ssh -i $key "ec2-user@$($n.DestinationPublicIP)" 'sudo systemctl stop cloudlink-test'
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop service.' }
    try {
        ssh -i $key "ec2-user@$($n.SourcePublicIP)" "curl --silent --show-error --fail --connect-timeout 5 --max-time 10 http://$($n.DestinationPrivateIP):8000/"
        $probeExit = $LASTEXITCODE
        if ($probeExit -eq 255) { throw 'SSH itself failed; this does not validate the service-failure scenario.' }
        if ($probeExit -eq 0) { throw 'Unexpected success while service should be stopped.' }
        Write-Host "Observed expected failed request; exit code: $probeExit"
    }
    finally {
        ssh -i $key "ec2-user@$($n.DestinationPublicIP)" 'sudo systemctl start cloudlink-test'
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Restore failed. Restart the test service manually before continuing.' }
    }
}
.\scripts\verify-aws.ps1
```

Do not mark the scenario passed until both failure and restored success are recorded. If the terminal is interrupted, run the start command and verify again.

## Other scenarios — planned, not run

- T02: remove only the destination's TCP 8000 rule; observe failed request; restore the same rule; recheck baseline.
- T03: change only that test rule to a nonmatching source; observe failure; restore source-security-group access; recheck baseline.
- T05: stop only the destination instance; record its state and failed reachability; start it; refresh public IPs; recheck baseline.
- T06: record successful recovery after each scenario.

Do not change SSH rules as part of these scenarios. Save exact original rules before changing them. Step-by-step rule-mutation scripts are still pending, not part of this completed handoff.

## Evidence

For each scenario record date/time, account/region (no credentials), source and destination IDs, exact change, expected result, actual command output, restoration steps and final baseline. Use `docs/test-scenarios.md` and create a separate result document. Keep private keys and tokens out of all logs.

## Troubleshooting

- Expired token: start the sandbox and rerun `scripts/connect-aws.ps1`.
- Wrong account or missing IDs: do not guess; use your local settings and correct credentials.
- Permission denied by AWS: check sandbox restrictions; do not attempt to create IAM users or bypass restrictions.
- PEM not found: verify its path; follow README key preparation.
- SSH publickey error: confirm `ec2-user`, your sandbox's PEM, and `vockey` on the instance.
- SSH timeout: check running state, current public IP, public routing and port 22 allowed from your current public IP.
- IP changed: fresh CloudFormation deployments can update the allowed SSH source by rerunning setup. Do not run setup against Johnny's manual environment; update only its SSH rules after inspection.
- Host key warning: verify the instance identity; do not blindly remove known-host entries or disable checking.
- First HTTP request refused during startup: wait and retry; the service may not be listening yet.

Destination logs:

```powershell
ssh -i $key "ec2-user@$($n.DestinationPublicIP)" 'sudo systemctl status cloudlink-test --no-pager; sudo journalctl -u cloudlink-test -n 50 --no-pager; sudo tail -n 50 /var/log/cloud-init-output.log'
```

CloudFormation failures (does not change resources):

```powershell
aws cloudformation describe-stack-events --stack-name cloudlink-dev --max-items 20 --output table --no-cli-pager
```

A stack in ROLLBACK_COMPLETE needs inspection and appropriate cleanup before a new deployment. Never keep launching duplicate instances to bypass an error.

If only your two existing project instances are stopped, after checking account and IDs:

```powershell
aws ec2 start-instances --instance-ids $n.SourceInstanceId $n.DestinationInstanceId --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw 'Start failed.' }
aws ec2 wait instance-running --instance-ids $n.SourceInstanceId $n.DestinationInstanceId
if ($LASTEXITCODE -ne 0) { throw 'Wait failed.' }
.\scripts\verify-aws.ps1
```

Do not assume restarting preserves public IPs or that all sandbox resources survive a session. Persistence remains a professor question.

## Cleanup — CloudFormation copies only

Deleting a stack destroys its servers and their root-disk data. Save needed work first. This is not cleanup for Johnny's manual environment. Stop if local settings lack `StackName` or the identity is not the intended account.

Inspect first:

```powershell
aws sts get-caller-identity --no-cli-pager
aws cloudformation describe-stack-resources --stack-name cloudlink-dev --output table --no-cli-pager
```

Only when you intend to destroy your dedicated CloudFormation copy:

```powershell
& {
    $n = Get-Content infrastructure/network.local.json -Raw | ConvertFrom-Json
    if ($n.StackName -ne 'cloudlink-dev') { throw 'Not a recorded CloudFormation deployment. Stop.' }
    $identityJson = aws sts get-caller-identity --region $n.Region --output json --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw 'Identity check failed.' }
    if (($identityJson | ConvertFrom-Json).Account -ne $n.AccountId) { throw 'Wrong account.' }
    if ((Read-Host "Destroy cloudlink-dev in account $($n.AccountId), region $($n.Region)? Type DELETE") -cne 'DELETE') { throw 'Cancelled.' }
    aws cloudformation delete-stack --stack-name $n.StackName --region $n.Region --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw 'Delete request failed.' }
    aws cloudformation wait stack-delete-complete --stack-name $n.StackName --region $n.Region
    if ($LASTEXITCODE -ne 0) { throw 'Cleanup incomplete. Inspect stack events.' }
    Remove-Item infrastructure/network.local.json
}
```

Do not assume End Lab means persistent resources were deleted. Check your sandbox's rules. A full safe cleanup procedure for Johnny's manual setup remains pending.

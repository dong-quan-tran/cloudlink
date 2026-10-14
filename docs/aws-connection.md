# AWS Connection — PowerShell

GitHub access shares code, not AWS access. Use your own sandbox credentials.

## Sign in

1. Start the sandbox and wait for the green AWS indicator.
2. Open Details > Show for the access key ID, secret access key and session token.
3. Note the sandbox's current AWS region; do not switch it.
4. In the repository terminal run:

```powershell
.\scripts\connect-aws.ps1
aws sts get-caller-identity --no-cli-pager
```

Expected: `UserId`, `Account`, `Arn` for your sandbox. This confirms authentication, not every service permission.

```powershell
aws ec2 describe-instances --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name,PrivateIP:PrivateIpAddress}" --output table --no-cli-pager
```

A table confirms EC2 read access. Empty output without an error can mean no instances in the selected region. A failed command is not a successful empty result.

## Lifetime

The script uses environment variables in this terminal. It does not write credentials to a file. Run it again in a new terminal or when temporary credentials expire. SSH uses a separate PEM key. Do not put either credential type in Git.

## Disconnect this terminal

```powershell
Remove-Item Env:AWS_ACCESS_KEY_ID -ErrorAction SilentlyContinue
Remove-Item Env:AWS_SECRET_ACCESS_KEY -ErrorAction SilentlyContinue
Remove-Item Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue
```

This removes credentials from this process. It does not revoke them, end the sandbox session, stop servers, or prevent another configured AWS profile from being used later.

See the main README for installation, deployment, SSH key preparation and verification.

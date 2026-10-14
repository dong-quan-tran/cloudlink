$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$template = Join-Path $repo "infrastructure/cloudlink.yaml"
$stack = "cloudlink-dev"

# Ask for this developer's sandbox credentials.
& (Join-Path $PSScriptRoot "connect-aws.ps1")

function Invoke-CloudLinkAws {
    $result = & aws @args
    if ($LASTEXITCODE -ne 0) {
        throw "AWS command failed. Stop and check the error above."
    }
    return $result
}

$identity = Invoke-CloudLinkAws sts get-caller-identity --output json
$account = ($identity | ConvertFrom-Json).Account

Write-Host ""
Write-Host "Target account: $account"
Write-Host "Target region: $env:AWS_DEFAULT_REGION"
Write-Host "This creates or updates stack $stack with TWO EC2 instances."
Write-Host "It does not reuse Johnny's manually created resources."

if ((Read-Host "Type SETUP to continue") -cne "SETUP") {
    throw "Cancelled. No resources created."
}

Invoke-CloudLinkAws ec2 describe-key-pairs --key-names vockey --output json | Out-Null

# Reuse the stack's AMI on later runs to avoid unexpected replacements.
$stackList = Invoke-CloudLinkAws cloudformation list-stacks --query "StackSummaries[?StackName=='$stack' && StackStatus!='DELETE_COMPLETE']" --output json
$stacks = @($stackList | ConvertFrom-Json)
$ami = $null

if ($stacks.Count -gt 0) {
    $details = Invoke-CloudLinkAws cloudformation describe-stacks --stack-name $stack --output json
    $existing = ($details | ConvertFrom-Json).Stacks[0]
    if ($existing.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE")) {
        throw "Stack status is $($existing.StackStatus). Stop and inspect it in CloudFormation."
    }
    $ami = ($existing.Parameters | Where-Object ParameterKey -eq "AmiId").ParameterValue
}

if (-not $ami) {
    # Avoid making another copy if a manual CloudLink setup already exists.
    $oldVpcs = Invoke-CloudLinkAws ec2 describe-vpcs --filters "Name=tag:Name,Values=CloudLink-VPC" --query "Vpcs[].VpcId" --output json
    if (@($oldVpcs | ConvertFrom-Json).Count -gt 0) {
        throw "A CloudLink VPC already exists outside this stack. Stop to avoid duplicates."
    }

    $instances = Invoke-CloudLinkAws ec2 describe-instances --filters "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" --query "Reservations[].Instances[].InstanceId" --output json
    if (@($instances | ConvertFrom-Json).Count -gt 7) {
        throw "Not enough room for two instances under the sandbox's nine-instance limit."
    }

    $ami = Invoke-CloudLinkAws ec2 describe-images --owners amazon --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" "Name=root-device-type,Values=ebs" --query "sort_by(Images,&CreationDate)[-1].ImageId" --output text
}

if (-not $ami -or $ami -eq "None") {
    throw "Amazon Linux AMI not found."
}

$root = Invoke-CloudLinkAws ec2 describe-images --image-ids $ami --query "Images[0].RootDeviceName" --output text
$ip = (Invoke-RestMethod "https://checkip.amazonaws.com").Trim()
$parsed = [System.Net.IPAddress]::Parse($ip)
if ($parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "Could not find a public IPv4 address."
}

Invoke-CloudLinkAws cloudformation validate-template --template-body "file://$template" | Out-Null

Invoke-CloudLinkAws cloudformation deploy --template-file $template --stack-name $stack --parameter-overrides "AmiId=$ami" "RootDevice=$root" "SshCidr=$ip/32" "KeyName=vockey" --tags Project=CloudLink --no-fail-on-empty-changeset

$outputJson = Invoke-CloudLinkAws cloudformation describe-stacks --stack-name $stack --query "Stacks[0].Outputs" --output json
$settings = [ordered]@{
    Region = $env:AWS_DEFAULT_REGION
    AccountId = $account
    StackName = $stack
}

foreach ($item in ($outputJson | ConvertFrom-Json)) {
    $settings[$item.OutputKey] = $item.OutputValue
}

$localPath = Join-Path $repo "infrastructure/network.local.json"
$settings | ConvertTo-Json | Set-Content -Encoding UTF8 $localPath

Write-Host ""
Write-Host "AWS resources created. Server startup may still be finishing."
Write-Host "Local resource details:"
Get-Content $localPath
Write-Host ""
Write-Host "Next: download your sandbox PEM key and test SSH."
Write-Host "Then test port 8000 from the source server."
Write-Host "Do not claim the baseline passed until that test succeeds."

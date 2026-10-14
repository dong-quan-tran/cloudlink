param(
    [string]$SettingsPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'infrastructure/network.local.json'),
    [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh/cloudlink.pem')
)
$ErrorActionPreference = 'Stop'
foreach ($command in @('aws', 'ssh')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Missing command: $command" }
}
if (-not (Test-Path -LiteralPath $SettingsPath)) { throw 'Local settings missing. Run setup, or follow the manual-environment instructions in docs/operations.md.' }
if (-not (Test-Path -LiteralPath $KeyPath)) { throw 'SSH key missing. Follow the README key preparation steps.' }
$n = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
foreach ($name in @('Region', 'AccountId', 'SourceInstanceId', 'DestinationInstanceId')) {
    if (-not $n.$name) { throw "Settings missing $name. Do not guess resource IDs." }
}
$env:AWS_PAGER = ''
function Invoke-CheckedAws {
    $result = & aws @args
    if ($LASTEXITCODE -ne 0) { throw 'AWS check failed. Check credentials, region and permissions.' }
    return $result
}
$identity = (Invoke-CheckedAws sts get-caller-identity --region $n.Region --output json) | ConvertFrom-Json
if ($identity.Account -ne $n.AccountId) { throw 'Wrong AWS account for this local settings file. Reconnect with the correct sandbox.' }
Write-Host "API access OK: account $($identity.Account), region $($n.Region)"
$json = Invoke-CheckedAws ec2 describe-instances --region $n.Region --instance-ids $n.SourceInstanceId $n.DestinationInstanceId --output json
$instances = @((($json | ConvertFrom-Json).Reservations | ForEach-Object { $_.Instances }))
$source = $instances | Where-Object InstanceId -eq $n.SourceInstanceId
$destination = $instances | Where-Object InstanceId -eq $n.DestinationInstanceId
foreach ($instance in @($source, $destination)) {
    if (-not $instance -or $instance.State.Name -ne 'running') { throw 'Both project instances must be running. Inspect EC2 before continuing.' }
    if (-not $instance.PublicIpAddress) { throw 'An instance has no public IP. Inspect its network configuration.' }
}
if ($n.VpcId -and ($source.VpcId -ne $n.VpcId -or $destination.VpcId -ne $n.VpcId)) { throw 'Instance VPC does not match local settings.' }
foreach ($entry in @{
    SourcePublicIP = $source.PublicIpAddress
    SourcePrivateIP = $source.PrivateIpAddress
    DestinationPublicIP = $destination.PublicIpAddress
    DestinationPrivateIP = $destination.PrivateIpAddress
}.GetEnumerator()) {
    $n | Add-Member -NotePropertyName $entry.Key -NotePropertyValue $entry.Value -Force
}
$n | ConvertTo-Json | Set-Content -Encoding UTF8 $SettingsPath
$instances | Select-Object InstanceId, PrivateIpAddress, PublicIpAddress, @{Name='State';Expression={$_.State.Name}} | Format-Table | Out-Host
$sshOptions = @('-i', $KeyPath, '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3')
Write-Host 'Checking destination SSH, startup and local service (up to 180 seconds).'
& ssh @sshOptions "ec2-user@$($destination.PublicIpAddress)" 'sudo timeout 180 cloud-init status --wait && hostname && python3 --version && sudo systemctl is-active cloudlink-test && curl --silent --show-error --fail --retry 5 --retry-connrefused --retry-delay 2 --connect-timeout 5 --max-time 10 http://127.0.0.1:8000/'
if ($LASTEXITCODE -ne 0) { throw 'Destination check failed. See docs/operations.md for logs and recovery.' }
Write-Host 'Checking source SSH and source-to-destination HTTP.'
$response = & ssh @sshOptions "ec2-user@$($source.PublicIpAddress)" "curl --silent --show-error --fail --connect-timeout 5 --max-time 10 http://$($destination.PrivateIpAddress):8000/"
if ($LASTEXITCODE -ne 0) { throw 'Source-to-destination request failed. Check the service and network rules.' }
if (($response -join "`n").Trim() -ne 'CloudLink destination is healthy') { throw "Unexpected response: $response" }
Write-Host $response
Write-Host 'PASS: source reached destination on private TCP port 8000.'

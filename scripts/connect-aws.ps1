$ErrorActionPreference = 'Stop'
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw 'AWS CLI is missing. Install AWS CLI v2 and reopen your terminal.'
}
function Read-CloudLinkSecret {
    param([string]$Prompt)
    $secure = Read-Host $Prompt -AsSecureString
    $value = ([System.Net.NetworkCredential]::new('', $secure)).Password.Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { throw "$Prompt cannot be empty." }
    return $value
}
Write-Host 'Start your sandbox. Open Details > Show for CLI credentials.'
Write-Host 'Enter values only, without labels or quotes. Do not share them.'
$key = Read-CloudLinkSecret 'AWS access key ID'
$secret = Read-CloudLinkSecret 'AWS secret access key'
$token = Read-CloudLinkSecret 'AWS session token'
$region = (Read-Host 'Current sandbox region, for example us-east-1').Trim()
if ($region -notmatch '^[a-z]{2}(-[a-z]+)+-\d+$') { throw 'Invalid region code.' }
$env:AWS_ACCESS_KEY_ID = $key
$env:AWS_SECRET_ACCESS_KEY = $secret
$env:AWS_SESSION_TOKEN = $token
$env:AWS_DEFAULT_REGION = $region
$env:AWS_REGION = $region
$env:AWS_PAGER = ''
Remove-Variable key, secret, token
aws sts get-caller-identity --no-cli-pager
if ($LASTEXITCODE -ne 0) {
    Remove-Item Env:AWS_ACCESS_KEY_ID -ErrorAction SilentlyContinue
    Remove-Item Env:AWS_SECRET_ACCESS_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue
    throw 'Connection failed. Start the sandbox and enter fresh credentials.'
}
Write-Host "Connected in $region. Credentials apply only to this terminal and child processes."
Write-Host 'No resources were created and no credentials were written to disk by this script.'

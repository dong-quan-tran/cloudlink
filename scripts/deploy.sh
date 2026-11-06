#!/usr/bin/env bash
# Deploy the existing lab from your personal AWS account's CloudShell session.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
region=us-east-1
availability_zone=us-east-1a
management_cidr=
repository_url=https://github.com/dong-quan-tran/cloudlink.git
repository_ref=personal-account-deploy
enable_peer_ssh=false
ssh_key_name=
apply=false
confirm_account=

usage() {
  cat <<'HELP'
Usage: bash scripts/deploy.sh [options]

Options:
  --management-cidr IP/32  Public IP of YOUR computer allowed to SSH to the web instance.
                           If omitted, the script asks for it. Do not use CloudShell's IP.
  --apply                  Deploy after confirming the displayed AWS account.
  --confirm-account ID     Explicit account confirmation for non-interactive deployment.
  --key-name NAME          Optional existing administrator EC2 key pair; no key pair is required.
  --repository-url URL     Public GitHub repository cloned by the web instance.
  --repository-ref REF     Branch or tag installed on a new instance (default: personal-account-deploy).
  --enable-peer-ssh        Allow SSH banner checks between nodes A and B. By default
                           this port stays blocked as a troubleshooting example.
  --help                   Show this help.

Region and Availability Zone are fixed to us-east-1 and us-east-1a.
Without --apply this only checks access and prints the deployment plan.
The script deploys cloudlink-network, then cloudlink-web, then cloudlink-probes.
It uses the current CloudShell identity, not API keys stored in this repository.
The demo dashboard is public unauthenticated HTTP. Do not store sensitive data.
HELP
}

while (($#)); do
  case $1 in
    --management-cidr|--repository-url|--repository-ref|--key-name|--confirm-account)
      option=$1
      if (($# < 2)); then
        printf 'Missing value for %s\n' "$option" >&2
        exit 2
      fi
      case $option in
        --management-cidr) management_cidr=$2 ;;
        --repository-url) repository_url=$2 ;;
        --repository-ref) repository_ref=$2 ;;
        --key-name) ssh_key_name=$2 ;;
        --confirm-account) confirm_account=$2 ;;
      esac
      shift 2
      ;;
    --enable-peer-ssh)
      enable_peer_ssh=true
      shift
      ;;
    --apply)
      apply=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for program in aws curl python3; do
  if ! command -v "$program" >/dev/null 2>&1; then
    printf 'Required program not found: %s\n' "$program" >&2
    exit 1
  fi
done

if [[ -z $management_cidr ]]; then
  if [[ ! -t 0 ]]; then
    printf 'Pass --management-cidr YOUR_COMPUTER_PUBLIC_IP/32 (not CloudShell IP).\n' >&2
    exit 2
  fi
  printf 'Enter your computer\047s public IPv4 address with /32 (not CloudShell\047s IP): '
  read -r management_cidr
fi

python3 - "$management_cidr" "$repository_url" "$repository_ref" <<'PY'
import ipaddress
import re
import sys

try:
    network = ipaddress.ip_network(sys.argv[1], strict=True)
    if network.version != 4 or network.prefixlen != 32:
        raise ValueError("the management address must be one IPv4 address with /32")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", sys.argv[2]):
        raise ValueError("the repository URL must be a public GitHub HTTPS URL")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", sys.argv[3]):
        raise ValueError("the repository ref contains invalid characters")
except ValueError as error:
    sys.exit(f"Invalid input: {error}")
PY

aws_args=(--region "$region" --no-cli-pager)
account=$(python3 "$script_dir/cloudlink_stacks.py" account)
if [[ -n $ssh_key_name ]]; then
  aws ec2 describe-key-pairs "${aws_args[@]}" --key-names "$ssh_key_name" >/dev/null
fi
for instance_type in t3.micro; do
  offered=$(aws ec2 describe-instance-type-offerings "${aws_args[@]}" \
    --location-type availability-zone \
    --filters "Name=instance-type,Values=$instance_type" "Name=location,Values=$availability_zone" \
    --query 'length(InstanceTypeOfferings)' --output text)
  if [[ $offered != 1 ]]; then
    printf '%s is not offered in %s. No stacks deployed.\n' "$instance_type" "$availability_zone" >&2
    exit 1
  fi
done
for template in network.yaml web.yaml probes.yaml; do
  aws cloudformation validate-template "${aws_args[@]}" --template-body "file://$repo_dir/infra/$template" >/dev/null
done
printf 'Using AWS account %s in %s.\n' "$account" "$region"
printf 'Using Availability Zone %s for the web and probe subnets.\n' "$availability_zone"
printf 'Plan: cloudlink-network -> cloudlink-web -> cloudlink-probes.\n'
printf 'Compute: 3 x t3.micro, Amazon Linux 2023; 8 GiB gp3 each; Standard CPU credits.\n'
printf 'The dashboard will be public on HTTP port 80; web-instance SSH is limited to %s.\n' "$management_cidr"
if [[ $apply != true ]]; then
  printf 'Preview only. Add --apply when you are ready to deploy and incur charges.\n'
  exit 0
fi
if [[ -z $confirm_account ]]; then
  if [[ ! -t 0 ]]; then
    printf 'Pass --confirm-account %s or run interactively to confirm deployment.\n' "$account" >&2
    exit 2
  fi
  printf 'Type AWS account %s to deploy these stacks and incur charges: ' "$account"
  read -r confirm_account
fi
if [[ $confirm_account != "$account" ]]; then
  printf 'Account confirmation did not match. No stacks deployed.\n' >&2
  exit 2
fi
python3 "$script_dir/cloudlink_stacks.py" record --account "$account"

deploy_stack() {
  local name=$1 template=$2
  shift 2
  printf '\nDeploying %s...\n' "$name"
  aws cloudformation deploy "${aws_args[@]}" \
    --stack-name "$name" \
    --template-file "$repo_dir/infra/$template" \
    --no-fail-on-empty-changeset \
    --tags Project=CloudLink ManagedBy=cloudlink-personal "OwnerAccount=$account" \
    --parameter-overrides "$@"
}

stack_output() {
  aws cloudformation describe-stacks "${aws_args[@]}" \
    --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" \
    --output text
}

deploy_stack cloudlink-network network.yaml \
  "AvailabilityZone=$availability_zone" \
  "ManagementCidr=$management_cidr" \
  WebClientCidr=0.0.0.0/0 \
  "EnablePeerSsh=$enable_peer_ssh"

deploy_stack cloudlink-web web.yaml \
  NetworkStackName=cloudlink-network \
  "RepositoryUrl=$repository_url" \
  "RepositoryRef=$repository_ref" \
  "SshKeyName=$ssh_key_name"

web_url=$(stack_output cloudlink-web WebUrl)
if [[ -z $web_url || $web_url == None ]]; then
  printf 'The web stack did not return a URL. Inspect cloudlink-web in CloudFormation.\n' >&2
  exit 1
fi

# CloudFormation reports EC2 creation before its user-data finishes. The probe
# instances must not start until the web server is serving their SSH public key.
printf 'Waiting for the web instance to finish installing...\n'
web_ready=false
for ((attempt = 1; attempt <= 120; attempt++)); do
  if curl --silent --show-error --fail --connect-timeout 3 --max-time 5 \
      --output /dev/null "$web_url" 2>/dev/null; then
    web_ready=true
    break
  fi
  sleep 5
done
if [[ $web_ready != true ]]; then
  printf 'Web app did not respond at %s. Probe stack was NOT started.\n' "$web_url" >&2
  printf 'Check cloudlink-web EC2 user-data log (/var/log/cloud-init-output.log).\n' >&2
  exit 1
fi

deploy_stack cloudlink-probes probes.yaml NetworkStackName=cloudlink-network "SshKeyName=$ssh_key_name"

node_a=$(stack_output cloudlink-probes NodeAInstanceId)
node_b=$(stack_output cloudlink-probes NodeBInstanceId)
printf 'Waiting for the probe instances to pass AWS status checks...\n'
aws ec2 wait instance-status-ok "${aws_args[@]}" --instance-ids "$node_a" "$node_b"
probe_public_ips=$(aws ec2 describe-instances "${aws_args[@]}" \
  --instance-ids "$node_a" "$node_b" \
  --query 'Reservations[].Instances[].PublicIpAddress' --output text)

printf '\nCloudLink stacks deployed in account %s. Open: %s\n' "$account" "$web_url"
printf 'Node A: %s\n' "$node_a"
printf 'Node B: %s\n' "$node_b"
printf 'Peer-to-peer SSH banner tests enabled: %s\n' "$enable_peer_ssh"
if [[ -n $probe_public_ips && $probe_public_ips != None ]]; then
  printf 'WARNING: Existing probe instance(s) still have public IP(s): %s\n' "$probe_public_ips" >&2
  printf 'Private subnet settings affect new launches only; these probes must be replaced to remove their public IPs. This script does not replace them.\n' >&2
fi
printf 'Try A -> B: Ping and custom TCP port 8080. HTTP/HTTPS on 80/443 are intentionally not served by the probe nodes.\n'
printf 'Probe user-data may still be finishing; if the first test cannot reach the source, retry shortly.\n'
printf 'On an existing web stack, CloudFormation does not reinstall app code when its template is unchanged.\n'
printf 'When finished: bash scripts/teardown.sh --apply\n'

#!/usr/bin/env bash
# Deploy the disposable CloudLink lab from an AWS Academy CloudShell session.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
region=us-east-1
availability_zone=us-east-1a
management_cidr=
repository_url=https://github.com/dong-quan-tran/cloudlink.git
repository_ref=main
enable_peer_ssh=false

usage() {
  cat <<'HELP'
Usage: bash scripts/deploy-sandbox.sh [options]

Options:
  --management-cidr IP/32  Public IP of YOUR computer allowed to SSH to the web instance.
                           If omitted, the script asks for it. Do not use CloudShell's IP.
  --region REGION          AWS region (default: us-east-1).
  --availability-zone AZ   Zone supporting t3.micro (default: us-east-1a).
                           Choose a zone in --region; changing it requires a fresh network.
  --repository-url URL     Public GitHub repository cloned by the web instance.
  --repository-ref REF     Branch or tag installed on a new web instance (default: main).
  --enable-peer-ssh        Allow SSH banner checks between nodes A and B. By default
                           this port stays blocked as a troubleshooting example.
  --help                   Show this help.

The script deploys cloudlink-network, then cloudlink-web, then cloudlink-probes.
It updates existing stacks without deleting them. The public demo dashboard uses
unauthenticated HTTP on port 80; do not store sensitive information in this lab.
HELP
}

while (($#)); do
  case $1 in
    --management-cidr|--region|--availability-zone|--repository-url|--repository-ref)
      option=$1
      if (($# < 2)); then
        printf 'Missing value for %s\n' "$option" >&2
        exit 2
      fi
      case $option in
        --management-cidr) management_cidr=$2 ;;
        --region) region=$2 ;;
        --availability-zone) availability_zone=$2 ;;
        --repository-url) repository_url=$2 ;;
        --repository-ref) repository_ref=$2 ;;
      esac
      shift 2
      ;;
    --enable-peer-ssh)
      enable_peer_ssh=true
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

if [[ $availability_zone != "$region"[a-z] ]]; then
  printf 'Availability Zone %s must belong to region %s. Pass --availability-zone, for example %sa.\n' "$availability_zone" "$region" "$region" >&2
  exit 2
fi

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
printf 'Checking AWS Academy access in %s...\n' "$region"
account=$(aws sts get-caller-identity "${aws_args[@]}" --query Account --output text)
aws ec2 describe-key-pairs "${aws_args[@]}" --key-names vockey --query 'KeyPairs[0].KeyName' --output text >/dev/null
printf 'Using AWS account %s and the lab key pair vockey.\n' "$account"
printf 'Using Availability Zone %s for the web and probe subnets.\n' "$availability_zone"
printf 'The dashboard will be public on HTTP port 80; web-instance SSH is limited to %s.\n' "$management_cidr"

deploy_stack() {
  local name=$1 template=$2
  shift 2
  printf '\nDeploying %s...\n' "$name"
  aws cloudformation validate-template "${aws_args[@]}" --template-body "file://$repo_dir/infra/$template" >/dev/null
  aws cloudformation deploy "${aws_args[@]}" \
    --stack-name "$name" \
    --template-file "$repo_dir/infra/$template" \
    --no-fail-on-empty-changeset \
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
  "RepositoryRef=$repository_ref"

web_url=$(stack_output cloudlink-web WebUrl)
if [[ -z $web_url || $web_url == None ]]; then
  printf 'The web stack did not return a URL. Inspect cloudlink-web in CloudFormation.\n' >&2
  exit 1
fi

# CloudFormation reports EC2 creation before its user-data finishes. The probe
# instances must not start until the web server is serving their SSH public key.
printf 'Waiting for the web instance to finish installing...\n'
web_ready=false
for ((attempt = 1; attempt <= 60; attempt++)); do
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

deploy_stack cloudlink-probes probes.yaml NetworkStackName=cloudlink-network

node_a=$(stack_output cloudlink-probes NodeAInstanceId)
node_b=$(stack_output cloudlink-probes NodeBInstanceId)
printf 'Waiting for the probe instances to pass AWS status checks...\n'
aws ec2 wait instance-status-ok "${aws_args[@]}" --instance-ids "$node_a" "$node_b"
probe_public_ips=$(aws ec2 describe-instances "${aws_args[@]}" \
  --instance-ids "$node_a" "$node_b" \
  --query 'Reservations[].Instances[].PublicIpAddress' --output text)

printf '\nCloudLink stacks deployed. Open: %s\n' "$web_url"
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

#!/usr/bin/env bash
# Run from your personal AWS account's CloudShell.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)
region=us-east-1
availability_zone=us-east-1a
repository_url=https://github.com/dong-quan-tran/cloudlink.git
repository_ref=personal-account-deploy
enable_peer_ssh=false

read -r -p "Enter your computer's public IPv4 address with /32 (not CloudShell's IP): " management_cidr
if [[ ! $management_cidr =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ ]]; then
  printf 'Enter one IPv4 address followed by /32.\n' >&2
  exit 1
fi
IFS=. read -r a b c d <<< "${management_cidr%/32}"
for octet in "$a" "$b" "$c" "$d"; do
  if ((10#$octet > 255)); then
    printf 'Invalid IPv4 address.\n' >&2
    exit 1
  fi
done

aws_args=(--region "$region" --no-cli-pager)
account=$(aws sts get-caller-identity "${aws_args[@]}" --query Account --output text)
printf 'Using AWS account %s in %s.\n' "$account" "$region"
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
  "RepositoryRef=$repository_ref" \
  'SshKeyName='

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

deploy_stack cloudlink-probes probes.yaml NetworkStackName=cloudlink-network 'SshKeyName='

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
printf 'When finished: bash scripts/teardown.sh\n'

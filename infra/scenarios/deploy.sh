#!/usr/bin/env bash
# Run in the personal account where CloudLink is already deployed.
set -Eeuo pipefail

usage() {
  cat <<'HELP'
Usage: bash infra/scenarios/deploy.sh SCENARIO
  private-subnets | sg-block-8080 | nacl-block-8080
  peering-working | peering-missing-route | delete

Only one scenario runs at a time. Choosing another deletes the previous
scenario stack before creating the new one. Existing CloudLink stacks stay.
HELP
}

[[ $# == 1 ]] || { usage >&2; exit 1; }
scenario=$1
case "$scenario" in
  -h|--help) usage; exit 0 ;;
  private-subnets|sg-block-8080|nacl-block-8080|peering-working|peering-missing-route|delete) ;;
  *) usage >&2; exit 1 ;;
esac

for tool in aws python3; do
  command -v "$tool" >/dev/null || { printf 'Required command: %s\n' "$tool" >&2; exit 1; }
done

scenario_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
stack=cloudlink-scenario
network_stack=cloudlink-network
services_stack=cloudlink-services
aws_args=(--region us-east-1 --no-cli-pager)
account=$(aws sts get-caller-identity "${aws_args[@]}" --query Account --output text)
printf 'Account %s, us-east-1. Selected scenario: %s\n' "$account" "$scenario"

exists=false
state=
active_scenario=
if details=$(aws cloudformation describe-stacks "${aws_args[@]}" --stack-name "$stack" --output json 2>&1); then
  exists=true
  read -r state owner project active_scenario < <(python3 -c '
import json, sys
stack = json.load(sys.stdin)["Stacks"][0]
tags = {item["Key"]: item["Value"] for item in stack.get("Tags", [])}
print(stack["StackStatus"], tags.get("ManagedBy", "missing"),
      tags.get("Project", "missing"), tags.get("Scenario", "missing"))
' <<< "$details")
  if [[ $owner != CloudLinkScenarios || $project != CloudLink ]]; then
    printf 'Refusing to change %s: scenario ownership tags do not match.\n' "$stack" >&2
    exit 1
  fi
  if [[ $state == *_IN_PROGRESS && $state != DELETE_IN_PROGRESS ]]; then
    printf '%s is %s. Wait for it to finish, then retry.\n' "$stack" "$state" >&2
    exit 1
  fi
elif [[ $details != *'(ValidationError)'*'does not exist'* ]]; then
  printf '%s\n' "$details" >&2
  exit 1
fi

delete_scenario() {
  if [[ $exists == true ]]; then
    printf 'Removing scenario %s (%s)...\n' "$active_scenario" "$stack"
    if [[ $state != DELETE_IN_PROGRESS ]]; then
      aws cloudformation delete-stack "${aws_args[@]}" --stack-name "$stack"
    fi
    aws cloudformation wait stack-delete-complete "${aws_args[@]}" --stack-name "$stack"
    exists=false
  fi
}

if [[ $scenario == delete ]]; then
  delete_scenario
  printf 'Scenario removed. Existing CloudLink stacks were kept.\n'
  exit 0
fi

# Check prerequisites and the new template before deleting a running scenario.
template="$scenario_dir/$scenario.yaml"
aws cloudformation validate-template "${aws_args[@]}" --template-body "file://$template" >/dev/null
for dependency in "$network_stack" "$services_stack"; do
  dependency_state=$(aws cloudformation describe-stacks "${aws_args[@]}" --stack-name "$dependency" \
    --query 'Stacks[0].StackStatus' --output text)
  case "$dependency_state" in
    CREATE_COMPLETE|UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE) ;;
    *) printf '%s is not ready: %s\n' "$dependency" "$dependency_state" >&2; exit 1 ;;
  esac
done

app_route_table() {
  aws cloudformation describe-stack-resource "${aws_args[@]}" --stack-name "$network_stack" \
    --logical-resource-id "$1" --query 'StackResourceDetail.PhysicalResourceId' --output text
}
route_a=$(app_route_table AppRoutesA)
route_b=$(app_route_table AppRoutesB)
[[ $route_a =~ ^rtb-[0-9a-f]+$ && $route_b =~ ^rtb-[0-9a-f]+$ && $route_a != "$route_b" ]] || {
  printf 'Could not find the two existing CloudLink app route tables.\n' >&2
  exit 1
}

if [[ $exists == true && ( $active_scenario != "$scenario" || $state == ROLLBACK_COMPLETE || $state == CREATE_FAILED || $state == DELETE_* ) ]]; then
  delete_scenario
fi

printf 'Deploying %s. Adds private management routes; does not redeploy the app.\n' "$scenario"
if ! aws cloudformation deploy "${aws_args[@]}" --stack-name "$stack" \
  --template-file "$template" --no-fail-on-empty-changeset \
  --parameter-overrides "NetworkStackName=$network_stack" "ServicesStackName=$services_stack" \
    "AppRouteTableAId=$route_a" "AppRouteTableBId=$route_b" \
  --tags Project=CloudLink ManagedBy=CloudLinkScenarios "Scenario=$scenario"; then
  printf 'Inspect the failure: aws cloudformation describe-stack-events --region us-east-1 --stack-name %s\n' "$stack" >&2
  exit 1
fi

node_a=$(aws cloudformation describe-stack-resource "${aws_args[@]}" --stack-name "$stack" \
  --logical-resource-id InstanceA --query 'StackResourceDetail.PhysicalResourceId' --output text)
node_b=$(aws cloudformation describe-stack-resource "${aws_args[@]}" --stack-name "$stack" \
  --logical-resource-id InstanceB --query 'StackResourceDetail.PhysicalResourceId' --output text)
printf 'Waiting for both probes to pass EC2 status checks...\n'
aws ec2 wait instance-status-ok "${aws_args[@]}" --instance-ids "$node_a" "$node_b"
aws cloudformation describe-stacks "${aws_args[@]}" --stack-name "$stack" \
  --query 'Stacks[0].Outputs[].{Item:OutputKey,Value:OutputValue}' --output table
printf '\nIn CloudLink, refresh the probe list and select the %s probes.\n' "$scenario"
printf 'Use private IP, Ping, and Custom TCP port 8080. Test both directions.\n'
printf 'Outputs above are expected results, not live test results. If boot is still finishing, retry shortly.\n'
printf 'Cleanup: bash infra/scenarios/deploy.sh delete\n'

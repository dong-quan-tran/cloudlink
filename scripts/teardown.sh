#!/usr/bin/env bash
# Delete only the three CloudLink stacks, in reverse deployment order.
set -Eeuo pipefail
aws_args=(--region us-east-1 --no-cli-pager)
account=$(aws sts get-caller-identity "${aws_args[@]}" --query Account --output text)
printf 'Account %s, us-east-1: delete cloudlink-probes, cloudlink-web, and cloudlink-network.\n' "$account"
printf 'This also deletes the web instance and its local history.\n'
read -r -p 'Type delete to continue: ' confirmation
[[ $confirmation == delete ]] || exit 1

for stack in cloudlink-probes cloudlink-web cloudlink-network; do
  if details=$(aws cloudformation describe-stacks "${aws_args[@]}" --stack-name "$stack" 2>&1); then
    printf 'Deleting %s...\n' "$stack"
    aws cloudformation delete-stack "${aws_args[@]}" --stack-name "$stack"
    aws cloudformation wait stack-delete-complete "${aws_args[@]}" --stack-name "$stack"
  elif [[ $details == *'(ValidationError)'*'does not exist'* ]]; then
    printf '%s does not exist; skipping.\n' "$stack"
  else
    printf '%s\n' "$details" >&2
    exit 1
  fi
done
printf 'CloudLink stack teardown complete.\n'

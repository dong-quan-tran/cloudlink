#!/usr/bin/env bash
# Run in your personal account's CloudShell. No options or API keys required.
set -Eeuo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
aws_args=(--region us-east-1 --no-cli-pager)
account=$(aws sts get-caller-identity "${aws_args[@]}" --query Account --output text)
revision=$(git -C "$repo_dir" rev-parse HEAD)
printf 'Deploying CloudLink in account %s, us-east-1.\n' "$account"

# AWS manages the CloudFront address ranges; look up their regional prefix list.
prefix_list=$(aws ec2 describe-managed-prefix-lists "${aws_args[@]}" \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)
if [[ -z $prefix_list || $prefix_list == None ]]; then
  printf 'CloudFront origin prefix list was not found.\n' >&2
  exit 1
fi

for template in network services probes web; do
  aws cloudformation validate-template "${aws_args[@]}" --template-body "file://$repo_dir/infra/$template.yaml" >/dev/null
done

deploy_stack() {
  local name=$1 template=$2
  shift 2
  aws cloudformation deploy "${aws_args[@]}" \
    --stack-name "$name" --template-file "$repo_dir/infra/$template.yaml" \
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset "$@"
}

deploy_stack cloudlink-network network --parameter-overrides "CloudFrontPrefixListId=$prefix_list"
deploy_stack cloudlink-services services
deploy_stack cloudlink-probes probes
deploy_stack cloudlink-web web --parameter-overrides "RepositoryCommit=$revision"

url=$(aws cloudformation describe-stacks "${aws_args[@]}" --stack-name cloudlink-web \
  --query "Stacks[0].Outputs[?OutputKey=='WebUrl'].OutputValue | [0]" --output text)
printf '\nCloudLink: %s\n' "$url"
printf 'When finished: bash scripts/teardown.sh\n'

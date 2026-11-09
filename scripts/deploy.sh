#!/usr/bin/env bash
# Run in your personal account's CloudShell. No options or API keys required.
set -Eeuo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
branch=$(git -C "$repo_dir" branch --show-current)
if [[ -z $branch ]]; then
  printf 'Check out a branch before deploying CloudLink.\n' >&2
  exit 1
fi
aws_args=(--region us-east-1 --no-cli-pager)
account=$(aws sts get-caller-identity "${aws_args[@]}" --query Account --output text)
printf 'Deploying CloudLink branch %s in account %s, us-east-1.\n' "$branch" "$account"

# AWS manages the CloudFront address ranges; look up their regional prefix list.
prefix_list=$(aws ec2 describe-managed-prefix-lists "${aws_args[@]}" \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)
if [[ -z $prefix_list || $prefix_list == None ]]; then
  printf 'CloudFront origin prefix list was not found.\n' >&2
  exit 1
fi

for template in network services scenarios/shared-vpcs scenarios/single-vpc scenarios/peering web; do
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
deploy_stack cloudlink-demo-network scenarios/shared-vpcs

for scenario in healthy-private-subnets sg-block-8080 nacl-block-8080; do
  deploy_stack "cloudlink-demo-$scenario" scenarios/single-vpc --parameter-overrides "Scenario=$scenario"
done
for scenario in peering-working peering-missing-forward-route peering-missing-return-route \
                wrong-route-table-association multiple-blockers; do
  deploy_stack "cloudlink-demo-$scenario" scenarios/peering --parameter-overrides "Scenario=$scenario"
done

deploy_stack cloudlink-web web --parameter-overrides "RepositoryBranch=$branch"

url=$(aws cloudformation describe-stacks "${aws_args[@]}" --stack-name cloudlink-web \
  --query "Stacks[0].Outputs[?OutputKey=='WebUrl'].OutputValue | [0]" --output text)
printf '\nCloudLink: %s\n' "$url"
printf 'When finished: bash scripts/teardown.sh\n'

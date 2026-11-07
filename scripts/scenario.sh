#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

PS3='Choose a scenario number: '
select scenario in Healthy MissingForwardRoute MissingReturnRoute SecurityGroupBlock AclReplyBlock NoListener MultipleBlockers Cancel; do
  if [[ -z $scenario ]]; then
    printf 'Enter a number from the menu.\n' >&2
    continue
  fi
  [[ $scenario != Cancel ]] || exit 0

  aws cloudformation deploy --region us-east-1 --no-cli-pager \
    --stack-name cloudlink-scenarios \
    --template-file "$repo_dir/infra/scenarios.yaml" \
    --parameter-overrides "Scenario=$scenario" --no-fail-on-empty-changeset

  port=8080
  if [[ $scenario == NoListener ]]; then
    port=8081
  fi
  printf '\n%s is active. In CloudLink, test Node A → CloudLink-Scenario-Node on TCP %s.\n' "$scenario" "$port"
  break
done
exit 0

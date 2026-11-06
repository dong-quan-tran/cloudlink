#!/usr/bin/env bash
# Preview by default; --apply and an exact account/Region confirmation delete.
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$script_dir/cloudlink_stacks.py" destroy "$@"

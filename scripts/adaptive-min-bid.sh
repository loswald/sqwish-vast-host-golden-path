#!/usr/bin/env bash

# Compute a guarded lower-market interruptible floor. The Python engine owns all
# Vast CLI calls so the apply path has one auditable mutation command.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

load_env_file
require_cmd python3
require_cmd vastai

state_root="$(ensure_state_dir)"
export VAST_STATE_DIR="$state_root"
exec python3 "${PROJECT_DIR}/tools/adaptive_pricing.py" "$@"

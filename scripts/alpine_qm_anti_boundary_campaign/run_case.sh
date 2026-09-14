#!/usr/bin/env bash
set -euo pipefail
export NADOC_CAMPAIGN_REMOTE_ROOT=${NADOC_CAMPAIGN_REMOTE_ROOT:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-anti-boundary-opt-v1}
exec bash "$NADOC_CAMPAIGN_REMOTE_ROOT/bundle/shared_run_case.sh"

#!/usr/bin/env bash
set -euo pipefail
remote_root=${NADOC_CAMPAIGN_REMOTE_ROOT:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-cis-syn-boundary-opt-v1}
export NADOC_CAMPAIGN_REMOTE_ROOT="$remote_root"
exec bash "$remote_root/bundle/shared_run_case.sh"

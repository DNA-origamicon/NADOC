#!/usr/bin/env bash
set -euo pipefail

syn_root=${1:?syn optimization campaign root is required}
anti_root=${2:?anti optimization campaign root is required}
canonical_root=${3:?canonical cis-syn optimization campaign root is required}
output_root=${4:?ESP campaign output root is required}
remote_root=${5:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-esp-v1}
log="$output_root.service.log"

printf '%s waiting for all three passed optimization collections\n' "$(date --iso-8601=seconds)" > "$log"
until jq -e '(.schema == "nadoc.photoproduct-alpine-boundary-optimization-collection.v1")' \
  "$syn_root/collection_report.json" >/dev/null 2>&1 && \
  jq -e '(.schema == "nadoc.photoproduct-alpine-boundary-optimization-collection.v1")' \
  "$anti_root/collection_report.json" >/dev/null 2>&1 && \
  jq -e '(.schema == "nadoc.photoproduct-alpine-boundary-optimization-collection.v1")' \
  "$canonical_root/collection_report.json" >/dev/null 2>&1; do
  sleep 30
done
printf '%s collections present; building fail-closed ESP campaign\n' "$(date --iso-8601=seconds)" >> "$log"
uv run python scripts/alpine_qm_boundary_esp_campaign/build_campaign.py \
  --optimization-campaign "$syn_root" \
  --optimization-campaign "$anti_root" \
  --optimization-campaign "$canonical_root" \
  --output-root "$output_root" >> "$log" 2>&1
printf '%s campaign built; waiting for Alpine control connection\n' "$(date --iso-8601=seconds)" >> "$log"
host=${ALPINE_HOST:-jojo6687@login.rc.colorado.edu}
control_socket=${ALPINE_CONTROL_SOCKET:-/tmp/nadoc-alpine-$(id -u)/control.sock}
while ! ssh -S "$control_socket" -O check "$host" >/dev/null 2>&1; do
  sleep 30
done
bash scripts/alpine_qm_boundary_esp_campaign/submit_from_local.sh \
  "$output_root" "$remote_root" >> "$log" 2>&1
printf '%s ESP campaign submitted; collecting\n' "$(date --iso-8601=seconds)" >> "$log"
exec bash scripts/alpine_qm_boundary_esp_campaign/watch_and_collect.sh "$output_root"

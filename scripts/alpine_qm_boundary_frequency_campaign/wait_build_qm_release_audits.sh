#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 SYN_OPT ANTI_OPT CANONICAL_OPT FREQUENCY_CAMPAIGN OUTPUT_DIR" >&2
  exit 2
fi

syn_opt=$1
anti_opt=$2
canonical_opt=$3
frequency=$4
output=$5
repository=/home/jojo/Work/NADOC
storage_root=/media/jojo/Archive/NADOC_archive
policy="$repository/backend/data/forcefield/photoproduct_parameter_acceptance.json"

for path in "$syn_opt" "$anti_opt" "$canonical_opt" "$frequency" "$output"; do
  case "$(realpath -m "$path")" in
    "$storage_root"/*) ;;
    *) echo "durable path escapes Archive storage: $path" >&2; exit 3 ;;
  esac
done

while true; do
  ready=true
  for campaign in "$syn_opt" "$anti_opt" "$canonical_opt" "$frequency"; do
    if [[ ! -f "$campaign/collection_report.json" ]]; then
      ready=false
    fi
  done
  [[ $ready == true ]] && break
  sleep 60
done

if [[ -f "$output/all_form_qm_reference_audit.json" ]]; then
  echo "QM release audit already exists; refusing to regenerate: $output" >&2
  exit 4
fi

cd "$repository"
exec uv run python scripts/photoproduct_workflow.py \
  --storage-root "$storage_root" \
  build-boundary-qm-release-audits \
  --optimization-campaign "$syn_opt" \
  --optimization-campaign "$anti_opt" \
  --optimization-campaign "$canonical_opt" \
  --frequency-campaign "$frequency" \
  --acceptance-policy "$policy" \
  --output-dir "$output"

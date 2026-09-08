#!/usr/bin/env bash
set -euo pipefail

syn_root=${1:?syn optimization campaign root is required}
anti_root=${2:?anti optimization campaign root is required}
canonical_root=${3:?canonical cis-syn optimization campaign root is required}
frequency_root=${4:?frequency campaign root is required}
output_root=${5:?boundary fit-input output root is required}
log="$output_root.service.log"

printf '%s waiting for all-eight passed boundary frequency collection\n' \
  "$(date --iso-8601=seconds)" > "$log"
until jq -e '
  .schema == "nadoc.photoproduct-alpine-boundary-frequency-collection.v1" and
  .status == "passed_harmonic_minimum_audits" and
  .product_count == 8 and .passed_product_count == 8
' "$frequency_root/collection_report.json" >/dev/null 2>&1; do
  sleep 30
done

printf '%s frequency evidence passed; materializing boundary fit inputs\n' \
  "$(date --iso-8601=seconds)" >> "$log"
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  build-boundary-fit-inputs \
  --optimization-campaign "$syn_root" \
  --optimization-campaign "$anti_root" \
  --optimization-campaign "$canonical_root" \
  --frequency-campaign "$frequency_root" \
  --output-dir "$output_root" >> "$log" 2>&1
printf '%s model/Hessian inputs complete; freezing nonbonded boundaries\n' \
  "$(date --iso-8601=seconds)" >> "$log"
cgenff_root=/media/jojo/Archive/NADOC_archive/reference_forcefields/toppar_c36_feb26/toppar
while IFS= read -r product_id; do
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    build-boundary-nonbonded-specification \
    --model-manifest "$output_root/$product_id/model/model_manifest.json" \
    --nucleic-topology backend/data/forcefield/top_all36_na.rtf \
    --cgenff-topology "$cgenff_root/top_all36_cgenff.rtf" \
    --cgenff-parameters "$cgenff_root/par_all36_cgenff.prm" \
    --output "$output_root/$product_id/nonbonded_specification.json" >> "$log" 2>&1
done < <(jq -r '.products[].product_id' "$output_root/campaign_manifest.json")
printf '%s boundary fit inputs and nonbonded specifications complete\n' \
  "$(date --iso-8601=seconds)" >> "$log"

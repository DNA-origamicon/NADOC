#!/usr/bin/env bash
set -euo pipefail

fit_root=${1:?boundary fit-input root is required}
esp_root=${2:?boundary ESP campaign root is required}
water_root=${3:?boundary water campaign root is required}
log="$fit_root.boundary-charge-fit.service.log"

printf '%s waiting for fit inputs plus passed all-eight ESP/water collections\n' \
  "$(date --iso-8601=seconds)" > "$log"
until jq -e '
  .schema == "nadoc.photoproduct-boundary-fit-input-campaign.v1" and
  .status == "passed_fit_input_materialization" and .product_count == 8
' "$fit_root/campaign_manifest.json" >/dev/null 2>&1 && \
  jq -e '
  .schema == "nadoc.photoproduct-alpine-boundary-esp-collection.v1" and
  .status == "passed_esp_import_and_audits" and .passed_product_count == 8
' "$esp_root/collection_report.json" >/dev/null 2>&1 && \
  jq -e '
  .schema == "nadoc.photoproduct-alpine-water-collection.v1" and
  .status == "passed_import_and_curve_audits" and .product_count == 8
' "$water_root/collection_report.json" >/dev/null 2>&1; do
  sleep 30
done

printf '%s evidence complete; fitting full-boundary charge candidates\n' \
  "$(date --iso-8601=seconds)" >> "$log"
cgenff_root=/media/jojo/Archive/NADOC_archive/reference_forcefields/toppar_c36_feb26/toppar
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  fit-boundary-charge-campaign \
  --fit-input-root "$fit_root" \
  --esp-campaign "$esp_root" \
  --water-campaign "$water_root" \
  --cgenff-parameters "$cgenff_root/par_all36_cgenff.prm" \
  --nucleic-parameters backend/data/forcefield/par_all36_na.prm >> "$log" 2>&1
printf '%s boundary charge campaign complete\n' "$(date --iso-8601=seconds)" >> "$log"

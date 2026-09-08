#!/usr/bin/env bash
set -u

fit_root=${1:?boundary fit-input root is required}
log="$fit_root.boundary-candidate-smoke.service.log"
cgenff_root=/media/jojo/Archive/NADOC_archive/reference_forcefields/toppar_c36_feb26/toppar
assembly_policy=backend/data/forcefield/photoproduct_candidate_assembly_policy_v3.json
psfgen=/home/jojo/Applications/NAMD_3.0.2/psfgen
namd=/home/jojo/Applications/NAMD_3.0.2/namd3

printf '%s waiting for all-eight physical boundary bonded fits\n' \
  "$(date --iso-8601=seconds)" > "$log"
while true; do
  ready=$(find "$fit_root" -mindepth 3 -maxdepth 4 -type f \
    \( -path '*/bonded/bonded_fit/boundary_bonded_fit.json' \
       -o -path '*/bonded/failed.txt' \) 2>/dev/null | wc -l)
  [[ "$ready" == "8" ]] && break
  sleep 30
done

passed=0
failed=0
while IFS= read -r product_id; do
  product_root="$fit_root/$product_id"
  bonded_root="$product_root/bonded"
  candidate_root="$product_root/candidate"
  if [[ ! -f "$bonded_root/bonded_fit/boundary_bonded_fit.json" ]]; then
    mkdir -p "$candidate_root"
    printf '%s bonded fitting failed closed\n' "$(date --iso-8601=seconds)" \
      > "$candidate_root/failed.txt"
    failed=$((failed + 1))
    printf '%s %s skipped because bonded fitting failed closed\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
    continue
  fi
  boundary_model=$(jq -r '.sources.screened_boundary_model.path' \
    "$product_root/model/model_manifest.json")
  printf '%s %s assembling full-boundary CHARMM candidate\n' \
    "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  if (
    set -e
    uv run python scripts/photoproduct_workflow.py \
      --storage-root /media/jojo/Archive/NADOC_archive \
      assemble-quantitative-parameter-workbook \
      --fit-plan "$bonded_root/fit_plan.json" \
      --nonbonded-fit "$product_root/boundary_charge_fit.json" \
      --charmm-transform "$bonded_root/bonded_fit/charmm_bonded_transform.json" \
      --dna-boundary-model "$boundary_model" \
      --cgenff-topology "$cgenff_root/top_all36_cgenff.rtf" \
      --cgenff-parameters "$cgenff_root/par_all36_cgenff.prm" \
      --policy "$assembly_policy" \
      --output "$candidate_root/parameter_workbook.json" >> "$log" 2>&1
    uv run python scripts/photoproduct_workflow.py \
      --storage-root /media/jojo/Archive/NADOC_archive \
      audit-parameter-workbook \
      --workbook "$candidate_root/parameter_workbook.json" \
      --output "$candidate_root/parameter_workbook_audit.json" >> "$log" 2>&1
    uv run python scripts/photoproduct_workflow.py \
      --storage-root /media/jojo/Archive/NADOC_archive \
      export-charmm-candidate \
      --workbook "$candidate_root/parameter_workbook.json" \
      --workbook-audit "$candidate_root/parameter_workbook_audit.json" \
      --variant-id "$product_id-full-boundary-v1" \
      --output-dir "$candidate_root/charmm" >> "$log" 2>&1
    uv run python scripts/photoproduct_workflow.py \
      --storage-root /media/jojo/Archive/NADOC_archive \
      build-candidate-context-topology \
      --fixture reciprocal-crossover-1xt \
      --candidate-manifest "$candidate_root/charmm/candidate_manifest.json" \
      --psfgen "$psfgen" \
      --output-dir "$candidate_root/context_topology_reciprocal_1xT" >> "$log" 2>&1
    uv run python scripts/photoproduct_workflow.py \
      --storage-root /media/jojo/Archive/NADOC_archive \
      run-candidate-engine-smoke \
      --candidate-manifest "$candidate_root/charmm/candidate_manifest.json" \
      --dna-boundary-model "$boundary_model" \
      --nucleic-topology backend/data/forcefield/top_all36_na.rtf \
      --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
      --psfgen "$psfgen" \
      --namd "$namd" \
      --minimize-steps 2000 \
      --dynamics-steps 50000 \
      --output-dir "$candidate_root/engine_smoke_100ps" >> "$log" 2>&1
  ); then
    passed=$((passed + 1))
    printf '%s %s real 100 ps NAMD candidate smoke passed\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  else
    mkdir -p "$candidate_root"
    printf '%s candidate assembly or vacuum smoke failed closed\n' \
      "$(date --iso-8601=seconds)" > "$candidate_root/failed.txt"
    failed=$((failed + 1))
    printf '%s %s candidate assembly or smoke failed closed; continuing\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  fi
done < <(jq -r '.products[].product_id' "$fit_root/campaign_manifest.json" | sort)
printf '%s candidate smokes complete: passed=%s failed=%s\n' \
  "$(date --iso-8601=seconds)" "$passed" "$failed" >> "$log"
[[ "$failed" == "0" ]]

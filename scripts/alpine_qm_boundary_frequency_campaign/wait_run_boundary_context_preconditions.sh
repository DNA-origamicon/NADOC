#!/usr/bin/env bash
set -u

fit_root=${1:?boundary fit-input root is required}
qm_release_root=${2:?QM release root is required}
log="$fit_root.boundary-context-precondition.service.log"
psfgen=/home/jojo/Applications/NAMD_3.0.2/psfgen
namd=/home/jojo/Applications/NAMD_3.0.2/namd3
policy=backend/data/forcefield/photoproduct_context_precondition_policy.json

printf '%s waiting for all-eight candidate manifests and QM release reports\n' \
  "$(date --iso-8601=seconds)" > "$log"
while true; do
  ready=0
  if [[ -f "$fit_root/campaign_manifest.json" ]]; then
    while IFS= read -r product_id; do
      candidate="$fit_root/$product_id/candidate/charmm/candidate_manifest.json"
      release="$qm_release_root/$product_id/qm_reference_report.json"
      if jq -e '.schema == "nadoc.photoproduct-charmm-candidate.v1"' \
        "$candidate" >/dev/null 2>&1 && \
        jq -e '.schema == "nadoc.photoproduct-qm-reference-release-audit.v1" and .passed == true' \
        "$release" >/dev/null 2>&1; then
        ready=$((ready + 1))
      fi
    done < <(jq -r '.products[].product_id' "$fit_root/campaign_manifest.json")
  fi
  [[ "$ready" == "8" ]] && break
  sleep 30
done

passed=0
failed=0
while IFS= read -r product_id; do
  product_root="$fit_root/$product_id"
  for fixture in reciprocal-crossover-1xt adjacent-intrastrand antiparallel-interstrand; do
    output="$product_root/candidate/context_precondition_$fixture"
    printf '%s %s/%s fitting QM product and running local real-NAMD precondition\n' \
      "$(date --iso-8601=seconds)" "$product_id" "$fixture" >> "$log"
    if uv run python scripts/photoproduct_workflow.py \
      --storage-root /media/jojo/Archive/NADOC_archive \
      run-candidate-context-precondition \
      --fixture "$fixture" \
      --candidate-manifest "$product_root/candidate/charmm/candidate_manifest.json" \
      --dna-boundary-model "$product_root/model/model_manifest.json" \
      --qm-release-report "$qm_release_root/$product_id/qm_reference_report.json" \
      --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
      --psfgen "$psfgen" \
      --namd "$namd" \
      --policy "$policy" \
      --output-dir "$output" >> "$log" 2>&1; then
      printf '%s %s/%s context precondition passed\n' \
        "$(date --iso-8601=seconds)" "$product_id" "$fixture" >> "$log"
      solution="$product_root/candidate/context_solution_smoke_$fixture"
      if uv run python scripts/photoproduct_workflow.py \
        --storage-root /media/jojo/Archive/NADOC_archive \
        run-candidate-context-solution-smoke \
        --candidate-manifest "$product_root/candidate/charmm/candidate_manifest.json" \
        --precondition-report "$output/candidate_context_precondition.json" \
        --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
        --water-parameters backend/data/forcefield/toppar_water_ions_cufix.str \
        --ion-nbfix-parameters backend/data/forcefield/par_stub_ions_nbfix.str \
        --namd "$namd" \
        --padding-nm 1.2 \
        --ion-conc-mm 150 \
        --minimize-steps 5000 \
        --heat-steps 5000 \
        --dynamics-steps 5000 \
        --output-dir "$solution" >> "$log" 2>&1; then
        passed=$((passed + 1))
        printf '%s %s/%s short explicit-solution context smoke passed\n' \
          "$(date --iso-8601=seconds)" "$product_id" "$fixture" >> "$log"
      else
        mkdir -p "$solution"
        printf '%s context solution smoke failed closed; see service log\n' \
          "$(date --iso-8601=seconds)" > "$solution/failed.txt"
        failed=$((failed + 1))
        printf '%s %s/%s context solution smoke failed closed; continuing\n' \
          "$(date --iso-8601=seconds)" "$product_id" "$fixture" >> "$log"
      fi
    else
      mkdir -p "$output"
      printf '%s context precondition failed closed; see service log\n' \
        "$(date --iso-8601=seconds)" > "$output/failed.txt"
      failed=$((failed + 1))
      printf '%s %s/%s context precondition failed closed; continuing\n' \
        "$(date --iso-8601=seconds)" "$product_id" "$fixture" >> "$log"
    fi
  done
done < <(jq -r '.products[].product_id' "$fit_root/campaign_manifest.json" | sort)
printf '%s 24 context preconditions complete: passed=%s failed=%s\n' \
  "$(date --iso-8601=seconds)" "$passed" "$failed" >> "$log"
[[ "$failed" == "0" ]]

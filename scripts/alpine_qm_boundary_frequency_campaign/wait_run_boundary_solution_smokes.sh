#!/usr/bin/env bash
set -u

fit_root=${1:?boundary fit-input root is required}
log="$fit_root.boundary-candidate-solution-smoke.service.log"
namd=/home/jojo/Applications/NAMD_3.0.2/namd3

printf '%s waiting for all-eight vacuum candidate outcomes\n' \
  "$(date --iso-8601=seconds)" > "$log"
while true; do
  ready=$(find "$fit_root" -mindepth 3 -maxdepth 5 -type f \
    \( -path '*/candidate/engine_smoke_100ps/candidate_engine_smoke.json' \
       -o -path '*/candidate/failed.txt' \) 2>/dev/null | wc -l)
  [[ "$ready" == "8" ]] && break
  sleep 30
done

passed=0
failed=0
while IFS= read -r product_id; do
  candidate_root="$fit_root/$product_id/candidate"
  vacuum_report="$candidate_root/engine_smoke_100ps/candidate_engine_smoke.json"
  solution_root="$candidate_root/solution_smoke_100ps"
  if [[ ! -f "$vacuum_report" ]] || ! jq -e '.passed == true' "$vacuum_report" >/dev/null; then
    mkdir -p "$solution_root"
    printf '%s vacuum candidate prerequisite failed closed\n' \
      "$(date --iso-8601=seconds)" > "$solution_root/failed.txt"
    failed=$((failed + 1))
    printf '%s %s skipped because its vacuum candidate did not pass\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
    continue
  fi
  printf '%s %s running real explicit-solution 100 ps candidate smoke\n' \
    "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  if uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    run-candidate-solution-smoke \
    --candidate-manifest "$candidate_root/charmm/candidate_manifest.json" \
    --vacuum-smoke-report "$vacuum_report" \
    --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
    --water-parameters backend/data/forcefield/toppar_water_ions_cufix.str \
    --ion-nbfix-parameters backend/data/forcefield/par_stub_ions_nbfix.str \
    --namd "$namd" \
    --padding-nm 1.2 \
    --ion-conc-mm 150 \
    --minimize-steps 5000 \
    --heat-steps 10000 \
    --dynamics-steps 50000 \
    --output-dir "$solution_root" >> "$log" 2>&1; then
    passed=$((passed + 1))
    printf '%s %s real explicit-solution 100 ps candidate smoke passed\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  else
    printf '%s explicit-solution candidate smoke failed closed\n' \
      "$(date --iso-8601=seconds)" > "$solution_root/failed.txt"
    failed=$((failed + 1))
    printf '%s %s explicit-solution candidate smoke failed closed; continuing\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  fi
done < <(jq -r '.products[].product_id' "$fit_root/campaign_manifest.json" | sort)
printf '%s candidate solution smokes complete: passed=%s failed=%s\n' \
  "$(date --iso-8601=seconds)" "$passed" "$failed" >> "$log"
[[ "$failed" == "0" ]]

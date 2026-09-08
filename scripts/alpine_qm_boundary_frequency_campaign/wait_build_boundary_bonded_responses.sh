#!/usr/bin/env bash
set -u

fit_root=${1:?boundary fit-input root is required}
log="$fit_root.boundary-bonded-response.service.log"
charge_campaign="$fit_root/boundary_charge_fit_campaign.json"
cgenff_root=/media/jojo/Archive/NADOC_archive/reference_forcefields/toppar_c36_feb26/toppar
improper_audit=/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions/validation/namd-improper-convention-v1/improper_convention_audit.json
refit_policy=backend/data/forcefield/photoproduct_bonded_refit_policy_v2.json

printf '%s waiting for all-eight boundary charge-fit campaign\n' \
  "$(date --iso-8601=seconds)" > "$log"
until jq -e '
  .schema == "nadoc.photoproduct-boundary-charge-fit-campaign.v1" and
  .product_count == 8 and (.products | length) == 8
' "$charge_campaign" >/dev/null 2>&1; do
  sleep 30
done

passed=0
failed=0
while IFS= read -r product_id; do
  product_root="$fit_root/$product_id"
  bonded_root="$product_root/bonded"
  mkdir -p "$bonded_root"
  printf '%s %s auditing full model parameter coverage\n' \
    "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  if (
  set -e
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    audit-model-parameter-coverage \
    --model-manifest "$product_root/model/model_manifest.json" \
    --nonbonded-fit "$product_root/boundary_charge_fit.json" \
    --hypothesis-id charmm36-hybrid-cyclobutane-v1 \
    --cgenff-parameters "$cgenff_root/par_all36_cgenff.prm" \
    --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
    --output "$bonded_root/model_coverage.json" >> "$log" 2>&1
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    build-bonded-fit-plan \
    --model-manifest "$product_root/model/model_manifest.json" \
    --hessian-targets "$product_root/hessian_targets.json" \
    --model-coverage "$bonded_root/model_coverage.json" \
    --improper-convention-audit "$improper_audit" \
    --output "$bonded_root/fit_plan_base.json" >> "$log" 2>&1
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    promote-bonded-refit-terms \
    --fit-plan "$bonded_root/fit_plan_base.json" \
    --policy "$refit_policy" \
    --output "$bonded_root/fit_plan.json" >> "$log" 2>&1
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    build-openmm-candidate-skeleton \
    --fit-plan "$bonded_root/fit_plan.json" \
    --nonbonded-fit "$product_root/boundary_charge_fit.json" \
    --cgenff-topology "$cgenff_root/top_all36_cgenff.rtf" \
    --cgenff-parameters "$cgenff_root/par_all36_cgenff.prm" \
    --nucleic-topology backend/data/forcefield/top_all36_na.rtf \
    --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
    --output-dir "$bonded_root/skeleton" >> "$log" 2>&1
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    build-openmm-linear-fit-basis \
    --skeleton-manifest "$bonded_root/skeleton/candidate_skeleton_manifest.json" \
    --fit-plan "$bonded_root/fit_plan.json" \
    --improper-equilibrium-mode fixed_qm_reference \
    --angle-urey-bradley-mode omit \
    --output-dir "$bonded_root/fit_basis" >> "$log" 2>&1
  printf '%s %s building full Cartesian OpenMM response\n' \
    "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    build-openmm-linear-response \
    --fit-basis-manifest "$bonded_root/fit_basis/linear_fit_basis_manifest.json" \
    --hessian-targets "$product_root/hessian_targets.json" \
    --output-dir "$bonded_root/linear_response" >> "$log" 2>&1
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    audit-openmm-fit-identifiability \
    --response-manifest "$bonded_root/linear_response/linear_response_manifest.json" \
    --fit-plan "$bonded_root/fit_plan.json" \
    --output "$bonded_root/identifiability.json" >> "$log" 2>&1
  uv run python scripts/photoproduct_workflow.py \
    --storage-root /media/jojo/Archive/NADOC_archive \
    fit-boundary-bonded-response \
    --response-manifest "$bonded_root/linear_response/linear_response_manifest.json" \
    --fit-plan "$bonded_root/fit_plan.json" \
    --output-dir "$bonded_root/bonded_fit" >> "$log" 2>&1
  ); then
    passed=$((passed + 1))
    printf '%s %s bonded response and physical smoke fit ready\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  else
    failed=$((failed + 1))
    printf '%s\n' "bonded preparation or physical fit failed closed" \
      > "$bonded_root/failed.txt"
    printf '%s %s bonded preparation failed closed; continuing\n' \
      "$(date --iso-8601=seconds)" "$product_id" >> "$log"
  fi
done < <(jq -r '.products[].product_id' "$charge_campaign" | sort)
printf '%s boundary bonded responses complete: passed=%s failed=%s\n' \
  "$(date --iso-8601=seconds)" "$passed" "$failed" >> "$log"
[[ "$failed" == "0" ]]

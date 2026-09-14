#!/usr/bin/env bash
set -euo pipefail

repository=${1:-/home/jojo/Work/NADOC}
archive_root=${2:-/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-campaign-policy-2.1.0-v1}
source_root=${3:-/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/fixed-geometry-qm-v2.1.0}
bundle="$archive_root/bundle"

if [[ -e "$bundle" ]]; then
  echo "Refusing to overwrite existing campaign bundle: $bundle" >&2
  exit 2
fi

mkdir -p "$bundle/nadoc/backend/parameterization"
mkdir -p "$bundle/nadoc/backend/core"
mkdir -p "$bundle/nadoc/backend/data/forcefield"
mkdir -p "$bundle/cases"

cp "$repository/backend/__init__.py" "$bundle/nadoc/backend/__init__.py"
cp "$repository/backend/core/__init__.py" "$bundle/nadoc/backend/core/__init__.py"
cp "$repository/backend/core/photoproduct_chemistry.py" "$bundle/nadoc/backend/core/"
cp "$repository/backend/core/photoproduct_registry.py" "$bundle/nadoc/backend/core/"
cp "$repository/backend/parameterization/__init__.py" "$bundle/nadoc/backend/parameterization/__init__.py"
cp "$repository/backend/parameterization/photoproduct_distributed_hessian.py" "$bundle/nadoc/backend/parameterization/"
cp "$repository/backend/parameterization/photoproduct_qm.py" "$bundle/nadoc/backend/parameterization/"
cp "$repository/backend/parameterization/photoproduct_coupled_conformer.py" "$bundle/nadoc/backend/parameterization/"
cp "$repository/backend/parameterization/photoproduct_models.py" "$bundle/nadoc/backend/parameterization/"
cp "$repository/backend/parameterization/photoproduct_improper_convention.py" "$bundle/nadoc/backend/parameterization/"
cp "$repository/backend/data/forcefield/photoproduct_qm_protocol.json" "$bundle/nadoc/backend/data/forcefield/"
cp "$repository/backend/data/forcefield/photoproduct_qm_protocol_v1.5.0.json" "$bundle/nadoc/backend/data/forcefield/"
cp "$repository/backend/data/forcefield/photoproduct_parameter_acceptance.json" "$bundle/nadoc/backend/data/forcefield/"
cp "$repository/backend/data/forcefield/photoproduct_registry.json" "$bundle/nadoc/backend/data/forcefield/"

products=(
  tt-cpd-cis-syn-ii
  tt-cpd-trans-syn-ii
  tt-cpd-cis-anti-i
  tt-cpd-cis-anti-ii
  tt-cpd-trans-anti-i
  tt-cpd-trans-anti-ii
)

: > "$bundle/cases.tsv"
index=0
for product in "${products[@]}"; do
  for conformer in 001 002 003 004; do
    source_case="$source_root/$product/conformer-$conformer"
    destination="$bundle/cases/$product/conformer-$conformer"
    plan="$source_case/distributed/distributed_hessian_plan.json"
    if [[ ! -f "$plan" ]]; then
      echo "Missing distributed plan: $plan" >&2
      exit 3
    fi
    mkdir -p "$destination/distributed/tasks"
    cp "$plan" "$destination/distributed/"
    while IFS= read -r input; do
      relative=${input#"$source_case/distributed/"}
      mkdir -p "$destination/distributed/$(dirname "$relative")"
      cp "$input" "$destination/distributed/$relative"
    done < <(find "$source_case/distributed/tasks" -type f -name input.json | sort)
    task_count=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["task_count"])' "$plan")
    plan_sha=$(sha256sum "$plan" | awk '{print $1}')
    printf '%s\t%s\tconformer-%s\t%s\t%s\n' \
      "$index" "$product" "$conformer" "$task_count" "$plan_sha" >> "$bundle/cases.tsv"
    index=$((index + 1))
  done
done

if [[ "$index" -ne 24 ]]; then
  echo "Expected 24 conformer cases, prepared $index" >&2
  exit 4
fi

cp "$repository/scripts/alpine_qm_campaign/run_case.sh" "$bundle/"
cp "$repository/scripts/alpine_qm_campaign/campaign_64.sbatch" "$bundle/"
cp "$repository/scripts/alpine_qm_campaign/README.md" "$bundle/"
chmod +x "$bundle/run_case.sh"

python3 - "$bundle" "$source_root" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

bundle = Path(sys.argv[1])
source_root = Path(sys.argv[2]).resolve()
cases = []
for line in (bundle / "cases.tsv").read_text().splitlines():
    index, product, conformer, count, plan_sha = line.split("\t")
    cases.append({
        "array_index": int(index),
        "product_id": product,
        "conformer_id": conformer,
        "task_count": int(count),
        "plan_sha256": plan_sha,
    })
policy = bundle / "nadoc/backend/data/forcefield/photoproduct_parameter_acceptance.json"
protocol = bundle / "nadoc/backend/data/forcefield/photoproduct_qm_protocol.json"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
manifest = {
    "schema": "nadoc.photoproduct-alpine-qm-campaign.v1",
    "status": "prepared_not_submitted",
    "gate_effect": "none",
    "simulation_ready": False,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "source_root": str(source_root),
    "policy": {"version": "2.1.0", "sha256": sha(policy)},
    "qm_protocol": {"version": "1.5.0", "sha256": sha(protocol)},
    "engine_environment": "/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/envs/nadoc-qm-1.11",
    "slurm": {
        "partition": "acpu",
        "qos": "cpu-normal",
        "array": "0-23",
        "cpus_per_case": 64,
        "parallel_tasks_per_case": 32,
        "threads_per_task": 2,
        "memory_gib_per_task": 3,
        "walltime": "02:00:00",
    },
    "case_count": len(cases),
    "task_count": sum(case["task_count"] for case in cases),
    "cases": cases,
    "interpretation": (
        "Each array element computes one immutable fixed-geometry displaced-gradient "
        "plan. Results remain unreviewed evidence until fetched, hash-audited, assembled, "
        "and accepted locally."
    ),
}
(bundle / "campaign_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY

(
  cd "$bundle"
  find . -type f ! -name MANIFEST.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum > MANIFEST.sha256
)

mkdir -p "$archive_root"
tar -C "$archive_root" -czf "$archive_root/alpine-qm-campaign-policy-2.1.0-v1.tar.gz" bundle
(
  cd "$archive_root"
  sha256sum alpine-qm-campaign-policy-2.1.0-v1.tar.gz \
    > alpine-qm-campaign-policy-2.1.0-v1.tar.gz.sha256
)

echo "$archive_root/alpine-qm-campaign-policy-2.1.0-v1.tar.gz"

#!/usr/bin/env bash
set -euo pipefail

repository=${1:-/home/jojo/Work/NADOC}
archive_root=${2:-/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-benchmark-v1}
source_case=${3:-/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/fixed-geometry-qm-v1/tt-cpd-cis-syn/conformer-001}
bundle="$archive_root/bundle"

if [[ -e "$bundle" ]]; then
  echo "Refusing to overwrite existing benchmark bundle: $bundle" >&2
  exit 2
fi

mkdir -p "$bundle/nadoc/backend/parameterization"
mkdir -p "$bundle/nadoc/backend/core"
mkdir -p "$bundle/nadoc/backend/data/forcefield"
mkdir -p "$bundle/case/distributed/tasks"

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
cp "$repository/backend/data/forcefield/photoproduct_qm_protocol_v1.4.0.json" "$bundle/nadoc/backend/data/forcefield/"
cp "$repository/backend/data/forcefield/photoproduct_registry.json" "$bundle/nadoc/backend/data/forcefield/"

cp "$source_case/distributed/distributed_hessian_plan.json" "$bundle/case/distributed/"
while IFS= read -r input; do
  relative=${input#"$source_case/distributed/"}
  mkdir -p "$bundle/case/distributed/$(dirname "$relative")"
  cp "$input" "$bundle/case/distributed/$relative"
done < <(find "$source_case/distributed/tasks" -type f -name input.json | sort)

cp "$repository/scripts/alpine_qm_benchmark/environment.yml" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/benchmark_manifest.json" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/setup_env.sbatch" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/benchmark_64.sbatch" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/benchmark_128.sbatch" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/benchmark_128_amem.sbatch" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/run_benchmark.sh" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/summarize_benchmark" "$bundle/"
cp "$repository/scripts/alpine_qm_benchmark/README.md" "$bundle/"
chmod +x "$bundle/run_benchmark.sh" "$bundle/summarize_benchmark"

(
  cd "$bundle"
  find . -type f ! -name MANIFEST.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum > MANIFEST.sha256
)

mkdir -p "$archive_root"
tar -C "$archive_root" -czf "$archive_root/alpine-qm-benchmark-v1.tar.gz" bundle
sha256sum "$archive_root/alpine-qm-benchmark-v1.tar.gz" > "$archive_root/alpine-qm-benchmark-v1.tar.gz.sha256"

echo "$archive_root/alpine-qm-benchmark-v1.tar.gz"

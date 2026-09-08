#!/usr/bin/env bash
#SBATCH --job-name=nadoc_qm_env
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/setup_env_%j.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/setup_env_%j.out

set -euo pipefail
remote_root=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1
bundle="$remote_root/bundle"
environment="$remote_root/envs/nadoc-qm-1.11"
mamba=/curc/sw/install/miniforge3/24.11.3-0/bin/mamba

mkdir -p "$remote_root/envs" "$remote_root/conda-pkgs"
export CONDA_PKGS_DIRS="$remote_root/conda-pkgs"

if [[ ! -x "$environment/bin/python" ]]; then
  "$mamba" env create --yes --prefix "$environment" --file "$bundle/environment.yml"
fi

"$environment/bin/python" -c \
  "import psi4,qcengine,qcelemental,numpy; expected=('1.11','0.51.0','0.51.0','2.5.2'); observed=(psi4.__version__,qcengine.__version__,qcelemental.__version__,numpy.__version__); assert observed == expected, (observed, expected); print(observed)"
"$environment/bin/python" -m pip freeze | sort > "$remote_root/environment.freeze.txt"
sha256sum "$bundle/environment.yml" "$remote_root/environment.freeze.txt" > "$remote_root/environment.sha256"

#!/usr/bin/env bash
#SBATCH --job-name=nadoc_cpd_energy
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=110G
#SBATCH --time=06:00:00
#SBATCH --array=0-7
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-relative-energy-v1/logs/%A_%a.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-relative-energy-v1/logs/%A_%a.out

set -euo pipefail
exec bash /scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-relative-energy-v1/bundle/run_case.sh

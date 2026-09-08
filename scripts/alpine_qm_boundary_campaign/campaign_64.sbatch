#!/usr/bin/env bash
#SBATCH --job-name=nadoc_cpd_boundary
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=110G
#SBATCH --time=24:00:00
#SBATCH --array=0-2
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-opt-v1/logs/%A_%a.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-opt-v1/logs/%A_%a.out

set -euo pipefail
export NADOC_CAMPAIGN_REMOTE_ROOT=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-opt-v1
exec bash "$NADOC_CAMPAIGN_REMOTE_ROOT/bundle/run_case.sh"

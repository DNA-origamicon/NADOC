#!/usr/bin/env bash
#SBATCH --job-name=nadoc_cpd_boundary_esp
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=40G
#SBATCH --time=04:00:00
#SBATCH --array=0-7
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-esp-v1/logs/%A_%a.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-esp-v1/logs/%A_%a.out

set -euo pipefail
remote_root=${NADOC_CAMPAIGN_REMOTE_ROOT:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-esp-v1}
exec bash "$remote_root/bundle/run_case.sh"

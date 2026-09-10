#!/usr/bin/env bash
#SBATCH --job-name=nadoc_fragment_freq
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=56G
#SBATCH --time=23:30:00
#SBATCH --signal=B:USR1@300
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-local-fragment-continuation-v1/logs/%A_%a.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-local-fragment-continuation-v1/logs/%A_%a.out

set -euo pipefail
remote_root=${NADOC_CAMPAIGN_REMOTE_ROOT:-/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-local-fragment-continuation-v1}
exec bash "$remote_root/bundle/run_case.sh"

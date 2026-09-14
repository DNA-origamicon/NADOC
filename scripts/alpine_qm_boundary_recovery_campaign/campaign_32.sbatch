#!/usr/bin/env bash
#SBATCH --job-name=nadoc_cpd_recovery
#SBATCH --partition=amem
#SBATCH --qos=mem-long
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=240G
#SBATCH --time=72:00:00
#SBATCH --signal=B:USR1@600
#SBATCH --array=0-2
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-recovery-v2r1/logs/%A_%a.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-recovery-v2r1/logs/%A_%a.out

set -euo pipefail
export NADOC_CAMPAIGN_REMOTE_ROOT=/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-recovery-v2r1
exec bash "$NADOC_CAMPAIGN_REMOTE_ROOT/bundle/run_case.sh"

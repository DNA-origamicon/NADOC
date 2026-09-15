#!/bin/bash
#SBATCH --job-name=oxdna_physics_ab
#SBATCH --partition=acpu
#SBATCH --account=ucb-general
#SBATCH --qos=cpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=00:30:00
#SBATCH --array=0-53%18
#SBATCH --output=run_%A_%a.log
set -eo pipefail
source /etc/profile
export LD_LIBRARY_PATH=/curc/sw/install/gcc/14.2.0/lib64:${LD_LIBRARY_PATH:-}
python3 campaign_worker.py --index "$SLURM_ARRAY_TASK_ID" --backend CPU

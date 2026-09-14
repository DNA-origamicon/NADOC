#!/usr/bin/env bash
#SBATCH --job-name=nadoc_qm_64c
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=110G
#SBATCH --time=01:00:00
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/qm64_%j.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/qm64_%j.out

set -euo pipefail
exec bash /scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/bundle/run_benchmark.sh 64 32

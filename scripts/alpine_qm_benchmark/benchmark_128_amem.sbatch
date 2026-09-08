#!/usr/bin/env bash
#SBATCH --job-name=nadoc_qm_128m
#SBATCH --partition=amem
#SBATCH --qos=mem-normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=128
#SBATCH --mem=256G
#SBATCH --time=01:00:00
#SBATCH --output=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/qm128_amem_%j.out
#SBATCH --error=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/qm128_amem_%j.out

set -euo pipefail
exec bash /scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/bundle/run_benchmark.sh 128-amem 64

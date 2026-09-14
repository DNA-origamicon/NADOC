#!/bin/bash
#SBATCH --job-name=ab_native_build
#SBATCH --partition=acompile
#SBATCH --account=ucb-general
#SBATCH --qos=compile
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=native_build_%j.log
set -eo pipefail
source /etc/profile
export PATH=/curc/sw/install/gcc/14.2.0/bin:/curc/sw/install/cmake/3.31.0/bin:$PATH
export LD_LIBRARY_PATH=/curc/sw/install/gcc/14.2.0/lib64:${LD_LIBRARY_PATH:-}
if [ ! -d native_source ]; then
 cp -a /projects/jojo6687/nadoc_jobs/strep_bussi_fixed_20260913/oxdna_source native_source
fi
cmake -S native_source -B native_build -DCMAKE_BUILD_TYPE=Release -DCUDA=OFF -DNATIVE_COMPILATION=OFF -DPython=OFF
for variant in baseline current_k rigid_mask combined_epsilon1 combined_epsilon2; do
 for relative in src/Backends/Thermostats/BussiThermostat.cpp src/Backends/Thermostats/BrownianThermostat.cpp src/Interactions/DNANMInteraction.cpp; do
  cp "cpu_sources/$variant/$relative" "native_source/$relative"
 done
 cmake --build native_build -j4 --target oxDNA
 mkdir -p "engines/$variant/bin"
 cp native_build/bin/oxDNA "engines/$variant/bin/oxDNA"
 sha256sum "engines/$variant/bin/oxDNA"
done
python3 alpine_preflight.py

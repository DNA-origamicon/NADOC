#!/bin/bash
# Detached NAMD multi-arch build. Launched via RunpodConnection.launch_detached.
cd /workspace/build || exit 90
bash namd_tilelist_fix/build_patched_namd.sh \
  /workspace/build/NAMD_3.0.2_Source.tar.gz \
  /usr/local/cuda-12.8 \
  sm_89,sm_120 \
  > /workspace/build/build_multi.log 2>&1
echo "exit=$?" >> /workspace/build/build_multi.log

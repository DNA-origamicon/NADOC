#!/usr/bin/env bash
# Incremental low-concurrency continuation after a high-parallelism CUDA OOM.
set -uo pipefail
cd /root/nadoc-amber-gbion
rescue_rc=0
(
  set -euo pipefail
  while pgrep -f 'cmake --build . --target install -j 96|gmake -f Makefile -j96' >/dev/null; do
    sleep 2
  done
  echo 'PHASE amber26_compile_low_concurrency_retry'
  cd amber26-build
  cmake --build . --target install -j 4 2>&1 | tee /root/nadoc-amber-gbion/build-retry.log
  test -x /opt/amber26/bin/pmemd.cuda
  test -x /opt/amber26/bin/pmemd
  echo 'PHASE native_validation'
  cd /root/nadoc-amber-gbion
  export AMBERHOME=/opt/amber26
  export TLEAP=/opt/ambertools26/bin/tleap
  export NADOC_REMOTE_ROOT=/root/nadoc-amber-gbion
  export NADOC_OUTPUT_DIR=/root/nadoc-amber-gbion/output
  export PYTHONPATH=/root/nadoc-amber-gbion
  /opt/ambertools26/bin/python runpod_worker.py
) || rescue_rc=$?
echo "$rescue_rc" > chain.exit
exit "$rescue_rc"

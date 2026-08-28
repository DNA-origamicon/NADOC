#!/usr/bin/env bash
# Resume an exp58 6HB pod after a peak-memory failure in the portable CUDA build.
# The local controller must remain SIGSTOP'd until this writes chain.exit.
set -uo pipefail
remote=/root/nadoc-amber-gbion-6hb
rm -f "$remote/chain.exit"
rescue_rc=0
(
  set -euo pipefail
  cd "$remote/amber26-build"
  echo 'PHASE amber26_compile_serial_rescue' | tee -a "$remote/nadoc_chain.out"
  cmake --build . --target install -j 4 2>&1 | tee -a "$remote/build.log" "$remote/nadoc_chain.out"
  test -x /opt/amber26/bin/pmemd.cuda
  test -x /opt/amber26/bin/pmemd

  cd "$remote"
  echo 'PHASE origami_validation' | tee -a "$remote/nadoc_chain.out"
  export AMBERHOME=/opt/amber26
  export TLEAP=/opt/ambertools26/bin/tleap
  export NADOC_REMOTE_ROOT="$remote"
  export NADOC_OUTPUT_DIR="$remote/output"
  export PYTHONPATH="$remote"
  export NADOC_CUDA_BUILD_SCOPE="sm89-only-source-patched"
  /opt/ambertools26/bin/python runpod_worker_6hb.py 2>&1 | tee -a "$remote/nadoc_chain.out"
) || rescue_rc=$?
echo "$rescue_rc" > "$remote/chain.exit"
exit "$rescue_rc"

#!/usr/bin/env bash
set -euo pipefail

host=${ALPINE_HOST:-jojo6687@login.rc.colorado.edu}
local_bundle=${NADOC_ALPINE_BENCHMARK_BUNDLE:-/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-benchmark-v1/alpine-qm-benchmark-v1.tar.gz}
remote_root=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1
control_dir=/tmp/nadoc-alpine-${UID}
control_socket=$control_dir/control.sock

if [[ ! -f "$local_bundle" || ! -f "$local_bundle.sha256" ]]; then
  echo "Benchmark bundle or checksum is absent: $local_bundle" >&2
  exit 2
fi
sha256sum -c "$local_bundle.sha256"

mkdir -p "$control_dir"
chmod 700 "$control_dir"
if ! ssh -S "$control_socket" -O check "$host" >/dev/null 2>&1; then
  echo "Opening a reusable Alpine SSH connection; password/Duo may be requested."
  ssh -MNf \
    -o ControlMaster=yes \
    -o ControlPersist=30m \
    -o ControlPath="$control_socket" \
    "$host"
fi

ssh -S "$control_socket" "$host" "mkdir -p '$remote_root'"
scp -o ControlPath="$control_socket" "$local_bundle" "$host:$remote_root/"

ssh -S "$control_socket" "$host" 'bash -s' <<'REMOTE'
set -euo pipefail
remote_root=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1
cd "$remote_root"
if [[ -e bundle ]]; then
  echo "Refusing to overwrite an existing remote benchmark bundle: $remote_root/bundle" >&2
  exit 3
fi
tar -xzf alpine-qm-benchmark-v1.tar.gz
cd bundle
sha256sum -c MANIFEST.sha256

sbatch --test-only setup_env.sbatch
sbatch --test-only benchmark_64.sbatch
sbatch --test-only benchmark_128.sbatch

setup_job=$(sbatch --parsable setup_env.sbatch)
setup_id=${setup_job%%;*}
job64=$(sbatch --parsable --dependency="afterok:$setup_id" benchmark_64.sbatch)
job64_id=${job64%%;*}
job128=$(sbatch --parsable --dependency="afterok:$setup_id" benchmark_128.sbatch)
job128_id=${job128%%;*}
printf 'setup=%s 64-core=%s 128-core=%s\n' \
  "$setup_id" "$job64_id" "$job128_id"
squeue -j "$setup_id,$job64_id,$job128_id" -o '%i|%P|%j|%T|%M|%L|%R'
REMOTE

echo "The reusable SSH control connection will remain available for up to 30 idle minutes:"
echo "  ssh -S '$control_socket' '$host'"

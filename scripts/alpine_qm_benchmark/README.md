# Alpine TT-CPD QM CPU benchmark

This bundle runs the same 128 immutable MP2/6-31G(d) displaced-gradient tasks twice:

- 64 allocated cores: 32 simultaneous tasks x 2 threads;
- 128 allocated cores: 64 simultaneous tasks x 2 threads.

The source is the already-completed cis-syn conformer-001 response plan, so this benchmark
cannot race or alter the active remaining-isomer campaign. Results are performance evidence
only and never advance a chemistry gate. `benchmark_manifest.json` records the exact input
hash, software versions, resource shapes, storage locations, and interpretation limits.

The report generator is invoked explicitly with the pinned QM Python. Do not invoke it
through Alpine's system `python3`, which is older than the benchmark's Python syntax.

## Upload from Compy5000

The helper below validates the local tarball, opens one reusable SSH control connection
(one password/Duo exchange), uploads and validates the bundle, runs all three Slurm
admission checks, and submits the environment, 64-core, and 128-core jobs with
dependencies. It deliberately
stops if the primary 128-core `acpu` request is rejected; it never opts into the more
expensive, less directly comparable `amem` fallback automatically:

```bash
cd /home/jojo/Work/NADOC
scripts/alpine_qm_benchmark/submit_from_local.sh
```

It leaves the separate NADOC UI connection alone and keeps its own SSH control connection
available for 30 idle minutes. The equivalent step-by-step upload is:

```bash
local_bundle=/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-benchmark-v1/alpine-qm-benchmark-v1.tar.gz
remote_root=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1
ssh jojo6687@login.rc.colorado.edu "mkdir -p $remote_root"
scp "$local_bundle" "jojo6687@login.rc.colorado.edu:$remote_root/"
ssh jojo6687@login.rc.colorado.edu "cd $remote_root && tar -xzf alpine-qm-benchmark-v1.tar.gz && cd bundle && sha256sum -c MANIFEST.sha256"
```

Each SSH/SCP command may request a Duo approval. If already in an Alpine terminal, upload
the tarball through Open OnDemand Files and begin with the extraction command instead.

## Validate and submit on Alpine

```bash
remote_root=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1
cd "$remote_root/bundle"

sbatch --test-only setup_env.sbatch
sbatch --test-only benchmark_64.sbatch
sbatch --test-only benchmark_128.sbatch

setup_job=$(sbatch --parsable setup_env.sbatch)
setup_id=${setup_job%%;*}
job64=$(sbatch --parsable --dependency="afterok:$setup_id" benchmark_64.sbatch)
job64_id=${job64%%;*}
job128=$(sbatch --parsable --dependency="afterok:$setup_id" benchmark_128.sbatch)
job128_id=${job128%%;*}
printf 'setup=%s 64-core=%s 128-core=%s\n' "$setup_id" "$job64_id" "$job128_id"
squeue -j "$setup_id,$job64_id,$job128_id" -o '%i|%P|%j|%T|%M|%L|%R'
```

If Alpine rejects 128 cores on `acpu`, use the provided high-memory fallback after checking
its higher billing cost:

```bash
sbatch --test-only benchmark_128_amem.sbatch
job128=$(sbatch --parsable --dependency="afterok:$setup_id" benchmark_128_amem.sbatch)
```

Do not submit both 128-core variants.

## Retrieve to the Archive drive

After both jobs finish, run from Compy5000:

```bash
local_root=/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-benchmark-v1/results
remote_root=/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1
mkdir -p "$local_root"
scp -r "jojo6687@login.rc.colorado.edu:$remote_root/results/." "$local_root/"
scp "jojo6687@login.rc.colorado.edu:$remote_root/"'*.out' "$local_root/"
```

Keep the remote results until the local hashes and QCSchema result/run-record pairs have
been audited.

# small_plate copied R2: Alpine upload audit

Verified 2026-09-05 21:11 UTC. NADOC job `e75ffd56c6f8`, SLURM `32108809`.
The scheduler independently reports RUNNING on `c3gpu-g7-u5`, partition
`artxpro6000`, with one RTX Pro 6000, eight CPUs and 70 GB memory. Its command
and working directory both point to `/scratch/alpine/jojo6687/nadoc_jobs/e75ffd56c6f8`.

The final prepared package has 24 configurations. All 22 with an active NPT piston
use period 10000 fs and decay 5000 fs. All 21 manifest relaxation segments are
present. In particular, `small_plate_03_300K_NPT_ENM_k0p01_p10.conf` loads the
k=0.1 p100 coordinates/velocities/cell and retains 10000/5000 fs, avoiding the
previous stage-boundary reset to 1000/500 fs. Its timestep remains 4 fs.
The manifest agrees with these settings. The actual graphene package passed
`validate_graphene_wall_package`, including the NGRC no-self-LJ force field.

All 75 prepared inputs (2,083,560,826 bytes), including all 24 configuration files,
have successful SFTP completion receipts with matching byte counts. Seven additional
submission/helper files also have successful receipts. No upload errors were recorded
for this job. SHA-256 hashes of all local inputs were recorded during upload and
rechecked afterward; all remained identical. No files or scientific settings needed
manual patching for this submission.

Evidence:
- `package_inventory.json`: relative input names, sizes and local SHA-256 hashes.
- `audit.json`: configuration values and corresponding successful transfer receipts.
- `slurm_probe.json`: live read-only scheduler response proving allocation and workdir.
- `audit.py`: repeatable read-only configuration/transfer audit.
- `keep_connection.log`: bounded read-only keepalive traffic, at most four hours.

Verification limits: the authenticated transfer's completion receipts and byte counts
were checked; independent remote SHA-256 readback was not performed. RUNNING is a
scheduler observation, not proof that the entire ladder has completed. This audit did
not wait for k=0.01 or establish full-run stability. The underlying 20 ps causal local
control is documented in `docs/namd_graphene_barostat_failure_audit.md`.

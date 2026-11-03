# User-validated in app — 2026-08-07 — supporting detail

[Topic head](../../project_alpine_cluster_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### User-validated in app — 2026-08-07

Every feature of this arc was hand-exercised by the user and **all pass**:

- GPU-availability popup; wizard step 1 "Where it runs" (local probe, Alpine partition table with
  wait/speed/SU, node selection) and the step-3 SLURM inspection block.
- Submit review: close-on-submit + double-submit guard; upload/prepare progress and stages.
- Cluster-chip ⇄ wizard state sync; the availability button's disabled reason when signed out.
- Live metrics on a running job, **including ns/day** (the `days/ns`-only regex fix).
- Health card populating on reconnect.
- One-frame display fetch for a running Alpine job, and its "Snapshot at step N" label.
- Progress bar carried forward while signed out, re-anchoring on sign-in.

So this feature set is **no longer manual-validation debt**; see `manual_validation_debt.md`
(`MV-ALPINE-GPU`). What that validation does *not* cover: the CPU-partition path above, and
`just smoke` (the console-error gate) still never ran — it stayed blocked by a running NAMD
production job throughout.

**Editing `backend/**` drops the SSH session** — uvicorn `--reload` watches `backend` and
`scripts` only, and the asyncssh connection lives in that process. `memory/**` and
`workspace/**` are excluded, so profile-JSON and memory edits are safe mid-session. Batch
backend edits, then reconnect once.

---

### Result download is a separate, verified lifecycle (2026-08-09)

SLURM completion and local result availability are deliberately independent. `MdJob.download_status`
persists the exact remote `relative path -> byte size` inventory, verified/transferred byte counts and
file counts. The unified Jobs card says **Download complete** only after every local file matches that
inventory; a browser reload or expired Duo session cannot invent success. For older jobs that predate
the per-file inventory, exact aggregate bytes plus exact file count are the conservative offline proof.

Every entry point (automatic completion reconciliation, Stop, Fetch remote, End run and download) goes
through one per-job async lock plus an advisory filesystem lock. This covers concurrent routes, dev-server
reload overlap and multiple backend processes. Downloads use `.part`, resume by exact byte offset and
atomically rename only after fsync + size verification. The offline verifier never touches a job whose
transfer state is `downloading`; after interruption it may promote an exact-size `.part` without Alpine.
Filesystem/permission errors fail the file operation but do **not** expire a healthy SSH/Duo session.

Byte verification is followed by a separately persisted `processing` phase while NADOC reads the fetched
trajectory to compute final health and metrics. This pass can take minutes for a multi-GB DCD. The unified
Jobs card keeps a striped 100% bar visible, says **Download verified — processing trajectory health and
metrics…**, and disables the action as **Processing…** until bookkeeping finishes. Browser refreshes and
offline verification preserve this state; successful finalization returns it to `verified` and marks the
job/segment complete.

Size authority follows the lifecycle: live remote heartbeat bytes while the job is active; actual local
directory size after download; verified inventory totals in the transfer UI. Directory-size caches are
invalidated after a transfer. This prevents a terminal card from retaining the last-running remote size.

Remote minimisation also participates in progress: node metrics carry the real minimisation step, successive
samples derive seconds/step when NAMD emits no TIMING record, and the card shows step/total, percent and ETA.
For a deliberately ended production, downloaded XST/restart markers supply actual completed steps and the
conf supplies the real timestep. The stage row reports actual ns (SLURM 30958617: **65.97 ns**) and renders
the green completion check because the job is marked complete, rather than claiming its requested 200 ns ran.

> **History.** Phase 1–5 build detail, in-sbatch early-stop, ensemble production, run logs + the appendix live in [project_alpine_cluster_submission_archive.md](../../project_alpine_cluster_submission_archive.md). Read on demand only.

### Flexibility-map / replica-package invariant (from upstream 2026-07-09)

- **Flexibility-map fix (2026-07-09)**: a replica production package must ALSO carry
  `charge_audit.json` (the segid→NADOC-chain map). `build_replica_package` originally
  hardlinked only PSF/PDB/forcefield/hmr, so `load_segid_chain_map` fell back to the
  reference-PDB P-order — which can't build the 21 phosphate-less 5'-termini specs → those
  bases rendered un-positioned/un-coloured in the Flexibility map (RMSF returned 1307/1328
  keys). Fix = two layers: (A) `build_replica_package` now `_link_or_copy`s
  `charge_audit.json`; (B) `load_segid_chain_map` falls back to `manifest.json`'s embedded
  `charge_audit` field when the standalone file is absent (fixes replicas already on disk —
  the child manifest already carries the map). Verified on prod job `6d7c2e38e455`: RMSF
  route now returns 1328/1328. See LESSONS A10.

### Patch-grid recovery and physical restraint inheritance (2026-09-04)

`small_plate` job `d882c98ac759` / Slurm `32086330` completed minimization but failed
in the first NPT settle stage with `Periodic cell has become too small for original
patch grid!`, before its first 5,000-step checkpoint. Alpine now stages
`remote_cell_recovery.py` and `remote_resume_conf.py` on both Submit and Resume.
The generated sbatch retries this exact failure within the allocation, rebuilding
from a validated checkpoint and remaining steps; one gentler pre-checkpoint retry is
allowed. Retries are bounded and reject stalled checkpoints or >15% cumulative volume
loss. Physical restraints and integrator choices persist. No scheduler auto-resubmission.

The same audit fixed harmonic anchors becoming hard fixed atoms in appended production,
inherited harmonic settings for production children, and graphene-only controls acquiring
an NPT barostat after their NVT relaxation. Details and verification limits are in
[the audit](../../../docs/namd_alpine_failure_audit.md). The failed job has not been resubmitted.

## R1 graphene force-field correction (2026-09-04)

R1 `0a2aaa5638ff` / Slurm `32088967` failed at k=0.1 step 14: unbonded
graphene CA sites experienced enormous mutual LJ repulsion at 1.42 Å. New
packages use dedicated NGRC sites with CA cross LJ and zero NGRC–NGRC NBFIX
in `par_np_thiol.prm`. Geometry, anchor stiffness and 4 fs timestep are unchanged.
`namd_graphene.validate_graphene_wall_package` blocks legacy wall packages before
Alpine submit/resume, local execution and RunPod provisioning. Copy + Run must
rebuild and minimize; old graphene checkpoints are not reusable. Copy remains an
editable draft and does not prepare or submit. See `docs/namd_graphene_wall_failure_audit.md`.

## small_plate restrained-wall barostat audit — 2026-09-05

Slurm `32089399` (`7aa73d7afe93`) failed after a successful k=0.1 recovery:
recovery had slowed the piston to 10000/5000 fs, but k=0.01 reset it to
1000/500 fs. Local 4 fs replays reproduce alternating, amplifying cell/pressure
oscillations within 12 steps, driving graphene restraint energy from 34.8k to
752M kcal/mol before the exclusion fatal. Margin 4, GPU offload, and retaining
k=0.1 all fail. Changing only the piston to 10000/5000 fs passes 5000 steps.
This is independent of the earlier corrected graphene self-LJ defect.

Restrained graphene NPT config composition now keeps at least 10000/5000 fs
across relaxation, appended production and replica production; NVT stays NVT.
See [audit](../../../docs/namd_graphene_barostat_failure_audit.md). The failing job's
intact pre-failure checkpoint can be used with the corrected piston; unlike the
self-LJ fix, this does not require rebuilding or reminimization. An isolated
continuation is under `experiments/namd_32089399_diagnosis/recovery_package`.
The backend was preserved during diagnosis, then restarted by the user before the
new copy was prepared. On September 5 at 21:11 UTC, copy `e75ffd56c6f8` was verified
as SLURM `32108809`, RUNNING on `c3gpu-g7-u5`. All 75 package inputs transferred
successfully and all 22 active NPT configs retain 10000/5000 fs. Full-ladder stability
is still unverified. See [upload audit](../../../experiments/namd_e75ffd56c6f8_upload_audit/README.md).

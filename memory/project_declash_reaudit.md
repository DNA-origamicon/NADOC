---
name: declash-reaudit
description: "Declash auto-trigger RETIRED (2026-08-19); WC/C1' ss-exclusion made topology-exact (2026-08-20); Alpine/RunPod early-stop tiers RETIRED, byte-for-byte local parity (2026-08-21). Read before touching CreateJobRequest.declash, prepare_mgh_slow_release, md_health ss-exclusion, or anything early-stop/tier on a remote target."
metadata: 
  node_type: memory
  type: project
  status: shipped
  originSessionId: 6c67bc07-671e-4f79-b559-639942dbaebe
  modified: 2026-08-20T04:20:01.494Z
---

# Declash retirement → ss-exclusion correctness → remote early-stop parity

Three causally-connected fixes, same investigation thread, escalating scope. Full history of
the FIRST (the 6hb_2xT confounded run, the wizard toggle bug) is in
[project_declash_reaudit_archive.md](project_declash_reaudit_archive.md) — read on demand only.

## 1. Declash auto-trigger retired (2026-08-19) — explicit-only, default OFF

`declash: Optional[bool] = None` now ALWAYS resolves to `False` (`bool(declash)`) in
`prepare_mgh_slow_release`, `namd_gbis.build_namd_gbis_package`, and
`routes_md_plan._relaxation_plan` — no more `design_requires_extra_base_declash`/
`design_has_extensions` auto-detection OR-chain. A design that would have auto-triggered
under the old rule still gets flagged, but only as a non-acting advisory condition
(`declash_off_on_a_clash_prone_design`, "warn never block" — same rule as
[[feedback_namd_4fs_production_only]]). `pre_declashed` (oxDNA-seeded builds) is unrelated,
unchanged. See the archive for the full incident this fixed.

## 2. WC/C1' ss-exclusion made topology-exact (2026-08-20)

Retiring declash's auto-trigger surfaced that `md_health`'s single-strand exclusion set
(what keeps designed ssDNA — crossover extra bases, native ssDNA, extension tails — out of
the WC/C1' pairing candidate pool) was badly broken, in two layers:

**Layer 1 — the exclusion set was unconditionally empty for any non-declash run.**
`_unpaired_exclusion_set` gated on `{stem}_build.pdb`, a side-effect file only the declash
rebuild path writes. Fix: call `identify_unpaired_residues(psf, pdb)` directly and
unconditionally — declash is a minimisation-stage protocol choice, not a fact about which
residues are single-stranded. Verified live on `fc2c7ceb596b` (6hb_2xT): 0 → 100 residues.

**Layer 2 — pure C1'-distance geometry itself misses residues.** A genuinely single-stranded
residue can sit close enough to an UNRELATED neighbour to read as "paired." Measured: a
minimal 2-helix, 2-extra-base ("2xT"-style) crossover missed 1 of 2 extra bases; a real
extension tail near a packed bundle measured 10.72 Å to its nearest unrelated cross-chain
C1' — under the 10.8 Å cutoff by 0.08 Å. This also fed declash's ENM-restraint exclusion
(`_ladder_enm_exclude`, always-on for any extra-base design, not just when declash runs),
where the code's own comment documents a real RATTLE-crash risk from a wrongly-pinned ss
residue — so this bug reached beyond WC health.

**Fix — topology-exact placement, geometry only for what has no tag.** Extra bases and
extensions carry an explicit `crossover_id`/`extension_id` tag on the `AtomisticModel`, so
`namd_topology.extra_base_segid_resids` / new `extension_segid_resids` place them by PSF
ORDINAL (never by distance — can't miss one regardless of 3D proximity). Native ssDNA (no
tag) still needs geometry. `md_protocols.topology_ss_exclusion_set(model, psf, pdb,
sort_chains=)` unions both legs and persists the topology-only leg to a sidecar,
`{name_stem}_ss_exclusion.json`, next to the PSF — because a later health check only has
the PSF/PDB on disk, never the `AtomisticModel`. Wired into all three ENM-exclusion call
sites (`prepare_mgh_slow_release` — also fixed a gate that skipped ENM exclusion for
extension-only designs — `namd_gbis.py`, `namd_vacuum.py`) and into
`md_health._unpaired_exclusion_set`.

Tests: `test_md_gbis.py` and `test_namd_anchors.py` gained REAL psfgen-build end-to-end
tests (both `sort_chains` conventions) proving geometry alone still misses a residue
(`assert not sidecar <= geometry_only`) while the topology-exact union doesn't.

**Open:** `rebuild_declashed_references`'s post-declash re-detection reads the sidecar +
fresh geometry (no `AtomisticModel` available there) — a package built before the sidecar
existed still falls back to geometry-only for that one path. No such job is in active use.
`design_rmsd_reports` (`namd_runner._record_design_rmsd`) still fails silently on both
`1c36b3ca6ee6`/`00e55345847a` — not chased. The declash arithmetic bug (step counts sized
for 4 fs while running at 2 fs) is UNTOUCHED — live whenever declash is explicitly on.

## 3. Alpine/RunPod early-stop tiers RETIRED — byte-for-byte local parity (2026-08-21)

Auditing "does an Alpine job differ from local" surfaced the early-stop Tier A/B split
(`job.early_stop_tier`) as a real, user-visible divergence: **Tier B (the default)** tested
energy(+volume) only, restricted to stages restrained at ENM k≥0.1 (k=0.01/MGHH-only always
ran in full) — a strictly weaker settle test than local's, which always requires energy AND
WC on every non-final chunk. **Tier A** (opt-in) was *supposed* to close the gap, but its
on-node WC computation used the SAME broken `identify_unpaired_residues` cross-module import
pattern as §2's Layer 1 — the staged `md_health.py` is a VERBATIM STANDALONE copy (no
`backend` package on the node), so `_unpaired_exclusion_set`'s
`from backend.core.md_protocols import ...` raised `ImportError`, caught internally, silently
returning an empty exclusion set. Reproduced directly on the real 24hb_2xT package
(`bb8654eef459`): standalone-staged → 0 excluded; in-app → 764. The health step itself never
crashed (wrote a plausible, just wrong, `wc.json`), so Tier A's own "fails safe to HOLD on no
data" safeguard never caught it.

**Fix — no tiers, one path, matches local exactly:**
- Moved `identify_unpaired_residues` (+ `_C1_NO_PARTNER_ANG`) and the sidecar helpers
  (`read_topology_ss_sidecar`/`_ss_exclusion_sidecar_path`) FROM `md_protocols.py` INTO
  `md_health.py` — the module that's actually staged standalone. `_unpaired_exclusion_set`
  now has zero cross-module imports; nothing left to fail on the node.
  `topology_ss_exclusion_set` (`md_protocols.py`, build-time only, never staged) now imports
  these lazily FROM `md_health` instead (one-directional; `md_health` never imports
  `md_protocols`, no cycle).
- `slurm_script.py`: `_early_stop_eligible(chain, idx)` dropped `scales`/`min_k`/`tier` —
  every non-final relaxation chunk is eligible now (matching what Tier A used to do alone).
  `_chain_scales`/`_DEFAULT_EARLY_STOP_MIN_K` deleted (nothing reads restraint scale for
  eligibility any more). `_early_stop_block` always emits the health-step-then-WC-gate body
  (the old Tier A body, unconditionally).
  `remote_cutoff_eval.py`: `--wc` is now a REQUIRED CLI arg; `decide()` has no energy-only
  branch — always `should_early_stop_stage` (energy AND WC).
  `md_executor._stage_early_stop_evaluator` always stages all three node scripts
  (cutoff evaluator + health step + `md_health.py`), no `tier=` branch.
- `runpod_script.py`/`runpod_executor.py` mirror the same change (shared
  `_early_stop_eligible`/`_early_stop_block` from `slurm_script.py`). Confirmed by a REAL
  bash-execution test (`test_runpod_script.py`) that the k=0.01 stage — previously
  Tier-B-ineligible — now bridges too.
- `MdJob.early_stop_tier` field REMOVED (the first-ever MdJob field removal, not just an
  addition) — `CreateJobRequest.early_stop_tier`, the wizard's "Remote early-stop test"
  dropdown, and `FIELD_SCOPE`/`DEFAULT_FIELD_SCOPES` entries all removed with it.
  **`MdJob.load()` now filters `data` down to the current dataclass's known field names
  before `cls(**data)`** — a real archived job.json (`bb8654eef459`, 24hb_2xT) still has
  `"early_stop_tier": "B"` on disk and would otherwise crash loading with a
  `TypeError: unexpected keyword argument`. Pinned by
  `tests/test_md_job_schema_evolution.py`, including a direct load of that real file.

**Practical effect:** an Alpine or RunPod relaxation with `early_stop_relax` on now runs the
identical settle decision a local run would make, on every stage including k=0.01/MGHH —
not an approximation gated by which target happened to be picked. RunPod specifically also
gets MORE savings (Tier A's WC criterion was always the one that unlocked eligibility on the
fragile low-k stages — Tier B "could not pay for" a big ladder; see the exp36 4.9x figure in
`runpod_script.render_chain_script`'s docstring).

Verified: `just test-smart` FAST, 7168 passed / 115 skipped (same one pre-existing unrelated
`DEFERRED` note); `just test-frontend` 337 files / 5771 passed.

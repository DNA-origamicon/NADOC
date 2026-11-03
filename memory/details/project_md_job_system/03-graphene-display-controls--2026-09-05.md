# Graphene display controls — 2026-09-05 — supporting detail

[Topic head](../../project_md_job_system.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Graphene display controls — 2026-09-05

The NAMD Hard surface card has a display-only **Show nanopore** checkbox and
**Simple plane / Ball / Stick** dropdown, separate from **Add graphene nanopore**.
Browser preferences (`nadoc.grapheneDisplay`) apply to the setup preview and actual
MD carbon coordinates, including paused frames. These controls never alter job
parameters, force fields, or simulation inclusion. MD display continues to suppress
the design preview; hiding graphene persists through frame updates and returning
to the preview.

`graphene_display_controls.js` owns preferences; `graphene_representation.js` owns
carbon rendering. Sticks infer nearest-neighbor visual edges with a 0.19 nm cutoff,
without adding simulation bonds or drawing periodic edges across the cell. The MD
plane fills complete carbon hexagons, preserving the pore and transformed membrane
position. Visual adjacency is retained between frames and reset on clear/new data.

## Direct NAMD PEG surface drafts (2026-09-11)

File → NAMD PEG Surfaces and the NAMD sidebar now open a standalone surface draft
editor, usable without DNA or an oxDNA source. It saves workspace-level definitions
under `namd_surfaces`, with support/plane/patch, density/seed, PEG representation,
chain length and chemistry/asset notes. Review uses shared plane geometry and a
schematic graft preview. The API is `/api/md/peg-surfaces`; create/list/update/review
never invoke engine preparation. Drafts are not attached to ordinary NAMD jobs yet.
Target assets, graft/cross interactions, molecular construction and engine validation
remain explicit blockers. See [direct PEG surface setup](../../../docs/namd_peg_surfaces.md).

- 2026-09-14 short electrode volume screen: 4/6/8 nm lateral sides at fixed 4 nm
  gap, 240 ps each, 10/22/39 ions. Larger counts lower short-window drift, but both
  larger jobs fail density; see `.development-artifacts/electrode_volume_screen_20260914/README.md`.
  GPU-resident one-worker timing is ~1.46x faster than offload at 24,677 atoms;
  CPU/Tcl coordinate and force handling remains ~70% of step time. Long resident
  qualification and physical-time/correlation-aware profile windows remain open.

- User preference (2026-09-14): future local NAMD electrode experimental dynamics
  should use GPU-resident mode; use one CPU worker based on measured timings.
  Explicit offload is reserved for requested comparisons or documented engine
  compatibility issues. Electrode preparation now maps `auto` to `on`, preserving
  explicit `off`; minimization retains its established offload startup path.
- Isolated direct-array NAMD prototype built at `.development-artifacts/electrode_native_bridge_v2/namd3`:
  bypasses per-atom Tcl conversion, ~6.6x faster than the compiled Tcl callback in
  resident mode at 24,677 atoms. Three-axis force/energy audits match exactly; 40 ps
  finite/confined dynamics passed. Still experimental: no long/DNA/PEG qualification,
  no installed engine replacement, matching bridge callback required. See
  `experiments/electrode_relax/native_bridge/README.md` and
  `.development-artifacts/electrode_native_bridge_validation_v2/README.md`.

- Completed resident Debye diagnostic (2026-09-14): 2.64 ns, 8 × 4 × 8 nm liquid,
  25,839 atoms/41 Na-Cl pairs. Jobs c6d0bcfc861d/e04b05b6df8a/df270bd5872a retained
  against `2electrode_solvent_only.nadoc`; all native/density/confinement/profile
  checks pass. Equilibrated solvent + experimental 0.22 nm oxygen clearance passes
  this empty control; default 0.32 nm still underfills it. Pooled λ=0.573 nm versus
  classical 0.536–0.605 nm looks promising but chunk fits 0.405/1.745 nm disagree:
  not quantitative Debye convergence, despite passing profile gates. Full ladder,
  DNA/PEG, dielectric, salt scaling and finite-gap checks remain open. Details:
  `.development-artifacts/electrode_debye_validation_20260914_v2/README.md`.
- Explicit experimental engine path/hash now survives adoption and restart, verified
  against package provenance (`namd_experimental_engine.py`). Callback remains an
  explicit experimental package choice. Installed NAMD remains unchanged.

- Larger-gap comparison completed (2026-09-14): 6 nm gap, 8×8 nm area, 38,644 atoms,
  64 Na-Cl pairs, same 300 mM target/300 K/2 fs, 2.64 ns GPU-resident. Jobs
  bf1562116993/f4bbd57fbd5b/2fb3c67ae5d9 retained and completed; density 33.17 nm^-3,
  confinement/profile gates pass. λ fits 0.580/0.819 nm across chunks, pooled
  0.685 vs classical 0.551–0.623: better constrained than 4 nm but central salt
  still changes 343→269 mM and microscopic field remains noisy. Not Debye convergence.
  `.development-artifacts/electrode_gap6_validation_20260914/README.md` and `PERFORMANCE.md`.
  Runtime 86.3 min; sustained ~44–45 ns/day and sampled GPU util ~28%. Remaining
  CPU gather/correction/scatter + padded PME limit speed, despite native-array
  bridge. Archived local DNA reference ~392 ns/day at 4 fs is not a matched benchmark.

- GPU correction prototype (2026-09-14): `experiments/electrode_relax/gpu_correction/`
  implements EW3DC moment, wall repulsion and harmonic anchors via NAMD's existing
  dynamic CUDA client API, without replacing the installed engine. No ordinary
  atomic position/force host transfers; scalar energy and server synchronization
  remain. Three-axis stressed and normal force/energy audits match CPU/NumPy;
  isolated configuration tests guard ordering and double application. Final build
  and source hashes: `.development-artifacts/electrode_gpu_plugin_final/provenance.json`.
  Longer performance/post-migration audits: `.development-artifacts/electrode_gpu_benchmark_final/`.
  Explicit experimental fixed-cell path only; managed plugin restart provenance,
  full ladder/minimization, DNA/PEG, virials, multi-GPU and long screening are open.

Final matched GPU benchmark: 254 ns/day without tuning, 291–297 ns/day with
GPU atom migration + twoAwayZ, versus 43.1 ns/day CPU at the same 2 fs (6.8–6.9×).
Four 120 ps GPU endpoints pass force/energy audits; these do not establish Debye
convergence. Details: `.development-artifacts/electrode_gpu_benchmark_final/README.md`.


- Managed GPU electrodes (2026-09-14): the local runner now auto-selects the
  registered CUDA correction for a matching engine ABI and resident, single-GPU
  electrode job. `namd_electrode_gpu.py` pins package-local library/parameter/PSF
  checksums and reference forces; restart writer orders client creation last;
  accepted offload restores CPU forces. Registry: `workspace/runtime/electrode_gpu`.
  Missing/mismatched registry retains a documented reference path. Canonical source:
  `backend/core/native/electrode_gpu.cu`; no installed NAMD replacement.
- Real Start-API 4 fs solvent pilot passed, followed by longer retained sampling
  against `2electrode_solvent_only.nadoc`; campaign
  `.development-artifacts/electrode_gpu_screening_4fs_20260914/`. It uses unchanged rigid-water
  masses, 2 ps frames and a fixed 4 fs PME-update interval across 2/4 fs comparisons.
  Native stability does not establish timestep-independent dielectric/screening.
  Separate physical-time blocks and water-mode diagnostics are retained.
- Screening analysis no longer hardcodes 2 fs; it checks DCD headers and respects
  restart lineage. Electrode stationarity now retains 600 ps, not 60 frames.
  Native PID matching now excludes shell text that merely mentions a NAMD config.
  Managed scope, verification and remaining barriers: `docs/namd_electrode_gpu.md`.

- Managed campaign completed: all ten jobs retained/visible, 9.84 ns at 4 fs plus
  1.20 ns at 2 fs, all runtime gates passed; ~475 vs ~294 ns/day. Pooled λ values
  0.519/0.597 nm (4 fs series) and 0.604 nm (2 fs), not converged by window fits.
  Water rotational temperature ~294.18 K at 4 fs versus ~298.93 K at 2 fs;
  quantitative screening remains timestep-sensitive/unqualified. Native 20-step
  resume proof passes. Final campaign README and comparison/native_summary retain
  evidence. Existing screening popup still rejects two-electrode jobs (409);
  finite-gap graphs are standalone artifacts pending UI integration.
- User-requested 40 ns 4 fs continuation launched 2026-09-14: job `4eb7176339e4`
  under `2electrode_solvent_only.nadoc`, source `548581d231f7`, unchanged 6 nm gap,
  salt/charges/masses, 2 ps output. Native GPU-resident/GPU plugin launch verified.
  Campaign `.development-artifacts/electrode_gpu_screening_40ns_20260914/`; persistent standalone
  `monitor.py` writes live progress, cumulative 5/10/20/30/40 ns analyses and final
  separate 10 ns windows. Check progress/completion files before reporting outcome.
  Initial throughput ~425–440 ns/day (~2.2 hours). This tests time averaging only;
  it does not resolve known 4 fs water-mode bias. No extra simulations authorized
  by this launch beyond the one 40 ns continuation.
- Remote duplicates of the 40 ns 4 fs electrode validation (2026-09-14 10:52 MDT):
  Alpine `b2b224bcb96d`, Slurm `32557806`, RTX PRO 6000: force/energy/restart probes
  pass, 40 ns running (~850 ns/day after startup). Isolated glibc loader bundle fixes
  old Alpine runtime; exact local engine/plugin preserved. Prior probe allocations
  32557480 (missing dl/pthread/rt companions) and 32557606 (probe timestep numbering)
  failed before any 40 ns dynamics; retained evidence. RunPod `4665025e7158` uses
  PRO 4500 Blackwell at $0.72/h after user changed GPU preference and capped total
  job spend at $5. Pod `q1qt7czydiaa15`, five-hour provider expiry + independent
  systemd watchdog. Check campaign `electrode_remote_40ns_20260914` for actual current
  validation/status; do not assume completed. Controllers retain ordinary job-list
  metadata, exact initial checkpoint/seed, and all fetched bytes on archive storage.
  Global remote engine defaults remain unchanged; generic remote resume/requeue GPU
  initialization is a remaining integration gap, documented in namd_electrode_gpu.md.

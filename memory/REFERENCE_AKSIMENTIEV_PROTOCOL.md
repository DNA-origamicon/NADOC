---
name: reference-aksimentiev-protocol
description: "The canonical Aksimentiev DNA-origami NAMD protocol, read from the tutorial's own scripts, plus the exact NADOC delta. Read before changing solvation, the ENM ladder, or barostat settings."
metadata:
  node_type: memory
  type: reference
---

# Aksimentiev DNA-origami NAMD protocol — ground truth + NADOC delta

Verified 2026-07-29 by reading the tutorial's **own scripts**, not the prose:
`origamitutorial.tar.gz` (108 MB; streamed and only the `*.namd/*.sh/*.tcl/*.pl` kept)
from <https://bionano.physics.illinois.edu/tutorials/practical-guide-dna-origami-simulations-using-namd>,
plus the Methods-in-Molecular-Biology chapter PDF (`origamiprotocols_0.pdf`).
Reference system = `hextube`, a cadnano hexagonal tube.

## The pipeline

**Stage 1 — cadnano → all-atom** via the ENRG-MD web service (returns psf/pdb/`.exb`/namd).

> **No web service needed.** `enrgmd` is a console script **mrdna installs** (`.venv/bin/enrgmd`),
> from the same lab — mrdna is the 2020 successor to the 2016 ENRG-MD paper it cites (NAR gkw155).
> It writes psf/pdb/`.exb`/namd locally via `SegmentModel.write_atomic_ENM` +
> `atomic_simulate(dry_run=True)`.
> **But it cannot be used for NADOC designs with extra bases**: it calls
> `_generate_atomic_model()`, rebuilding the structure from cadnano JSON, and cadnano has no
> representation for extra bases at crossovers. Regenerated atom ordering would not match a
> NADOC PSF either. Reuse the *recipe* against NADOC's own topology instead — see
> `experiments/exp48_vacuum_enrgmd/`.
>
> The `.exb` has two parts, both in `mrdna/segmentmodel.py::write_atomic_ENM`:
> - **ENM**: a 52-key template table of measured atom-pair distances keyed by
>   (pairtype, seq1, seq2) over `pair`/`stack`/`cross`/`paircross` neighbours, k=0.1
>   (honeycomb gets per-key corrections). NOT the same as the step-3 base-ring ladder ENM.
> - **PUSHBONDS**: interhelical P–P, k=1.0, r0=31 Å. Rule: pairs of dsDNA segments joined by
>   ≥2 crossovers → consecutive crossover pairs → both ends parallel (tangent·tangent > 0.5;
>   antiparallel is an explicit `continue`, "not yet implemented") → walk the nucleotides
>   between, interpolating on the shorter span → **skip anything within 11 nt of either
>   crossover** → both strand directions → P atoms, deduped.
>   Consequence: a span must exceed ~22 nt to place any bond, so a densely crossed-over
>   bundle generates **zero** and they appear only where crossovers are sparse. This is what
>   produces the end-weighted distribution seen on the hextube.

**Stage 2 — in-vacuo ENM optimisation** (`step2/hextube.namd`): `PME no`, 1000 Å cell,
`margin 30`, **`langevinDamping 0.1`** (deliberately low friction for fast relaxation),
2 fs `rigidBonds all`, `minimize 4800` then ~40 ps with `hextube.exb`. This is the step
that folds the idealised lattice into the chickenwire arrangement. The chapter's claim:
*"In less than 2 ns of simulation using the above protocol, better structure is obtained
than in 200 ns of all-atom MD simulation."*

> **Measured on NADOC designs (exp48, 2026-07-30).** "Less than 2 ns" is an upper bound, not
> a recipe — the tutorial's own step-2 script runs **~40 ps**, and mrdna's `enrgmd` default of
> `1e6` steps (2 ns) is 4–100× more than needed. Plateau reached at 0.04 ns (2hb), 0.03 ns
> (6hb), 0.64 ns (24hb; r_max by ~0.2 ns). **0.5 ns is ample.**
> Base pairing survives intact at every size (0 broken of 42 / 252 / 3192).
>
> ⚠ **The "shrinks the box 7–9%" claim is ROTATION-box-specific and was inverted by the
> 2026-07-30 switch to bbox sizing for relax packages.** exp50 re-measured the same runs
> against both rules: `r_max` does fall 3–4% (so a rotation cell shrinks 9–12%), but the
> BOUNDING box *grows* 27–85%, because the bundle splays transversally as it relaxes. A
> bbox-sized relax package therefore pays 1.3–1.9× more solvent for this step, not less.
> What it buys is shape: RMSD 10.7–26.1 Å on every design tested — not a no-op even on a
> straight bundle. **Curved designs are the exception that justifies it**: `6hbx100_90deg`
> relaxes its per-helix centreline bend 98.5° → 69.9° and grows its bbox only 27% (vs
> 81–85% straight), because a bent structure's bounding box already has room. Skip it
> below ~4 helices.
> Minimisation must scale with the structure: an idealised 224k-atom build starts at
> ~1×10⁹ kcal/mol VDW concentrated at inserted bases, and a fixed 2400–4800 steps leaves
> thousands of `BAD CONTACTS` that blow up ~130k steps later (RATTLE failure). One step per
> 10 atoms is enough. Full numbers: `experiments/exp48_vacuum_enrgmd/REPORT.md`.

**Stage 3 — solvate + ionise** (`step3/solIon.tcl`, `add_mgh_ver2_3.tcl`):
- Mg²⁺ inserted as explicit **Mg(H₂O)₆²⁺ (MGHH)**, with `mghh_extrabonds` harmonic bonds
  holding the six waters on the Mg.
- `solvate -minmax` — the script's own recipe (commented block) is the DNA bbox **± 20 Å
  on every face**.
- `autoionize -nions {{CLA …}}` — Cl⁻ only, to neutralise.
- FF: `par_all36_na.prm` + **`par_water_ions_cufix.prm`** (CHARMM36 NA + CUFIX NBFIX).

**Stage 4 — ENM release ladder** (`equil_min` → `equil_k0.5` → `k0.1` → `k0.01` → `k0`):
- ENM from `cadnano2pdb2enm.pl --namd --k=$k --cut=8`: pairs of the **nine base-ring atoms
  only** (`next unless ($atom =~ /(N1|C2|N3|C4|C5|C6|N7|C8|N9)/)`, P/O1P/O2P/H/primes
  skipped), **inter-residue only**, within **8 Å**, 30 Å residue-COM prefilter, equilibrium
  length = the measured distance in the input PDB.
- k = **0.5 → 0.1 → 0.01 → 0** kcal/mol/Å², `run 2400000` at 2 fs = **4.8 ns per stage**
  (19.2 ns total). k=0 = ENM `extraBondsFile` commented out; `mghh_extrabonds` stays on.
- `minimize 4800` in `equil_min`.
- 2 fs, `rigidBonds all`, `switchdist 8 / cutoff 10 / pairlistdist 12`,
  `PME yes / PMEGridSpacing 1.5`, `nonbondedFreq 1`, `fullElectFrequency 2`,
  `stepspercycle 12`.
- `langevin on`, **`langevinDamping 5`**, `langevinHydrogen off`.
- `langevinPiston on`, target 1.01325 bar, **`langevinPistonPeriod 1000` /
  `langevinPistonDecay 500`**. `useFlexibleCell` / `useGroupPressure` are NOT set (NAMD
  defaults, i.e. off).
- **`wrapAll off`, `wrapWater off`.**

**Stage 5 — their equilibration criteria** (`step4/`): box-size trace (`grepBoxTrace.sh`)
— *"the box should shrink in the first 300 ps; after that the box size should become
stable"*; RMSD vs the idealised design; total charge within 2 nm of the origami; broken-bp
count — purine H1/N1 within **3 Å** of pyrimidine N3/H3 **AND the N1–H1–N3 / N1–H3–N3
angle greater than 140°**. The angle term matters: without it a sheared or stacked pair
with a coincidentally short heavy-atom distance counts as intact.

## Three notes that bear directly on NADOC failures

1. **Underfilled box → vacuum bubbles.** VMD `solvate` "usually underestimates the number
   of water molecules needed", so the box shrinks under 1 atm — that shrink IS their
   equilibration monitor. Their sanctioned fix (Note 4): *"run your simulation in NPT with
   the DNA position fixed, allowing the box size to fluctuate until it reaches a value
   appropriate for the amount of water molecules in the system"* — explicitly preferred
   over resolvating. If the bubble is big enough that its removal destabilises the run,
   **increase `langevinPistonPeriod`/`Decay` by ×10**, then revert once the box is stable.
2. **NVT for applied fields.** *"The NVT ensemble is also recommended if you are running a
   simulation that includes externally applied forces or electric fields. Running these
   types of simulations in NPT guarantees this error will eventually occur."* → applies to
   [[project_oxdna_efield]] / any NAMD E-field run.
3. **The k=0 stage length is the user's problem.** *"one may need to modify the protocol,
   in particular the duration of a free equilibration simulation (k=0)."* Their 4.8 ns is
   for a *relaxed structure*, not an equilibrium ensemble — everything NADOC does beyond
   that (200 ns free runs for pose/stiffness extraction) is outside the reference envelope,
   so the box rules have to be extended with it. See [[crossover-catenation]] §2026-07-29.

## NADOC delta — CLOSED 2026-07-30 (recipe version 2)

Audited against the chapter PDF itself (`Literature/Aksimentiev_Tutorial.pdf`, 21 pp);
eight divergences found, all now resolved. `md_protocols.RELAX_RECIPE_VERSION` is the
stamp, and every package carries a **derived** `protocol_fidelity` manifest block listing
what it reproduces and what it deliberately does not. **Read that block, not this table,
to know what a given trajectory actually ran** — a prepared package is frozen on disk, so
old jobs correctly keep their old physics.

Faithful before this round, and unchanged: **the ENM is a byte-equivalent
reimplementation** — same nine base-ring atoms, `cut_ang=8.0`, k ladder 0.5/0.1/0.01/0,
4.8 ns/stage, inter-residue, measured equilibrium lengths. MGHH + `mgh_extrabonds` ✓.
CHARMM36 NA + CUFIX ✓. Ladder piston 1000/500 ✓. Electrostatics adopted 2026-07-29 ✓.

### What was wrong, and what it is now

| | tutorial | NADOC before | now |
|---|---|---|---|
| **counterion** | **Mg(H₂O)₆²⁺** neutralises, Cl⁻ balances, **no Na⁺** | **Na⁺** neutralised; Mg a 12.5 mM bath only | `namd_solvate.ion_counts` — Mg neutralises, `n_na = 0` |
| **Mg placement** | inserted into the DRY system, against the DNA | uniform random over the box | seeded within `MGH_SEED_SHELL_NM` of the backbone |
| **vacuum pre-step** | §3.2, mandatory, before solvation | absent | still absent — **deliberately**, see below |
| broken-bp criterion | 3.0 Å **and angle > 140°** | 3.6 Å heavy-atom, no angle | both — theirs reported, ours still gates |
| charge within 2 nm | §3.4 criterion | absent | `md_health.charge_within_shell` |
| RMSD vs design | §3.4 criterion | absent | `namd_runner._record_design_rmsd` |
| Note-4 settle stage | fixed-DNA NPT | detector only, no remedy | `_0S_` segment, 500 ps, all DNA fixed |
| Note-4 piston ×10 | on an abrupt box change | absent | `namd_runner.soften_piston` on shrink-resume |
| minimisation | Note 2: scale it | flat 4800 | `minimize_steps_for_atoms` (1 step / 10 atoms) |
| solvent padding | bbox ± 20 Å | 1.2 nm | 2.0 nm, trimmed only when the cell would not fit |
| `wrapAll` | off | **on in production/reseed** | off everywhere |

⚠ The `wrapAll` row is why it mattered: NAMD wraps **connected components of the bond
graph**, and an origami's scaffold and its ~200 staples are separate molecules — so
`wrapAll on` could translate individual staples a full box length from the duplex they
are hybridised to. The relax ladder was always `off`; production and reseed were not.

### Deliberate, documented deviations (kept)

| | tutorial | NADOC | why |
|---|---|---|---|
| production dt | 2 fs `rigidBonds all` | **4 fs + HMR** | measured structurally indistinguishable, ~2× throughput |
| `fullElectFrequency` | 2 | 1 | dt-dependent; the PME *interval* already matches at 4 fs. The literal 2 would exceed the r-RESPA limit |
| `wrapWater` | off | on | solute-neutral (`wrapAll off`); keeps coords in [0, L) for the periodic charge query |
| switch / cutoff / pairlist | 8 / 10 / 12 | 8 / 10 / **13.5** | pairlist buffer for the longer `stepspercycle` |
| water fill | full box | full box **or carved shell** | memory fallback. ⚠ a carve forces NVT, which **disables** the settle stage and the box trace — `resolve_padding_nm` trims padding rather than trigger one, and the manifest records it |
| production piston | 1000 / 500 | 200 / 100 | ladder matches; production stiffer by choice |
| unrestrained length | 4.8 ns | up to 200 ns | beyond the reference envelope |

**Still unvalidated on hardware.** The ion-composition change is the one that alters
physics most, and it has NOT been run head-to-head. A short arm against an exp47-style
baseline is owed before any published number uses recipe 2.

## ✅ Their electrostatics are strictly better here — MEASURED (2026-07-29)

Two 2 ns arms, same full-water-box 2hb_1xT package (32,572 atoms), same checkpoint, 4 fs
+ HMR, GPU-resident; E0 is literally what `build_production_conf` emits
(`experiments/exp47_protocol_delta/run_electrostatics_arms.py`):

| | ns/day | cell settled | linear drift | bp intact | T (K) | E_tot drift |
|---|---|---|---|---|---|---|
| **E0 NADOC** (10/12/14, PME 1.0, fullElect 1) | 265.3 | ✓ | +0.43 % | 1.000 | 297.7 | −0.19 % |
| **E1 tutorial** (8/10/12, PME 1.5, fullElect 2) | **369.6** | ✓ | +0.76 % | 1.000 | 298.4 | −0.20 % |

**+39 % throughput, structurally indistinguishable** — identical base-pair integrity,
temperature and energy drift, both cells settled. Wave 1's caveat (a smaller cutoff makes
a finer patch grid and so crashed *sooner*) only applied while the cell was collapsing;
with the box fixed it does not arise. NADOC's current values are not wrong — they match
Roodhuizen/ACS Nano — but on this hardware they cost 39 % for no measurable gain.

## Relax presets shipped (2026-07-29) — `backend/core/md_presets.py`

**ONE control** (`#md-jobs-relax-preset`, in the launch form), **defaults to Standard**.
The old `#md-jobs-preset` protocol dropdown is GONE — there were briefly two menus both
labelled "Protocol", and they could contradict: the panel always sent `protocol`, so it
always sat in `model_fields_set` and the preset's own protocol never won. "Standard
(Aksimentiev)" + separately-selected implicit solvent produced a job promising explicit
MgCl₂/CUFIX and running with no water at all, uncaught.

| id | label | protocol | state |
|---|---|---|---|
| `fast_shape` | Fast Shape Check (Vacuum) | `vacuum_enrgmd_namd` | **SHIPPED 2026-07-30** |
| `implicit_gbis` | Implicit Solvent (GBIS) | `implicit_gbis_namd` | **host-gated** — needs a non-CUDA NAMD build, so DISABLED on this machine |
| `standard` | Standard (Aksimentiev) | `equilibrium_aware_namd` | **default**; runs the vacuum stage first |
| `full_physics` | Slow (full physics) | `equilibrium_aware_namd` | padding 1.5 nm, early-stop OFF |

⚠ **Availability is HOST-aware, not just build-aware** (`preset_availability`). GBIS is
unsupported on the NAMD 3 CUDA nonbonded kernel (crashes in `buildTileLists`), so it needs
a multicore build — which this machine does not have. Two bugs were found by actually
running it, both now fixed:

1. `prepare_implicit_gbis_namd()` did not accept `gpu_resident_mode` /
   `production_timestep_fs`, so **every GBIS job had been failing at prep since commit
   8823377 (2026-07-28)** — the GPU-resident dropdown added them to the ONE shared
   `run_in_threadpool(prepare, ...)` kwarg set without updating that signature. Pinned by
   `tests/test_prepare_signatures.py`, which parses the real call site with `ast` and
   checks every protocol's entry point against it.
2. Even with prep fixed, the run died on the first segment because of the CUDA build. The
   preset now probes `find_namd(prefer_cpu=True)` at catalogue time, so the menu greys it
   out **and** `POST /md/jobs` 400s up front instead of paying for solvation first.

To actually use GBIS here, install the multicore build at
`~/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3`; the preset re-enables itself.

**`protocol` is DERIVED from the preset, never separately selectable.** `_apply_relax_preset`
forces it; every other field is a default that an explicit request value overrides. API
compatibility: `protocol` alone (no `relax_preset`) is still honoured as the legacy path;
both-and-agreeing is fine; both-and-contradicting is a **400**, not a silent override.

**`mgh_slow_release` is retired from the menu, not from the API** — it is
`equilibrium_aware_namd` with `require_full_topology` OFF (`prepare_equilibrium_aware_namd`
is a four-line wrapper that adds the gate), i.e. a validation choice wearing a protocol's
label. Old jobs and scripted callers still work; `presetIdForProtocol` maps it to `null`
so a draft recorded with it restores to the default, which is the same ladder anyway.
`GET /md/relax-presets` serves the catalogue; the UI module is
`frontend/src/ui/md_relax_presets.js` (16 vitest tests) and renders an unavailable tier
disabled-with-reason rather than hiding it.

**`fast_shape` SHIPPED AND WAS RETIRED, 2026-07-30 — read this before reviving it.**
The tutorial's §3.2 unfolds caDNAno's abstract parallel-helix lattice. NADOC *derives*
geometry from topology + B-DNA constants + deformations, so no design ever arrives in
that state (measured: `6hbx100_90deg`'s ideal build already holds ~98.5° of per-helix
bend). Worse, the repulsion surrogate needs a >22 nt crossover-free span while honeycomb
crossovers recur every 21 nt → **zero push bonds** on a dense bundle → the run has no
interhelical force term at all, and bundles swelled 5.6–10% AWAY from the Mg-screened
equilibrium. Reviving it needs a NADOC-native spacing restraint (the lattice pitch is
known from topology), not mrdna's transplanted rule. Historic note follows.

 Both blockers this used to list are closed: the
placement rule is `backend/core/namd_push_bonds.py` (mrdna's, ported from exp48 with its
self-test now collected as `tests/test_namd_push_bonds.py`), and the DNA-only package
path is `backend/core/namd_vacuum.py`. The hextube's `.exb` settled the parameters —
`k = 1 kcal/mol/Å², r₀ = 31 Å`, and only **64** of them for the hextube (sparse, NOT one
per base pair) alongside 75,503 ENM terms. Reproduced exactly on NADOC designs:
2hb → 0 push bonds, 6hb → 11, 24hb → 495.

## Other defaults flipped (2026-07-29)

- **Box sizing → `rotation`** (`namd_solvate.DEFAULT_BOX_MODE`), cubic `2·r_max + 2·pad`.
  `resolve_box_mode` falls back to `bbox` **with a recorded note** when rotation would
  exceed the hardware's atom cap — a cell too big to run is not safer than one too small,
  because it forces a carve, which forces NVT, which kills the free stage rotation sizing
  existed to protect. Cap comes from the same `md_vram` helpers the carve sizer uses
  (3.17 M atoms on this box); estimator validated against the real 2hb package
  (predicted 33,276 vs actual 32,572).
- **Electrostatics → the tutorial's** `switchdist 8 / cutoff 10 / pairlistdist 12`,
  `PMEGridSpacing 1.5`. ⚠ **`fullElectFrequency 2` was deliberately NOT adopted** — it is
  dt-dependent. At their 2 fs it means PME every 4 fs, which our 4 fs path already does
  with `fullElect 1`; copying the literal 2 would put PME on an 8 fs interval, past the
  r-RESPA resonance limit. The invariant is `PME_MAX_INTERVAL_FS = 4.0`, not the literal
  value. This costs ~12 of the measured +39 %.
- **`early_stop_relax` → ON by default** (request, model and checkbox). `full_physics`
  turns it back off — a stage you intend to publish should not be truncated.

## What of this is now implemented (2026-07-29)

Shipped: carved package ⇒ `langevinPiston off` in production AND reseed
(`package_npt_allowed` reads the manifest's new `solvation` block); `margin 3` on NPT
stages; `xstFreq` capped at 10 ps so the 300 ps criterion is resolvable; the box-trace
criterion itself as `md_cell_health.settle_report`, recorded per NPT stage on the job;
`is_collapsing` + a refusal to auto-resume a collapsing cell; `box_mode="rotation"` in
`namd_solvate` plus an always-on `box_check` in the manifest. See
[[project_water_shell_carve]] for the details and the measured thresholds.

NOT implemented: the fixed-DNA NPT **settle stage** as a default ladder segment (their
Note-4 remedy run as its own stage) — the checker exists and the collapse refusal has
teeth, but inserting a segment changes every job's ladder and wants its own decision.
Also not changed: padding default (still 1.2 nm; `box_mode` still defaults to `bbox`), so
sizing is *reported* on every build but not *changed* without opting in.

Priority if matching them: padding 1.2 → 2.0 nm; production piston back to 1000/500; add
their fixed-DNA NPT pre-stage to settle an underfilled box; carve → NVT everywhere
including production; `wrapAll off`; adopt the box-size trace as an automated gate.
**Matching them does NOT fix small-solute tumbling** — ±20 Å on a 2hb still gives 60 Å
against a 71 Å requirement; their systems are large origami run 4.8 ns unrestrained, so
tumbling never bites. That extra rule is NADOC-specific.

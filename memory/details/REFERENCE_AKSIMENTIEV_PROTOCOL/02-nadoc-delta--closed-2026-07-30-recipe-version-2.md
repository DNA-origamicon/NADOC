# NADOC delta — CLOSED 2026-07-30 (recipe version 2) — supporting detail

[Topic head](../../REFERENCE_AKSIMENTIEV_PROTOCOL.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
| Note-4 settle stage | fixed-DNA NPT | detector only, no remedy | `_0S_` segment, 500 ps, all DNA heavy atoms **restrained at k=1**, not fixed — see below |
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

## Literature-comparability audit (2026-08-03) — the full list

Every emitted parameter checked against the published protocol, asking what a critical
reviewer could call a difference that makes a NADOC result non-comparable. **Tier 1–2
items are now declared in every package's `protocol_fidelity` block**; read that for a
given run rather than this table.

**Tier 1 — genuinely different ensembles.** (1) Production was truly unrestrained while
the published "unrestrained" runs retain an ENM at k = 0.1 — FIXED, see
`project_md_job_system.md`. (2) `langevinDamping` 5 ps⁻¹ in production, an equilibration
value that overdamps every kinetic observable — FIXED, now 1. (3) Early-stop truncates
stages on an unpublished criterion and is ON by default, so "19.2 ns ladder" is false for
most runs — now DECLARED in `protocol_fidelity`; `literature`/`full_physics` disable it.
(4) The declash ns defect (2.4 ns/rung instead of 4.8) — pinned and displayed. The
automatic trigger was narrowed on 2026-08-09: a one-base insertion no longer selects
declash; any individual junction above one base remains conservative pending a full-ladder
audit. Extensions and explicit declash requests are unchanged.

**Tier 2 — defensible, now declared.** Production piston 200/100 vs 1000/500 ·
`stepspercycle` 20/10 vs 12 (with `pairlistdist` 13.5 to compensate; the constant
`AKSIMENTIEV_STEPS_PER_CYCLE` is misnamed — 20 is not their number) · stage chunking (5
restart boundaries per rung; the tutorial runs each k flat) · 4 fs + HMR vs 2 fs ·
bbox cell sizing below 20 ns free, so the solute cannot tumble and the minimum-image
distance is smaller than a rotation-sized cell · no §3.2 vacuum pre-relaxation.

**Tier 3 — open, verify before publishing.**

- **Ion recipe 2 has never been validated head-to-head.** No arm against an exp47-style
  baseline. The Mg-neutralisation setup is *believed* to match §3.3; it has not been shown
  to reproduce a known result.
- **Protein systems may be running on stub vdW parameters.** `namd_topology.py` maps
  imported PDB residues to CHARMM36 *protein* RTF names, but `namd_solvate._FF_FILES`
  ships only `top_all36_na.rtf` / `par_all36_na.prm` / water+ions /
  `par_stub_ions_nbfix.str`. That stub file invents approximate terms for OC, OG2P1, NH3,
  NC2… on the explicit premise that *"these residue types are NEVER present in a
  DNA+water+Mg2+ simulation"* — which a protein attachment falsifies. Either psfgen fails
  (safe) or the protein runs on fabricated parameters (not safe). **Untested; check before
  any protein-containing result is used.**
- **Water coordinates come from `spc216.gro` under a TIP3P topology.** SPC geometry
  (r_OH 1.0 Å, θ 109.47°) ≠ TIP3P (0.9572 Å, 104.52°); SETTLE constrains it from step 0,
  so it is a transient, but the shell's initial density is SPC-equilibrated. Mention in
  methods; not a flag.

**Checked and clean:** Mg(H₂O)₆ k = 1 kcal/mol/Å², r₀ = 1.94 Å · CHARMM36 nucleic + CUFIX ·
base-ring ENM k = 0.5/0.1/0.01/0 at 8 Å · PME grid 1.5 · switch/cutoff 8/10 · isotropic
NPT · `wrapAll off` · `langevinHydrogen off` · size-scaled minimisation · settle stage and
×10 piston softening · 300 K throughout the ladder (the 310 K block in `namd_solvate` is
the retired periodic-cell path, not the origami ladder).

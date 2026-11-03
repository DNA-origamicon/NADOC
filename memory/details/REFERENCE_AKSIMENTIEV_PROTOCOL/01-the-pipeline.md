# The pipeline — supporting detail

[Topic head](../../REFERENCE_AKSIMENTIEV_PROTOCOL.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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

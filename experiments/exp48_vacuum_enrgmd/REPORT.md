# exp48 — Vacuum ENRG-MD as a pre-solvation shape-relaxation step

**Question.** The Aksimentiev pipeline relaxes shape cheaply in vacuum *before* solvating.
NADOC solvates the idealised build and does all shape relaxation in explicit water — the
most expensive place to do it. Does adding the vacuum step (a) speed up the relax overall
and (b) let us cut stages from the solvated k-ladder?

**Date.** 2026-07-30. Hardware: RTX 3080 Ti, NAMD 3 Git-2025-12-04 CUDA build, `+p8`.

---

## Headline

Vacuum ENRG-MD is **safe at every size tested** — zero base pairs broken out of 42 / 252 /
3192 — and **shrinks the solvation box 7–9% on any design with real global shape**. It is
*not* free and it is *not* useful on a 2-helix structure. mrdna's 2 ns default is 4–100×
longer than needed; **0.5 ns is ample**, which is what makes the step affordable.

| design | atoms | push bonds | pairs broken | r_max Δ | **rotation box Δ** | wall (2 ns) |
|---|---|---|---|---|---|---|
| 2hb_1xT | 3,043 | 0 | 0 / 42 | +2.8% | **+6.8%** | 21 min |
| 6hb_2xT | 20,797 | 11 | 0 / 252 | −2.6% | **−6.9%** | 19 min |
| 6hb_2xT `r0=31` | 20,797 | 11 | 0 / 252 | −3.5% | **−9.1%** | 21 min |
| 24hb_1xT | 224,261 | 495 | 0 / 3192 | −3.1% | **−8.5%** | 3.2 h |

The sign flip at 2hb → 6hb is the whole story. A 2hb has no global shape to relax, so the
vacuum step only lets it pivot about its single junction and *grows* r_max. From 6 helices
up, it genuinely compacts the structure.

## Convergence — the actionable result

Plateau reached at (RMSD within 5% of final; r_max cross-checked):

| design | plateau RMSD | reached at | fraction of the 2 ns run |
|---|---|---|---|
| 2hb_1xT | 9.16 Å | 0.04 ns | 2% |
| 6hb_2xT | 10.58 Å | 0.03 ns | 1% |
| 24hb_1xT | 25.35 Å | 0.64 ns (r_max by ~0.2 ns) | 32% |

**This agrees with the reference, not with mrdna's default.** The tutorial's own
`step2/hextube.namd` runs ~40 ps — the chapter's "less than 2 ns" is an upper bound, not a
recipe. mrdna's `--enrg-md-steps 1e6` (2 ns) is 4–100× more than any structure here needed.
At 0.5 ns the 24hb costs ~50 min instead of 3.2 h.

## The r0 = 31 Å question, settled empirically

mrdna hard-codes r0 = 31 Å for the interhelical P–P springs. NADOC's honeycomb is 2.25 nm
centre-to-centre and the phosphates this rule selects sit much closer, so 31 Å is a large
local stretch:

| design | built P–P (median) | 31 Å implies |
|---|---|---|
| 6hb_2xT | 20.6 Å | +51% |
| 24hb_1xT | 23.3 Å | +33% |

Ran 6hb both ways. **31 Å is safe**: the springs pulled those 11 sites to a median 30.7 Å
and *not one* of 252 base pairs broke. The `measured` (shape-preserving) arm drifted
outward on its own, 20.6 → 22.6 Å, so the structure wants to open in vacuum regardless;
31 Å just takes it further. Consistent with the term being a genuine repulsion surrogate
for truncated electrostatics rather than a mis-transferred constant.

**Not yet adopted as default.** 11 springs on a 20k-atom structure is a weak test; the
24hb has 495. Re-run the 24hb with `--push-r0 31` before making it the default.

## Economics

Two channels, and only one is measured:

1. **Box shrink — measured, modest.** 7–9% fewer solvated atoms is 7–9% off every
   downstream ladder step. On the 6hb that is 1.60M → 1.49M atoms for 20 min of vacuum.
   Worth it, but not transformative.
2. **Ladder shortening — NOT measured.** This is the larger potential win and needs the
   two-arm comparison (`build_ladder_arms.py`, wired and import-checked but not run).
   Blocked on cost: a 2hb ladder in rotation mode is ~12.7 h per arm.

## What is faithful and what is not

Faithful, read from `mrdna/segmentmodel.py::write_namd_configuration`: PME off, cutoff 10 /
switch 8 / pairlist 12, fixed cell = bbox + `margin 30`, `wrapAll off`, **no barostat**,
2 fs with `rigidBonds all`, `langevinDamping 0.1`, `langevinHydrogen off`.

**Deviation, deliberate — the ENM.** mrdna's vacuum ENM is a 52-key template table of
measured atom-pair distances over pair/stack/cross/paircross neighbours at k=0.1. We use
NADOC's existing tutorial-style base-ring ENM (nine ring atoms, inter-residue, 8 Å cutoff)
at k=0.5, because it already maps onto our atom indices and is validated in our pipeline.
Both hold local duplex geometry while global shape moves; they are not identical.

**Why not just run `enrgmd`.** It ships with mrdna (`.venv/bin/enrgmd`) — no web service
needed, contrary to what `REFERENCE_AKSIMENTIEV_PROTOCOL.md` said. But it calls
`_generate_atomic_model()`, building its own structure from cadnano JSON / vHelix / PDB.
**cadnano has no representation for extra bases at crossovers**, which is the entire
subject of these runs, so a JSON round-trip drops them and the regenerated atom ordering
would not match a NADOC PSF anyway.

## Stability: minimisation must scale with the structure

The 24hb failed on the first attempt — RATTLE constraint failure at 0.26 ns. *Not* a
startup clash: energies were sensible right up to the failure. Root cause is initial VDW of
**1.0×10⁹ kcal/mol** concentrated at the 384 inserted bases, with mrdna's fixed 2400-step
minimisation leaving 4355 atoms still flagged `BAD CONTACTS`. Residual strain found a way
out 130k steps later.

Fix: minimisation scales as one step per 10 atoms (`MINIMIZE_ATOMS_PER_STEP`), 22,428 steps
for the 24hb. Clean 2 ns run afterwards. NAMD requires it to be a multiple of
`stepsPerCycle` (12).

## Bugs found (both produced plausible wrong numbers)

- **`AtomisticModel` is in nm; the PDB writer emits Å** (`pdb_export.py:152`). Every
  push-bond atom lookup failed at a 10× offset and silently produced zero bonds.
- **Every nucleobase carries both N1 and N3.** Picking "whichever of N1/N3 is present"
  paired the wrong nitrogens and read as a 50%-broken duplex on a perfectly good idealised
  build. The atom must be chosen by residue type: purine N1 ↔ pyrimidine N3. Verified —
  A–T lands at 2.60 Å and G–C at 3.39 Å, versus 4.7–6.6 Å for every mis-assignment.

## Which designs exercise the push-bond rule

The ±11 nt crossover exclusion means a crossover-free span must exceed ~22 nt to place any
bond. A densely crossed-over honeycomb bundle generates **zero**; they appear only where
crossovers are sparse — which reproduces the end-weighted distribution measured on the
tutorial's hextube.

| design | helices | crossovers | widest span | push bonds |
|---|---|---|---|---|
| 2hb_1xT | 2 | 2 | 2 nt | 0 |
| 6hb_2xT | 6 | 30 | 26 nt | 11 |
| 24hb_1xT | 24 | 384 | 42 nt | 495 |
| VoltronCore | 59 | 666 | 128 nt | 3143 |

## Files

- `build_vacuum.py` — design → PSF/PDB/ENM/push-bonds/conf. `--ns`, `--push-r0 31|measured|off`
- `push_bonds.py` — mrdna's interhelical rule + coordinate-matched atom resolver +
  topology-derived Watson–Crick pairs. Self-test: `python push_bonds.py`
- `analyse_vacuum.py` — shape, projected solvation cost, base-pair integrity
- `build_ladder_arms.py` — two solvated ladder packages differing only in starting
  coordinates (vacuum result enters via `solute_coords`). **Built, not yet run.**

## Next

1. Re-run 24hb with `--push-r0 31` to decide the default on 495 springs rather than 11.
2. Run the ladder arms — the unmeasured half of the question.
3. If adopted: 0.5 ns, not 2 ns; skip the step entirely below ~4 helices.

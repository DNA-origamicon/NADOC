# exp57 RunPod implicit-solvent validation — result

Date: 2026-08-27. Status: **duplex smoke/stability PASS; paired crossover-2HB
production gate FAIL.** No 6HB or curved origami was run. All pods were destroyed
and the RunPod account was independently verified clean.

## Protocol

- 21-bp mixed-sequence duplex, unrestrained
- AMBER14/OL15 + nucleic-acid GBn2
- 0.150 M generic monovalent Debye screening (κ = 0.927 nm⁻¹)
- 300 K Langevin-middle, 1/ps, 2 fs, HBond constraints
- OpenMM 8.6, CUDA mixed precision, RTX 4090
- 20 ps equilibration, 200 ps clean timing block, 800 ps sampled stability
  block: 1.02 ns total implicit dynamics
- same-card explicit reference: OL15 + TIP3P/PME, explicit 0.150 M NaCl and
  neutralizing counterions, 20 ps equilibration + 200 ps timing

## Performance

| model | atoms | μs/step | ns/day |
|---|---:|---:|---:|
| implicit GBn2 | 1,330 | 97.15 | 1,778.71 |
| explicit TIP3P/PME | 55,414 | 298.67 | 578.56 |

The measured same-engine, same-GPU speedup is **3.074×**. Atom count fell
41.7×, but runtime did not: this small duplex is dominated by fixed GPU/launch
overheads and GB's long-range work. Treat 3.07× as evidence that the direction is
worth scaling, not as an origami performance forecast. This comparison isolates
implicit versus explicit solvent in OpenMM; it is not yet a same-card NAMD versus
OpenMM engine benchmark.

## Stability

The preregistered basic gate passed.

| observable | result | gate |
|---|---:|---:|
| final core WC contact occupancy | 100% | ≥80% |
| 40-frame mean core WC occupancy | 99.30% | — |
| minimum sampled core WC occupancy | 93.02% | — |
| final aligned C1′ RMSD | 0.193 nm | ≤0.50 nm |
| maximum sampled aligned C1′ RMSD | 0.290 nm | — |
| final mean core C1′ pair distance | 1.075 nm | — |
| maximum sampled core C1′ pair distance | 1.120 nm | ≤1.40 nm |
| final potential energy | −34,487 kJ/mol | finite |

This proves only short-run duplex integrity. It does not establish long-time
ensemble fidelity, origami mechanics, crossover stability, or ion-specific
physics.

## Paired 2HB crossover result

A fully sequenced 2HB motif (95 nucleotides including one crossover insertion,
42 mapped WC pairs, and three physical inter-helix O3′–P bonds) was run for the
same 1.02 ns protocol in both implicit GBn2 and explicit TIP3P/PME. The explicit
arm used 150 mM NaCl plus neutralizing counterions. Both arms ran on the same RTX
4090 with the same seed and sampling schedule.

| model | atoms | ns/day | mean WC occupancy | final C1′ RMSD | max O3′–P |
|---|---:|---:|---:|---:|---:|
| implicit GBn2 | 3,011 | 1,037.63 | 97.07% | 0.932 nm | 0.171 nm |
| explicit TIP3P/PME | 111,062 | 336.52 | 99.82% | 0.527 nm | 0.167 nm |

The paired same-engine, same-GPU speedup was **3.083×**, with 36.9× fewer atoms.
The explicit arm passed the fixed 0.70 nm final/global C1′ RMSD gate; implicit
failed it. A prior implicit technical repeat also failed, ending at 0.756 nm,
while retaining 98.61% mean WC occupancy. These are technical repeats with the
same seed, not an independent-seed ensemble.

The failure is collective rather than covalent. In the paired run all crossover
bonds remained near their expected covalent length, and individual-helix
internal C1′ RMSD stayed below 0.469 nm. CPU-only decomposition relative to the
first saved frame showed:

| collective observable | implicit | explicit |
|---|---:|---:|
| maximum global C1′ RMSD | 0.627 nm | 0.450 nm |
| helix COM separation range | 2.768–3.027 nm | 2.493–2.652 nm |
| maximum inter-helix axis angle | 23.59° | 8.34° |

Thus the generic screened GBn2 model preserves duplexes and phosphodiester
junctions over this short run but allows materially greater helix separation and
reorientation than the matched explicit-ion/water control. That is direct
evidence against promoting this salt-only model to production origami MD.

## Cost and lifecycle

The successful duplex pod cost approximately **$0.033**; the successful first
2HB and paired 2HB pods cost approximately **$0.056** and **$0.108**. Including
short attempts that exposed integration and host defects, total campaign spend
was **$0.522** of the authorized $5. The one interrupted teardown was recovered
by an explicit account reaper and a separately minted termination receipt. The
final account check reported zero live pods and no compute billing.

Downloaded primary evidence is under
`/media/jojo/Archive/nadoc_openmm_exp57/duplex_runpod/`:

- `result.json` — full 40-frame metric series and timing
- `implicit.dcd` — sampled implicit trajectory
- `implicit-final.cif`, checkpoint, and portable OpenMM State
- `chain.log`, lifecycle ledger, spend ledger, and confirmation receipts

The decisive paired 2HB evidence is under
`/media/jojo/Archive/nadoc_openmm_exp57/2hb_paired_runpod_v2/`, including both
trajectories, final structures, checkpoints, portable states, full metric
series, and lifecycle receipts. The earlier 2HB technical repeat is preserved
under `2hb_runpod_v2/`.

## Integration defects found by the paid gate

1. RunPod's base Python is PEP-668 managed; the campaign now installs into a venv.
2. OL15 terminal residue names and OpenMM hydrogen-definition names differ. The
   topology stays canonical and uses explicit `XX5`/`XX3` residue-template maps.
3. OpenMM uses `unit.molar`, not the old checker's `moles_per_liter` spelling.
4. Loading `implicit/gbn2.xml` makes `implicitSolvent=GBn2` redundant and invalid;
   the XML accepts `implicitSolventKappa` directly.
5. pip resolved CUDA 12.9 NVRTC, which fails with PTX error 222 on driver-570
   hosts. The RunPod campaign now requires CUDA 12.9-capable hosts before rental.
6. Origami atom generation is helix-oriented and interleaves crossover strands;
   OpenMM requires each chain and its residues to be contiguous. The direct
   builder now groups by full strand ID and orders residues by physical
   `seq_num`, while preserving serial-indexed covalent bonds.
7. A quiet venv install can leave a valid detached launch log at zero bytes for
   the first receipt window. Launch verification now accepts the independently
   observed live chain process; phase, exit, and process monitoring cover the
   remainder of the run.

## Next gate

Do not advance to 6HB or curved origami with the present salt-only model. The
next scientific gate must explain the excess inter-helix separation with
independent seeds and longer matched 2HB runs. Plausible model-development arms
are explicit mobile counterions embedded in an otherwise implicit solvent, or a
validated ion-atmosphere/field correction; neither may double-count the current
Debye kappa. Only a model that matches explicit 2HB spacing and bending
distributions should return to the 6HB ladder. The active explicit NAMD
trajectory remains untouched as the eventual curved-origami reference.

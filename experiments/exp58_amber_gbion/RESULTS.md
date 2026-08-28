# exp58 result — native Amber26 OL15/GBION duplex

The preregistered basic duplex gate passed on 2026-08-27. This establishes that
the selected Amber26 model runs natively on an NVIDIA GPU, preserves a short DNA
duplex for 1 ns, and is slightly faster than a tightly solvated explicit-water
duplex on the same GPU. It does not yet establish long-timescale or origami-scale
accuracy.

## Environment and lifecycle

- Engine: licensed Amber26 `pmemd.cuda`, SHA-256
  `11ccef9721484963b20389a15aea2604e3169276fb450642e6edc4858e790ac2`
- Build input: `pmemd26.tar.bz2`, Amber MD5
  `ceeabc133e772c115183d5cf6a87676b`
- GPU: NVIDIA GeForce RTX 4090, driver 570.195.03
- Pod: `jf745usk4kfhqm`, $0.74/hour
- Estimated exp58 spend: $0.69645 of the $5 hard cap
- Setup, launch, and deletion confirmations all passed; the pod is absent from
  the account. An unrelated agent's pod was preserved.
- The local NAMD production process remained active and untouched. No local
  molecular test was run.

The initial portable build used all 96 vCPUs and one CUDA compilation was killed
for memory pressure at 93%. The cached build completed with four jobs, but the
subsequent clean 6HB build showed that four jobs can still exceed 251 GiB when two
coarse-grid units overlap. The generic portable launcher is now serial; the separate
Ada-only 6HB launcher uses an SM8.9 source patch and four jobs.

## Model and topology

- Sequence: `CGCGAATTCGCGATCGATCGA`, 21 base pairs
- OL15 with standard unphosphorylated 5' termini
- GBneck2: `igb=8`
- GBION v3: `gbion=3`, `gbsa=3`, `alpb=0`, `saltcon=0`
- Explicit ions: 51 Na+ and 11 Cl- from the SLTCAP equation for a 40 Å sphere
  at nominal 0.150 M; solute charge -40 e and final system charge effectively 0
- Joung/Cheatham TIP3P ion parameters, `mbondi3`, chloride GB radius 1.4 Å
- 1,392 atoms; 40 phosphorus atoms; no inter-strand covalent bonds
- Ion-wall sampling maximum: 40.401 Å against a 40.5 Å gate

The input conversion removes the P/OP1/OP2 atoms from each NADOC 5' terminus,
preserves PDB `TER` records, and explicitly rejects an inter-strand bond. This was
necessary because the NADOC NAMD/CHARMM export and standard Amber OL15 terminal
chemistries differ.

## Native GPU and parity evidence

- The Amber output contains the GPU device banner and echoes `gbion = 3`.
- One-cycle CPU `pmemd` energy: -6369.5 kcal/mol
- One-cycle GPU `pmemd.cuda` energy: -6369.5 kcal/mol
- Parsed difference at Amber's printed precision: 0.0 kcal/mol; preregistered
  relative tolerance: 1e-4
- Clean GBION timing: 633.65 wall-clock ns/day (Amber-reported 646.27 ns/day)

## Duplex stability over 1 ns

- 100 trajectory frames, 10 ps apart
- Mean core Watson-Crick contact occupancy: 0.9872
- Minimum per-frame core occupancy: 0.9302
- Final core occupancy: 0.9767
- Final aligned C1' RMSD: 0.4288 nm (gate <= 0.5 nm)
- Final maximum core C1'-C1' pair distance: 1.1204 nm (gate <= 1.4 nm)
- All 1,433 covalent bonds in the final frame were 0.08–0.20 nm
- Bond RMS deviation from equilibrium: 0.00261 nm; maximum: 0.01252 nm
- Energies remained finite

These metrics support **basic run stability**, not converged structural fidelity.
The final RMSD is below the preregistered bound but is close enough that longer
and larger validation remains mandatory before production use.

## Same-GPU explicit-water comparison

The explicit reference used the same OL15 solute, 12,478 TIP3P waters, 79 Na+,
39 Cl-, a 10 Å octahedral buffer, and 0.1487 M added salt. It contained 38,882
atoms and ran at 604.06 wall-clock ns/day (Amber-reported 621.85 ns/day).

GBION was therefore **1.049x faster** for this compact duplex. The small gain is
scientifically informative: a 4090 is under-filled by both systems, and explicit
PME is highly optimized. The duplex proves correctness and stability but is a
poor proxy for the intended sparse/curved-origami workload, where water-box atom
count grows much faster. A representative origami comparison is still required
to establish a production-relevant speedup.

## Evidence archive

Authoritative artifacts are under
`/media/jojo/Archive/nadoc_amber_exp58/duplex_runpod/`:

- `result.json` — all gates and per-frame metrics; SHA-256
  `8c2a4d88a716daa3ec50282237d0d6df264d633f8dcedddfe201c7fd57cd39fa`
- `controller_summary.json` and `confirmations.jsonl` — budget and lifecycle proof
- `gbion.parm7`, `gbion.rst7`, `disang_NaCl.txt` — implicit/explicit-ion input
- `gb_production.nc`, `gb_production.mdout`, `gb_production.rst7` — 1 ns evidence
- `explicit.parm7`, `explicit.rst7`, `explicit_benchmark.mdout` — same-GPU control
- `cmake.log`, `build.log`, `nadoc_chain.out` — native build and execution log

No additional package or force-field download is required for this validated
duplex workflow. Amber26 and the conda-forge AmberTools26 data provide all needed
OL15, Joung/Cheatham, GB radii, and execution files.

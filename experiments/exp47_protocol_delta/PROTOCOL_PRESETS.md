# Named MD protocols NADOC could offer, and what hardware each needs

Research pass, 2026-07-29. **No code was changed.** Every parameter below was read out of
the protocol's own scripts or its Methods section, not from a summary — where a number
could not be verified it is marked *(not stated)*.

The goal is that a user should be able to pick a named protocol instead of hand-matching
conditions, and afterwards be able to answer *"is this what I would have got if I had
followed an established protocol?"* — see the conformance-report design at the end.

---

## P1 — ENRG-MD vacuum relax  (*"Aksimentiev Structure Relax"*)

Cadnano's idealised lattice → a realistic conformation, **with no solvent at all**.
Source: `step2/hextube.namd` in the origami tutorial; chapter §3.2.

| | |
|---|---|
| engine / FF | NAMD, `par_all36_na.prm` + `par_water_ions_na.prm` |
| solvent | **none** — cell 1000³ Å, `PME no`, `margin 30` |
| restraints | `.exb` from the ENRG-MD server, serving **two** purposes: base ENM *and* an inter-helical **P–P repulsion** term (harmonic bonds, 31 Å rest length, between the phosphorus atoms of every base pair) that stands in for the electrostatic repulsion of explicit solvent |
| integrator | 2 fs, `rigidBonds all`, `fullElectFrequency 3`, `stepspercycle 12` |
| nonbonded | `switchdist 8 / cutoff 10 / pairlistdist 12` |
| thermostat | Langevin 300 K, **`langevinDamping 0.1`** (deliberately low friction to relax fast), `langevinHydrogen off` |
| length | `minimize 4800` + **43 ps** (hextube). Chapter: *"For a ~7500-bp object, 2 ns was sufficient to achieve a fully relaxed structure."* |
| cost | DNA atoms only. The chapter claims this route is **~10⁴× cheaper** than explicit-solvent MD and *"in less than 2 ns … better structure is obtained than in 200 ns of all-atom MD"* |

**Use when:** you want a relaxed starting structure, not thermodynamics. Runs on a laptop.

---

## P2 — Aksimentiev explicit-MgCl₂ origami relax  (*"Aksimentiev Relax"*)

The canonical one. Source: `step3/*.namd`, `solIon.tcl`, `mk_extra.sh`,
`cadnano2pdb2enm.pl`. Already detailed in
[REFERENCE_AKSIMENTIEV_PROTOCOL](../../memory/REFERENCE_AKSIMENTIEV_PROTOCOL.md).

| | |
|---|---|
| FF | CHARMM36 NA + **CUFIX** (`par_water_ions_cufix.prm`), TIP3P |
| ions | Mg²⁺ as explicit **Mg(H₂O)₆²⁺** with `mghh_extrabonds` holding the 6 waters; Cl⁻ by `autoionize` to neutrality |
| box | VMD `solvate`, DNA bbox **± 20 Å per face**, full fill |
| restraints | ENM on the **nine base-ring atoms** (N1,C2,N3,C4,C5,C6,N7,C8,N9), inter-residue, ≤ **8 Å**, equilibrium length = measured |
| ladder | k = **0.5 → 0.1 → 0.01 → 0** kcal/mol/Å², **4.8 ns each** (19.2 ns total) |
| integrator | 2 fs `rigidBonds all`, `fullElectFrequency 2`, `stepspercycle 12` |
| nonbonded | 8 / 10 / 12, `PME yes`, **`PMEGridSpacing 1.5`** |
| thermostat / barostat | Langevin 300 K damping 5; piston 1.01325 bar, **period 1000 / decay 500**; `useFlexibleCell`/`useGroupPressure` unset |
| output | `wrapAll off`, `wrapWater off` |
| size of the reference system | cell 124 × 114 × 323 Å ⇒ **≈ 0.46 M atoms** |
| acceptance gates | box trace flat after ~300 ps; RMSD plateau; charge within 2 nm; broken-bp count |

---

## P3 — Membrane-spanning DNA nanopore  (*"Aksimentiev Nanopore-in-Membrane"*)

Joshi, Li & Aksimentiev, *Methods Mol. Biol.* **2639**, 113–128 (2023).

| | |
|---|---|
| system | DNA origami nanopore + POPC bilayer + 1 M KCl, **235,646 atoms** |
| FF | CHARMM36 water/ions/nucleic/lipid + **latest CUFIX** (ion–DNA, ion–ion, DNA–lipid) |
| minimisation | 1200 steps conjugate gradient |
| restraint ladder | all DNA non-H atoms harmonically restrained at **k = 1 kcal/mol/Å² for 205 ns** (lets lipid + water equilibrate around a held-rigid solute), then 0.5, then 0.1 × 4.8 ns each; **then** switch to ENM (excludes H, phosphate groups, same-nucleotide pairs, and pairs > **8 Å**) at 0.5 → 0.1 → 0.01, 4.8 ns each |
| integrator | **2–2–6 fs multiple time-stepping**, SETTLE (water) + RATTLE (other H) |
| nonbonded | **8–10–12 Å**, PME grid **1.2 Å** |
| ensemble | NPT 295 K, Nosé–Hoover Langevin piston, **anisotropic** with the membrane-plane (x–y) ratio held constant |
| production | **2.2 µs on Anton 2** |

**Note the 205 ns fixed-solute stage** — the same idea as the tutorial's Note-4 remedy,
run to convergence. This is the reference for anything with a lipid or a long solvent
relaxation.

---

## P4 — Counterion / low-Mg stability  (*"Markvoort Counterion"*)

Roodhuizen, Hilbers, de Greef & Markvoort, *ACS Nano* **13**, 10798 (2019).

| | |
|---|---|
| engine / FF | **NAMD**, CHARMM36 DNA + improved ion and polyamine parameters, TIP3P |
| system | 512-bp origami rectangle, box **250 × 70 × 270 Å** (≈ 0.47 M atoms) |
| ions | 10 mM Mg²⁺ / 5 mM Mg²⁺+10 mM Na⁺ / 20 mM Na⁺ / oligolysine K₁₀ / spermine⁴⁺ at N:P ≈ 1:1 |
| minimisation | 10⁴ steps with **all DNA backbone atoms fixed** |
| equilibration | NVT stepwise heating to 295 K → NPT 0.5–1.5 ns with polyamine restraints → NPT 3–4 ns with the DNA backbone restrained (ions free) → brief minimise + NVT after release |
| nonbonded | **10–12 Å switching**, PME grid **1.0 Å** |
| barostat | Langevin thermostat + Nosé–Hoover barostat; **piston period 1000 fs during equilibration, 200 fs during production** |
| production | **100 ns**; equilibrium judged by backbone RMSD relative to the half-way structure — steady after **50 ns** |

**This is the protocol NADOC's electrostatics and production barostat already match**
(10–12 Å switching, PME 1.0, piston 200 in production). NADOC is not "off-protocol"; it is
on *this* one rather than on P2's.

---

## P5 — mrdna multi-resolution  (*"mrdna Predict"*)

Maffeo & Aksimentiev, *Nucleic Acids Res.* **48**, 5135 (2020). Engine: ARBD (GPU).

| stage | model | typical length | wall clock (Quadro RTX 5000) |
|---|---|---|---|
| coarse | 5 bp / bead | 200 ns – 4 µs (800 ns typical, 4 M steps) | ~5 min |
| fine | 2 beads / bp | 800 ns (20 M steps); 10 ns ×2 for linking-number relaxation | ~4 h |
| atomistic | spline → canonical bp coordinates | — | seconds |

Whole workflow **≤ 30 min** for a typical origami; output is *"directly suitable for
subsequent all-atom MD"* and can hand off to oxDNA or ENRG-MD. Use as the front end for
anything too large for P1.

---

## Which protocol at which size, on which machine

Measured on this box (RTX 3080 Ti 12 GB, 16 threads) unless marked *(est)*:

| solvated atoms | throughput | P1 vacuum | P2 ladder (19.2 ns) | 100–200 ns production |
|---|---|---|---|---|
| 3 k (DNA only, 2hb) | n/a — vacuum | seconds | — | — |
| **21 k** (2hb, carved) | **353 ns/day @ 4 fs+HMR**; 127 @ 2 fs resident; 80 @ 1 fs | — | 1.3 h @ 4 fs / 3.6 h @ 2 fs | 13 h @ 4 fs (measured: 200 ns) |
| ~35 k (2hb, full box) | ~250 ns/day *(est)* | — | ~2 h | ~19 h |
| ~90–100 k (2hb, tumble-proof box) | ~100 ns/day *(est)* | — | ~5 h | ~2 days |
| **~225 k** | 42 ns/day (resident, measured previously) | — | ~11 h | ~5 days |
| **~0.46 M** (P2 hextube, P4 rectangle) | ~20 ns/day *(est)* | — | ~1 day | ~10 days → cluster |
| **1.3 M** (VoltronCore) | 6.7 ns/day (25.7 ms/step, measured) | — | ~3 days | not local |
| **8.9 M** (VoltronCore full box) | won't fit 12 GB | — | — | RunPod / Alpine |

Rules of thumb this supports:

- **P1 (vacuum ENRG-MD) has no size ceiling worth worrying about** — it is DNA-only and
  ~10⁴× cheaper. It should be the default first pass at every size, and it is the only
  thing that is genuinely cheap for ≥ 1 M-atom designs.
- **P2 is affordable locally up to ~250 k atoms.** Beyond that the 19.2 ns ladder alone is
  a day or more.
- **P3-scale work (µs production) is not a local protocol** — its reference production ran
  on Anton 2. Offer it as a *settings* preset for cluster/RunPod targets only.
- **P4's 100 ns production at ~0.5 M atoms is ~10 days locally** — cluster territory, and
  its own RMSD criterion says 50 ns is the minimum useful window.
- **mrdna (P5) is the front end that makes large designs tractable at all**; NADOC already
  has an mrdna runner.

---

## Answering *"is this what an established protocol would have done?"*

The gap is not that NADOC's settings are wrong — it is that nothing tells the user which
protocol their run corresponds to. Proposed (not implemented): every prepared job emits a
`protocol_conformance.json` and a one-screen rendering of it.

**Per setting**, compare the value used against each preset, and classify
`match` / `deviates` / `not-applicable`, with the reference's citation attached. Cover:

1. force field files, water model, ion model and concentration;
2. box padding, fill mode (full / carved), resulting solute-to-image clearance;
3. restraint scheme — atom set, cutoff, k ladder, per-stage durations;
4. integrator — dt, `rigidBonds`, HMR, multiple time-stepping;
5. electrostatics — switch / cutoff / pairlist / PME grid;
6. thermostat, barostat, ensemble, piston period + decay;
7. run lengths per stage;
8. the protocol's **own acceptance gates** — box trace flat after 300 ps (P2), RMSD
   plateau, broken-bp count, charge within 2 nm.

The verdict line should read like a diff, e.g.

> Matches **Aksimentiev Relax (P2)** except: `timestep` 4 fs vs 2 fs (HMR; locally
> validated, `feedback_namd_4fs_production_only`), `PMEGridSpacing` 1.0 vs 1.5 (finer),
> `switch/cutoff` 10/12 vs 8/10 (matches **Markvoort P4** instead), `padding` 1.2 nm vs
> 2.0 nm (**deviation, no justification recorded**).

Two properties matter: deviations carry a *reason*, and conformance is reported on
**evidence as well as settings** — a run that used the right numbers but whose box trace
never flattened has not followed the protocol, whatever its config said.

Cheapest first step, independent of any preset work: **emit the protocol's own gates as
job health output.** The box-size trace is the one that would have caught the failure in
`exp47` on its first 300 ps.

---

## Sources

- [A Practical Guide to DNA Origami Simulations Using NAMD](https://bionano.physics.illinois.edu/tutorials/practical-guide-dna-origami-simulations-using-namd) — tutorial + `origamitutorial.tar.gz` (scripts read directly)
- Yoo, Li, Slone, Maffeo, Aksimentiev, *A Practical Guide to MD Simulations of DNA Origami Systems*, Methods Mol Biol **1811** (2018) — [PDF](https://bionano.physics.illinois.edu/sites/default/files/origamiprotocols_0.pdf)
- Joshi, Li, Aksimentiev, *All-atom MD simulations of membrane-spanning DNA origami nanopores*, Methods Mol Biol **2639** (2023) — [tutorial](https://bionano.physics.illinois.edu/tutorials/all-atom-simulation-membrane-spanning-dna-nanopores)
- Roodhuizen et al., *Counterion-Dependent Mechanisms of DNA Origami Nanostructure Stabilization*, ACS Nano **13** (2019) — [PMC6764110](https://pmc.ncbi.nlm.nih.gov/articles/PMC6764110/)
- Maffeo & Aksimentiev, *mrdna*, Nucleic Acids Res **48**, 5135 (2020) — [NAR](https://academic.oup.com/nar/article/48/9/5135/5814051)
- Maffeo, Yoo, Aksimentiev, *De novo reconstruction of DNA origami structures*, Nucleic Acids Res **44**, 3013 (2016) — [NAR](https://academic.oup.com/nar/article/44/7/3013/2467847)
- Haggenmueller, Matthies, Sample, Šulc, *How we simulate DNA origami* (2024) — [arXiv:2409.13206](https://arxiv.org/pdf/2409.13206) (oxDNA-side context)

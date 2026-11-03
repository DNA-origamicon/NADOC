# The settle stage restrains, it does not use `fixedAtoms` (2026-08-04) — supporting detail

[Topic head](../../REFERENCE_AKSIMENTIEV_PROTOCOL.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### The settle stage restrains, it does not use `fixedAtoms` (2026-08-04)

Note 4's "with the DNA position fixed" is **prose in the chapter, not a scripted choice** —
the tutorial's own step-4 scripts have no settle stage at all — so it describes intent, not
NAMD's `fixedAtoms` keyword. NADOC implements it as harmonic position restraints on DNA
heavy atoms at **k = 1 kcal/mol/Å²** (`md_protocols.SETTLE_RESTRAINT_K`,
`restraints_settle.pdb`). Three reasons, none of them throughput:

- **NAMD's manual argues against the literal reading.** "The use of constant pressure with
  significant numbers of fixed atoms is not recommended." Forces *between* fixed atoms are
  also dropped from the virial unless `fixedAtomsForces` is on — so a fixed-DNA settle
  stage feeds the barostat an incomplete pressure in the one stage that exists to let the
  barostat find the right volume. GROMACS states the same rule outright: positional
  restraints, not frozen atoms, are what pressure equilibration needs.
- **k = 1 is Aksimentiev's own published value** for holding origami during equilibration
  (PNAS 2013 *In situ structure and dynamics*; NAR 2016 *De novo reconstruction*): harmonic
  restraints on all DNA heavy atoms, k = 1 kcal/mol/Å².
- **NAMD 3 refuses `fixedAtoms` under GPU-resident** and names harmonic restraints as the
  sanctioned workaround.

**Measured equivalence** (6hbx32, 234 646 atoms, 50 ps, 2 fs, three arms): the cell settles
to **95.34 %** of its starting volume restrained vs **95.39 %** fixed — 0.05 pp apart on a
4.6 % shrink — while the DNA moves **0.35 Å RMS** (minimisation alone moves it 1.19 Å; the
ENM ladder that follows, ~10 Å). Throughput: 254.6 s vs 489.3 s for the same 50 ps, i.e.
**1.9× faster**, all of it from keeping GPU-resident (restraints are ~7 % *slower* than
fixed atoms on the offload path, since fixed atoms skip force evaluation).

⚠ The restraint reference must be the **minimised** coordinates. The package ships it at the
build pose (prep runs before any minimisation exists) and `namd_runner.retarget_settle_restraints`
re-points it after minimisation — without that it pulls at ~2.4 kcal/mol/Å average (11 at
worst) against exactly the clashes minimisation just relieved.

⚠ Anything that still emits `fixedAtoms` — **hard anchors** (`anchor_k is None`) — forfeits
GPU-resident. That gate lives in **two** conf writers, `_segment_conf` *and*
`build_production_conf`; fixing only one leaves the other emitting the fatal pair
(LESSONS H16).

**Confirmed in production** (job `4dbc788c1b54`, 6hbx32, 2026-08-05): probe flips to
`gpu_resident_ok: true`, no Gate-B modal, `Running with GPU-resident mode`, 11 330 atoms
held at k=1.00, live DNA-vs-reference **0.354 Å RMSD** (predicted 0.348), reference-vs-
minimised 0.0005 Å (the retarget fired), solvent free at 47.6 Å RMSD, cell −4.80 % at
66.6 ps, T = 299.8 K, NAMD warning set byte-identical to the validated probe.

⚠ **Open: absolute throughput is below the probe.** Live 15.4 ms/step (11.2 ns/day) vs
~10.2 ms/step in the isolated probe of the same conf. The *relative* 1.9× over
fixed+offload still holds (both arms were measured at identical output cadence), but the
absolute rate is not the probe's. Only clear config difference: production writes a restart
every **5 000** steps and a DCD frame every 8 320, against 25 000/25 000 in the probe — and
at 15.4 ms/step that is a restart every 77 s, ~2.3× more often than the ~3 min optimum
`_RESTART_EVERY_STEPS` documents. Pre-existing (the constant assumes a faster ms/step), not
caused by the restraint change, and **untested** — do not run a competing GPU job to check
it while a production sim is live.

Priority if matching them: padding 1.2 → 2.0 nm; production piston back to 1000/500; add
their fixed-DNA NPT pre-stage to settle an underfilled box; carve → NVT everywhere
including production; `wrapAll off`; adopt the box-size trace as an automated gate.
**Matching them does NOT fix small-solute tumbling** — ±20 Å on a 2hb still gives 60 Å
against a 71 Å requirement; their systems are large origami run 4.8 ns unrestrained, so
tumbling never bites. That extra rule is NADOC-specific.

# NAMD nanopore ion transport

NADOC can prepare an explicit-solvent graphene nanopore either beneath a
surface-deposited oxDNA seed or as a membrane-only control. Both workflows use the
same CHARMM/CUFIX electrolyte model, periodic cell, field configuration, transport
analysis, and local/Alpine/RunPod execution paths.

## Choose the experiment

Use an **oxDNA-seeded nanopore** when the DNA origami is the object whose effect on
conductance or selectivity is being measured. Complete surface deposition first,
choose **Use as NAMD seed**, and enable the graphene hard surface in the NAMD setup.
The deposited pose, ordinary anchors, and surface anchors are inherited. They remain
editable before launch.

Use **Graphene only** for the open-pore control. Enable **Apply hard surface** and
**Graphene-only control** without selecting a DNA seed. The default aperture is
2.1 nm in diameter. Reservoir padding controls the water depth normal to the sheet;
salt mode and concentrations are properties of the explicit-solvent job rather than
of the hard-surface card.

The control is scientifically useful: it checks the field, electrolyte, periodic
boundary, pore geometry, current estimator, and finite-size behavior before DNA is
introduced. It is not a calibration of a specific experimental chip unless the
graphene model, thickness, ion parameters, voltage, and reservoir dimensions match
that experiment.

## Preparation and relaxation

An oxDNA seed is backmapped from the current native oxDNA sites, including simulated
crossover-extra positions and orientations. It is recentered only after atomistic
reconstruction. Seeded jobs always run declash/minimization and restrained release;
coarse-grained excluded volume is not sufficient evidence that the atomistic seed is
clash-free. Ring-pierced covalent topology is rejected unless the explicit wizard
override is selected.

A graphene-only package contains no DNA elastic network. Its relaxation therefore
uses one chunked **300 K NVT graphene/solvent equilibration** stage rather than the
DNA `k=0.5 → 0.1 → 0.01 → 0` release ladder. The graphene sites retain their hard
surface restraints. Early stopping uses potential-energy stability (and volume when
an applicable ensemble supplies it); C1′ and Watson–Crick metrics are marked not
applicable. Once stable, remaining control chunks are bridged from the accepted
checkpoint.

The same rule is emitted into local, Alpine, and RunPod execution. DNA-containing
jobs keep the stricter energy-plus-Watson–Crick early-stop rule. GPU-resident NAMD is
used when selected and compatible; harmonic positional restraints are used for the
graphene and inherited anchors so the control does not require NAMD `fixedAtoms`.

## Manual UI workflow

1. Open **Dynamics → NAMD** and create a relaxation job.
2. In the hard-surface card, enable **Apply hard surface**.
3. For an open-pore control, enable **Graphene-only control**. For an origami run,
   start from the completed surface-deposited oxDNA job instead.
4. Set pore diameter, layer count and spacing, water clearance, and sheet margin.
5. In the Job Wizard set reservoir padding and the salt mode/concentrations. These
   controls determine the solvated cell and electrolyte, so they are intentionally
   not duplicated in the hard-surface card.
6. Use the optimized/design-speed protocol for exploratory equilibration. Review the
   generated plan, GPU target, estimated cost, and field before preparing or running.
7. After relaxation, start an ion-transport production job with the intended voltage,
   duration, output cadence, and random seed. Use multiple independent productions
   for uncertainty estimates.

## Display and analysis

Turn on **Display MD**, then use the Visualizations controls to show **Water**,
**Ions**, and **Periodic box** independently. DNA jobs are unwrapped and aligned to
the design. Graphene-only jobs have no DNA reference, so the pore and cell center are
placed at the scene origin and solvent/ions receive the identical transform. A water
hydration shell is undefined without DNA; graphene-only water display therefore uses
the whole cell, subject to the viewer's safety cap.

When the selected design contains a nanopore, the Metrics card exposes the ion
transport plot. NADOC reports species-resolved current, total current, cumulative
positive/negative/net crossings, pore occupancy, cumulative transported charge, and
conductance when a nonzero voltage is recorded. A crossing is counted when a tracked
ion intersects the membrane plane between successive frames inside the circular
aperture. Use current over a sufficiently long stationary production interval as the
primary observable; raw crossing counts are a diagnostic and become noisy at short
duration or sparse trajectory output.

## Headless workflow

`scripts/nadoc_ion_transport.py` exposes preparation, execution, status, and analysis
without the browser. It supports either an oxDNA job identifier or the graphene-only
control flag, along with pore geometry, reservoir padding, salt composition, field,
execution target, and budget settings. Run its `--help` output for the current command
and option names; the script calls the same API used by the UI, so validation and
manifest provenance remain identical.

The prepared package records the nanopore descriptor, aperture center and normal,
box dimensions, electrolyte census, random seed, restraint mechanism, protocol
fidelity, and execution settings. Preserve the package manifest and generated
`ion_transport_analysis.json` with any reported result.

## Interpretation and controls

- Run the graphene-only open pore before the DNA-blocked pore.
- Match voltage, salt, box, temperature, pore geometry, timestep, and output cadence
  between control and DNA runs.
- Discard equilibration before estimating current and uncertainty.
- Use independent velocity/random seeds for replicate productions.
- Check ion trajectories visually for periodic-image or membrane-bypass artifacts.
- A single graphene layer with neutral Lennard-Jones carbon sites is a modeling choice,
  not a generic solid-state nanopore. Report it explicitly.

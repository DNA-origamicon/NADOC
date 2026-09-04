# NAMD nanopore ion transport

NADOC can prepare an explicit-solvent graphene nanopore against a fresh NAMD design,
beneath a surface-deposited oxDNA seed, or as a membrane-only control. All workflows use the
same CHARMM/CUFIX electrolyte model, periodic cell, field configuration, transport
analysis, and local/Alpine/RunPod execution paths.

## Job creation and the package freeze boundary

Creating a relaxation job records a lightweight draft; it does not build or solvate a
package. The user may continue changing the hard surface, pore geometry, structural and
surface anchors, electric field, protocol, and compute target. Pressing **Run** freezes
the live design and those saved controls, builds the package once, and then starts it
locally or stages it to Alpine/RunPod. Consequently a topology-changing pore edit never
causes a throwaway first solvation, and the remote target receives the same manifest,
restraint marker, and NAMD configuration that the local package inspector displays.

Once preparation begins, topology-changing controls are locked for that run. Create a
new draft to change the pore geometry of a package that has already started.

## Choose the experiment

Use an **oxDNA-seeded nanopore** when the DNA origami is the object whose effect on
conductance or selectivity is being measured. Complete surface deposition first,
choose **Use as NAMD seed**, and enable the graphene hard surface in the NAMD setup.
The deposited pose, ordinary anchors, and surface anchors are inherited. They remain
editable before launch.

For a fresh design, open **Hard surface** and choose the intended **Design face**
(`-X`, `+X`, `-Y`, `+Y`, `-Z`, or `+Z`). The aperture is centered on that face's
bounding-box projection. **Face offset** moves the first graphene layer outward from
the face and is persisted in the job, so subsequent recentering, reload, retry, copy,
and production derivation retain the same placement. **DNA clearance** is an
independent minimum atom-to-sheet separation; the larger of clearance and face offset
governs the final contact distance. Leave the face on **Inherited / auto** to reuse a
resolved oxDNA deposition plane, then enable **Add graphene nanopore** to reveal its
aperture, layer, clearance, and margin settings.

Use an empty design for the open-pore control and enable **Add graphene nanopore**.
NADOC detects that the design contains no DNA strands and automatically selects the
graphene-only preparation and relaxation path. The default aperture is 2.1 nm in
diameter. Reservoir padding controls the water depth normal to the sheet;
salt mode and concentrations are properties of the explicit-solvent job rather than
of the hard-surface card.

The control is scientifically useful: it checks the field, electrolyte, periodic
boundary, pore geometry, current estimator, and finite-size behavior before DNA is
introduced. It is not a calibration of a specific experimental chip unless the
graphene model, thickness, ion parameters, voltage, and reservoir dimensions match
that experiment.

Historically, published all-atom origami calculations usually converted a caDNAno
design directly to an idealized atomistic PDB/PSF and then relaxed it in NAMD. An
oxDNA seed is an optional NADOC refinement, not a requirement imposed by NAMD: it
allows atomistic relaxation to start from an already bent, twisted, or
surface-deposited conformation. For a rigorous comparison, retain a direct-build
control when the coarse-grained preparation history could affect conductance.

## Preparation and relaxation

An oxDNA seed is backmapped from the current native oxDNA sites, including simulated
crossover-extra positions and orientations. It is recentered only after atomistic
reconstruction. Seeded jobs always run declash/minimization and restrained release;
coarse-grained excluded volume is not sufficient evidence that the atomistic seed is
clash-free. Ring-pierced covalent topology is rejected unless the explicit wizard
override is selected.

A graphene-only package contains no DNA elastic network. Its relaxation therefore
uses one chunked **300 K NVT graphene/solvent equilibration** stage rather than the
DNA `k=0.5 → 0.1 → 0.01 → 0` release ladder. The graphene sites retain stiff
harmonic positional restraints. Early stopping uses potential-energy stability (and volume when
an applicable ensemble supplies it); C1′ and Watson–Crick metrics are marked not
applicable. Once stable, remaining control chunks are bridged from the accepted
checkpoint.

The same rule is emitted into local, Alpine, and RunPod execution. DNA-containing
jobs keep the stricter energy-plus-Watson–Crick early-stop rule. GPU-resident NAMD is
used when selected and compatible; harmonic positional restraints are used for every
graphene and DNA anchor combination, whether native or seeded. DNA anchors default to
0.02 kcal/mol/Å² while graphene defaults to 50 kcal/mol/Å²; sharing a marker does not
make them share a force constant. The final-package audit rejects `GPUresident on`
together with active `fixedAtoms` before local execution or remote staging.

Surface deposition does not by itself guarantee that an unrestrained origami will
remain registered over the aperture during zero-field relaxation. Internal DNA/ENM
restraints preserve structure but do not restrain center-of-mass translation, sliding,
tilt, or separation from graphene. The recommended physical workflow is therefore:

1. inherit the oxDNA structure and surface anchors for backmapping and equilibration;
2. release the origami's external positional anchors before the primary production
   trajectory;
3. apply the field with the polarity that electrophoretically docks the negatively
   charged origami against the membrane; and
4. retain harmonic restraints on the graphene throughout production.

Keep origami anchors in production only when they represent experimental tethers or
when deliberately running a restrained stability control. A useful intermediate
control is a weak lateral/tilt or flat-bottom restraint that prevents loss of pore
registration without suppressing vertical contact, bending, or pore breathing.

Changing the physical graphene pore diameter requires a new package and relaxation.
It changes the carbon topology, atom ordering, pore-edge forces, excluded waters, and
local ion distribution, so an old binary checkpoint is not topology-compatible. A
different analysis-only crossing radius does not require relaxation, although it
should normally remain tied to the physical aperture.

## Manual UI workflow

1. Open **Dynamics → NAMD** and create a relaxation job.
2. In the hard-surface card, choose the face/offset and enable **Add graphene nanopore**.
3. For an open-pore control, use an empty design; NADOC detects the absence of DNA.
   For an origami run, use either the native design or a completed deposited oxDNA seed.
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

**View trajectory** also supports graphene-only systems. Such a run has zero
nucleotide keys by design; the trajectory slider is driven by complete DCD frames and
the synchronized graphene/solvent/ion/cell representation rather than by fabricated
DNA coordinates. Growing DCDs are counted from their complete fixed-size records so a
temporarily stale DCD header cannot make a live run appear to contain one frame.
Selecting a production child after reload inherits the relaxation parent's hard-
surface controls and nanopore descriptor.

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

## Production voltage and duration

Experimental electrophoretic docking commonly uses about **100 mV**. Atomistic MD
often uses a larger bias to accumulate enough transported charge in tens of
nanoseconds, but elevated fields can introduce nonlinear deformation, concentration
polarization, or detachment. NADOC records user-facing voltage and derives the uniform
periodic field from `V = -E_z L_z`; changing reservoir padding or the equilibrated box
height therefore changes the required NAMD `eField` for the same voltage.

Use these as practical sampling tiers rather than universal constants:

| Purpose | Bias | Production sampling |
|---|---:|---:|
| Pipeline/debug | 0.5–1 V | 2–10 ns |
| Initial graphene control | 0.25, 0.5, and 1 V | 20–40 ns each |
| Origami conductance comparison | 0.1, 0.25, and 0.5 V | 40–50 ns each |
| Accelerated high-field control | 1–2 V | 20–40 ns |

A 10 ns trajectory is a functional control, not normally a precise conductance
estimate. For a serious comparison, prefer at least three independent 20–50 ns
productions per condition, separate the first 2–5 ns after field application as a
transient, and block-average current over 0.1–1 ns windows. Verify that current remains
approximately linear across the lower-voltage points before interpreting a high-field
trajectory as accelerated sampling of the same regime. Published reference protocols
include [48 ns at 100–500 mV](https://pmc.ncbi.nlm.nih.gov/articles/PMC4469488/)
and [40 ns per bias for graphene–origami hybrid pores](https://pmc.ncbi.nlm.nih.gov/articles/PMC6636640/).

## Interpretation and controls

- Run the graphene-only open pore before the DNA-blocked pore.
- Match voltage, salt, box, temperature, pore geometry, timestep, and output cadence
  between control and DNA runs.
- Discard equilibration before estimating current and uncertainty.
- Use independent velocity/random seeds for replicate productions.
- Report both aggregate sampling and per-replica duration; replicas expose
  between-run variability that one long trajectory hides.
- Check ion trajectories visually for periodic-image or membrane-bypass artifacts.
- A single graphene layer with neutral Lennard-Jones carbon sites is a modeling choice,
  not a generic solid-state nanopore. Report it explicitly.

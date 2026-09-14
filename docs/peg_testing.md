# PEG testing playground

Open **Help → PEG testing**. The toggle opens an isolated 3D playground; closing
it releases the sampler, graphics resources, and animation loop. It does not
modify a design or submit a production oxDNA/NAMD job.

## Initial research (2026-09-09)

Approximate PEG simulation is well established. The narrower intersection of
chemically calibrated coarse-grained PEG, a grafting electrode, electrolyte, and
field-controlled height was **not established by this initial search**. That is
not a claim that no such study exists.

* **Direct field/PEG precedent:** Vemparala et al., J. Chem. Phys. 121,
  5427–5433 (2004), DOI [10.1063/1.1781120](https://doi.org/10.1063/1.1781120).
  The [author-hosted paper](https://bpb-us-w1.wpmucdn.com/sites.usc.edu/dist/0/597/files/2020/12/Vemparala-SAMsEfield-JCP04.pdf)
  models short PEG-terminated alkanethiol monolayers on gold using atomic partial
  charges. Fields change trans/gauche populations, tilt, and oxygen exposure.
  The study uses 200 K and fields up to ±2 V/Å (±20 V/nm), not an aqueous
  physiological long-chain brush. Its field-sign convention also needs care.
  It supports field-responsive conformations, not a transferable low-field
  PEG height law.
* **Coarse-grained PEG precedent:** Lee et al., J. Phys. Chem. B 113,
  13186–13194 (2009), DOI [10.1021/jp9058966](https://doi.org/10.1021/jp9058966).
  [Full manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC2937831/).
  A MARTINI-compatible model uses CHARMM atomistic distributions to parameterize
  bonds, angles, and dihedrals. It reproduces chain-size trends and investigates
  grafted chains. This provides a route to a richer model; the playground does
  not implement that force field.
* **Coarse-grained field/brush precedent:** Smook and de Beer (2024),
  [Electrical Chain Rearrangement: What Happens When Polymers in Brushes Have a Charge Gradient?](https://pmc.ncbi.nlm.nih.gov/articles/PMC10906002/).
  Uses Kremer–Grest coarse-grained MD for end-grafted polymers with charge
  gradients under normal fields. It is a charged-brush study, not a neutral-PEG
  parameterization. Ion screening is a relevant limitation of the model.

The useful first distinction is **contour length versus effective extension**.
An electric field can change height, orientation, and conformational populations
without changing the number of repeat units. Neutral PEG has no net backbone
charge, but neutrality does not eliminate partial-charge, dipolar, or induced
polarization responses. A bead model that removes those degrees of freedom must
add and validate effective couplings to recover them.

## Implemented preliminary model

The playground samples 64 independent freely jointed Kuhn chains. All anchors
are fixed; an optional impenetrable plane enforces z ≥ 0. Segment length b is
fixed, and L = N b is the contour length. The default b = 0.7 nm is an
**illustrative adjustable parameter**, not a newly fitted PEG parameter.
N counts statistical segments, not ethylene-oxide units or nucleotides. No
molecular-weight conversion is claimed.

The presets are:

1. **Neutral control:** zero terminal charge and no effective dipole coupling.
   Its distribution is invariant under field reversal or field magnitude changes.
2. **Charged-terminal PEG hypothesis:** an otherwise neutral chain with a
   selectable ±1e end group. U(z) = −q E z for a uniform field.
3. **Screened charged-terminal hypothesis:** E(z) = E₀ exp(−z/λ), giving
   U(z) = q E₀ λ exp(−z/λ), up to an irrelevant constant.
4. **Free-chain benchmark:** remove the wall and retain a fixed anchor to test
   the exact FJC force-extension relation.

E is in V/nm, z in nm, q in elementary charges, and kBT = 0.01380649 T pN nm.
One e in 1 V/nm experiences 160.2176634 pN. Positive E points away from the
surface. λ is prescribed; this is not a Poisson–Boltzmann electrode solver.
The surface field cannot be converted to an applied electrode voltage without
additional geometry and electrolyte information.

Chains have no excluded-volume, chain–chain, dipolar, hydration, adsorption,
hydrodynamic, or DNA interactions. Display spacing has no thermodynamic role.
This is a dilute/ideal-chain baseline, not a dense-brush simulation. It cannot
reproduce the neutral monolayer torsional response in the 2004 paper.

## GPU implementation and sampling

`frontend/src/scene/peg_gpu.js` uses actual WebGL2 floating-point ping-pong
textures for Metropolis pivot updates. Each chain proposes a rotation of its
tail about a randomly chosen joint and isotropically distributed axis. The
inverse rotation has equal proposal probability. Moves preserve bonds, reject
wall crossings, and accept with min(1, exp(−ΔU/kBT)).

Every fragment belonging to a chain uses the same integer-hashed random stream
for that proposal. Shader rendering reads the resulting position texture
directly. A CPU implementation uses the same algorithm and seed construction;
floating-point differences can eventually produce different trajectories.
Unsupported float-render-target devices fall back to CPU sampling and report
that explicitly. The 3D view itself requires WebGL2.

Work is capped at eight proposals per chain per animation frame, at most about
30 frames/s. Sampling pauses in a hidden tab and ends when the dialog closes.
No CUDA installation, server process, or long GPU job is needed. The browser may
choose a hardware or software WebGL driver; inspect its renderer when reporting
hardware performance.

The first 1000 proposals per chain are discarded. Later snapshots are collected
at least 100 proposals apart. Their correlations are explicitly disclosed;
there is no automatic claim of convergence or independent-sample error bars.
Playback has no calibrated molecular-time interpretation. Large forces or long
chains can require more equilibration than the fixed initial discard.

## Statistical validation

The independent height reference propagates a 1D transfer integral with uniform
segment increments Δz in [−b,b]. At every segment it excludes heights below the
wall, then weights the final distribution by exp(−U(z)/kBT). This exactly
specifies the ideal-chain problem before quadrature discretization. The UI uses
24 grid cells per segment and shows binned end-height probabilities.

For the no-wall uniform-field case the exact result is

    <z> = N b [coth(x) − 1/x],  x = q E b / kBT
    <R²> = N b²                (zero field only)

The origin of the first relation is the single-segment partition function
Z₁ = 4π sinh(x)/x and <cos θ> = d ln Z₁/dx. The small-x limit is x/3.
Tests compare the independent quadrature and sampled configurations against
these equations, test field reversal and neutral invariance, and check anchors,
bond lengths, wall exclusion, and screened-field sampling.

This validates implementation of the **ideal-chain surrogate**, not agreement
with real PEG. Export includes parameters, seed, backend, proposal count,
histogram, reference probabilities, recent snapshot metrics, and final
coordinates. Snapshots are limited to the most recent 2000 entries; histogram
and mean retain all post-burn-in samples.

Initial hardware check used Chromium/ANGLE on the NVIDIA RTX 3080 Ti, with
128 independent eight-segment chains, b = 0.7 nm, T = 300 K, seed 173, and
3000 proposals per chain. Means below use 20 snapshots after the first 1000
proposals; numerical references use 48 cells per segment. These are diagnostic
sample means, not confidence intervals or performance benchmarks.

| Case | GPU mean end height (nm) | Reference (nm) |
|---|---:|---:|
| Free chain, E = 0 | −0.040 | 0.000 |
| Free chain, +1e end, E = +0.03 V/nm | 1.441 | 1.454 |
| Wall, +1e end, E = −0.03 V/nm | 0.781 | 0.769 |
| Wall, +1e end, E₀ = +0.03 V/nm, λ = 2 nm | 1.558 | 1.554 |

The free-chain zero-field mean R² was 3.950 nm², versus N b² = 3.920 nm².
The maximum bond-length deviation in these checks was below 0.00024 nm.
Floating-point rotation drift is monitored during playback; the playground
pauses if a bond deviates by more than 0.02 nm or a wall crossing is detected.

Reproduce the checks from `frontend/`:

```sh
npx vitest run src/scene/peg_model.test.js
npx playwright test e2e/peg_testing.spec.js --workers=1
npm run build
```

Browser tests also exercise the real Help toggle, polarity changes, neutral
invariance, CPU selection, export, close/reopen, long-chain geometry, and
automatic CPU fallback. The Playwright configuration uses dedicated test
servers rather than the user's running workspace backend.

## Next calibration work

Start with isolated PEG in explicit water using an appropriate PEG force field
in NAMD; fit chain dimensions and low-force extension over selected lengths.
Then tether a chain to a specified substrate and compare terminal-height and
bead-density distributions at zero field. Only after that compare both field
polarities, neutral/charged terminal chemistry, and explicit electrolyte.

Use independent replicas and block averages, checking equilibration and
autocorrelation. Fit on one chain length/field and test held-out conditions.
If neutral PEG responds through torsions or dipoles, fit a separate effective
coupling or retain additional segment orientations/conformational states;
do not assign a fictitious net backbone charge. Dense brushes additionally
require excluded volume and collective interactions. Coupling to oxDNA needs
PEG–DNA cross-interactions and mixed-particle integration.

No NAMD PEG calculation has been launched or claimed as validation. Existing
QM work is independent of this browser playground.

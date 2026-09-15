# cube_pore P1 Alpine cavity investigation

**Local investigation complete. No application or existing-job change has been applied.**

The evidence identifies a setup defect: the periodic-wall safeguard disables solvent-density equilibration. The actual relaxation runs at fixed volume under substantial tension while water accumulates near the origami, and a dry pore-region cavity develops. The evidence does not support an initially carved hole, an ion detector failure, or a demonstrated steric plug by the origami.

See [the review-only change proposal](REVIEW_PROPOSAL.md), [experiment methods](README.md), and [evidence plots](evidence.png).

## What happened in the original job

The parent is `60e854232e8c`; P1 production is `a4cb52583c26`. The available production trajectory contains 2374 frames, 0.04–94.96 ns at 40 ps intervals. This audit does not claim to cover the requested full 200 ns. The original system has 1,679,987 atoms, including 508,219 waters, a restrained graphene membrane with an 8 nm opening, and 5227 Na / 1392 Cl ions.

Water oxygens inside the aperture (r < 4 nm, within 0.25 nm of the plane) decrease as follows:

| Checkpoint | Elapsed relaxation | Aperture water count | Accessible local void (nm³) |
|---|---:|---:|---:|
| As solvated | Before minimization | 744 | — |
| Minimized | 0 ns | 816 | 2.56 |
| Early stage 01 | 0.008 ns | 799 | 3.52 |
| Stage 01 | 0.24 ns | 552 | 101.12 |
| Stage 02 | 0.72 ns | 146 | 221.25 |
| Stage 03 | 1.20 ns | 1 | 306.30 |
| Stage 04 | 1.68 ns | 0 | 363.26 |

The accessible-void diagnostic excludes grid sites within 0.35 nm of DNA heavy atoms or graphene and requires no water oxygen within 0.4 nm. It measures a fixed local region on a 0.4 nm grid; it is not a thermodynamic vapor-volume definition. The initial largest connected void is only 0.32 nm³, whereas the final 363.26 nm³ region forms one connected component.

The first stage uses 2 fs; the remaining stages use 4 fs. Thus the cavity starts before the timestep switch. In the downloaded production, the pore region remains dry for nearly 95 ns. Direct ion coordinates show no sampled pore-plane crossings; an independent minimum-image plane-crossing check and a synthetic crossing positive control support the detector result. No DNA atom occupies the central aperture-plane slab at the examined production endpoints. Zero current in this dry setup cannot establish that DNA sterically blocks a hydrated pore.

The original stage-04 runtime record, `output/live_metrics.json`, reports 297.86 K and **averaged group pressure −462.38 bar**. A separate CPU energy/virial evaluation of the same endpoint gives a comparable negative pressure. The archived runtime measurement is stronger evidence than a single local static evaluation.

An additional static comparison uses the original **8 ps** coordinates, when the pore-plane slice still contains 799 water oxygens. With all original stage forces, the group pressure is −986.8 bar. Disabling only the elastic network gives −380.9 bar; disabling the network and wall restraints gives −344.9 bar. The network therefore contributes about −606 bar in this snapshot, while substantial physical-system tension remains without either restraint. Original velocities for this frame were unavailable, so these evaluations use the same initialized 300 K velocities; they are force/virial diagnostics, not archived runtime averages. Direct evaluation of the extra-bond energy and virial in all saved restrained-stage frames gives mean network contributions of approximately −316, −105, and −21 bar in stages 01–03, respectively. These are network contributions, not total pressures. The cavity continues growing as this stress is released and persists in the stage without ENM. This confirms that tension precedes the large cavity and identifies early restraint stress as an additional contributor. It does not establish that removing the network alone would solve hydration.

## Trace to the setup code

`backend/core/namd_graphene.py`, `graphene_pressure_conf(..., fixed_cell=True)`, turns both supported barostats off. `backend/core/md_protocols.py` also records `solvation.npt_allowed = false` for graphene. The fixed-cell behavior was introduced in commit `4719cd999` to prevent a Cartesian-restrained periodic wall from becoming unstable during cell dilation. That solved a wall problem but removed density equilibration entirely; the stage names still include NPT.

Initial solvation is not deleting an aperture-shaped water region. Reproducing its census gives the original number exactly: 519616 GROMACS waters minus 4778 actual wall-overlap waters, minus 6619 replacements with ions, equals 508219. The graphene exclusion checks proximity to actual carbon sites, not the cylindrical opening. Re-solvating the relaxed geometry with the same algorithm yields 505866 waters, so repeating that operation alone is not an evidenced fix.

No water or ion positional restraints, ENM links to solvent, or relaxation electric field were found. The wall uses a distinct neutral NGRC type, with zero wall–wall LJ and nonzero cross interactions with solvent. The configured production field corresponds to 300 mV across the periodic cell; its normalized value is 6.918164349 kcal/(mol·e), consistent with [NAMD's normalized-field definition](https://www.ks.uiuc.edu/Research/namd/2.11/ug/node42.html). This verifies configuration, not an unavailable original production field log.

## Controlled local evidence

Four 6 nm bulk-electrolyte tests use the same force field and solvent construction. The initial box is 216 nm³. Each runs 200 ps; summaries below exclude the first 50 ps. Uncertainties are standard errors of 20 ps block means, not independent replicate confidence intervals.

| Ensemble / timestep / electrostatics interval | Mean volume (nm³) | Mean group pressure (bar) |
|---|---:|---:|
| NVT / 2 fs / 4 fs | 216.00 | −630.7 ± 6.2 |
| NPT / 2 fs / 4 fs | 208.07 | +13.5 ± 7.9 |
| NPT / 4 fs / 4 fs | 208.39 | −3.6 ± 11.1 |
| NPT / 4 fs / 8 fs | 208.39 | −21.9 ± 10.8 |

The large underpressure disappears after approximately 3.5–3.7% contraction. Changing the timestep/electrostatics interval has a much smaller effect on equilibrium volume. These simple controls establish a density-equilibration problem with the packing-plus-fixed-volume procedure; they do not determine the final volume of the DNA system.

The 8 nm open-pore control, with the same wall parameters and fully solvated starting water count, remains wet over 500 ps and permits sampled ion crossings. A constant-area, normal-pressure branch reduces its box height from 12.0 to about 11.47 nm while retaining a wet aperture and an intact wall. A completed 500 ps fixed-volume 300 mV run from that equilibrated checkpoint remains wet in all 500 saved frames and finishes with 806 aperture-plane water oxygens. It records 139 sampled plane-crossing events involving 16 distinct ions. These counts include recrossings and are not a converged conductance estimate. These controls show that the implemented wall does not inevitably exclude water or ions. They lack DNA and its excess counterions, and are not quantitative conductance predictions for cube_pore.

Additional 96% and 92% water-count controls use random whole-water removal rather than an imposed cavity. The completed 96% run remains wet over 500 ps, with 709 aperture-plane waters in its last saved frame and a late mean group pressure near −1299 bar. It records crossings by 14 distinct ions. This demonstrates that solvent shortage/tension does not guarantee rapid nucleation in a small bare-pore control; it does not refute the original trajectory’s observed cavitation, but limits any claim that density alone determines its timing or location. The 92% run developed a growing void but its GPU-resident segment failed at step 96012 with “atoms moving too fast”; that segment is explicitly marked failed. Its 156 ps checkpoint was branched into pressure equilibration and a fixed-volume continuation, detailed below. The numerical failure's cause remains unresolved; it is not evidence of physical blockage or an explanation of Alpine's unexpected shutdown.

A short full-system NAMD intervention starts from the original dry checkpoint with the same coordinates, velocities, masses, force field, restraints and timestep. It changes pressure control to fixed lateral area / constant normal pressure, with the cell origin placed on the membrane plane. Local GPU memory allocation fails for the full NAMD system, so this test uses CPU NAMD. The 10 ps test completed cleanly: box height decreases from 24.2394 to 23.7889 nm (1.86%), with the two lateral vectors unchanged. The local water-void estimate falls from 373.952 to 360.320 nm³ (3.65%); after excluding nearby solute, the corresponding accessible void is 363.264 → 350.080 nm³, while the aperture-plane slice still contains only one water oxygen. Graphene remains within about ±0.033 nm of its plane. The available `GPRESSAVG` tensor gives mean normal pressure about −1.0 bar during 4–10 ps, with an 8.3 bar standard deviation across its 0.4 ps interval averages. Lateral pressures remain negative, as allowed at fixed area. Thus the normal mechanical pressure approaches the target over this short window while the cavity persists: pressure alone is not a hydration-equilibrium test. This is a stable short intervention, not recovery of the dry pore. The independent 50 ps engine comparison is reported below.

### Depleted-pore pressure intervention

The 8% deficit produced multiple voids near the sheet and pore, rather than an imposed cylindrical exclusion. At 156 ps, the saved checkpoint contains **80.512 nm³** of water-free grid volume outside the graphene exclusion region, with 550 aperture-plane water oxygens. The largest individual component is 16.704 nm³; separate components can cross periodic boundaries, so total void volume is the more useful comparison here.

A 200 ps fixed-area/normal-pressure branch from that checkpoint **eliminates the detected void volume** and finishes with **806 aperture-plane water oxygens**. Box height contracts from 12.0 to 10.5785 nm, with lateral dimensions unchanged and no water or ions added. Mean interval-averaged normal pressure over 50–200 ps is −2.0 bar (interval SD 18.9 bar), consistent with approach to the 1.01325 bar target within these fluctuations. The final low-density regions are absent from the spatial density map. See [the density maps](depletion_density.png) and [branch comparison](depletion.png).

The fixed-volume continuation starts from the identical immutable checkpoint. At the same **+200 ps**, its detected void volume has grown to **114.304 nm³**, with only **504 aperture-plane water oxygens**. Over 50–200 ps, its mean interval-averaged normal pressure is −527.8 bar (interval SD 28.6 bar), compared with −2.0 bar under pressure equilibration. Mean void volume over the final 50 ps of this common window is 111.168 nm³ at fixed volume versus zero under pressure equilibration. The fixed-volume continuation completed its full 344 ps (500 ps including the shared parent history). Its last saved DCD frame at +340 ps contains 128.576 nm³ of detected void and 526 aperture-plane waters; the final dynamics step is +344 ps. Thus the void persists beyond the matched 200 ps comparison.

| Same starting checkpoint, then 200 ps | Fixed volume | Fixed area / normal pressure |
|---|---:|---:|
| Detected void volume (nm³) | 114.30 | 0 |
| Aperture-plane water oxygens | 504 | 806 |
| Box height (nm) | 12.0000 | 10.5785 |
| Mean normal pressure, 50–200 ps (bar) | −527.8 | −2.0 |

Because the original resident-mode segment failed, the fixed-volume continuation uses CPU integration/GPU force offload. The pressure branch uses resident mode. Both use the same 4 Å computational patch margin, force-field parameters, composition, restraints and byte-identical initial coordinates, velocities and cell. This execution-mode difference and the single independent stochastic continuation per condition limit a strict dynamical comparison. [Machine-readable paired comparison](depleted_comparison.json).

The pressure-equilibrated membrane retains its original lateral cell vectors, lies within ±0.029 nm of its reference plane, and has a nearest rim site 4.001 nm from the pore axis. Its RMS displacement from the restrained wall reference is 0.0135 nm. Thus removal of the voids did not require collapsing the opening or moving the sheet away from its reference. [Final geometry measurements](wall_geometry.json).

This intervention provides direct evidence that volume/density equilibration can remove depletion-induced voids with the existing graphene interactions. It does not prove that the much larger cavity in the full DNA system will recover on the same timescale, or that negative pressure alone fixes where a bubble nucleates.

### Independent full-system comparison

A validated OpenMM GPU implementation allowed two 50 ps tests from the same original dry coordinates and velocities, with the same atom masses, force field and wall restraints. Its bonded/LJ component checks agree closely with NAMD and electrostatic energy differs by 0.0141%; integrator, thermostat, PME interpolation and pressure-control differences remain explicitly documented in [the validation record](openmm_full/VALIDATION.md).

| OpenMM branch | Box-height change | Final aperture water count | Accessible cavity (nm³) | Mean sampled normal pressure, 10–50 ps |
|---|---:|---:|---:|---:|
| Fixed volume | 0% | 0 | 368.26 | −399 bar |
| Fixed area / normal pressure | −1.14% | 0 | 353.09 | −231 bar |

Pressure values here average only nine instantaneous samples and are descriptive, not converged equilibrium estimates. The pressure-controlled box was still contracting at about 0.0073 nm/ps over its final 20 ps. Both runs stayed mechanically stable, and neither restored a hydrated pore. The pressure-controlled cavity became modestly smaller while the fixed-volume cavity became slightly larger. This supports the direction of the intervention but **does not validate a 50 ps recovery protocol** or prove the final equilibrium state. It favors beginning a new run from a wet system and checking convergence through the full relaxation, rather than assuming that enabling a barostat on the existing dry state repairs it immediately.

## Mechanistic interpretation and its limits

Water within 0.4 nm of a DNA heavy atom increases from 42088 after minimization to 52076 after relaxation. Water in a fixed cylinder around the developing cavity falls from 15386 to 4436. These are spatial membership counts; they do not prove that those same individual molecules transferred directly between the two selections. They show that origami hydration and pore-region depletion occur together.

The most supported explanation is cavitation in solvent held under tension, with the membrane/pore providing a favorable place for the cavity to form or remain pinned. A rounded void is compatible with an interface minimizing its area; a neat outline is not evidence of an artificial solvation mask. This interpretation is consistent with [research on cavitation in stretched water](https://pmc.ncbi.nlm.nih.gov/articles/PMC5137690/), but the precise nucleation barrier and contribution of graphene wettability have not been measured here.

There is also relevant protocol precedent: Li et al. describe reservoir contraction as water hydrates origami, and use constant-area pressure equilibration for a restrained solid/origami hybrid before fixed-volume current simulations. Their multi-nanosecond equilibration supports the proposed approach, without proving an appropriate duration for this particular design. [Author manuscript and methods](https://api.repository.cam.ac.uk/server/api/core/bitstreams/75e87e28-cbcc-4e24-ace0-b8e6275a92d3/content).

More reservoir is not a substitute for equilibrating density. The original far-side DNA-to-next-membrane-plane clearance is approximately 2.4 nm; the nearest DNA atom in an axial periodic image is about 3.6 nm away at the final relaxation endpoint. There is room to investigate finite-size and reservoir effects, but these measurements do not establish a converged reservoir thickness or justify a particular new padding default.

## Review decision

The evidence supports adding a compatible **density-equilibration path for newly built graphene systems**, followed by NVT production from the equilibrated cell. It does not support changing the voltage conversion, crossing detector, graphene attraction, or salt chemistry to force a desired current. The review proposal specifies the experimental configuration, affected application paths, and acceptance checks. It is not an applied fix and does not certify the current dry trajectory as a hydrated-pore transport measurement.

## Completion and preservation

The planned controls and replacement continuation have finished. [Run audit](run_audit.json) checks the intended final step, completion marker and fatal-error status; it retains the failed original 92% GPU-resident segment as a failure. The replacement offload segment completed all 172000 steps. No local simulation from this investigation remains running or paused. [Preservation checks](preservation_check.json) confirm that the 14 recorded original inputs and the pre-existing tracked application diff are unchanged. Experiments, logs, figures and the review proposal remain isolated in this directory.

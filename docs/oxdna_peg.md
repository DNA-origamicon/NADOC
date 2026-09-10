# Experimental PEG surface in oxDNA: milestone 1

Open `workspace/PEG_surface_review.nadoc`. Its saved `metadata.peg_surface`
restores the hard surface, PEG controls, and DNA probe anchors. Dynamics → oxDNA
contains completed job `666f5b417cee`; select it to inspect the trajectory.
The document has four grafted chains, nine beads per chain (eight statistical
segments), and a 16 bp DNA probe: 68 simulated particles. Only the probe's
forward strand is positionally restrained. The PEG contour parameter is 5.6 nm.

The document stores the reproducible surface recipe; engine topology and bead
coordinates are generated when preparing a relaxation. Simulation artifacts
remain in `workspace/oxdna_jobs/<job-id>/`. Use **Store PEG setup in design**
after changing the controls, then save the NADOC document normally.

## Engine and model

`bash scripts/build-oxdna-peg.sh` builds a separate CPU/CUDA engine at
`~/.local/share/nadoc/engines/oxdna-peg/current/bin/oxDNA`. It pins upstream
revision `8028cf33b3cba12992b771156085fa54879f50cd`, applies
`tools/oxdna_peg/patch_engine.py`, and compiles for the local CUDA hardware.
`NADOC_PEG_OXDNA_BIN` can override that path. The existing DNA engine and oxpy
installation are untouched. The builder requires Git, CMake, C++, and CUDA.

The opt-in interaction is `DNA2PEG`. DNA–DNA interactions retain oxDNA2.
Topology base type `500` identifies a PEG bead. PEG interactions use particle
centers and produce no orientational torque:

* Adjacent PEG beads: harmonic spring, `U = k(r-b)^2/2`, without DNA stacking,
  hydrogen bonding, FENE, or adjacent-pair excluded volume.
* Nonadjacent PEG–PEG and PEG–DNA: WCA repulsion,
  `U = 4 ε[(σ/r)^12-(σ/r)^6] + ε` below `2^(1/6) σ`, zero above.
* Defaults: `b = 0.7 nm`, PEG `σ = 0.5 nm`, mixed `σ = 0.75 nm`,
  `k = 100` in engine energy/length² units, `ε = 0.1` in engine energy units
  (one kBT at 300 K). The mixed diameter uses an illustrative 1 nm DNA CM sphere.
* Each root bead has a stiff positional trap. A repulsive harmonic plane
  supplies the substrate; its finite stiffness allows tiny penetrations.
* CPU Monte Carlo and CPU/CUDA MD use the same interactions. Integration
  timesteps are capped at 0.001 engine time units for the PEG springs.

Neutral PEG receives no DNA backbone charge. An optional terminal charge in
[-2e, 2e] receives `qE` only in a consolidated **Run** with a physical electric
field specified in V/m. Legacy per-nucleotide force mode acts on DNA only.
There is no terminal-charge pair electrostatics, ionic screening, electrode
potential solver, PEG polarization, adsorption, or hydration model. The neutral
model therefore has no direct field response, though charged DNA can move and
interact sterically with it. The screened ideal-chain browser playground is a
separate model; its screening option has not been ported to this engine.

This milestone supports local DNA/PEG simulations. Protein hybrids, remote
execution, covalent DNA–PEG links, and oxpy Live are unsupported. Continuing
production preserves PEG interactions, the substrate, and root restraints.
PEG displays as beads and bonds without fictitious DNA bases.

## Verification and physical limits

The review job completed 100 CPU MC steps, 20,000 CUDA relaxation steps,
10,000 CUDA equilibration steps, and 50,000 CUDA production steps. All final
coordinates are finite. Final PEG spring lengths span 0.657–0.771 nm; maximum
root displacement is 0.0053 nm. Chain-end heights decreased from 5.6 nm to
1.13–2.99 nm. These are individual snapshots, **not equilibrated ensemble
estimates**. The partially restrained short DNA probe frayed: the geometric
base-pair retention readout was 38% at the final frame. The existing production
health check has no retention threshold for this smoke run; completion does
not assert a stable duplex or a calibrated PEG response.

`tests/test_oxdna_peg.py` checks saved-recipe round trips, deterministic graft
placement, bond spacing, terminal-only field assignment, and stage selection.
With the isolated engine installed, it runs actual spring and WCA force checks
against analytical values on CPU and both CUDA neighbor-list modes. DNA-only
one-step trajectories agree between DNA2 and DNA2PEG on each backend. Browser
coverage verifies saved controls, all 36 displayed PEG beads, center-coordinate
trajectory updates, and metadata persistence.

The statistical segments are not ethylene-oxide repeat units. Segment size,
excluded volume, mixed DNA sterics, masses, friction, and physical time mapping
have not been fitted to PEG data. This is a flexible, extensible self-avoiding
chain model, not the fixed-length ideal FJC used in the playground. Next
validation should fit bulk chain-size and bond distributions, then surface
height distributions and force–extension curves against statistical mechanics
and atomistic trajectories. Field-dependent neutral PEG requires additional,
validated effective interactions. See [the initial research](peg_testing.md).

To reproduce a separate review in a chosen workspace:

```bash
.venv/bin/python scripts/create_peg_surface_review.py --workspace /path/to/workspace --run
```

The script refuses to overwrite an existing `PEG_surface_review.nadoc`.

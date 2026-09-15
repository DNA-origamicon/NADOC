# cube_pore R1 Alpine: complete stage configuration audit

Job: `d49d12f98a47` / SLURM `32590815`.

**Finding:** The previously identified adaptive-minimization `cellOrigin` placement is the only initialization/control-flow defect found. No additional defects were found in the remaining 21 managed stages, their input references, or the 84 examined dynamics restart configurations. The original job package was preserved; its minimization configuration still needs regeneration or repair before rerunning.

## Scope and findings by stage

| Stage | Configurations | Result |
| --- | ---: | --- |
| Adaptive minimization, ENM k=0.5 | 1 | Original repeats `cellOrigin` inside the loop and aborts. Corrected writer emits it once at top level. |
| DNA-restrained 300 K settling | 1 | Startup settings precede `run`; reads minimization coordinates, velocities and XSC; NPzAT enabled. |
| ENM k=0.5, checkpoints 10/25/50/75/100% | 5 | Correct sequential handoffs and ENM input. First chunk intentionally uses the manifest's 2 fs soft start; later chunks use 4 fs. |
| ENM k=0.1, checkpoints 10/25/50/75/100% | 5 | Correct sequential handoffs, restraints, 4 fs timestep and NPzAT settings. |
| ENM k=0.01, checkpoints 10/25/50/75/100% | 5 | Correct sequential handoffs, restraints, 4 fs timestep and NPzAT settings. |
| Mg-hexahydrate bonds only, checkpoints 10/25/50/75/100% | 5 | DNA ENM removed; graphene positional restraints retained; correct handoffs and NPzAT settings. |
| Auxiliary `namd.conf` / `namd_fast.conf` | 2 | Checked inputs and Tcl execution order. These are not members of the managed 22-stage chain. |

Every managed dynamics configuration has one top-level `run`. Initialization directives precede it. The declared predecessor matches the actual `.coor`, `.vel`, and `.xsc` inputs, and step counts match the manifest and are cycle-aligned. The XSC carries the equilibrated cell into each subsequent segment. All dynamics stages retain the intended fixed X/Y dimensions, variable Z dimension, membrane-centered origin and 1.01325 bar target; minimization leaves the piston off.

All referenced molecular, parameter, ENM and restraint files exist. Every referenced PDB has 1,615,887 atoms. Standard and HMR PSFs have matching atom identities, ordering and charges, positive masses, and effectively neutral total charge. Total mass differs by only approximately 0.040 amu across the entire system, consistent with PSF decimal rounding.

Combined positional-restraint files select 24,618 graphene sites. Only the settling configuration additionally restrains DNA. Water and ions have zero positional-restraint coefficients throughout. Settling uses its own `restraints_settle.pdb` reference; the Alpine launch writer retargets this reference to minimized coordinates before starting dynamics. Later stages use the expected ENM files, with no DNA ENM in the final family.

Alpine's interruption handler explicitly refuses automatic restart of an interrupted minimization. For dynamics, both the node-side and continuation writers were checked at step 5,000 and with only 20 steps remaining in every segment: 84 variants in total. Each preserves cell constraints, integrator, restraint references and same-stage restart inputs, emits initialization before execution, and runs only the remaining steps.

## Verification

- **109 Tcl executions:** all 24 original configurations, corrected minimization, and 84 dynamics restart variants. A harness executes the actual Tcl control flow, substitutes NAMD command recording for molecular dynamics, and rejects initialization commands after the first `run`/`minimize`. Only original minimization fails, with the expected late `cellOrigin` command.
- **22 real NAMD 3.0.2p1 GPU-resident control runs:** one per managed stage, sequentially handing off actual binary coordinates, velocities and XSC. All complete. The corrected minimization executes two 20-step chunks; each subsequent stage executes 20 dynamics steps.
- **123 regression tests pass:** Slurm script generation, Alpine restart handling, cell recovery, remote resume generation, graphene pressure control, and adaptive minimization.

The NAMD runs substitute an existing small hydrated graphene control's molecular inputs and box geometry, omit DNA/Mg extra bonds, and shorten the run lengths. They validate NAMD acceptance of the stage settings and restart handoffs, **not** physical stability or equilibration of the full cube_pore DNA system. The packaged DNA force and restraint inputs were inspected separately. No full-size simulation was run or submitted.

Audit scripts, per-file hashes, per-stage results and NAMD logs are under `experiments/cube_pore_stage_audit_20260915/`:

- `audit.py` / `audit.json`: static package, input and restart checks.
- `check_tcl.py` / `tcl.json`: actual Tcl control-flow checks.
- `run_controls.py` / `runtime.json` / `controls/`: isolated NAMD runs.

The host lacked `tclsh`; the Ubuntu Tcl packages were extracted under `/tmp/nadoc-stage-audit-tcl` for these tests without a system installation. No additional application changes were needed.

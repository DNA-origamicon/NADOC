# small_plate R1 graphene wall failure — 2026-09-04

## Evidence

Job `0a2aaa5638ff`, Slurm `32088967`, node `c3gpu-g7-u9`, failed with exit
6:0 after 49:11. The saved `output/nadoc_failure.log` identifies
`small_plate_02_300K_NPT_ENM_k0p1_p10`: `SequencerCUDA: Atoms moving too fast`
at step 14. All 16 reported atoms are graphene CA sites. The preceding k=0.5
p10 stage used 2 fs; k=0.1 uses 4 fs. The p25–p100 bridge checkpoints match
p10 byte-for-byte (coordinates, velocities and cell), consistent with early stop.
The earlier patch-grid recovery succeeded; this is a distinct molecular instability.

The package has 38,617 graphene atoms (zero-based indices 50765–89381).
They were independent, unbonded CA sites at a 1.42 Å honeycomb spacing, with
k=50 kcal/mol/Å² positional restraints and **no mutual nonbonded exclusion**.
CHARMM CA has epsilon=0.07 kcal/mol and pair Rmin=3.9848 Å. At 1.42 Å,
its LJ pair energy is 16,623.937 kcal/mol and repulsive force is
140,772.845 kcal/mol/Å. Thus minimization and the 2 fs stage already equilibrated
against a badly repulsive wall Hamiltonian; switching to 4 fs exposed it.

Independent coordinate/energy calculations from the saved package:

| State | Median nearest graphene neighbor (Å) | RMS displacement from restraint reference (Å) | Graphene restraint energy (kcal/mol) |
|---|---:|---:|---:|
| Reference | 1.41935 | 0 | 0 |
| Minimized | 2.44027 | 1.44748 | 4,045,525.91 |
| Settled | 2.61675 | 1.81076 | 6,330,960.47 |
| k=0.5 p10 | 2.43748 | 1.44664 | 4,040,803.74211 |

The last calculated energy matches the entire logged BOUNDARY energy
4,040,803.7421 at k=0.1 step zero. This independently ties the instability to
the deformed graphene wall, rather than loss of DNA anchors or corrupt continuation.

## Correction

- New graphene PSFs use dedicated neutral `NGRC` atoms with unchanged carbon mass.
- `forcefield/par_np_thiol.prm`, already loaded by minimization, relaxation and
  production, supplies CA-equivalent NGRC LJ mixing parameters and an explicit
  zero NGRC–NGRC NBFIX (including 1–4). Solute/water/ion cross interactions are
  preserved; aromatic protein CA parameters are unaffected.
- This is the existing externally restrained wall model, **not** a bonded elastic
  graphene force field. No coordinates, bonds, anchors, spring constants, HMR
  settings, or stage timesteps were changed.
- Package metadata records the model. Launch validation checks that metadata,
  actual normal/HMR PSF atom types and charges, and the actual supplementary
  parameters. Legacy packages are rejected before Alpine submit/resume, local
  execution, or RunPod provisioning/staging.
- Old checkpoints cannot be reused with this correction. Copy creates an editable
  draft; Run rebuilds from the frozen initial design/seed and repeats minimization.
  No submission occurs on Copy. Existing failed outputs are preserved.

NAMD's [nonbonded parameter documentation](https://www-s.ks.uiuc.edu/Research/namd/3.0/ug/node25.html)
and `Parameters::add_vdw_pair_param` in the local `NAMD_3.0.2_Source.tar.gz`
confirm CHARMM NBFIX converts well depth to A=-well*Rmin^12 and
B=-2*well*Rmin^6: zero well depth explicitly gives zero pair force.

## Verification

Nine new regressions pass: pair energy/force, preservation of cross interactions,
PSF segment boundaries, valid model acceptance, corrupt/legacy model rejection,
and rejection before any Alpine submit/resume remote operation.
Ruff and `git diff --check` pass.

`just test-smart`: **FAST**, **7,636 passed, 35 skipped, 1 failed, 1 setup error**,
73.10 s pytest / 82 s guarded wall time. The two unchanged workspace-fixture
failures are VoltronCoreArm empty-cluster assumptions and BigO 56-versus-168
helix assumptions; source designs were not altered. No new test failures.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

No real NAMD simulation was run: the required user-opened test session is absent.
The rebuilt job still needs live minimization and passage through the 4 fs stages.
Restart the backend to load these changes and reconnect to Alpine before Run.

Prepared recovery action: draft `7aa73d7afe93` copies R1 settings and the identical
frozen `design.json`; `prep_params.autostart=false`, `draft=true`, no package or
Slurm ID. It has not been prepared or submitted.

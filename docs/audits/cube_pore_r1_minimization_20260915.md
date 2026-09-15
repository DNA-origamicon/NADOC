# cube_pore R1 Alpine minimization failure

Job `d49d12f98a47`, SLURM `32590815`, failed after 14 min 8 sec.

## Confirmed cause

The downloaded `output/nadoc_failure.log` shows completion of the first adaptive minimization chunk at step 5060, followed by:

```
TCL: NADOC_ADAPTIVE_MIN step=5060 energy=-8122000.532523233 improvement= stable=0/3
TCL: Setting parameter cellOrigin to 131.746 132.1195 10
FATAL ERROR: Setting parameter cellOrigin from script failed!
```

The generated `cube_pore_00_min_enm_k0p5.conf` puts `cellOrigin` at line 83, inside the adaptive `while` loop immediately before `minimize`. The graphene pressure configuration writer inserted initialization settings before the first textual dynamics command without accounting for its enclosing Tcl loop. The first iteration initializes NAMD successfully; the second tries to reset an initialization-only parameter after simulation startup and aborts.

This is a configuration-generation regression in the new graphene pressure-control path. It is not evidence of minimization divergence, GPU memory exhaustion, or an Alpine shutdown. The minimization itself has `langevinPiston off`; pressure-controlled settling had not started.

## Correction and validation

`backend/core/namd_graphene.py::_normal_pressure_conf` now emits its initialization directives once at the start of the configuration, removing previous copies. Normal-pressure relaxation remains enabled. Regression coverage includes the actual adaptive minimization generator, repeated application, and repair of the malformed placement.

43 tests pass across graphene pressure, graphene configuration, surface profiles, and adaptive minimization.

Two isolated local NAMD 3.0.2p1 GPU-resident runs use an existing small hydrated graphene control and the actual generated adaptive script shortened to two 20-step chunks:

- Old placement: completes step 20, then aborts with the identical `cellOrigin` fatal error.
- Corrected placement: completes steps 20 and 40, exits successfully, and writes the expected membrane-centered origin to its final XSC.

Reproduction script and results: `experiments/graphene_adaptive_origin_20260915/verify.py` and `results.json`. This short test validates script execution, not physical equilibration of the full cube_pore system.

The failed job and its package were not changed or resubmitted. Newly generated packages use the correction; the existing malformed configuration must be regenerated or repaired before rerunning it.

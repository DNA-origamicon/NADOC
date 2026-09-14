# Protein rotational degrees of freedom

`rigid-body-bussi.patch` applies to oxDNA revision
`8028cf33b3cba12992b771156085fa54879f50cd`, alongside NADOC's existing patches.

ANM protein beads are point particles. Upstream MD initialization nevertheless
assigns them angular momentum, and Bussi counts three rotational degrees of
freedom per particle. CPU Bussi includes this fictitious energy but only rescales
rigid particles, whereas CUDA rescales every particle. This can severely cool or
heat DNA rotations in protein-DNA simulations even when total kinetic energy
looks reasonable.

The patch zeroes nonrigid angular momentum during initialization (including old
checkpoints), counts only rigid-body rotational degrees of freedom, and handles
zero rotational degrees of freedom. CUDA orientation updates retain the previous
orientation for zero angular momentum instead of dividing by zero. The initial
Gaussian draw order is preserved. The runtime signature is
`Bussi rigid-body DOF fix v1`; build caches use a new version and marker.

Run the force-free regression with a patched CUDA engine:

```bash
.venv/bin/python scripts/validation/check_dnanm_thermostat.py \
  --binary /absolute/path/to/oxDNA --out /path/to/results --seeds 202 303
```

It tests isolated DNA, DNA mixed with protein points, and protein points alone
on CPU and CUDA. It requires zero protein rotational energy and DNA rotational
energy within 8% of the canonical expectation. It does not test protein force
field accuracy or adsorption chemistry.

`cuda-bussi-rng.patch` additionally aligns CPU/CUDA Bussi random streams. CUDA
initialization previously consumed `lrand48()` to seed a device generator that
Bussi never uses: Bussi draws through the shared host implementation. Skipping
that unused draw preserves the probability law while making a given seed
comparable across backends. Other CUDA thermostats retain their existing seed
initialization. The runtime signature is `CUDA Bussi CPU-matched RNG v1`.

The managed installation/cache suffix is now `bussi-v2`, with both
`bussi-rigid-dofs=v1` and `bussi-cuda-rng=v1` markers. The force-free regression
also requires the complete CPU/CUDA kinetic-energy histories to agree within
1e-6 relative error. The CUDA-only patch leaves all CPU source files unchanged;
this permits reusing a completed CPU reference when auditing this change.

## Physics corrections v3 (2026-09-13)

`physics-corrections.patch` applies after the v1 rigid-body and v2 RNG patches. It
uses current kinetic energy in CPU/CUDA Bussi, masks fictitious John/Langevin point
rotations while preserving random draws and CUDA sorting identities, and guards
zero cross-product normalization in CUDA DNA torques. It deliberately retains
upstream CPU/GPU protein–DNA contact amplitudes pending model validation.

Local, Alpine, and RunPod builders apply the same patch and record
`physics-corrections=v3`; executable/library signature checks reject older local
engines for new runs. GPU is the user-requested default, with convergence and
sampling validation still open (TD-OXDNA-PHYSICS). The original gold/strep/DNA
system also requires NAMD validation (TD-STREP-NAMD).

Ordinary DNA2 uses the pinned upstream equal-strength sequence parameter file.
This restores the average model across backends without changing a force kernel;
DNANM initializes those tables correctly and keeps its existing input path.

---
name: Langevin thermostat heating time from 0 K
description: Expected temperature vs time when starting NVT from 0 K (gen-vel=no) with Langevin thermostat
type: project
originSessionId: 850be451-9e2e-4b70-a3e8-bb898f34b034
---
When NVT is started with `gen-vel = no` (zero initial velocities), the Langevin thermostat heats the system from 0 K. The relaxation follows:

  T(t) = T_target × (1 − exp(−t/τ))

where τ = tau-t (GROMACS `tau-t` parameter, default 10 ps in NADOC nvt.mdp).

With T_target = 310 K, τ = 10 ps:
- t = 25 ps (25,000 steps × dt=0.001): T ≈ 289 K  ← insufficient
- t = 50 ps (50,000 steps × dt=0.001): T ≈ 308 K  ← acceptable (~1 K below target)
- t = 70 ps: T ≈ 309.7 K

**How to apply:** For NADOC skip-structure NVT runs with gen-vel=no, use 50,000 steps (50 ps) as the minimum. This is already the default when `_has_skips` is True and the user hasn't overridden `nvt_steps`.

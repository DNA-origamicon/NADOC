# What we already have (≈60% of the machine) — supporting detail

[Topic head](../../project_snupi_dynamics.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## What we already have (≈60% of the machine)
| Term | Paper | Ours | Status |
|---|---|---|---|
| **M** mass matrix | seq-dependent nodal masses, 6 DOF/node | `assemble_mass_matrix` (G6, SPD, kg) | ✅ |
| **F** elastic internal force | corotational consistent internal-force vector | `snupi_corotational.element_force_tangent` → `f_g=T·K₁₂·d_local`; global assembly in `solve_corotational` | ✅ |
| **F** electrostatic | Debye–Hückel inter-helix, salt-dependent | `snupi_electrostatics` / `_snupi_electro_sparse` | ✅ |
| element D (74 motif 6×6) | anisotropic + coupled | `snupi_material`, exact | ✅ |

## What's missing (the dynamics contribution)
1. **Friction matrix `Z`** — generalized Rotne–Prager–Yamakawa (RPY) mobility `Ξ` (6 DOF/node,
   Wajnryb 2013), `Z = Ξ⁻¹`. σ=1.1 nm hydrodynamic radius, η=890 µN·s/m² @ 300 K. Dense; updated
   every 1000–10000 steps.
2. **Random force `R`** — `⟨R⟩=0`, `⟨R(t)R(t′)⟩=2k_BT·Z·δ(t−t′)`; colored by a Cholesky factor of
   `Z` (full matrix ⇒ correlated noise), refactored at the same slow cadence.
3. **Modified Grønbech-Jensen–Farago integrator** — half-time stepping + Simpson's rule on the
   internal force (Supp Note 4), real-time Δt=5 ps. Inner loop reuses our global `F(x)`.
4. **Base-stacking Morse element** — `Π_sk(r)=ε[(1−e^{−a(r−r₀)})²−1]`, ε=42.79 pN·nm, a=2.668 nm⁻¹,
   r₀=0.3742 nm; salt-dependent ε. 2-node FE (easy); the work is identifying stacking-site topology.
   **Only needed for reconfigurable designs** (switch/rotor). Not needed for equilibrium dynamics.
5. **Trajectory analysis** — RMSD(t), RMSF-from-frames, PCA (→ breathing freq + mode shapes),
   correlation maps, 3DNA bp-step distributions. Reuses existing compare/DCCM code on a frame stack.
6. **Salt-schedule reconfiguration driver** — orchestration (mgcl2_M schedule → ES + stacking react).

## The load-bearing insight (why phase it this way)
The **equilibrium config distribution is friction-independent** — GJF samples the correct Boltzmann
distribution `∝exp(−U/k_BT)` regardless of `Z` (friction only sets the *timescale* and dynamic
cross-correlations, not the static variance). So:
- **trajectory RMSF must equal our NMA RMSF** (both sample `k_BT·K⁻¹`) — a clean, cheap validation
  gate that needs NO hydrodynamics, only the integrator + units + fluctuation-dissipation.
- Node inertial relaxation `m/ζ ≈ 0.06 ps ≪ Δt=5 ps` → heavily overdamped; GJF is built for exactly
  this (correct Boltzmann sampling at large Δt). Confirms the paper's Δt.

Consequence: hydrodynamics (RPY) buys **kinetics + motion cross-correlations + damped real
frequencies**, NOT the static flexibility we already match. Build the integrator first with cheap
diagonal (Stokes) friction, validate against NMA, *then* add RPY.

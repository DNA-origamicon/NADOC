# Constant-potential gold in NAMD: feasibility and implementation design

2026-09-15. **Feasible as new electrostatics development; not supplied by the
current GPU correction plugin.** This is an implementation proposal following
local source inspection, not a claim of native constant-potential validation.
The installed engine and existing simulation defaults were not modified.

## Scientific scope

First implementation: two fixed, explicit Au slabs, an electroneutral complete
cell, fixed cell dimensions, lateral periodicity, normal vacuum padding, and an
imposed potential difference. Retain neutral IFF LJ/contact terms as the separate
structural baseline. Solve the metal charges at each force evaluation. No charge
transfer reactions, redox kinetics or electronic current are implied.

Constant-potential methods minimize a charge-dependent energy under electrode
potential constraints. Charge smearing or hardness is part of that model, not a
PME accuracy setting. The generalized point-charge/hardness approach provides a
possible route through existing electrostatics solvers, but its equivalence to
Gaussian electrodes depends on conditions and must be checked. Choose one model
and a matched reference; do not add a second core–shell polarization model by
default. [Sitlapersad et al., 2024](https://doi.org/10.1063/5.0171502)

The initial electrode charge-width/hardness parameter remains a scientific
selection item. A value copied from a carbon example would not establish gold
calibration. It must be explicit, versioned, and traced to the benchmark selected
for Au. Neutral IFF parameters alone do not determine electrode capacitance.

## Local source audit

Root: `/home/jojo/Applications/NAMD_Git-2025-12-04_Source/src`.

| Source | Observed behavior | Consequence |
| --- | --- | --- |
| `CudaGlobalMasterClient.h:142–150,224–239` | `requestUpdateCharges` asks NAMD to copy charges **to** a client buffer. | This is not a setter for engine charges. |
| `CudaGlobalMasterServer.C:536–564,589–632` | Copies resident coordinates/charges to clients and dispatches callbacks. | A client changing its private charge buffer does not refresh engine nonbonded/PME charge arrays. |
| `backend/core/native/electrode_gpu.cu:109–114` | Current NADOC client requests no charge updates; charges come from a static parameter file. | Its dipole moment becomes wrong for fluctuating charges unless this ownership is changed. |
| `ScriptTcl.C:2015–2024`, `Node.C:1227–1253` | `reloadCharges` reads a host file, broadcasts charges and marks device kernels for update. | A between-run test route exists; it is not a proven per-step resident charge-solve API. |
| `SequencerCUDA.C:2615–2618,3042–3045` | Resident charge buffers feed force/PME data paths. | Updating host molecular charges alone is insufficient; atom maps and charge scaling must be consistent. |
| `CudaPmeSolverUtil.C:1569–1576` | Ordinary PME self energy is recomputed at the first step or when its cached value is zero. | A variable-charge implementation must explicitly invalidate/recompute this term. Verify every related energy cache. |
| `CudaPmeSolverUtil.h:227–260` | Internal grids and a cached self energy exist. | Grid potential availability internally does not mean a supported per-atom potential query exists for plugins. |
| `CudaGlobalMasterClient.h:322–359` | Clients can submit forces and scalar MISC energy. | An external complete electrostatic correction is possible in principle, but requires its own consistent periodic operator. |

Source hashes and engine/plugin hashes are retained with the calibration report.
These findings apply to this inspected build. No claim about every NAMD version
or every possible extension is intended.

## Recommended architecture

**Prefer a source-level experimental electrode adapter that reuses NAMD's
electrostatic operator.** Start with fixed gold and a small dense reference solve.
Keep the initial implementation isolated from ordinary jobs until its energy,
force and charge-update paths have native evidence.

Two alternatives remain useful for development:

- A host-driven `reloadCharges` experiment can test numerical semantics on small
  configurations. File I/O, startup/repeat behavior and PME cache refresh need
  checking before using it even as a reference. Do not advertise it as performant.
- A GPU plugin could leave native gold charges at zero and supply the complete
  metal–metal and metal–electrolyte electrostatic correction, including periodic
  images and all solvent forces. This avoids native charge setters, but duplicates
  an electrostatic solver and creates a substantial double-counting risk. A local
  image force or slab-dipole correction alone cannot fill this role.

### Solve and force sequence

For electrode charges q, fixed electrolyte charges Q, positions R and target
potentials v, write the variable-charge energy as

```text
U(q,R) = U_solvent(R) + U_LJ(R) + 1/2 qᵀ A(R) q + b(R)ᵀ q
G(q,R) = U(q,R) - vᵀ q
```

A includes the selected metal self/hardness model and periodic electrode–electrode
interaction. b is the potential at metal sites from all electrolyte charges.
Both must use the same Green function, exclusions and boundary correction as the
forces. q is in elementary-charge units; energy is kcal/mol, so volt inputs need
the elementary-charge voltage-to-energy conversion (approximately 23.0605
kcal/mol per volt per elementary charge).

Enforce total-cell neutrality by solving the augmented system

```text
[ A   1 ] [q] = [v - b   ]
[ 1ᵀ  0 ] [λ]   [-sum(Q)]
```

For a neutral electrolyte, the two electrodes' total charges are equal and opposite,
but their values and site distributions are outputs. Set working/counter targets
to −ΔV/2 and +ΔV/2 as a gauge convention. A common shift changes λ rather than
the charges. This is an imposed potential difference, not an absolute potential
relative to SHE or an experimentally established potential of zero charge.

For the current normal-vacuum geometry, the existing correction has

```text
c = 2π k_e / V
M = z_eᵀ q + M_solvent
U_slab = c M²
A_slab = 2c z_e z_eᵀ
b_slab = 2c z_e M_solvent
F_z,i = -2c q_i M
```

These expressions are derivatives of the same correction, including all charges.
They must enter the charge solve as well as the force evaluation. The old static
EW3DC client must be disabled or replaced so the term is applied exactly once.
Total neutrality makes the dipole independent of a common origin shift; consistent
image tracking remains necessary. Slab-corrected 3D electrostatics still needs
padding/mesh convergence and is not exact two-dimensional electrostatics at finite
padding. [Boundary treatment in the CPM literature](https://doi.org/10.1063/5.0099239)

At each force evaluation:

1. Gather current coordinates with stable global atom IDs.
2. Obtain b with the agreed periodic operator; reuse A only if electrode positions,
   cell, width/hardness and electrostatic settings are unchanged.
3. Solve for q and λ; retain residuals in physical potential units and total charge.
4. Update all real-space, reciprocal-space, self-energy and slab charge paths
   before evaluating final forces. Synchronize the GPU streams explicitly.
5. Evaluate forces from the stationary G; include the voltage-source work term in
   the appropriate energy diagnostic. Do not infer NVE drift from U alone at fixed
   voltage. Incomplete charge minimization introduces a force error to quantify.
6. Emit electrode charges, potentials, component energies and solver diagnostics.

For fixed sites A can be factored once. At 2,880 metal sites one dense double
matrix occupies about 63.3 MiB; factors and workspaces add memory. Storage scales
quadratically and factorization cubically. Restrained/mobile gold requires updating
A as its atoms move; do not reuse a fixed-site matrix for those models. Initial
fixed-site qualification therefore precedes mobile-electrode support.

## Proposed package/API contract

New experimental model ID, separate from `iff-au-12-6-neutral-v1` and the abstract
wall schema. An example shape, **not a currently accepted request**:

```json
{
  "model": "experimental_au_constant_potential_v1",
  "electrodes": {
    "working_atom_ids": "working.ids",
    "counter_atom_ids": "counter.ids",
    "mobility": "fixed"
  },
  "potential_difference_V": 0.1,
  "total_cell_charge_e": 0.0,
  "charge_model_asset": "reviewed_charge_model.json",
  "electrostatics": "pme_ew3dc_fixed_cell",
  "solver_asset": "qualified_solver_settings.json"
}
```

The charge-model asset must name the equation, width/hardness and reference. The
solver asset must record precision, convergence settings and their native accuracy
evidence. Neither silently receives a numerical default from an unrelated model.
Reject overlapping/missing groups, changes of atom identity, unsupported boundary
conditions, and charge updates with stale solver state.

Checkpoints include coor/vel/xsc plus per-site charges, group map, target voltage,
charge-model hash, operator settings, cell, atom-order hash, runtime/plugin hashes
and solver-state version. On restart, recompute the stationary charge solution and
compare it with the saved state before advancing; preserve COM velocity. Store a
factorization only as a rebuildable cache with a full identity key. Exact restart
charge identity cannot replace residual/energy checks.

## Qualification sequence before enabling voltage-controlled jobs

| Check | Independent reference or physical basis |
| --- | --- |
| Charge operator and solve | Small direct Ewald calculation, symmetry of A, neutrality, invariance to common potential offset, and the linear response of a fixed empty cell. |
| Force/energy consistency | Finite differences of minimized G after re-solving charges at perturbed coordinates; electrode and electrolyte forces checked separately. |
| Native charge propagation | Change a known charge vector and compare real-space, reciprocal-space and self-energy contributions against fresh-process evaluation of the same state. |
| Convergence settings | Tighten solve/PME/padding accuracy and quantify changes in charge, potential and force against the independent reference; derive tolerances from the intended observable accuracy. |
| Restart | Same saved state and voltage, no COM impulse, consistent charges and component energies; repeated uninterrupted runs establish numerical reproducibility sensitivity. |
| Capacitor boundary | Compare empty parallel plates against their continuum large-area/large-gap limit while accounting for the chosen image-plane position and finite size. |
| Water/electrolyte interface | Matched published facet, charge model, solvent, salt and temperature; independent replicas and reported sampling uncertainty. |
| Capacitance | Prefer charge-versus-voltage slope initially. A fluctuation estimate for a Born–Oppenheimer charge solve needs the ensemble correction described by Scalfi et al.; it is not simply an unchecked charge variance. |
| Runtime | Benchmark the complete force/charge-solve loop on the local GPU and report memory and convergence cost, not isolated matrix multiplication speed. |

The [LAMMPS ELECTRODE implementation](https://docs.lammps.org/fix_electrode.html)
provides a useful external reference with explicit neutrality, fixed-potential and
fixed-charge variants; it is not evidence of NAMD compatibility. Charge-fluctuation
interpretation follows [Scalfi et al., 2020](https://doi.org/10.1039/C9CP06285H).
No production solver, new force-field fit or cloud execution was authorized or
performed as part of this feasibility design.

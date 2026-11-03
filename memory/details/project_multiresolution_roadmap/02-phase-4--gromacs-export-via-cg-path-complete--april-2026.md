# Phase 4 — GROMACS Export via CG Path [COMPLETE — April 2026] — supporting detail

[Topic head](../../project_multiresolution_roadmap.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Phase 4 — GROMACS Export via CG Path [COMPLETE — April 2026]

**mrDNA-sourced sibling added 2026-07-02** (route established, hardware validation pending —
see `manual_validation_debt.md` MV-MRDNA-SEED): `POST /design/export/gromacs-mrdna-start`
seeds `build_gromacs_package` from a COMPLETED **fine-stage** mrDNA JOB's relaxed structure
instead of running oxDNA. Wiring lives in two `mrdna_runner.py` helpers —
`resolve_md_seed_inputs` (gates: completed + `fine_steps>0` + snapshot/PSF/DCD present; raises
UI-ready ValueError → 409) and `build_md_seed_override` (calls `nuc_pos_override_from_arbd_strands`,
crossovers INCLUDED). It seeds from the JOB's `design.json` snapshot, NOT the live design.
Gating + wiring pinned `tests/test_mrdna_md_seed.py` (7 fast + 1 skip-guarded integration).
**Still TBD (deferred with the user):** coarse-only fallback policy, ssDNA/overhang atomistic
handling (Phase 5), NAMD parity, and a frontend "seed MD" affordance in the mrDNA panel.
The end-to-end GPU→fine-ARBD→override→GROMACS-EM step-reduction payoff is unrun (needs a fine
job on a CUDA box; the one on-disk job is coarse-only).

- [x] `backend/api/crud.py`: `POST /design/export/gromacs-cg-start` — oxDNA relax → `_refit_helix_axes` → `build_gromacs_package`
- [x] `nuc_pos_override` parameter added to `build_gromacs_package`/`build_atomistic_model` but NOT used in CG path (axis refit approach is superior)
- [x] Frontend: "Pre-relax with oxDNA" checkbox in GROMACS export modal
- [x] **Verified (2026-04-20): Current CG path does NOT reduce EM.** The API endpoint and frontend exist and work, but the gromacs-cg path currently provides no benefit over the ideal path for this design. Pending Phase 3b redesign.

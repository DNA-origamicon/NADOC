# Fresh-session startup prompt: manual cis-syn TT-CPD conversion

Copy the text below into a fresh Codex session opened at `/home/jojo/Work/NADOC`.

---

We need to implement the manual product-state part of the DNA-origami photoproduct study.
Read `/home/jojo/Work/NADOC/docs/manual_cis_syn_cpd_namd_plan.md` completely before making
changes, then inspect any repository `AGENTS.md` instructions and the current dirty
worktree. Preserve all unrelated user changes and untracked experiment outputs.

Goal: allow a NADOC user to select exactly two thymine nucleotides, manually mark/convert
them as a formed cis-syn thymine CPD, and prepare a chemically complete product topology
and safe starting geometry that can be simulated in NAMD. This manual conversion must work
for crossover-extra bases as well as ordinary bases and must preserve unambiguous design to
PSF identity. Automatic conversion during a running NAMD trajectory is explicitly out of
scope for this session.

Scientific context: we want paired reactant/product simulations to separate stability due
to unreacted extra thymines from stability caused by an actual interstrand photoproduct.
The current KIMMDY analysis scores reactant-state geometric propensity only. Do not change
that interpretation and do not turn its geometry gate into a stability filter.

Critical chemistry constraint: a final cis-syn TT-CPD is not a pair of NAMD
`extraBonds` restraints. It needs the real C5(1)-C5(2) and C6(1)-C6(2) covalent bonds plus
product-specific atom types, charges, angles, dihedrals, impropers/stereochemistry, and all
matching parameters. The product should conserve atom count and pair charge. Never claim a
simulation-ready product if only the two bonds or harmonic restraints were added.

Start with an evidence/provenance spike for a CHARMM36-compatible cis-syn TT-CPD patch and
parameter set. The local `backend/data/forcefield` bundle does not currently contain one.
Do not invent missing terms, infer them casually by analogy, or mix an AMBER lesion model
into the CHARMM36 system. Document the chosen source/version/license/validation in
`docs/cpd_forcefield_provenance.md` and a machine-readable manifest. Use RCSB 1N4E and the
TTD chemical component as structural validation references, not as automatic parameter
authority. If no defensible parameter set can be obtained, implement safe design/UI
plumbing behind an explicit capability gate and make every NAMD path fail closed with a
clear error. Tell me exactly what is missing rather than creating a chemically incomplete
fallback.

Build on the existing architecture:

- `backend/core/models.py`: dormant `PhotoproductJunction` and
  `Design.photoproduct_junctions`.
- `backend/core/scadnano.py`: legacy scadnano-CPD round-trip.
- `frontend/src/scene/base_ref.js`: canonical ordinary/loop/extension/extra base keys.
- `frontend/src/scene/selection_manager.js`: multi-base selection and
  `getSelectedBaseKeys()`.
- `frontend/src/ui/properties_panel.js`: selected-base UI.
- `backend/core/atomistic.py` and `backend/core/atomistic_to_nadoc.py`: per-atom stable
  provenance, including `crossover_id`, `extra_base_k`, `copy_k`, and `base_key`.
- `backend/core/namd_topology.py`: authoritative full CHARMM/psfgen topology builder and
  robust segment/residue ordinal mapping.
- `backend/core/cpd_metrics.py` and `frontend/src/scene/cpd_geometry.js`: existing
  reactant-state geometry definitions; keep these analysis-only.
- `backend/core/namd_solvate.py`, `namd_vacuum.py`, `namd_gbis.py`, `md_protocols.py`,
  `namd_package.py`, `periodic_cell.py`, `md_precondition.py`, and
  `backend/api/routes_md.py`: duplicated package/config force-field consumers that must
  either include the CPD assets or explicitly reject CPD designs.

Implement in vertical, tested increments:

1. Add a backend base-key parser/resolver that exactly mirrors the frontend grammar,
   including right-splitting IDs containing colons, loop copies, extensions, and
   `__xb__:crossover_id:k`. Use shared fixtures for Python and JavaScript tests.
2. Migrate/extend `PhotoproductJunction` to persist ordered base keys, `TT-CPD`,
   `cis-syn`, manual provenance, and deterministic patch/template orientation while
   retaining lossless legacy scadnano fields.
3. Add read-only preflight plus undoable create/delete API operations. Revalidate on the
   server: two distinct resolvable Ts, no endpoint reused, required C5/C6 atoms present,
   supported stereochemistry, and no stale identity. Return whether the pair is
   interstrand/intrastrand and extra-extra/extra-native/native-native.
4. Add **Form cis-syn TT-CPD** to the two-base selection workflow, with a compact preflight
   confirmation and visible reasons when disabled. Render a formed-product marker that is
   distinct from the KIMMDY propensity view. Support remove, save/reload, undo/redo, and
   feature-log seek.
5. Add a versioned, provenance-backed product coordinate builder. It must preserve
   glycosidic/backbone connectivity, enforce the selected cis-syn chirality, locally fit or
   minimize the two product bases, reject excessive strain/clashes/piercing, and return a
   machine-readable placement report. Test both adjacent intrastrand and antiparallel
   interstrand cases; never mirror a template merely to make it fit.
6. Extend the shared psfgen builder to resolve each endpoint by atomistic provenance,
   load the validated lesion topology, apply an ordered two-residue patch, regenerate
   bonded terms, and audit the resulting PSF. Prove exactly one C5-C5 and C6-C6 bond per
   lesion, conserved atom count/charge, expected product types and impropers, and complete
   reverse identity mapping.
7. Propagate the matching parameter file through every stage and continuation of the
   production-grade explicit-solvent NAMD path. Centralize the force-field manifest where
   practical. Make unsupported GBIS/vacuum/legacy exporters reject product designs rather
   than silently emitting reactant topology. Package hashes and topology/placement audits.
8. Add a CPD-specific staged local minimization/preflight and a real NAMD 2 fs smoke test.
   Keep CPD jobs at 2 fs until product-specific HMR/4 fs behavior is separately validated.

Use `backend.api.state.mutate_with_feature_log` for design mutations. Do not store transient
atom serials or `segid:resid` values in the design; derive those in the simulation package
and record them in its audit metadata. Handle sequence/crossover/extension edits so a
lesion cannot become stale or non-thymine unnoticed.

Run focused tests after each increment and then the relevant backend/frontend suites. Run
real psfgen and NAMD smoke tests when the installed executables are available; mocks may
supplement but not replace the chemistry/topology integration test. Report commands,
results, skipped external-engine tests, remaining scientific assumptions, and any paths
that deliberately fail closed.

Do not stop at a plan or high-level code review. Implement and verify as much of the
manual workflow as the validated chemistry permits. Do not start automatic in-trajectory
conversion.

---

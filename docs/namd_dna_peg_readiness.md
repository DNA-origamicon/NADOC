# Readiness for covalent DNA–PEG simulations

Assessment: 2026-09-12, after commit `8487cb0d` was pushed. Here “conjugated” means
an explicit chemical linkage between DNA and PEG. Surface attachment may remain
the existing mechanical spring reference; an explicit gold substrate is not a
prerequisite for this next step.

## What is now demonstrated

- Atomistic methyl-capped PEG8/TIP3P preparation, harmonic substrate grafts and
  repulsive slit walls, using pinned additive ether assets.
- Shared HMR machinery, constrained X–H bonds, GPU-resident integration, native
  Run/Stop/Resume and continuation-aware evidence parsing.
- Full job `48c1995afbd5` is **completed**, with no job error: 25 ps at 2 fs followed
  by 480 + 1920 + 2400 ps at 4 fs. Every chunk actually ran; no skips occurred.
- Saved safety reports pass throughout. Across the three 4 fs chunks, maximum
  sampled wall penetration is 0.4762 Å and maximum graft excursion is 0.9197 Å.
  The warm-up's maximum graft excursion is 1.2247 Å. These are sampled maxima.
- Every 4 fs chunk fails the current energy and polymer plateau criteria. Completing
  4.8 ns therefore demonstrates execution/sampled safety, not brush equilibration.
- PEG-only Display MD, RMSF, trajectory, solvent/cell and atomistic representations
  are available. Production promotion remains deliberately gated.

This is a four-chain, **9,092-atom** PEG/water case. It contains neither DNA nor a
DNA–PEG covalent junction. Its retained methyl caps and positional graft springs
must not be mistaken for a chemical conjugation model.

## Gaps and concrete acceptance gates

| Priority | Gap | Required result |
|---|---|---|
| P0 | Exact conjugate identity | Record the DNA attachment site (5′, 3′ or internal), actual linker/end-group structure, PEG repeat count, protonation/net charge, and which PEG end attaches to DNA versus the support. A supplier structure or explicit chemical graph resolves this; “PEG linker” alone does not. |
| P0 | Junction topology and force-field coverage | A versioned patch/residue definition removes the correct terminal caps/atoms, assigns charges and creates every required junction bond, angle, dihedral and improper. Verify exclusions/1–4 treatment, valence, net charge and parameter coverage after psfgen. Existing NP5C/NP3C patches implement DNA C3 thiolate linkers, not PEG conjugation. |
| P0 | Chemical validation of the junction | Audit existing parameter coverage first. Validate representative junction conformers, torsions and hydration; generate/fix parameters only where coverage or accuracy is missing. Use held-out targets and isolated new atom types where required. Do not retune the validated DNA backbone merely to accommodate a linker. |
| P0 | Combined molecular construction | Produce one consistent DNA + linker + PEG topology and coordinate set, with stable atom identities through patching, solvation, ionization, HMR and restarts. Verify the intended covalent connected component, cap deletion, charge, chain contour reach, overlap clearance and wall/graft registration. Build HMR from the final patched topology. |
| P1 | Buffer and cross interactions | Qualify a consistent DNA/ether/TIP3P parameter stack, including duplicate atom-type definitions, water conventions, exclusions and mixing/overrides. Add the intended Na/Cl/Mg model and concentrations; the present PEG case has no ions. Existing DNA ion preparation does not by itself validate PEG ion coordination or PEG–DNA interactions. |
| P1 | Mixed relaxation protocol | Compose DNA restraint release with permanent physical substrate grafts and the covalent junction. The PEG–DNA attachment must not acquire a second positional spring by accident. Keep the final wall model in a consistent fixed-cell ensemble; determine solvent density before locking it, rather than allowing an unqualified barostat to move the walls. |
| P1 | Mixed safety and skip decisions | Run DNA structural checks AND PEG/junction checks. Audit restraint-energy accounting: the current PEG validator attributes BOUNDARY entirely to grafts and MISC to the wall; added DNA restraints/forces can invalidate those assumptions. Use explicit force-component accounting, not relaxed energy-agreement tolerances. A converged PEG chain cannot excuse strained DNA or an unstable junction. |
| P1 | Mixed visualization and persistence | Preserve DNA nucleotide mapping and explicit PEG/linker/water/ion atom classifications together. The PEG-only renderer currently selects PEG atoms plus non-PEG oxygens as water; applying it unchanged would omit DNA atoms and mislabel DNA oxygen atoms. Support covalent junction bonds, periodic unwrapping across the junction, chain/atom RMSF and complete restarts. |
| P2 | General user preparation and production | Connect saved surface/conjugation definitions to the validated combined builder, expose only supported parameters, and qualify production handoff. The direct surface editor is still a schematic draft, and oxDNA PEG seed review still stops before atomistic backmapping. |

The existing additive ether model is a defensible starting point: the published
C35r work tested ether conformations and PEG/PEO solution dimensions. That scope
does not establish a DNA–PEG junction or the mixed system's thermodynamics.
[Lee et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18456821/).

A psfgen patch can span residues, but merely adding a bond does not demonstrate
complete bonded topology. The audit must explicitly check junction angles,
dihedrals and any chemistry-specific impropers; psfgen provides regeneration tools
for angles/dihedrals where needed.
[psfgen User's Guide](https://www.ks.uiuc.edu/Research/vmd/plugins/psfgen/ug.pdf).

## Recommended next experiment

1. Resolve **one actual DNA–PEG chemical structure**. The first blocking input is
   the desired attachment site and linker chemistry, not an engine setting.
2. Build an isolated nucleotide/linker/short-PEG test fragment. Prepare an explicit
   current-versus-candidate atom/bond review, with charge, valence, parameter and
   per-junction geometry deltas, before introducing candidate geometry into the
   normal pipeline. This follows the repository's geometry authorization gate.
3. Once the patch is reviewed, build one short DNA duplex conjugated to one short
   PEG chain in the intended buffer. Qualify the soluble conjugate first, then
   add the existing harmonic graft and repulsive wall to isolate surface effects.
4. Compare physical-mass 2 fs and HMR 4 fs execution on this conjugate using
   multiple seeds, junction torsions/geometry, DNA base pairing/stacking, PEG
   dimensions and short energy-drift probes. Thermostatted survival alone is
   insufficient to establish numerical equivalence. Set quantitative acceptance
   criteria before running; do not manufacture a pass by loosening constraints.
5. Add a small surface patch/multiple conjugates, then a representative origami
   system. Test combined restraint release, continuation and skip behavior before
   offering routine production or a general frontend launch path.

A harmonically connected DNA/PEG pair could test scheduling or display plumbing,
but its results must be labeled as a mechanical surrogate. It would not close the
covalent junction or chemical-validation gaps above.

## What need not block the first conjugate pilot

- MC seeding: useful for decorrelating brush conformations, but not a substitute
  for a chemical junction or a prerequisite for a small reviewed conjugate.
- Explicit gold, Au–S chemistry, electrode polarization or applied potential:
  required only when those physical mechanisms become part of the intended model.
- General oxDNA-to-atomistic PEG backmapping: direct atomistic construction can
  qualify the first conjugate; the existing seed-review barrier remains in place.
- Replacing HMR or weakening origami force constants: no present evidence calls
  for either. The new junction still needs its own 4 fs qualification.

No molecular geometry or force-field parameters were changed during this assessment.

## Regression baseline still open

After native NAMD completed, `just smoke` ran without a guard override: **22 passed,
1 failed**. The assembly-exit console test caught an HTTP 500 from the existing
mrDNA reconciliation save race (`job.json.<pid>.tmp` collision); no PEG action was
involved. This remains an engineering regression gate to repair separately.
Global teardown removed six temporary documents and the failure-safe wrapper
removed browser outputs; no E2E workspace/session artifacts remained.

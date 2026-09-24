---
name: Preliminary cis-syn CPD strand-builder integration
description: Additive v6 is usable through explicit-solvent NAMD; full scientific release remains pending.
type: project
status: active
authority: supporting
---

User accepted bounded preliminary research qualification, then requested strand-builder
integration (2026-09-20). See `docs/cpd_strand_builder.md` and its verification report.

- `simulation_ready` still means full scientific release (false); `simulation_supported`
  also allows hash-verified preliminary research qualification. Do not mark old full gates passed.
- Curated assets: `backend/data/forcefield/photoproducts/tt-cpd-cis-syn/preliminary-v6/`.
  No runtime archive dependency. Review + evidence hashes travel in every package.
- Scope: additive, adjacent internal TT, 5′→3′ patch ordering, ordinary masses, ≤2 fs.
  Drude, other stereoisomers, termini/interstrand/nonadjacent contexts remain unsupported.
- CSV6 retypes both nucleotides, retains carbonyl impropers, deletes two reactant planar
  C5 impropers present in bundled THY but absent in the tested reference fixtures.
- Product coordinates use native-relaxed 1T4I template, never falsely label provenance as QM.
  Base-only placement preserves normal sugar/backbone geometry; rejects clashes/strain.
- Raw solute coordinate override and graphene-only omission are blocked for product designs.
- Example .nadoc is under docs/examples; native ZIP + screenshot under
  `.development-artifacts/cpd-builder-integration-v1/`.
- 12-bp builder duplex passed 1,000 native minimization + 1,000 dynamics steps (2 ps).
  Earlier overnight 34-ns benchmark remains stability evidence; one CPD replica opening
  is unresolved energetically, not automatic reason to refit indefinitely.
- Final verification: 61 scoped backend tests, 6,573 frontend tests, CPD builder/progress
  browser checks pass. Broad backend/smoke/lint retain non-CPD failures; see report.
- No spending or new long-run campaign during integration. Shared VR/other work preserved.

User-visible copy requested 2026-09-20: `workspace/CPD/cpd_preliminary_duplex.nadoc`.
Completed native integration job `a2c3e3a2b7bd` lives in standard `workspace/md_jobs/`,
linked by `design_source_path`. Both min + 2-ps NVT recorded; 10-frame/24-nucleotide
trajectory and display readiness verified through the running app API. No new simulation.
The docs example remains a reusable regression fixture.

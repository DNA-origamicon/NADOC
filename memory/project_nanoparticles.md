---
name: project-nanoparticles
description: Display-layer nanoparticle authoring and automation.
---

# Nanoparticles

**Status (2026-09-02): Gold nanospheres shipped; gold nanorods and quantum dots are menu placeholders.**

Gold nanospheres are persisted as `Design.nanoparticles` display records with diameter (nm),
visibility, and a rigid pose. Creation, resize/move, and deletion use the
`nanoparticle-{create,patch,delete}` snapshot feature-log operations, so undo, timeline revert,
save, and reload use the standard design-state contract. The core itself never enters DNA
topology; thiol surface strands do, through the ownership records described below.

The frontend `nanoparticle_subsystem.js` owns metallic-gold sphere meshes, picking, canonical
`{kind: "nanoparticle", id}` selection, the shared protein-style transform gizmo behavior, and the
right-click Edit diameter / Conjugate Manager / Delete menu. REST endpoints live in
`routes_nanoparticles.py`; `window.__nadocTest.nanoparticles` is the stable Playwright facade.

**Thiol conjugation (2026-09-02).** `Design.nanoparticle_conjugations` owns a
versioned thiol surface specification and maps every surface site to a real
`Design.strands` strand on a `__np__...` virtual helix. The four initial presets
are direct thiol, alkyl-thiol, PEG-thiol, and PEG-thiol backfill. Coverage uses a
nonlinear 1/2/3/5/10/25%/50%/75%/100% control and reports both a central estimate
and literature-based range. Applying/replacing/removing a corona is one snapshot
feature operation. Unbound owned helices translate/rotate and resize with the
particle. A surface strand can be converted in-place (same strand ID) to an
ordinary `OH_BINDER` on a compatible overhang.

The gold core intentionally remains non-atomistic. Full representation draws the
surface-to-DNA connector; atomistic modes add S plus scheme-dependent C/O linker
atoms and explicit linker/surface bond segments. Automation lives at
`window.__nadocTest.nanoparticles.conjugation`; backend CRUD/estimate/validate/bind
routes are in `routes_nanoparticles.py`.

**Handle connections (2026-09-03).** The right-sidebar Overhang Connections card
has an NP-handle ↔ overhang mode with a compact two-option direct-connection
picker. The thiolated terminus is the handle root. UI and API independently
reject any attachment choice that would produce parallel rather than
reverse-complementary strand directionality. Applied versions materialize a
native measurable Duplex; collective N-anchor relaxation reorients rigid
handle/overhang duplexes before translating the particle and carries every owned
surface handle with the solved pose. Public workflow and automation documentation
lives in `docs/nanoparticle_conjugation.md`.

Playwright validation copies `workspace/NP_test.nadoc` to a prefixed file under
`workspace/playwright_tests/` and never mutates the original. Spec teardown,
global teardown, and the exit-time artifact cleanup reporter jointly remove the
fixture, screenshots, traces, reports, and `.last-run.json` on success or failure.

---
name: project-nanoparticles
description: Display-layer nanoparticle authoring and automation.
---

# Nanoparticles

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Attachment authoring (2026-10-09):** `ui/nanoparticle_attach.js` owns right-click
Attach to overhang → one-shot overhang selection, Escape, filter restoration and
error handling. `api/nanoparticle_attachment.py` is the shared atomic builder for
the new endpoint, Conjugate Manager binding and standard generated designs.
Reuses thiol handles, existing antiparallel duplex application and closed-loop
kinematics; generator locks centers and shares the rigid circle/roll fitter.
Occupied targets and unreachable fits reject before commit. Per the October 30
user correction, automatic fitting preserves covalent root length in both viewer
and export atom geometry; DNA/protein/other-core collisions are advisory and never
justify stretching a root. Manual movement remains free to stretch bonds. Scope: uncoated gold;
existing coated-particle chemistry remains separate. See docs/nanoparticle_conjugation.md.
The endpoint checks the submitted revision before fitting, then compares design
content inside the feature transaction: an intervening autosave may advance the
active loadout's persistence cursors, but a real design edit rejects the fit.

**Status (2026-09-12): Gold nanospheres and quantum-dot catalog/import are implemented; gold nanorods remain a menu placeholder.**

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

- [Nanoparticles — continued detail](details/project_nanoparticles/01-nanoparticles.md)

<a id="gold-quenching-research-and-display-2026-09-12"></a>
- [Gold quenching research and display (2026-09-12)](details/project_nanoparticles/01-nanoparticles.md#gold-quenching-research-and-display-2026-09-12)

<a id="gold-creation-optical-popup-2026-09-12"></a>
- [Gold creation optical popup (2026-09-12)](details/project_nanoparticles/01-nanoparticles.md#gold-creation-optical-popup-2026-09-12)

<a id="streptavidin-coatings-2026-09-12"></a>
- [Streptavidin coatings (2026-09-12)](details/project_nanoparticles/01-nanoparticles.md#streptavidin-coatings-2026-09-12)

<a id="fixed-core-oxdna-minimal-build-2026-09-13"></a>
- [Fixed-core oxDNA minimal build (2026-09-13)](details/project_nanoparticles/01-nanoparticles.md#fixed-core-oxdna-minimal-build-2026-09-13)

<a id="explicit-dna-occupancy-2026-09-14"></a>
- [Explicit DNA occupancy (2026-09-14)](details/project_nanoparticles/01-nanoparticles.md#explicit-dna-occupancy-2026-09-14)

<a id="biotin-visualization-2026-09-14"></a>
- [Biotin visualization (2026-09-14)](details/project_nanoparticles/01-nanoparticles.md#biotin-visualization-2026-09-14)

<a id="atomistic-loading-audit-2026-09-14"></a>
- [Atomistic loading audit (2026-09-14)](details/project_nanoparticles/02-atomistic-loading-audit-2026-09-14.md#atomistic-loading-audit-2026-09-14)

<a id="biotin-terminal-extensions-and-alpine-validation-2026-09-16"></a>
- [Biotin terminal extensions and Alpine validation (2026-09-16)](details/project_nanoparticles/02-atomistic-loading-audit-2026-09-14.md#biotin-terminal-extensions-and-alpine-validation-2026-09-16)

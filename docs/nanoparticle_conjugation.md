# Gold nanoparticles and thiol conjugation

NADOC currently supports spherical gold nanoparticles (AuNPs). Gold nanorods and
quantum dots appear in the Nanoparticle menu as future entry points but are not
yet authoring tools.

## Authoring and persistence

Choose **Tools → Nanoparticle → Gold nanosphere**, enter a diameter in nanometres,
and place the particle in the 3D workspace. A gold nanosphere:

- is saved in the `.nadoc` design and survives save/open and browser reload;
- remains selected until empty space is clicked or Escape is pressed;
- uses the protein-style move/rotate gizmo and remains selected while orbiting;
- has a metallic gold Photo Mode material; and
- has right-click actions for diameter editing, conjugation, and deletion.

Create, resize/move, and delete are snapshot-bearing Feature Log operations and
can therefore be edited, reverted, or deleted through the normal history tools.

## Thiolated ssDNA handles

Open **Conjugate Manager** from the particle context menu. The manager can be
orbited independently and previews the Full representation's helical ssDNA
geometry. It supports direct thiol, alkyl-thiol, PEG-thiol, and PEG-thiol
backfill schemes. The coverage control provides low-copy 1, 2, and 3 handle
targets plus percentage-density targets derived from the selected scheme and
particle diameter. A value above the estimated maximum may also be entered
manually.

Creating the corona makes every previewed handle a first-class NADOC strand.
Handles on one particle share a color and group, and receive stable names such as
`NP-1:S1`. Unbound handles rigidly follow particle translation, rotation, and
diameter changes.

The gold core intentionally has no atomistic gold lattice. Full representation
shows the surface connector. Atomistic export supplies the sulfur and
scheme-dependent spacer atoms and bonds that mediate attachment to the standard
DNA backbone. The supplied NAMD topology/parameter additions describe those
attachment residues; users should still validate force-field compatibility and
simulation conditions for their intended gold-interface model.

## Connecting handles to origami overhangs

Open the right-sidebar **Overhang Connections** card and choose
**Nanoparticle ↔ Overhang**. Select a nanoparticle ssDNA handle and a target
overhang, then choose one of the two direct connection icons. The compact picker
renders above the sidebar tabs; a warning marks any forbidden geometry.

The handle's **root** is the terminus carrying the thiol. Its **free end** is the
opposite terminus. NADOC permits a connection only when the selected attachment
ends produce antiparallel, reverse-complementary DNA. For example, a root-to-root
connection between two 5′ roots is forbidden. This rule is enforced in both the
UI and backend, so an automation client cannot create or apply invalid topology.

**Connect** (or **Add version**) records a candidate. **Apply** materializes the
selected version as one measurable duplex, and **Relax** solves all applied
anchors collectively. Multiple versions can coexist and be applied or unapplied;
only the active compatible materialization is present in the design. During
movement and relaxation, each handle–overhang duplex acts as a rigid linker,
while the overhang crossover and handle-to-particle attachment behave as joints.
The solver first reorients duplexes to reduce bond residuals, then translates the
particle and applies DNA-avoidance displacement. All attached and unattached
particle handles follow the solved particle pose.

## Automation and regression testing

Backend routes are rooted at `/api/design/nanoparticles`. They cover sphere CRUD,
coverage estimation, conjugation CRUD/validation, connection-version CRUD, and
collective relaxation. Browser automation should use the stable facade at
`window.__nadocTest.nanoparticles`; conjugation and connection helpers are under
`window.__nadocTest.nanoparticles.conjugation`.

The main regression ground is `workspace/NP_test.nadoc`. A Playwright test must
copy it to `workspace/playwright_tests/` using an `__e2e__` prefix and must never
modify the original. Every test that can persist data must identify a
failure-safe cleanup mechanism before execution. Spec teardown, global teardown,
and the cleanup reporter remove disposable designs, screenshots, traces, reports,
and `.last-run.json`; the relevant paths must be queried after every run to prove
that no generated artifact remains.

Focused coverage lives in:

- `tests/test_nanoparticles.py` and `tests/test_nanoparticle_kinematics.py`;
- `frontend/src/ui/overhang_connections_panel.nanoparticle.test.js`;
- `frontend/src/ui/nanoparticle_conjugate_logic.test.js`; and
- `frontend/e2e/nanoparticle*.spec.js`.

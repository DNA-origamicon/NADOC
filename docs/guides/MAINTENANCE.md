# Maintaining illustrated guides

[Guide library](README.md) · [Coverage ledger](LEDGER.md) · [UX findings](UX_LEDGER.md)

## Writing convention

Explain what each control does and the action the reader should take. Keep captions
and introductions focused on the demonstrated workflow; omit lists of things a
feature does not do. Apply this convention to every future guide and its capture recipe.

## Lesson scope

Keep each guide focused on using its named tool successfully. Do not add
cancellation/no-commit demonstrations, Undo/Redo, feature-history editing, or
chapters teaching another tool. Link prerequisite guides instead. The generated
example still requires complete verified construction history.

## Representation convention

Every 3D guide image uses **Full** representation, with no regional representation
overrides. The shared capture helper checks this before every screenshot and
records the representation in `steps.json`; it refuses a nonconforming capture.
Only a lesson about changing representations may opt out by passing
`{ feature: 'representations' }` to `createGuide`. Do not switch ordinary lessons
to Cylinders for readability; adjust framing instead. Tool previews retain the
appearance users see in the real application. Native cadnano path-view captures are
2D, recorded as `view: cadnano-path` with no 3D representation. The capture helper
verifies that the editor and Full 3D window share the same document.

## Check freshness

From the repository root, with Python 3.12 or the project's `.venv/bin/python`:

```sh
python3 -m scripts.check_feature_guides
python3 -m scripts.check_feature_guides --json
python3 -m scripts.check_feature_guides --require-all
```

No application, browser, network or Git history is required for these checks.
The source fingerprints are SHA-256 hashes of actual file contents, not file
timestamps or only the last commit. Uncommitted changes are therefore detected,
and a shallow clone works. Added/deleted files matching dependency globs count
as changes, as do changed watch patterns and declared lesson scope.

- `CURRENT`: declared dependencies and guide assets match the capture.
- `STALE`: source files, dependency rules or lesson scope differ. Review the
  listed paths; a shared file may have changed for an unrelated reason.
- `BROKEN`: missing metadata/dependencies, damaged assets or an incomplete guide.
- `not-created`: registered feature with no illustrated guide yet.
- `INVENTORY`: `FEATURES.md` and the catalog differ, or the Markdown ledger needs
  regeneration. New features, renamed features and changed subfeature lists are
  reported rather than silently omitted.

Exit status is **0** when existing guides and inventory pass, **1** when attention
is needed. `--require-all` also returns 1 until every feature has complete coverage.
It is expected to fail today. Planned/blocked features otherwise do not fail the
ordinary check. JSON output includes every feature and the exact changed paths.

`CURRENT` is deliberately limited to declared dependencies. This is not automatic
dependency analysis or proof that an arbitrary UI change is irrelevant. Maintain
the watch lists when extracting modules or moving behavior. Shared menus,
sidebars, rendering, command dispatch and capture infrastructure are deliberately
watched conservatively; review false positives rather than narrowing rules just
to clear a warning. External browsers, drivers and unlisted dependencies can also
affect rendering and require visual review.

## Generate or regenerate a guide

The installed project environment and Playwright Chromium are required:

```sh
# First canonical capture (refuses an existing destination):
just validate-safe .venv/bin/python -m scripts.generate_feature_guide

# Regenerate the existing guide after reviewing the stale report:
just validate-safe .venv/bin/python -m scripts.generate_feature_guide --replace

# Separate Bend lesson (use --replace on later captures):
just validate-safe .venv/bin/python -m scripts.generate_feature_guide --feature bend-and-twist

# Separate Twist lesson under the same feature:
just validate-safe .venv/bin/python -m scripts.generate_feature_guide --feature bend-and-twist --guide twist

# Optional disposable editorial preview (does not update the canonical ledger):
just validate-safe .venv/bin/python -m scripts.generate_feature_guide \
  --output .development-artifacts/feature-guides/extrude-preview
```

The default destination is `docs/guides/extrude/`. Inspect its rendered Markdown
and images before committing. Do not commit or publish a guide solely because its
browser run passes. Confirm that targets are unobstructed, parameters are readable
and the final view shows the operation's effect.

Generation takes a source fingerprint before capture and compares it again after
capture. It refuses a mixed-source run. The browser uses isolated servers on
8019/5189, a fresh workspace/profile and real mouse/keyboard input. Existing user
documents and the development server are not used. Chromium requests ANGLE OpenGL
for responsive Full-mode capture; it may use Mesa software rendering when a GPU
is unavailable. This does not alter the application’s preview lifetime. It waits for the actual
autosave, independently replays the construction and publishes the example
through `scripts.agent_structure_guard.publish`. Saved/reopened replay is checked
again. Parts and assemblies retain their document ownership; this part generator
does not publish assemblies or history-free snapshots.

Screenshots, Markdown, verification and asset hashes are prepared in a temporary
sibling directory before promotion. `--replace` requires an identifiable guide,
refuses unexpected extra files and checks that the destination has not changed
during capture. A failed promotion restores the previous directory. This is a
rollback-safe directory replacement, not a crash-proof atomic exchange. Keep
editorial notes in `UX_LEDGER.md`, not inside generated guide directories.

`created_at` preserves the first canonical capture timestamp on replacement;
`captured_at` records the latest capture. Times include the America/Denver offset.
The manifest also records the source revision and whether the worktree was dirty;
content hashes identify the captured state even before it is committed. Asset
hashes detect changed screenshots, captions and example files. They are integrity
checks, not signatures against deliberate tampering.

After publication the canonical ledger is regenerated automatically. To refresh
only the Markdown table after catalog changes:

```sh
python3 -m scripts.check_feature_guides --write-ledger
```

This **never** updates captured source hashes, dates or review status. A stale
guide remains stale. There is no “accept current hashes” shortcut: recapture and
review the guide to establish a new baseline.

## Add coverage

**Current editorial convention:** use a **3-row × 6-column square lattice**
(18 helices) unless the lesson explicitly requires another model. Length is a
lesson parameter: Extrude begins at 64 bp. The executable footprint convention
lives in `frontend/guides/model.js`. Use offset numbered arrows with their labels
away from click targets; use a dashed box to illustrate drag bounds.

The Extrude guide is the style-review specimen. Iterate its wording, framing and
annotations with the user before adding batch/scheduled generation or expanding
the guide-production automation. The existing launcher is used only for deliberate
editorial captures and verification during these iterations.

1. Add/update the feature in `FEATURES.md` and its entry in `catalog.json` together.
   Stable IDs use lowercase words separated by hyphens. Preserve the main-feature
   name, category and subfeature list so inventory drift can be checked.
2. Choose a small example and specify exactly which workflows/editor contexts
   the guide teaches. Use `partial` until all listed subfeatures and intended
   contexts have guides; use `blocked` with a concrete reason when appropriate.
3. Add a real-input recipe under `frontend/guides/`, outcome checks and source
   dependencies. Extend the generator/config to select that recipe: the generator selects the feature’s primary lesson by default. Use
   `additional_guides` for more lessons under the same inventory feature, each with
   its own `guide`, `recipe`, `watch`, `covered_workflows` and `introduction`.
   Select these with `--feature <feature-id> --guide <guide-id>`; the checker and
   ledger track every lesson independently.
4. Capture to `docs/guides/<stable-id>/`, preserve/replay the complete construction,
   review images, record UX findings and add a reader link to this library.
5. Run the checker and the focused documentation-tool tests. Review the diff,
   especially screenshots, scope, dates and dependency additions/removals.

The catalog includes every current main feature and subfeature from `FEATURES.md`.
It does not assert that this inventory exhausts every menu item or context-menu
variant. Reconcile it during UX review. Experimental CPD work remains blocked
pending a specifically authorized session. Simulation guides must not launch
production calculations without explicit authorization.

## UX review

Track discoverability, prerequisites, selection/gesture friction, obstructed
targets, preview clarity, success feedback, cancel/undo and actionable errors.
Record any workaround used by the recipe. A successful scripted path must not
hide a usability defect. UX findings stay open until the corresponding behavior
is fixed and exercised; regenerating screenshots does not close them.

## Storage and implementation

Commit only readable Markdown, the latest compact PNG set, the verified example,
and portable JSON manifests. Relative links make this work on online Git viewers.
Keep the browser version at `docs/guides/extrude.html`, referencing the existing
images rather than duplicating them. Avoid raw traces, video, logs, caches and
timestamped copies. Keep the image count and total download size under review as coverage grows.

Reusable code is kept in established source locations:

- `frontend/guides/`: UI recipes and capture helper.
- `frontend/playwright.guides.config.js`: isolated browser/server configuration.
- `scripts/generate_feature_guide.py`: capture, verification and publication.
- `scripts/feature_guides.py`: catalog, fingerprints, rendering and checks.
- `scripts/check_feature_guides.py`: read-only check CLI and explicit table refresh.
- `tests/test_feature_guides.py`: freshness, integrity and replacement regressions.

Before every browser run, inventory persistent writes: the only retained output
is the selected guide directory and canonical ledger. Workspace files, project
histories, browser downloads/profiles, caches, credentials and Playwright output
live beneath the printed owned scratch root. `finally` stops owned processes and
deletes that root and failed staging; verify absence after the run. A replacement
backup is removed after promotion or restored after failure. Abrupt power loss or
SIGKILL requires review of the printed scratch root and hidden staging/backup
directories; never delete unrelated directories on a prefix alone.

The storage preflight honors `NADOC_TEST_SCRATCH_ROOT` and
`NADOC_TEST_SCRATCH_MOUNT`. Resource guards serialize browser work. No CI job,
hook, schedule, commit or remote publication is installed by this tooling.

## Refresh the browser version

After accepting an Extrude capture, render its captions and images as static HTML:

```sh
python3 -m scripts.render_feature_guide_html
python3 -m scripts.render_feature_guide_html --check
```

This presentation-only export leaves the capture baseline and verified design
unchanged. Its separate `--check` detects HTML drift after a capture or renderer
change; run it alongside the guide freshness check. Open `extrude.html` directly
in a browser. There are no remote fonts, scripts, fetch requests or server
requirements. Keep the entire guide directory when downloading for offline use.

Render the offline browser versions with `python3 -m scripts.render_feature_guide_html`
and `python3 -m scripts.render_feature_guide_html --guide bend`. Add `--check` to
verify each export. Bend is registered under the existing Bend and Twist feature;
Bend and Twist have separate lessons, dates and freshness checks under that entry.
Use `--guide twist` to render or check the Twist browser version.

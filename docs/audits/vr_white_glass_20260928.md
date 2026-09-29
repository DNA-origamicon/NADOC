# White frosted VR menus and button tints — 2026-09-28

The shared native glass compositor now uses a near-white tint with dark neutral
lettering. Scene content remains blurred separately for each eye. Sidebar buttons
and detailed-menu controls have subtle colored interiors. Visualization tool hues
follow the desktop `.vt-btn` palette; success/destructive actions use the desktop
green/red tokens. Other controls receive a stable fallback accent. Disabled fills
are fainter, and selected sidebar controls retain blue styling. The view-tools
atlas uses the corresponding per-tool desktop hues as well.

Evidence is retained in `.development-artifacts/vr-white-glass/`. The first
`initial` capture exposed the old panel's blue tint affecting the white-glass
composite and failed the independent blur comparison. The shader now limits tint
extraction to control fills, leaving the panel substrate neutral. This failure
was retained; blur thresholds and controller motion profiles were not relaxed.
The text oracle now requires dark lettering rather than pale lettering, with a
blank white image as a negative case. The independent blur model uses the new
white substrate and opacity; opaque and unblurred alternatives must still fail.

Physical through-lens readability and comfort remain pending. The floor and
calibrated SteamVR boundary are unchanged.

The `initial-02` attempt stopped before clicking because the released grip was
exactly in the menu plane, making the approach side ambiguous. The tour now moves
the released controller to a headward observation point before measured navigation.
`profiles` exposed a measurement issue: the neutral-glass blur oracle included
new colored button interiors. It now excludes projected control rectangles when
measuring the neutral substrate; control text is tested separately. Blur thresholds
are unchanged. The first corrected eye measurements have approximately 0.26 / 255
mean blur error, versus 4.51 / 255 for unblurred transparency at scene edges.

The first two all-tab attempts exposed a faint inactive simulation scrollbar in
the light theme. Its source fill was raised to neutral mid-gray, producing a
clearer dark thumb after the glass compositor. The text oracle retains its
separate, stricter dark-thumb criterion. These attempts remain in `all-tabs` and
`all-tabs-02`.

The tablet regression uses the existing isolated browser/native tour with
`NADOC_VR_VIEW_START=8`: equip with all eleven tiles visible, then the layout-related
toggles and stow. It is a visual styling regression, not an exhaustive retest of
all visualization actions. Its pixel oracle now checks colored pastel interiors,
excluding neutral white panels, dark text and the saturated cyan floor outline.

Playwright artifact inventory before this run: the tour owns a temporary
`/tmp/nadoc-ligation-tour-*` workspace removed by `TemporaryDirectory` on success
or failure; fixture names use `__e2e__`. Session cache is disabled. Native viewer
shutdown is in `afterEach`; backend/frontend processes are Playwright-owned.
`frontend/test-results` and `frontend/playwright-report` are removed by the final
cleanup reporter. Retained screenshots/probes go only to the requested artifact
output directory, including native capture files managed by the existing probe.

Additional test artifacts: Vite bridge credentials live at
`/tmp/nadoc-viewer-test-<root-hash>-<port>.json`. Their pre-run filenames were
recorded, and the server-close hook removes owned credentials; the post-run check
will verify no additional file remains. Existing credentials are preserved.

Full frontend suite: 568 files passed, 7,223 tests passed, one skipped.
Five focused native tests passed (sidebar controls/grips, live inspector,
OpenGL object IDs, simulation panel). Changed Python checks pass Ruff.

## Superseded by the user's transparency correction

The user found the white version too opaque. Final styling reduces the white
substrate from 78% to **10%**, with 90% blurred scene, reduces native button fills
to 4.5% accents (2% disabled; 10% selected), and reduces tint amplification.
Light foreground lettering returns for contrast over the nearly transparent veil.
The tablet now reads the actual desktop computed background, border and icon
colors, rather than the approximate pastel palette. Cloned desktop SVGs retain
their explicit color values and gradient definitions; `currentColor` is resolved
from the desktop button. Source RGB values are no longer inverted/remapped.

Final evidence root: `.development-artifacts/vr-clear-glass/`. Its `initial`
steady-fast run passes stereo glass/text/boundary and desktop correspondence
checks. The mirror capture was visually inspected: the model and floor are
clearly visible through the faint surface, with subtle button color and sharp text.
The previous white version's `all-tabs-03` passed 13 page checks and detailed-menu
actions but failed its final desktop-mirror comparison (1.85% match). This is
retained as a failed transport check; the final clear-glass initial desktop check
passes. The previous white tablet regression passed; its temporary workspace,
project revisions, default Playwright outputs and stale owned bridge credential
were cleaned and verified absent.

Final clear-glass validation:

- `vr-clear-glass/profiles/result.json`: all four motion profiles pass, including
  stereo blur/text checks, calibrated floor edges and actual desktop correspondence.
- `vr-clear-glass/tablet`: isolated tablet regression passes (equip, Deform,
  Unfold/Cadnano layout transitions and stow); offscreen/stowed negatives pass.
  The actual mirror image was visually inspected.
- `desktop-icon-rgb.json`: heatmap icon source colors `(59,130,246)`,
  `(168,85,247)`, `(239,68,68)` each match more than 110 rendered pixels per eye,
  within 3 channel levels. This confirms the desktop's multicolor values survive
  the compositor, rather than being replaced by an approximate pastel.
- Five native regression tests pass on the final build. The final frontend run
  passes 7,223 tests across 568 files, with one skipped. Ruff and diff checks pass.
- `cleanup.json`: temporary tablet workspace and default Playwright outputs are
  absent; the one stale owned Vite bridge credential was removed. The user's
  existing credentials were retained.

Worn-headset comfort is still not established by these stereo captures.

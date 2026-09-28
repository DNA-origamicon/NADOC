# VR sidebar UI audit — 2026-09-27

Implemented independent left/right controller sidebars with desktop tab ordering,
vertical labels, dark colors and blue selected tabs. Added Tools on the right and
retained the right-trackpad shortcut. Unsupported controls are gray and inert.
The generated inventory contains 851 control/option rows across 12 tabs and 113
pages. Static controls are extracted from the desktop DOM after right-tab wiring;
dynamic widgets have source-linked control templates, including Assembly parts,
groups, mates, gears and belts. Source hashes detect inventory drift.

Review command: `just vr-menu-tour`. Full validation command:
`just vr-menu-tour --validate --hold 0 --exit`.
See [usage and mapping](../vr_sidebar_menus.md).

## Iterations

- Exhaustive native layout tests exposed concatenated select-option labels and a
  duplicate overhang control. The catalog extraction now separates option labels
  and removes duplicate dynamic rows.
- Initial live steady-fast and imprecise variable-fast passes opened all tabs.
  Rendered inspection exposed icon-only labels and missing font glyphs; the VR
  mapping now uses the desktop tooltip for icon buttons and supports ASCII glyphs.
- Full scrolling exposed a short axis label with insufficient visible text. It
  now includes its section context. The pixel visibility threshold was retained.
- Source review found dynamically constructed Assembly controls absent from the
  DOM extraction. Added their disabled templates before final validation.
- Enlarged and raised only the owned viewer window for desktop observation. No
  monitor configuration or physical head tracking was altered.

Failed/partial runs are retained under `.development-artifacts/vr-sidebar/`,
including `variable-iteration2`, `final-validation`, and `full-iteration2`.
The latter was deliberately interrupted to expand the catalog.

## Checks and limits

The native suite passes 37 tests, including exhaustive row reachability, layout,
scroll bounds, independent menu state and disabled dispatch. Eight focused Python
tests cover pixel-oracle negative cases and authoring navigation. Ruff and catalog
drift checks pass.

Live validation uses the real SteamVR/OpenXR viewer and ScryWrite input bridge,
with an isolated empty fixture. Every page checks exported IDs, disabled state,
layout and physical target size, plus stereo pixels for visible text, gray disabled
controls and blue active controls. Disabled first-page controls are also clicked.
All four existing motion profiles run unchanged, with stable-hover acquisition,
no endpoint snapping, bounded retries and the existing 150 ms playback-lag limit.
The scripted reaches approach within 30 cm of the target panel; results do not
establish arbitrary-distance acquisition or physical headset comfort.

The inventory maps available UI controls; it does not populate user-specific
jobs, configurations, plates or annotations, or implement their disabled actions.
Representation/color controls retain the desktop-owned request/acknowledgement
path. The isolated tour does not claim backend simulation or geometry validation.

Final evidence directory:
[final-expanded](../../.development-artifacts/vr-sidebar/final-expanded/).
A representative [Assembly stereo capture](../../.development-artifacts/vr-sidebar/final-expanded/variable_fast/right-assembly-24/left.png)
shows wrapped labels, vertical tabs and disabled styling. Each preset's
`trials.json` retains unsuccessful reaches as well as successful retries.

## Final full-tour results

All four presets passed 113 pages / 851 controls each (452 page captures total).

| Preset | Reach attempts | Retries | Result |
| --- | ---: | ---: | --- |
| steady_deliberate | 225 | 0 | Passed |
| steady_fast | 124 | 0 | Passed |
| variable_deliberate | 266 | 41 | Passed |
| variable_fast | 268 | 43 | Passed |

The imprecise presets needed retries; every target was acquired by the second
attempt. No threshold or preset changes were made. Maximum measured playback lag
was 46 ms, below the existing 150 ms limit. The final actual X11 client image
matched 100% of tested mirror feature pixels (95% required, with the existing
32-level color and one-pixel registration tolerances). Detailed Options, Tools
and Inspect entry checks passed while preserving the left sidebar.

The first shortcut capture activated the radial menu but framed it poorly after
the last noisy reach. A separate observation pass places the simulated hand above
the columns, outside measured reaches. [Final shortcut evidence](../../.development-artifacts/vr-sidebar/final-shortcut/right-trackpad-shortcut/left.png)
shows the retained radial menu; both eyes pass a cyan-menu pixel check and the
right input owner is `radial`. The additional variable-fast tab preview, detailed
menu checks and actual desktop check all passed. This adjustment changes only
the review pose, not production placement or motion profiles. Owned viewers and
temporary sockets were removed after both final runs; retained artifacts are
confined to `.development-artifacts/vr-sidebar/`.

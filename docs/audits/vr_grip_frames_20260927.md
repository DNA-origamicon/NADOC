# Visible, accessible menu grip frames

Sidebars now reserve wide outer rails with four textured corner handles, side
notches and a readable grip/status hint. The 40 mm local rail is about 26 mm wide
at the initial sidebar scale. Contents retain their prior bounds and hit targets;
the outer surface grows to include the frame. Ready/moving/resizing states use
blue/amber/green plus explicit status text. Move and resize acquisition also
pulse the appropriate controllers. Detailed tool and lattice panels share the
outlined corner/rail treatment.

The existing physical near-grip contract remains: a controller within 75 mm of a
border can grab it; one grip repositions and rotates, a second grip at another
edge resizes uniformly. A held grip retains ownership. Close or overlapping
sidebars now resolve by nearest border instead of array order. Acquisition also
suppresses model manipulation until grips release, including after one hand
releases a resize. Frame state, proximity, edge targets, position and scale are
exported through ScryWrite for inspection.

Validation:

- Native CTest 38/38 passed, including new nearest-border, ownership, movement,
  second-grip resize, release, invalid tracking, interior rejection and frame bounds.
  Existing expanded/collapsed layout checks still cover every mapped menu entry.
- Focused frame-pixel oracle test passed: blank, wrong-state and offscreen frames
  are rejected despite successful application metadata.
- Initial physical-runtime `steady_fast` move/resize test passed. A resizing mirror
  capture was visually inspected. It exposed avoidable panel overlap caused by
  the diagnostic movement using world X instead of the observed panel's right/up
  directions; the final diagnostic derives its outward movement from runtime
  frame geometry. Production behavior and motion presets were unchanged.
- All four unchanged motion presets passed both menus' grip/move/resize/release
  checks, confirming that the other menu and model transform remain unchanged.
  Final ready/moving/resizing captures matched every sampled frame point in both
  eyes (48 eye/state checks), and final actual X11 desktop agreement was 100%.

Evidence: `.development-artifacts/vr-grip-frame/steady-fast` and
`.development-artifacts/vr-grip-frame/validated`. Run
`just vr-menu-tour --grip-checks --validate` for the live review. Physical reach
comfort, through-lens legibility and haptic preference remain human review items;
synthetic profiles are not measurements of human accessibility.

The final `steady_fast` menu regression also passed card collapse/expand, pointer
and touchpad selection, scrollbar navigation, focus handoff, detailed Tools and
shortcut checks, with 100% desktop agreement. Evidence:
`.development-artifacts/vr-grip-frame/menu-regression`. All owned viewers and
temporary sockets were cleaned up; the disposable build log was removed.

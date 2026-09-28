# Rounded VR sidebar controls and scrollbars

Sidebar buttons now use rounded fills, outlines and focus rings. Colors follow
`frontend/src/styles/tokens.css`: dark surfaces, muted strong borders, a slight
blue accent on enabled actions and a subtle danger tint on Close. Unsupported
controls remain neutral gray. Hit rectangles remain forgiving at rounded corners.
Detailed legacy panels retain their existing button geometry.

Each sidebar has one vertical scrollbar instead of the two scroll buttons. Its
thumb indicates the visible fraction and position, with a minimum visible size.
Short tabs show a disabled full-height thumb. Pointing and holding the trigger
positions the thumb along the rail. In touchpad focus mode, up/down on the rail
pages content and keeps rail focus; left/right exits to the adjacent row/footer.
Center-click and deliberate steady aim retain the existing pointer handoff.
An in-panel hint explains the changed directions when the rail is focused.

The catalog tour and focus workflow now use the scrollbar. Pixel checks require
a visible thumb rather than a nonexistent scrollbar text label; blank controls
still fail. Control text wraps and fits the narrower content width without
truncation or lowering the native minimum text size.

Validation:

- Native CTest: 37/37 passed, including every catalog control/page, rounded
  silhouettes within their bounds, thumb containment, scroll bounds and focus exit.
- Focused pixel tests: 4/4 passed, including missing-thumb and disabled-thumb cases.
- Physical-runtime ScryWrite focus checks: all four controller profiles passed,
  including both rails' pointer selection and bidirectional touchpad scrolling.
  Pointer acquisition includes normal bounded retries: steady_fast used one
  extra rail reach; steady_deliberate none; variable_fast three;
  variable_deliberate two. The separate dwell-handoff trial used one retry each.
- Final actual X11 desktop comparison: 100% agreement. The initial desktop capture
  was visually inspected for the rounded borders, gray controls and visible thumbs.

Evidence is retained under `.development-artifacts/vr-scrollbar/steady-fast` and
`.development-artifacts/vr-scrollbar/validated`. These checks establish rendered
stereo and desktop behavior, not through-lens legibility or physical comfort.

The full `steady_fast` catalog tour also passed all 12 tabs / 113 pages / 851
controls, including stereo text/disabled/thumb pixel checks, with 100% final
desktop agreement. Evidence: `.development-artifacts/vr-scrollbar/full-catalog`.
All owned test viewers and temporary sockets were cleaned up.

Follow-up: the left rail now sits left of its content; row bounds are reflected
so both panels mirror one another. The existing 851-control layout test passed.
All four physical-runtime focus/controller profiles passed, and the native mirror
was visually inspected to confirm placement. Evidence:
`.development-artifacts/vr-scrollbar/mirrored`. The separate final X11 desktop
comparison failed (2.38% agreement across all nine samples); this run does not
establish desktop delivery. The failed evidence is retained without saving
potentially obscuring applications. The owned viewer and socket were cleaned up.

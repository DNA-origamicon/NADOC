# Archived native simulation-jobs menu

Archived on 2026-08-20 while NADOC establishes basic hybrid display support.

The native `Jobs` tablet page (sometimes visually read as `OBS` on the low-resolution
stroke font) exposed read-only job identity, status, and progress. It did not activate
desktop visualizations or mutate the VR model, so its entry point was removed from the
active options menu. The parser and dormant page implementation remain temporarily in
`src/jobs.hpp` and `src/main.cpp` to preserve the already-tested transport while the
desktop-authoritative simulation workflow is evaluated.

The supported workflow is now:

1. Open NADOC's interactive Desktop tablet in VR.
2. Select MD Display, Flex Map, or another display mode in the normal desktop UI.
3. The browser publishes the active per-base positions and scalar colors through the
   private visualization feed.
4. The native scene applies those updates without restarting the OpenXR session.

Do not restore the native Jobs menu until its controls have a defined, tested action
contract beyond read-only status display.

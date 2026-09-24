# Mobile shared viewer implementation — 2026-09-24

Scope: the standalone prepared/shared viewer on touch devices. The editor is unchanged.

## Delivered

- Coarse-pointer devices use Orbit navigation: one finger rotates, two fingers pan, pinch zooms. Center arms a single tap on the design to choose the rotation center; drags and multi-touch gestures do not trigger it. Loading snapshots, Reset, presenter camera updates, and view-cube navigation retain Orbit even when the presenter uses Multiscale or Trackball.
- Sign-in remains usable in portrait, with 16px fields and 44px buttons. After successful sign-in and scene loading, portrait users get a dismissible landscape prompt. The landscape button requests fullscreen/orientation lock when available; unsupported/denied requests explain physical rotation. Browser restrictions mean rotation cannot be guaranteed automatically.
- Dynamic viewport height, safe-area padding, compact header, horizontally scrollable meeting/trajectory controls, and Help for detailed status. No forced CSS rotation or disabled browser page zoom.
- Mobile renderer caps device pixel ratio at 1, retains antialiasing/stencil for existing representations, and skips its render loop while hidden. Representation geometry and independent view volumes remain exactly as published.
- Returning to the foreground reconnects the presentation stream, allowing the server's current revision to catch the viewer up. Existing scene-update handling preserves the guest camera.
- Graphics context loss displays a recovery message, removed on restoration. Recovery depends on browser resources; the message directs persistent failures to reload the invitation.

## Verification

- Chromium phone emulation (390×844, then 844×390, touch enabled, DPR 3): incorrect/correct password, prompt only after login, landscape canvas space with meeting toolbar, no horizontal page overflow, one-finger rotate, actual two-finger pinch/pan and tap-to-center through CDP touch input, renderer DPR cap, presenter Multiscale pose retaining Orbit, and Help. Passed, no page errors. Meeting transport/package fixture stays in memory.
- Focused viewer tests: 24 passed, including orientation rejection, context-loss status, foreground reconnection and listener cleanup, hidden render suppression, and mobile navigation policy.
- Full frontend run: 6,882 passed, 1 skipped; existing quantum_dot_dialog.test.js suite still fails to import backend/data/quantum_dots/hecz-450.png?inline (Vite denied ID).
- App smoke suite: 23 passed; test workspace files and project revision stores cleaned by teardown.
- Production build and lint passed. Main.js LOC delta: 0.

## Hardware acceptance still needed

Open a fresh shared invite on iPhone Safari and Android Chrome. Enter display name/password in portrait; rotate to landscape. Try rotate/pinch/pan, Reset, Follow presenter and then drag to leave Follow. Have the presenter switch representations, add an overhang, resize an end and extrude while the phone explores independently. Background the browser, make another presenter edit, then return and check catch-up. Repeat with a view volume and multi-overlay.

This work does not establish phone memory limits, thermal performance, frame-rate targets, or large fine/oxDNA scene capacity. It does not convert a heavy published package into a simpler representation on the guest. Physical device testing remains pending.

## First phone feedback and idle-sharing fix

User reported smooth Orbit in Android Chrome and confirmed Samsung Internet eventually opened the invitation. They also reported a recurring “Loading visualization” popup with the presenter idle.

The publisher's scene fingerprint used material/buffer GPU upload counters as change signals. Those counters can advance for identical rendered data. Fingerprints now ignore material upload versions and use cached content signatures for vertex, instance, color, interleaved and index buffers. Actual changes still invalidate the shared scene; redundant uploads no longer trigger exports. Content signatures are non-cryptographic change detection only; package integrity continues to use SHA-256.

Verification: real editor/guest browser regression holds an idle presenter across several publication polls, then checks overhang creation, resize, extrusion and overlay edits. Passed along with the mobile touch test. Full frontend run: 6,886 passed, 1 skipped, same existing quantum-dot PNG import suite failure. Phone confirmation of the idle-popup fix remains pending.

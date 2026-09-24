# Live investigation: P2 Alpine / 3x6SQ_norm_skips

The active Windows host advertised `live-timeline-v1` but neither
`live-large-frames-v1` nor `live-unlimited-frames-v1`. Its cached viewer assets did
not contain `data-frame-buffering`. compy5000 was connected to this old host.
The publisher therefore still chose the legacy raw-frame limit, rejecting large
ball-and-stick updates before any newer frame could be announced to guests.
Rebuilding the repository did not replace the detached host's cached assets/modules.
The previous server-lifecycle hook removed rooms but left that process running.

Changes:

- Editor-server startup/shutdown stops the detached host, including cached code.
- Host status reports a build identity covering cached viewer entry/assets references
  and sharing runtime source. Starting hosting checks the current build and protocol,
  serializes replacement, waits for old listeners to stop, and launches the current host.
- The editor reports an outdated host and refuses trajectory publication through the
  legacy protocol, rather than silently selecting the old size limit.
- If host replacement invalidates an existing selected invitation, publication creates
  a fresh invitation instead of attempting to update the vanished room.

The old host was stopped and the updated Windows host was launched. Publicly served
viewer assets were verified to include the buffering UI. The local status reports
`live-unlimited-frames-v1` and a matching build identity.

## Validation

Regression tests cover stale build replacement (including concurrent start requests),
server lifecycle, refusal of the legacy trajectory host, and fresh-invitation fallback.
The frontend production build passes.

A temporary verification presentation used the completed production job's real DCD
frames 1 and 34, with 149,666 heavy atoms and 167,851 bonds. Frame 34's render packet
was 29,558,232 bytes raw and 8,035,627 bytes compressed. It was published through the
local editor middleware and Windows bridge to the actual internet sharing host.
A browser joined through the public Tailscale URL, received frame 1, showed Buffering
while a delayed frame-34 download was pending, advanced to frame 34 only after full
application, and cleared Buffering. The diagnostic invitation was then deleted.

The full-scene screenshot attempt exceeded the software-rasterizer test budget.
The completed transport/UI test suppressed large instanced GPU draw calls in the
headless browser only; it still decoded/applied all atom and bond buffers. This is
not a compy5000 GPU/FPS benchmark. Earlier measured-data tests verify guest matrices
against the source. No simulation/job data was changed.

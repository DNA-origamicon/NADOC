# Trajectory sharing feasibility — 2026-09-21

Assessment only: no viewer/host behavior changed, no live meeting restarted, no
simulation launched. WAN throughput and guest GPU playback have not been measured.

## Conclusion and proposed targets

Recorded trajectories can support independent guest orbiting through the existing
browser-only meeting flow. Prepare immutable trajectory chunks on the host, buffer
ahead on guests, and synchronize a playback clock. Do not send replacement scenes
for every trajectory frame. Target 30 render FPS initially, with 60 as a later
hardware-dependent target. First match the editor's existing 8 trajectory steps/s;
then test 15 and 30 steps/s independently of rendering. These are proposed targets,
not achieved internet rates. Smooth orbiting does not imply smooth molecular motion
when coordinates advance only eight times a second.

## Current implementation constraints

- `editor_broadcast.js` samples visual fingerprints once a second, waits for changes
  to settle, and allows full scene export no more often than every three seconds.
  Continuously changing trajectories may never settle. There is no supported
  shared-trajectory playback rate today.
- `prepared_scene.js` exports a visible scene; the standalone viewer has no
  topology-bound time-series adapter. Scene revisions rebuild GPU resources.
- `prepared_share_transport.js` spawns a Windows Node subprocess per management
  request on WSL. Keep this path for bounded control operations; do not put every
  trajectory frame through it.
- `prepared_view_host.mjs` stores up to 512 MiB of snapshots in memory. Trajectory
  chunks need a separate bounded, authenticated, disk-backed serving path.
- `oxdna_trajectory_player.js`, used by `md_jobs_panel.js`, defaults to 8 steps/s.
  Existing exact-frame paging, binary formats and cache cancellation can be reused.

## Read-only cube_pore inventory

Job `796c568b5690`, frozen `design.json`, PSF and
`output/cube_pore_01_production_100ns_k0.dcd` in its package:

- DCD: 20,282,697,580 bytes; 1,046 complete fixed-record frames;
  1,615,887 atoms; 19,390,724 bytes/record.
- Header saved-frame interval approximately 20 ps. The filename's "100ns" is not
  evidence of 100 ns of recorded content or physical convergence.
- DNA: 3,878 residues, 79,320 heavy atoms.
- Graphene: 24,618 carbon atoms.
- Ions: 1,327 Na, 1,328 Cl, 1,918 Mg = 4,573. Hexahydrated Mg's waters are not ions.
- Ordinary TIP3 water: 476,335 molecules; Mg contributes another 11,508 waters.
- One extracted Full frame verified shape `(3878, 12)`; the existing NTRJ
  transport packs these measured positions/orientations as float32.

Calculated coordinate payloads (decimal MB/Mbps; no compression, metadata, initial
geometry, protocol overhead or retransmission included):

| Channels | Bytes/frame | Mbps/guest at 8 steps/s | Mbps/guest at 30 steps/s | Host Mbps for 3 guests at 30 steps/s |
| --- | ---: | ---: | ---: | ---: |
| Full DNA, 12 float32 values/residue | 186,144 | 11.9 | 44.7 | 134.0 |
| Full DNA + all ions + graphene coordinates + cell | 536,532 | 34.3 | 128.8 | 386.3 |
| DNA heavy atoms, existing float64 compact coordinate format | 1,903,680 | 121.8 | 456.9 | 1,370.6 |
| Entire system positions, float32 | 19,390,644 | 1,241.0 | 4,653.8 | 13,961.3 |

Rows are alternatives, not additive. The Full row excludes water; it does not
silently remove any ions. Graphene is budgeted as moving unless its immobility is
verified. Atomistic float64 reflects the existing aligned-coordinate wire contract;
switching its precision would require a separate explicit fidelity decision.

Formula: `Mbps = bytes/frame * trajectory steps/second * 8 / 1e6`.
Three independently served guests multiply host traffic by three. The Full +
companions coordinate stream alone totals 561.2 MB for this interval, exceeding
the current 512 MiB snapshot budget. A 60-frame clip is 32.2 MB per guest and can
play repeatedly from cache. Buffering absorbs jitter but cannot sustain an
unbounded stream whose average consumption exceeds delivery.

## Bounded extraction measurement

Used existing `scripts/benchmark_md_playback.py --job 796c568b5690 --frames 160
--stride 10`: 16 sampled frames (0,10,...150), advisory cold eviction OFF, BLAS
limited to one thread, AMD Ryzen 5 3600 under WSL. A private temporary playback
cache was removed in `TemporaryDirectory` cleanup; no user job files were changed.

| Operation | Total seconds / 16 frames | Mean ms/frame |
| --- | ---: | ---: |
| Context setup | 1.7201 | — |
| DNA prefix reads | 0.0549 | 3.43 |
| Aligned DNA heavy-atom positions | 0.2273 | 14.21 |
| Full measured bases | 0.3332 | 20.82 |

This short, sequential, cache-affected sample excludes solvent/graphene preparation,
serialization, transfer, browser application, rendering and host contention. It
supports preparing once and reusing results; it is not a 48 FPS viewer result or a
sustained extraction capacity certification.

## Transport and browser barriers

[Tailscale Funnel documentation](https://tailscale.com/docs/features/tailscale-funnel)
states that traffic has non-configurable bandwidth limits, without specifying a
numeric guaranteed rate. Measure the actual public route with one and three guests;
local/LAN rates cannot certify it. Host upload, guest download and relay throughput
all constrain delivery. Retain the current tunnel initially; an alternative relay
would only be justified by measured failure to meet acceptance targets.

Guest GPUs, scene complexity, dynamic buffer uploads, allocation/garbage collection
and frame preparation can still cause stalls after all data is downloaded. Update
existing geometry in place, decode off the main thread where beneficial, and keep
bounded buffers. Do not assume a modest laptop matches the RTX 2080 SUPER's earlier
static Voltron numbers.

For literal hidden/background tabs, browsers commonly suspend animation callbacks
([MDN requestAnimationFrame](https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame)).
Resume from the shared clock when visible. Timeline progression must not depend on
the presenter editor's render callbacks, allowing the presenter to inspect another
tab while the background host continues serving the prepared clip. Pausing editorial
broadcast and pausing a shared trajectory should be explicit, separate actions.

Preserve model/serial identity, simulation timestamps, units, cell, alignment and
periodic imaging across DNA, graphene, ions and water. Start with exact recorded
frames. Any optional interpolation must be labeled and handle periodic crossings;
it must not invent transport events or feed scientific measurements.

## Next implementation and acceptance slice

1. Package one frozen cube_pore frame interval with topology/content hashes, static
   render assets and exact Full/ion/graphene/cell chunks. Keep water an explicit
   channel and defer atomistic expansion until this slice passes.
2. Add authenticated chunk delivery, bounded cache, cancellation, preparation and
   buffering status, and in-place guest updates. Keep name/password/link behavior.
3. Share small play/pause/seek/speed/timestamp messages; independent guest cameras
   remain available, and timeline following is separate from camera following.
   Slow guests buffer/resync with visible status rather than accumulate a queue.
4. Measure A/B on identical content/hardware: editor, fully buffered standalone,
   then public-link playback with one and three guests. Exercise seeks, pause,
   reconnect, presenter away/return and visibility changes. Test 8/15/30 steps/s.
5. Extend copyable metrics with actual applied steps/s, render p50/p95/p99, stalls
   and their duration, startup/seek latency, bytes/s, buffered seconds, clock skew,
   decode/apply times, memory and topology/frame identity. Compare equivalent
   representations; no silent scientific omissions or precision reduction.

Retain the original plan's regression gates (including repeatable p95 regressions
exceeding both 10% and 1 ms) and separately test the proposed 30 render FPS target.
Local tests and simulated latency are useful controls; a visible browser on another
internet connection is required before claiming a smooth remote experience.

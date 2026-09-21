# Standalone viewer and presentations: phased development plan

Status (2026-09-20): checkpoint `302d50f6` is committed and pushed. Prepared
static snapshots, standalone viewing, and temporary password-protected public HTTPS
sharing are implemented. The transport milestone was brought forward from Phase 4.
Camera-only presenter Jump/Follow is now implemented and locally browser-tested.
The user approved the browser-only remote guest experience. Scientific-selection,
representation/assembly parity and recorded-playback milestones remain open.

The earlier controlled RTX 2080 SUPER A/B (42.34/42.78 median FPS; 26.0/26.6 ms p95)
covered decoder extraction only. It does not certify the prepared viewer, room
traffic, large assemblies or trajectories. See [production comparison](audits/viewer_ab_production_20260920/README.md),
[prepared viewer](prepared_viewer.md), and [public HTTPS validation](audits/internet_viewer_20260920/README.md).

Development branch: `feature/standalone-viewer-presentations`.
Baseline commit: `cce80858ff528a2648cba3f18351685f75dc673c` (master at branch creation).
Existing uncommitted test and experiment changes are unrelated and must not be
included in feature commits. A branch does not isolate processes or uncommitted
files; automated performance runs use separate worktrees, ports, and scratch data.

## Intended result

- One reusable viewer inside NADOC, in a standalone browser page, and in a live
  presentation. Preserve current navigation behavior and scientific selection IDs.
- Guests open an HTTPS link, enter a display name, and explore without installing
  NADOC, Python, Node, extensions, or a VPN. Browser asset/data transfer is expected.
- Presenter highlights are distinct from guest selection. Guest camera ownership
  and follow behavior follow the decision below.
- Large parts and assemblies retain comparable performance on the same hardware.
- Presentation capabilities remain separate from design editing, filesystem access,
  simulation controls, and trusted workspace peer credentials.

## Accepted scope (2026-09-20)

Current framework: a background helper on the personal/office PC owns an
expiring prepared-viewer listener and a Tailscale Funnel HTTPS route. Guests on
unrelated networks enter a display name and meeting password in an ordinary
browser, without installing software, signing into a provider, or changing network
settings. Setup/account approval belongs only on the host. LAN HTTP remains an
optional manual path, not the default guest experience.

1. Prepared viewer packages first; raw legacy designs without Python and browser
   scientific geometry generation are deferred.
2. Presenter selection supplies shared highlights. Guests opt into jump/follow;
   their independent selection and camera stay separate from presenter attention.
3. Full representation is the first priority. Atomistic is second, and reviewing
   actual simulation data together is required staged functionality. Preserve
   physical display overrides and trajectory topology identity. Include prepared
   recorded frames with bounded buffering and shared presenter playback state;
   guests keep independent orbiting. Other recommended capabilities stay on the
   roadmap, subject to parity inventory. Guest devices do not run simulations.
4. HTTPS invite link plus generated password and display name; host-controlled meeting lifetime. Stop hosting
   invalidates credentials and stops serving packages/frames. Already-downloaded
   data may remain on a guest device; expiry cannot revoke that copy.
5. Host only from a personal or office PC. No permanent cloud application or data
   host. Target four total participants initially, including presenter. Mobile is
   separate. Start/Stop presentation owns the public listener and any tunnel.
   Restart must not silently resume public sessions or restore credentials.

Selected: `workspace/VoltronCoreArmV2.nadoc` for large Full/protein/nanoparticle
viewing and `workspace/cube_pore.nadoc` for graphene/ion-transport trajectories.
See `viewer_dependency_inventory.md` for hashes and available completed jobs.
A large assembly fixture and recorded-playback captures remain outstanding. Bundled
examples validate software but cannot substitute for those performance results.
Public transport is implemented with Tailscale Funnel on HTTPS port 443, proxying only
the guest loopback listener on port 5183. Local host management uses a separate listener on port 5184
and file-only credentials. Existing private editor routes are preserved; no router
forwarding or incoming Node firewall exception is required. The managed relay is
third-party infrastructure, not persistent NADOC cloud application/data hosting.
Guests never need Tailscale. Host shutdown/expiry revokes sessions and stops its
owned tunnel; a downloaded snapshot cannot be retracted.

## Execution order after the HTTPS checkpoint

| Milestone | Status / exit evidence |
| --- | --- |
|0: Baseline and diagnostics | Done for static Voltron decoder extraction; assembly/trajectory fixtures still needed. |
|1/2A: Shared runtime and frozen packages | Prototype delivered; public Voltron loading and same-pose image parity verified. Full parity and hardware A/B remain gates. |
|4A: Temporary internet delivery | Implemented and externally exercised; HTTPS, password, hidden host, expiry, revoke, isolated management. |
|3A: Presenter perspectives | Implemented: separate presenter authority, snapshot-bound camera state, opt-in Jump/Follow, late join and reconnect. Browser/host evidence is in the [perspectives audit](audits/presenter_perspectives_20260920/README.md); real-GPU/WAN acceptance remains open. |
|2B/3B: Scientific selection and highlights | Stable base/domain/cluster/object and assembly-instance references; presenter selection highlights distinct from guest selection. Connect editor selection only when snapshot identity matches. |
|2C: Full/assembly parity | Shared-transform shader adapters, physical overlays, complete Full proteins/nanoparticles, unsupported-asset feedback and representation readiness. |
|3C: Recorded simulations | Prepared cube_pore frames, topology/content hashes, bounded buffering and coordinated playback; Full first, atomistic second. |
|4B: Acceptance | Four participants including presenter; Windows/macOS/Linux browser matrix, WAN transfer/reconnect and real-GPU A/B under presentation traffic. |
|5: Browser geometry generation | Deferred unless raw-design opening without preparation is requested. |

A milestone may ship independently, but no earlier open parity/performance gate is
implicitly passed by later connectivity work. Validate one coherent slice, retain
reviewable evidence, and checkpoint it separately.

## Architecture boundaries

`Design -> existing Python geometry -> versioned portable scene -> shared viewer`

The live editor and file/package loader supply the same scene contract through
adapters. Viewer core does not fetch arbitrary editor APIs or own document writes.
Room messages update attention/camera state without regenerating geometry.

Keep Python scientific geometry authoritative initially. Its existing pure compute
boundary in `backend/core/design_geometry.py` is a useful starting point. Do not
duplicate geometry mathematics in JavaScript as part of extracting the viewer.
Browser generation is a later decision, potentially using one shared engine.

Scene contract: schema/producer versions; units and coordinate conventions;
revision/content identity; typed geometry/connectivity; labels and selection
references; assembly instance identity and transforms; visual settings and camera
poses; optional representation assets. Preserve geometry reuse for repeated parts.
Keep topology, computed geometry, and physical display overrides distinguishable.
Unsupported representations must be reported, never silently shown incorrectly.

## Phase 0 — scope, baseline, and measurement contract

- Inventory renderer dependencies and API calls against the accepted scope.
- Select immutable copies of small, large, and stress fixtures, including repeated
  and heterogeneous assemblies. Record hashes, sizes, object counts, and poses.
- Preserve baseline source at the commit above; create reproducible build/run
  instructions and isolated A/B worktrees when implementation begins.
- Extend existing `frontend/src/perf/process_log.js` and `operation_timing.js`
  through a small dedicated benchmark module. Add equivalent instrumentation to
  the baseline without applying viewer refactors to it; record its patch hash.
- Establish measurement overhead and baseline run-to-run variance before tuning.

Exit: agreed scope, fixtures, copyable real baseline logs, and runnable A/B recipe.

## Phase 1 — extract the shared viewer with the existing data path

- Extract cohesive factories/modules for viewer state, scene lifecycle, controls,
  selection/highlighting, and rendering; composition roots get thin wiring only.
- Adapt existing editor responses to the scene boundary. Preserve event ordering,
  display overrides, instance transforms, navigation modes, and teardown behavior.
- Keep baseline A runnable; candidate B remains explicit/opt-in during development.
- Add meaningful behavior and lifecycle tests; check visual/selection parity on
  fixture references, not only screenshots or mesh counts.

Exit: editor behavior parity and A/B performance gate pass. No standalone package
or networking changes should be required to explain performance at this stage.

## Phase 2 — portable package and standalone local viewer

- Add validated, versioned package export/import with compact geometry data and
  instance reuse. Bound parser allocations and handle corrupt/unsupported input.
- Include metadata needed for base/domain/cluster inspection and optional assets
  for agreed representations. Avoid serializing the entire editor/job history.
- Add standalone entry point and file picker/drag-and-drop through ordinary browser
  file access. No dependency on a running Python service for prepared packages.
- Load a useful lightweight view first; prepare expensive assets on demand.
  Move expensive parsing/decompression off the UI thread where measured useful.
- Define offline delivery: cached application assets or a local application bundle;
  visiting a hosted viewer for the first time still requires network access.

Exit: standalone package opens with backend stopped; parity, teardown/memory, and
performance checks pass. Raw legacy designs require preparation. Optional omitted assets are clearly identified.

## Phase 3 — presentation rooms on isolated local infrastructure

- Create/end rooms; separate presenter authority from guest identity and permissions.
- Join by link/name; snapshot revision is fixed during a session initially.
- Start with server-sent state events over HTTPS and coalesced presenter POSTs.
  This fits four participants without adding a server WebSocket dependency. Keep
  the state contract transport-independent for future WSS if measurements justify it.
  Validate roles/messages server-side; rate-limit and coalesce transient updates.
- 3A uses a separate presenter invitation, available only in the local host UI.
  Presenter mode opens the same immutable snapshot as guests. Guest invitations
  cannot acquire presenter authority or post camera changes. Guests begin free;
  Jump is one-shot, Follow is opt-in, and direct camera input exits Follow.
- 3B adds semantic highlights after stable selection references exist. A spatial
  camera target is not a base/domain/cluster identity and must not be labeled as one.
- Implement agreed highlight/jump/follow behavior without camera feedback loops.
- Handle late join, reconnection, event ordering, host disconnect/rejoin, and expiry.
  Network loss must not prevent local orbiting of an already loaded scene.
- Bind callouts to both snapshot revision and assembly instance identity.

Exit: multiple independent browsers exercise the room; guests cannot edit designs
or send presenter actions. Measure rendering during highlight/camera traffic.

## Phase 4 — meeting-scoped local hosting and compatibility

- Build a dedicated local listener serving built viewer assets, room messages,
  prepared packages and recorded frames only. Editor and filesystem/job APIs stay
  unreachable from the public route. Start/Stop hosting owns this listener and
  any tunnel child process, revokes sessions on stop, and fails closed on restart.
- Supply HTTPS/WSS links, scoped access, revocation, deletion/expiry, and reconnect
  behavior. Public routes expose only presentation functions.
- Test current Chrome/Edge/Firefox on Windows, applicable Safari/Chrome/Firefox
  combinations on macOS, and Chrome/Firefox on Linux. Record actual versions.
- Detect WebGL 2 availability and offer useful errors and lower-detail settings.
  Treat mobile/touch support as a separately verified target if requested.
- Exercise download delays, interrupted transfer, weak devices, and realistic
  concurrency. Keep delivery timing distinct from rendering performance.

Exit: a fresh supported browser joins without installed NADOC dependencies; manual
user acceptance and hosted-load results are recorded before rollout.

## Phase 5 — optional browser geometry generation

Only pursue if opening raw designs without preparation is an accepted requirement.
Audit dependency/runtime cost; compare selective browser computation with a shared
engine usable from Python and WebAssembly. Verify geometry against canonical
fixtures, including loops/skips, deformations, overhangs, and assembly placement.
Measure startup, memory, and interaction responsiveness on modest hardware. Do not
replace the scientific engine on the strength of visual similarity alone.

## A/B performance protocol and manual workflow

Two comparisons are required:

1. **Renderer regression:** A baseline editor versus B refactored editor and B
   standalone using equivalent geometry, representation, resolution, and pose.
2. **Delivery experience:** local/hosted package loading and room joining, with
   network/cache conditions declared. Do not attribute WAN latency to the renderer.

Run production builds on the same device/browser, viewport, device pixel ratio,
quality settings, power mode, and foreground-tab state. Record refresh rate and
GPU metadata when available. Avoid background simulation contention. Alternate A/B
order, use one warmup and at least five measured repetitions per scenario, and
separate cold application/cache runs from warm runs. Declare cache reset procedure;
do not label a browser-cache reset as a cold OS filesystem cache. Never clear the
user's normal browser profile or mutate their active design to run benchmarks.

Required scenarios: open to useful view; open to requested representation ready;
fixed-duration orbit/pan/zoom; base/domain/cluster picking; representation switches;
assembly instance selection; repeated open/close; highlight and camera updates while
orbiting. Include recorded Full and atomistic trajectory scenarios in their phase.

Record:

- Download bytes and transfer, parse/decompress, scene construction, and GPU upload
  stages where measurable; precise readiness definitions per representation.
- Frame interval p50/p95/p99, worst interval, and slow-frame counts during a fixed
  scripted camera path. Average FPS is supplementary, not the sole metric.
- Picking and highlight latency; input-to-render timing labeled as a browser-side
  estimate, not physical input-to-photon measurement.
- Draw calls, triangles, rendered instances, and geometry/texture counts.
- Peak JS heap when supported, retained resource counts after repeated teardown,
  and memory measurement method. GPU counts are not GPU bytes; unsupported memory
  metrics are `null`, never invented or treated as zero.
- Errors, context loss, visibility changes, interrupted runs, and missing assets.
- For rooms: event delivery/apply timing with clock methodology recorded. Use RTT
  or synchronized clocks; do not subtract unsynchronized device timestamps.

Manual experience to implement:

1. Open isolated A or B build and load the same benchmark fixture.
2. Choose **Performance comparison**, confirm visible run settings, and start the
   repeatable camera/selection scenario or a separately labeled freeform capture.
3. Read a completed Process Log entry with human-readable timings and **Copy run
   metrics**. Provide selectable text/download fallback if clipboard is unavailable.
4. Paste A and B entries into the development conversation for analysis. No profiler
   installation or DevTools knowledge is required for the normal workflow.
5. Retain original records plus comparison deltas in a benchmark results artifact.

Each copyable record has a stable prefix such as `[NADOC_VIEWER_PERF v1]` followed
by JSON containing run ID, A/B variant, commit/build/instrumentation IDs, fixture
hash/revision, browser/OS, available GPU metadata, viewport/DPR, quality/representation,
cache/network mode, scenario/duration, measured metrics, availability flags, and
errors. Exclude file paths, sequences, invite tokens, and participant names.
This is a proposed log contract, not an existing command or fabricated sample result.

Proposed initial regression gates, calibrated after Phase 0 noise measurements:

- No correctness differences, crashes, lost selections, or WebGL context loss.
- Investigate/block repeatable p95 frame-interval regression exceeding both 10%
  and 1 ms; load/readiness regression exceeding both 10% and 100 ms; picking latency
  regression exceeding both 10% and 5 ms under equivalent conditions.
- Investigate >10% measured peak heap regression and any accumulating retained
  scene resources across repeated open/close cycles.
- Report tails and all repetitions; compare per-run summaries rather than pooling
  frames to hide variability. No passing claim from a single favorable run.
- Absolute usability goals for target hardware and large fixtures are established
  with the user after baseline measurements; relative parity alone is insufficient
  when both A and B are slow.

## Validation, checkpoints, and rollback

Follow `FEATURE_DEVELOPMENT.md` module boundaries and applicable test/check policy.
Each phase gets a focused commit/checkpoint, behavior evidence, A/B results, and
manual validation records for gestures/visual behavior. Report unverified cases.
Keep benchmarks isolated from the user's running NADOC server and workspace data.
Use additive, versioned packages; never rewrite original design files as a migration
side effect. Keep the original viewer runnable until final acceptance. Remove any
temporary dual-path switch only after regression gates and manual review pass.
Geometry generation remains in Python; the prepared renderer and transport do not rewrite scientific geometry.

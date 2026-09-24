# ScryWrite live agent interface

Looking for the **live visual inspector**? See the [inspector capability index](scrywrite_inspector.md).
This API is its inspection/control foundation. Start the separate graphical client
with `python3 -m tools.scrywrite_inspector`; see the index for launch arguments.
`inspect` mode alone does not open a panel. `scrywrite_scene_visibility` accepts
`normal` or `hidden` in inspect/control modes, changing rendering only.

For recorded Vive motion and seeded controller variability, see the
[human movement modeller](vr_human_motion.md). Its live adapter uses this existing
bridge and retains session/sequence, input-release and browser-authority contracts.

Implemented 2026-09-16. This interface adds an opt-in Linux Unix socket to the
production C++ viewer and a dependency-free Python MCP stdio bridge. It preserves
physical HMD views, the existing mirror, and browser authority over design edits.
It does not replace the OpenXR runtime.

## Start from a browser document

Use an isolated document/design copy for editing tests. Append
`&scrywrite=transactions` to its existing `?doc=...` URL, then select **View in VR**.
Use `&scrywrite=inspect` for observation and capture with physical controller input.
Normal launches expose no agent endpoint. Enabling the URL flag does not launch
VR by itself or change a viewer which is already running.

The backend creates a private directory and supplies the socket path to the viewer.
`GET /api/vr/status` reports `scrywrite_live` and `scrywrite_socket`. The bridge follows
the existing private backend state file (`/tmp/nadoc-vr-<uid>.json`) on every request,
so restarting the viewer and receiving a new socket path does not require changing
the MCP configuration. A new viewer session still invalidates old action requests.

Register a local **stdio MCP server** using:

- Command: `/usr/bin/python3`
- Arguments: `[/absolute/path/to/NADOC/frontend/scrywrite/mcp_bridge.py]`

A generic configuration example (adapt the enclosing configuration to your client):

```json
{
  "mcpServers": {
    "nadoc-scrywrite": {
      "command": "/usr/bin/python3",
      "args": ["/home/jojo/Work/NADOC/frontend/scrywrite/mcp_bridge.py"]
    }
  }
}
```

Optional bridge arguments: `--trace /private/path/commands.jsonl`,
`--state /private/path/backend-state.json`, or `--socket /private/path/viewer.sock`.
The last pins a standalone viewer instead of following backend discovery. Logs never
share stdout with MCP. Tool discovery and ping work while the viewer is offline.
The bridge implements the MCP newline-delimited stdio transport and tool discovery:
[transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

## Standalone viewer

Create an owned directory with mode 0700 and use a socket filename inside it:

```sh
install -d -m 700 /tmp/my-nadoc-scrywrite
native/vr_viewer/build/nadoc-vr-viewer path/to/fixture.nadocvr \
  --scrywrite-live /tmp/my-nadoc-scrywrite/viewer.sock \
  --scrywrite-live-mode control --mirror-eye left
```

This uses the already configured OpenXR runtime. Existing scene-framing flags still
apply; do not move a physical headset's view through the agent interface. `control`
refuses a browser event output; `transactions` explicitly permits the existing
browser event/feedback paths. Witness and live control are mutually exclusive.
A socket path already in use is never replaced. After an unclean process death,
verify the old viewer is gone before removing its stale socket or choose a fresh
private directory. Captures persist in the private directory for review.

## Tools and interaction contract

| Tool | Purpose |
|---|---|
| `scrywrite_observe` | Session, frame/time, focus/tracking flags, menu targets, hands, selection/owner identities, layout, browser feedback and Extrude state |
| `scrywrite_pose` | Test controller pose in OpenXR LOCAL meters, normalized XYZW quaternion |
| `scrywrite_button` | Menu, trigger, grip, or trackpad press/release through normal input handling |
| `scrywrite_aim_menu` | Aim at a discovered label, including `EXTRUDE LENGTH WHEEL` and `LATTICE EXIT` |
| `scrywrite_aim_lattice` | Aim at the visible portion of a lattice cell |
| `scrywrite_aim_border` | Aim at a menu/lattice border; grip-drag also requires a suitably positioned controller |
| `scrywrite_activate` | Semantic entry to the production radial-tool activation handler; does not test radial acquisition |
| `scrywrite_release` | Neutralize test hands/buttons and stop wheel/radial activity |
| `scrywrite_wait` | Bounded observable-state or frame wait, pinned to a session |
| `scrywrite_capture` | Next submitted stereo app frame, semantic metadata and left-eye image response |

1. Observe before acting. Supply the returned `session` and `command_sequence`
   (as `expected_sequence`) to every action, including capture. Accepted commands
   advance the sequence; rejected commands do not. Acknowledgement means the input
   was accepted, not that a future frame or design commit has completed.
2. Set a hand pose, aim at a discovered target, wait for its independent production
   hover result, press, wait for the expected state, then release. Hand indices are
   0=left and 1=right. Lattice painting uses the right hand.
3. Held buttons expire after two seconds without another control command. Neutral
   poses persist for later targeting. Focus loss invalidates poses too. Physical menu
   buttons abort scripted input. No scripted haptics or desktop mouse/scroll injection
   is allowed. Explicitly release on errors; do not rely on the lease for normal use.
4. To drag a wheel or panel, send successive hand poses while holding trigger or grip.
   Wheel targeting owns its trigger and blocks lattice painting. Observe the resulting
   length/panel position. Runtime frame waits are not virtual deterministic stepping.
5. Inspect `tool_sequence`, `execution_feedback_sequence` and `committed_feature_id`
   to correlate browser execution. Never infer persistence from a native preview or
   successful input call. Commands with an uncertain delivery result are not retried.

The MCP tool descriptions and JSON schemas are available through `tools/list` even
without a running application. The live mode in `observe` determines which calls the
viewer permits. Inspection mode rejects controller/tool mutations.

## Evidence

On-demand capture reads both app swapchain eyes from the same frame before release.
After successful `xrEndFrame`, it writes a session/command-specific directory with:

- `left.png`, `right.png`, and tolerant visual fingerprints;
- `left.depth.f32` / `right.depth.f32`: native-endian float32 OpenGL window depth,
  bottom-up (nonlinear, not meters);
- `left.classes.u8` / `right.classes.u8`: bottom-up coarse stencil render classes;
- `left.ids.u32` / `right.ids.u32`: bottom-up native-endian uint32 primitive IDs;
- `objects.json`: visible IDs mapped to primitive identities and canonical owner tokens;
- `evidence.json`: frame/time, selection, tool/config/feedback sequences, feature ID,
  per-eye pose/FOV/dimensions, and near/far planes.

See `SpectatorRenderClass` in `spectator_diagnostics.hpp` for class values. This is the
**application's submitted image**, not SteamVR overlays, lens distortion, or proof
of compositor presentation. Metadata says `object_ids_available:true` and
`compositor_acknowledged:false`. Readback/file writing is diagnostic work and can
stall frames; do not use a capture run as an undisturbed performance benchmark.
Capture fails if no submitted frame arrives within four seconds. Spectator fallback
is never silently substituted for a submitted-eye capture.

The integer ID attachment is written in the same opaque geometry pass as color,
using the same depth test, sphere-impostor discard/depth and displayed coordinates.
IDs are keyed by primitive identity and stay stable for the viewer session, including
style switches and coordinate updates; restart creates a new scope. Several primitives
can share canonical owners: use `owner_tokens` to group them at the desired selection
level. An empty owner list means the snapshot supplied no ownership mapping.

Zero means no identified design surface: background, viewer axes, or a pixel covered
by a final UI/grid/controller stencil class. Decorative glow never creates an ID;
underlying opaque design retains its ID. Transparent panel areas that do not draw
remain see-through. The table includes only IDs visible in either eye, so absence
means not visible in this capture, not absent from the design. PNG rows are top-down;
ID/depth/class rows are bottom-up, so flip Y when correlating them. The ID texture is
allocated/read only for captures; normal launches do not build the identity registry.

`--trace` records live commands and returned observations as JSONL. The development
browser facade (`window.__nadocTest.scrywrite`, only with a `scrywrite` URL parameter)
provides a bounded 128-record event/verdict history and transaction snapshots.
`execution_verdict` records the browser's result before feedback transport; it does
not claim that native received it. This facade drives the existing event handler,
not a separate mutation implementation.

## Validation and remaining gates

- Native tests compile the production viewer handlers into a separate test executable
  without creating GL/OpenXR. They exercise parser/session checks, semantic targets,
  lattice paint/erase, wheel detents/input priority, panel dragging and Cancel.
- A real OpenGL test (`nadoc-vr-scrywrite-live-test --gl-ids`) checks front/rear
  occlusion, sphere corner discard, all primitive shaders, stable IDs after style
  changes, canonical owner mapping, glow exclusion and production overlay masking.
  CTest skips this specific test when no OpenGL display/context is available.
- Python tests exercise real socket IPC, MCP stdio discovery, malformed/stale input,
  timeout release, offline discovery and backend-state rediscovery. The native harness
  explicitly reports `runtime_connected:false`.
- The isolated Playwright browser test drives the production native-event receiver,
  real desktop preview/commit/undo, and a real throwaway backend. It checks Cancel
  persistence, exact translation, feature-log acknowledgement identity, and Undo.
  Only the absent headset feedback HTTP transport is intercepted. It is not a
  physical or combined native/browser end-to-end test.
- Browser test servers use separate ports/workspace and `--lifespan off`; they do
  not start job supervisors or cloud autoconnection. No CPD tests are part of this gate.

```sh
just test-scrywrite
just test-scrywrite-browser
```

For an independent build, configure CMake using `/usr/bin/g++` and system pkg-config
paths, outside Conda's compiler/linker/library overrides. Limit build/test workers
when another agent is running scientific tests. Set `SCRYWRITE_LIVE_TEST_BIN` to the
built `nadoc-vr-scrywrite-live-test` executable to enable Python IPC tests.

Physical SteamVR/Vive validation passed on 2026-09-16: tracked, focused, submitted
stereo; live paint/erase, +21 bp wheel adjustment, 10 cm grip drag, Cancel/release;
and per-object ID visibility under the tool panels. See the
[retained validation record](generated/scrywrite/live_agent_20260916/README.md).

**Still open:** a single combined native-input → browser-persistence → eye-image
transaction trace; rolling pre/post image history and
unified deterministic replay. Painted Extrude footprint commit/undo remains
unsupported by the existing application contract. The live interface reports
`footprint_state:unresolved` and `commit_supported:false`; this work tests its UI and
cancellation without inventing a backend geometry mutation path. Human comfort,
reach, haptics and stereo legibility gates remain unchanged.

# VR simulations implementation and validation — 2026-09-28

## Scope

Merged `origin/feature/standalone-viewer-presentations` into local `master` in
`6dbe0ed1` before development, retaining both sides of the assembly/part persistence
and VR wiring conflicts. No push was performed. Existing unrelated working-tree
changes were preserved.

The VR Simulations tab mirrors desktop engine order, job labels and availability.
Selecting a job opens a separate right-hand visualization column. Both columns
support ray selection, scrolling and touchpad click focus with Trigger activation.
Child jobs follow the desktop's expanded list. Select/numeric/checkbox/radio controls invoke the
same desktop handlers. Trajectories are excluded. Versioned, document-bound
snapshots and acknowledged native requests guard stale or duplicate activation.
Actual static display geometry uses the native scene feed; Frame result uses its
bounds. `main.js` is thin wiring only: +7/-3 lines, net +4.

The discoverable demo is **Debug → VR Tours & Tests → Left sidebar → Simulation
results · 2hb_1xT**. It copies completed local and archived jobs to a temporary
workspace, linking only immutable trajectory inputs. Viewer shutdown and temporary
workspace cleanup run on failures too. Evidence is retained under
`.development-artifacts/vr-simulations/`.

## Known scientific bug, deferred

The user confirms that the `2hb_1xT` CanDo predicted-shape expansion is an unresolved
bug. A design-specific or small-design issue is suspected; the cause is unknown.
No solver output or molecular coordinates were changed to disguise it. Result
framing and ordinary two-hand enlargement are observation adjustments, not a fix.
VR activation/transport checks do not establish the scientific correctness of this
saved result. See `BUG-CANDO-SMALL-DESIGN-EXPANSION` in `manual_validation_debt.md`.

## Software checks

- Full frontend suite: 568 files; 7,223 passed, one skipped.
- `just smoke`: 23 passed, including document and assembly teardown. The default
  frontend port was occupied; the successful isolated run used ports 18001/15174.
- Focused backend bridge tests: 3 passed. Memory lint: zero errors (62 existing
  warnings). Changed Python modules pass Ruff.
- Native build uses the system linker (`PATH=/usr/bin:/bin`); the inherited Conda
  linker fails on system GL/XCB/jsoncpp symbols. Sidebar, grip and simulation-panel
  focused native tests pass (3/3).
- Backend fast suite: 9,402 passed, 93 skipped, one failure in unchanged
  `test_the_scalar_and_loop_skip_fast_paths_agree`. Its exact floating-point array
  comparison also fails in isolation. Scientific geometry was left untouched.
- `just test-smart` decision and deferral:

  ```text
  decision: FAST  (fast suite only)
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  ```

- `just lint` identifies a pre-existing unused `Path` import in the user's untracked
  `tests/test_cpd_shape_sensitivities.py`; it was not edited.
- Merge regression checks for standard part simulation and view-volume editing
  pass (2 browser tests), with their temporary files cleaned.

## Live observation and retained failures

The physical SteamVR runtime and production native viewer were used. Controller
input is software-generated with the unchanged human-motion profiles. Captures
contain submitted stereo eyes and native mirror pixels; they do not establish
through-lens readability, physical panel scanout or subjective comfort.

The tour positions the menu and result beside each other using normal grips.
Frame result fits saved geometry, then an ordinary vertical two-hand gesture
magnifies it 2× for observation. These adjustments and review holds occur outside
measured reaches. Captures require result-class pixels in both eyes, visible menu
controls, an offscreen negative control, and actual desktop-mirror correspondence.

Earlier retained `cando-*` attempts exposed menu-label alignment, ineffective
horizontal gripping near a panel edge, and input playback stalls. Labels were
centered, magnification uses vertical grip separation and asserts actual scale
change. Thresholds and profiles were not loosened. `all-engines-01` failed with a
0.466 s input lateness during startup; the tour now settles initial upload/window
resize before starting measured input.

`all-engines-02` activated and captured all four CanDo static modes with passing
stereo/menu/desktop checks. SNUPI predicted shape passed stereo/menu checks but
failed actual desktop correspondence (0.00161 versus the required 0.95). That
failure is retained. Subsequent runs collect desktop delivery failures at their
final gate so one covered/mismatching mirror does not erase other engine evidence.

`final-campaign-02/end/variable_deliberate` completed all 22 available static modes:
CanDo 4, SNUPI 4, mrDNA 5, oxDNA 5, NAMD 4. All 22 captures passed stereo result
pixels, menu checks, the offscreen negative case and actual desktop correspondence.
All nine completed NAMD jobs were inspected; ion-path and ion-vector controls are
unavailable for these jobs, matching desktop. Trajectories were never activated.
An unmodified [NAMD occupancy review frame](../../.development-artifacts/vr-simulations/review-namd-occupancy.png)
shows the actual submitted-eye mirror, expanded result column and selected job.
That profile ran after the identity fixes below. The earlier three profiles retain
their timing or pre-fix identity failures and are not counted as passing full tours.

The final navigation campaign samples one available static mode per engine across
all four profiles (`NADOC_VR_SIM_MODE_LIMIT=1`). This is explicitly navigation
coverage; it does not claim all 22 modes under every profile. The default Debug
demo and validation commands have no mode limit.

`navigation-profiles-final` passes **steady_fast, steady_deliberate, variable_fast
and variable_deliberate**, each covering all five engines (20 successful result
captures total). Every sampled capture also passed actual desktop correspondence.
The final native build and three focused sidebar tests pass. Frame-result bounds
are used only while a simulation view is active; ordinary recenter behavior is
preserved for other views. `main.js` remains net +4 lines.

The isolated final frontend rerun passed all 7,223 tests. A prior concurrent
frontend/backend run hit three 5 s frontend timeouts; its log is retained as
`frontend-tests-contended.log`. No timeout thresholds were increased. The Debug
menu discovery/launch browser test also passes.

Temporary tour workspaces and shared-workspace `__e2e__` artifacts were verified
absent after the full tour. Five orphaned simulation sidecars from early runs,
before shutdown cleanup was added, were removed only after confirming their base
event files were gone. The exact paths are in `orphan-sidecar-cleanup.json`.
After the final four-profile campaign, the owned viewer was stopped and all
temporary tour workspaces, simulation sidecars and shared-workspace `__e2e__`
artifacts were again verified absent. `cleanup-final.json` records the check.

The live job check exposed an identity-handling bug in mrDNA curvature and oxDNA
deviation: crossover inserts use `helix_id="__xb__"` and a UUID-valued `bp_index`,
but those readers attempted `int(bp_index)`. Deviation now preserves insert keys
and uses its existing reference intersection; paired-column curvature excludes
crossover particles from slab centroids. Saved positions and reference geometry
remain unchanged. Four focused regression tests pass, including exact equality
with the original core-only measures and input immutability. Earlier profile
attempts retain the original HTTP 500 and failed activation evidence.

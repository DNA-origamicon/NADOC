Validation follow-up (November 17, 12-tether fix): FAST 21,067 passed / 19 skipped;
lint passes. Aggregate timing warning (498 s) has zero per-test violators, maximum
4.56 s. Required triage found no shared accidental wait in reviewed leading
modules/fixtures. Full-JJ 12.62 s test is centrally registered slow+headless and
collection verified. FULL sweep remains deferred in `.nadoc-slow-pending` because
no test-dedicated session is open. See ISSUE-214 for exact guard message.

---
name: ssdna-flexible-segments
description: "Flexible ssDNA segments — mark unpaired runs flexible → fixed-length arc between EXISTING clusters → real-time \"ssDNA constrained\" cluster drag (free until taut). Replaced the auto-cut \"ball joint\" approach. Shipped 2026-05-30."
metadata: 
  node_type: memory
  type: project
  originSessionId: 874f5bfb-0255-4978-aea7-e313162dea01
---

# Flexible ssDNA segments + real-time "ssDNA constrained" drag

Latest (2026-11-17, ISSUE-219): M-before-selection uses coalesced attachments and
request-scoped gate discovery; delayed replies refresh pivot options without
reviving a cancelled/superseded tool. Live coupled solves use reusable geometry,
a refitted rod-contact hierarchy, and 60 ms continuation slices; only validated
poses publish. Reversal discards obsolete work. One display transaction covers
all bodies. Numeric edits retain the complete solve budget. JJ GPU full-frame
120-update benchmark max 171.8 ms; see fix log and task receipt for scope.

Apply diagnostic follow-up (ISSUE-220): null receipts previously hid the server's
specific rejection behind “Pending movement has been retained.” Atomic moves now
propagate request-local error details; organized placement Apply opts into the
same behavior. Pending poses and publication guards remain intact. Isolated
JJ_Hinge successive X requests 55/65/90 projected to 19.772/19.820/19.868°
and committed; poses above 50° were not reached. The user's original failure
is not reproduced; do not describe it as fixed or as an angle-limit defect.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Mark a contiguous run of UNPAIRED beads as a flexible tether. Each marked run bridging two **existing** clusters becomes a fixed-contour-length `FlexibleConnection`. The move/rotate tool gains an **"ssDNA constrained"** pivot option (enabled only when every inter-cluster connection from the selected cluster is flexible); dragging the cluster is clamped per-frame so no tether exceeds its contour length ("free until taut"), and the segment renders as a fixed-length geometric arc. Display-layer only — NEVER mutates topology. Plan: `~/.claude/plans/we-want-to-create-indexed-pancake.md`.

**REPLACED the earlier auto-cut "ball joint" approach** (mark beads → derive new arms → Powell solve). The user found that paradigm wrong. Rigid arms are now the user's OWN clusters; no auto-cut, no solver, no new clusters. (Old `ball_joint_arms.py`/`ball_joint_solve.py` deleted; `ClusterRigidTransform.kind` removed.)

## November 17, 2026 — compliant tether motion and collision toggle

Move/Rotate exposes **Detect collisions during tethered motion**, default ON.
The checkbox and its wrapping label share a horizontal row. Numeric inputs and
pointer changes use the same constrained preview path (ISSUE-217).

For gate-approved flexible components with at least three clusters, the new
`tether_network_solver.js` solves all connected rigid bodies together. The largest
cluster is pinned; smaller bodies translate and rotate preferentially under tether
and duplex-contact corrections. `tether_network_motion.js` resolves exact ownership,
starts from current pending poses, captures all follower previews and queues their
absolute poses in the existing atomic Apply transaction. Cancel/Undo discard the
whole preview. Unsupported mixed/overhang components retain the earlier solver.

All paired duplex axes in the part participate as contact geometry. Geometry
outside the eligible flexible component remains a fixed obstacle. The coupled
solver checks follower/anchor, follower/driver and follower/follower contacts,
using the existing conservative 1 nm radius / 0.167 nm flat-end padding. Contact
OFF disables contacts while retaining coupled tether compliance. Sampling advances
at most 0.25 nm of requested driver axis displacement, with 200 steps and 600 projection passes per edit;
blocked steps cannot accumulate into an unchecked jump. Projection corrections
are iterative, so this is not exact continuous collision detection.

Both contact and tether residuals must be within 0.001 nm of their initial valid
bounds; initially invalid geometry cannot worsen. Contact bounds are fixed for a
gesture rather than tightened after every step, avoiding the old monotonic
stop-only ratchet (ISSUE-218). Initial overlaps are tolerated, not repaired by this
tool. These are duplex contact bounds, not atomic sterics or ssDNA self-avoidance.
The toggle applies to tether-constrained part motion, not free group movement or
assembly instance transforms. No topology, contour or native molecular placement
rules change. Main.js LOC delta 0. Subjective pointer feel remains MV-70.

Real JJ app verification: increase and reverse Cluster 2's X rotation through the
actual numeric field, contact toggle ON/OFF, unchanged largest cluster, all
17,926 inter-owner duplex pairs and all 12 flexible connections checked. With
contacts ON, additional penetration was 0.000626 nm and added tether stretch
0.000857 nm; reversal stayed below 0.0001 nm for both. Followers yielded and
Cancel restored every displayed backbone position within 1e-6 nm. With contacts
OFF, tether compliance remained active while penetration reached 1.1795 nm.
The requested +5-degree edit advanced X from 19.580 to 19.772 degrees under the
work cap (2.05 seconds in headless Chromium); reversal reached 17.734 degrees
(1.04 seconds). This is local constrained projection, not a global motion planner
or a guarantee that every requested angle is reachable. Rendered anchor coordinates
agreed with queued transforms to 1.12e-13 nm. Pointer responsiveness
and crowded motion feel remain MV-70. Full frontend suite: 979 files, 10,688 passed / 1 skipped.
Isolated smoke: 24 passed / 2 skipped. Cleanup verified; receipt:
`.development-artifacts/compliant-motion-verification.json`.
Full view/toggle visually inspected; no
saved derivative of this legacy design was created. Source SHA256 unchanged:
`74c416cf56d157df29587df6b60323086ebe9b80d45cdc4ea40317682fc44ada`.

## November 17, 2026 — twelve-tether contact-constrained closure (current)

The user marked the remaining two bases on h_XY_5_5 (135–136 FORWARD).
All 12 tethers are now present and both large clusters pass the constrained-move
gate. The v1 soft contact schedule fails on this state: 10.245 nm maximum
overstretch and 1.804 nm capsule penetration. More starting poses and penalty
schedules did not establish acceptance. No contour lengths or topology changed.

Two corrections now ship as `rigid-flex-staged-contact-v2`:
- Finite duplex cylinders have flat ends, padded by half the native bp rise
  (0.167 nm). Rounded capsules falsely reported 0.998 nm penetration between
  three pairs of consecutive hinge duplexes whose terminal axis sites are
  1.002 nm apart. Radial capsules plus exact axial support-plane bounds certify
  separation conservatively; they may retain false contacts, never certify an
  intersecting cylinder pair as clear. Degenerate single-site primitives retain
  conservative spheres. Closest-segment math uses cross products to avoid the
  nearly-parallel Gram-determinant cancellation.
- A contact-repair least-squares initialization handles overlapping starts.
  SLSQP then minimizes tether overstretch subject to contact gaps >= 0.
  This replaces the v1 tradeoff between tether and contact residual penalties.
  Largest-cluster pinning, all-tether/native-contact acceptance, atomic failure,
  explicit-pose history and replay remain unchanged.

Actual app verification on source SHA256
`999bd567db350ac8ada5de559815e630f7c0204d1d8e6bf0b2e2d4a3fe9db303`:
F19 (mark) -> F20 (Relax), all 12 lengths <= 1.18 nm, maximum excess 0,
maximum contact-bound penetration 1.86e-13 nm, zero overlaps. Geometry Cluster 1
fixed. Front/side/top/oblique Full views inspected: open hinge, no visible
inter-bundle duplex intersections. Full geometry refetch changes rendered
backbone coordinates by exactly zero. Geometry Cluster 2's real Move/Rotate
panel offers and selects Constrained (tethers). This checks availability, not
a new network-following drag algorithm.

Focused network tests: 10 passed, including recorded publication/reopen/replay,
atomic rejection, initial overlap repair and the updated local 12-tether numeric
regression (12.62 s; explicitly slow). Contact geometry tests: 8 passed.
Source remains unchanged; no legacy derivative published. Both browser capture
directories, host parts/project stores, credentials/session/output paths removed.
Compact app evidence: `.development-artifacts/jj-twelve-app-verification.json`.
Coverage remains paired rigid duplexes only, not ssDNA, overhangs, atomistic
sterics or continuous collision-free motion.

## November 17, 2026 — actual JJ_Hinge app verification

Follow-up to the user's failure report: the preceding production check was only
a numeric solve, not an applied/rendered JJ check. The local file now ends at F18
(all cluster poses identity), SHA256
`b2e3723a8bc5afc1030e6b720d53b280f58a74bfe3b96bbf5d5908d1b1c24834`.
Two isolated app runs invoked the real Relax all controller/API and committed
F19 successfully. Maximum actual tether excess was 0.000348 / 0.000511 nm;
actual duplex-capsule penetration 0.00000248 / 0.00000363 nm, zero overlaps
at 0.001 nm tolerance. Largest cluster stayed fixed under route validation.
Full geometry refetch changed rendered backbone coordinates by exactly zero.
Inspected front/side/top/oblique full-representation views: separated bundles
forming an open hinge, no visible inter-bundle duplex intersections. This does
not certify atomistic or excluded ssDNA/overhang contacts. The user's failure
was not reproduced from this saved state; no production fix was inferred.
The optional JJ browser regression now applies Relax and checks refresh parity.
Autosave/session caching off; source unchanged; no derivative published.
Screenshots/traces are disposable; compact evidence:
`.development-artifacts/jj-actual-relax-visual.json`.

## November 17, 2026 — staged contacts in production Relax

User explicitly authorized integration after the comparison trials. Scope-based
Relax now uses `rigid-flex-staged-contact-v1`: the same joint rigid network,
with contact residual weights 0.1, 0.3, 1, 3, 10, 150 evaluations per stage,
1e-5 pose regularization, and 1e-9 optimization tolerances. BLAS is limited to
one thread as in Relax Origami. Already-slack tethers no longer bypass overlap
repair. The pure numeric anchor-only API remains compatible when no capsules
are supplied; the app/headless design adapter always supplies collision geometry.

`flexible_contacts.py` owns finite-segment distances, dynamic broad-phase
screening, and contiguous paired-duplex axis capsules using canonical cluster
ownership. The contact model covers participating rigid clusters, including
cross-component contacts. It excludes intra-body contacts, ssDNA/overhangs and
nonparticipating obstacles. No atomistic or noncrossing-trajectory guarantee.

Acceptance requires every tether and capsule penetration <= 0.001 nm. Before
atomic commit, the route independently reconstructs native posed capsule geometry
and checks clearance and all fixed-body capsules, in addition to the existing
anchor checks. Failure records nothing and does not change undo/revision state.
Recorded feature parameters include initial/final contact metrics, coverage,
model/radius/tolerances and the complete stage schedule. Existing absolute-pose
replay remains deterministic without rerunning optimization.

Production read-only JJ_Hinge check: 11 tethers close, 0.000187992 nm maximum
excess; 28 initial capsule overlaps become zero at 0.001 nm tolerance (maximum
penetration 0.000001347 nm). Geometry Cluster 1 fixed; 91.99 seconds. Source
SHA256 remains `30fd5a0571658be4d9bef5096818c7d401a83c58d61f4fdd89055f5aa671dc98`.
No derivative of the legacy document is published.

## November 17, 2026 — joint flexible-network relaxation

Relax commands now share the backend kinematic least-squares solver in
`flexible_network.py`. All tether contour inequalities are solved simultaneously
with six rigid degrees of freedom per movable body. The largest participating
cluster by owned backbone-slot count stays fixed in each connected component;
ties use cluster ID. Overlapping organizational groups with no owned tether
endpoints are excluded. Scope one solves the selected connection's complete
component, exposed as **Relax connected flexible network**; all solves every
component. Slack stays free. This is kinematic fitting, not molecular dynamics;
the subsequently authorized staged contacts are described above.

The previously saved JJ_Hinge had three residual lengths of 7.785, 5.892 and 6.940 nm after
the old pairwise solve (1.18 nm contours). Repeated pairwise translations trade
violations between neighbors; 80 sweeps do not resolve them. The joint numeric
solve closes all 11 with Geometry Cluster 1 fixed. The legacy source remains
unchanged by the agent; it has no recipe root and is not an agent-publishable derivative.
The user's subsequent saved retry closes all 11 but contains inter-body overlaps.

The public `/design/flexible-relax` scope request computes and verifies actual
NADOC posed-anchor closure (0.001 nm tolerance) before one atomic commit.
Nonconvergence, unresolved anchors, moving a fixed reference through overlapping
poses, or stale source revision reject without a partial commit. Pose-only
recording skips topology reconciliation and pending-ligation retries.
`part_flexible_commands.py` replays recorded absolute poses independently;
parameters retain solver version, selection, fixed IDs and per-tether metrics.
The existing explicit-transform request remains supported. Headless Relax uses
the same route; the older single-body PBD code remains for drag parity.

## November 17, 2026 — collision-aware solver investigation (isolated)

The user's saved retry (SHA256
`30fd5a0571658be4d9bef5096818c7d401a83c58d61f4fdd89055f5aa671dc98`)
closes all 11 tethers but has 28 intersecting inter-body duplex-axis capsule
pairs, maximum penetration 1.834712 nm. The pre-Relax snapshot already has
3 capsule overlaps, so collision-free initialization cannot be assumed.

`experiments/flexible_collision_benchmark.py` reads either existing state and
solves numeric arrays only. It never edits, exports or publishes a structure.
262 contiguous occupied paired-axis capsules, radius `HELIX_RADIUS_NM` (1 nm),
cover participating rigid bodies; all 17,926 inter-body pairs are checked.
Exact-base ownership, missing/flexible slots and bends delimit capsules.
Geometry Cluster 1 is fixed. Overhangs, ssDNA paths, internal-body clashes,
nonparticipating bodies and atomistic sterics are outside this benchmark.
Endpoint clearance is not a collision-free motion-path guarantee.

Saved-state trials: simultaneous equal-weight hinge/contact least squares
failed (0.210816 nm max tether excess; 23 overlaps). Contact continuation
(residual weights 0.1, 0.3, 1, 3, 10; 150 evaluations/stage) succeeded:
0.00017831 nm max tether excess, 0 overlaps at 0.001 nm tolerance,
0.00000128 nm max penetration. Direct SLSQP from the infeasible saved state
failed both with pose-vector norm and physical endpoint-displacement objectives.
No failed trial is eligible for committing. Full metrics and timings live in
`.development-artifacts/flexible-collision-*.jsonl`; no candidate poses are saved.
At investigation time production Relax was still tether-only; the subsequent
authorized staged-contact integration is documented above.

Starting at the existing pre-Relax snapshot, continuation also passes both
0.001 nm acceptance thresholds: tether excess 0.00060071 nm, penetration
0.00000427 nm, zero overlaps, 69.0 s (AABB broad phase enabled). Its final
optimizer flag is false (evaluation budget); acceptance is independently based
on all final inequalities. Feasible-seeded physical-displacement SLSQP also
passes (0.00013817 / 0.00019784 nm respectively), but costs another 68.0 s and
does not meaningfully improve endpoint displacement. Thus continuation alone
is the best measured cost/closure/clearance compromise here, not cold SLSQP.
The reported RMS displacement samples capsule start points including the fixed
body; it is not mass-weighted RMSD. Four focused geometric oracle tests pass.

Research: [XPBD](https://matthias-research.github.io/pages/publications/XPBD.pdf)
offers compliant joint/contact projection; it was researched, not benchmarked
as a dynamics implementation here. [Rigid IPC](https://ipc-sim.github.io/rigid-ipc/)
offers collision-free rigid trajectories but requires an intersection-free
initial state and conservative continuous collision detection. Merely adding
a barrier or endpoint test does not implement IPC. The practical candidate is
continuation recovery; constrained refinement did not justify its extra cost;
continuous collision checking and proper body/ssDNA coverage remain necessary
before claiming general collision prevention.
Future integration must evaluate contacts even when all tethers are already
within contour: the current tether-only early no-op cannot detect the jumble.

Follow-up: explicit expand/separate-then-relax trials on the same saved state
did not outperform joint contact continuation. The isolated benchmark now has:

- `radial_expand_relax`: rigid body centers translated away from the fixed
  body's geometric centroid, trying factors 1.25–8. First clear seed was 3x,
  temporarily overstretching a tether by 72.563 nm. Reapplying joint contact
  continuation ended with 7.7484 nm excess / 122 capsule overlaps (rejected).
- `separate_reclose`: contact-only local separation with a small pose penalty,
  then per-tether temporary allowances reduced through 1, .5, .25, .1, 0 while
  retaining contact residual weight 10. Initial separation cleared contacts
  with 1.5481 nm tether excess; final 0.32380 nm excess / 5 overlaps (rejected).
- `radial_expand_reclose`: same 3x seed, then the strong-contact gradual
  reclosure above; final 0.78545 nm excess / 12 overlaps (rejected).

Every stage is numerical only: body dimensions and actual contour parameters
stay unchanged, root body is fixed, and no intermediate overstretched state is
committed. These schedules are bounded local trials, not a proof that all
expansion methods fail. Joint contact continuation remains the successful
tested approach on this input. [LAMMPS soft push-off](https://docs.lammps.org/pair_soft.html)
is a related established approach using finite repulsion to separate initial
overlaps; our kinematic prototype does not invoke LAMMPS or implement its
potential. Radial expansion may be useful as an optional restart, but clearance
of the expanded seed does not establish closability or a noncrossing return path.

## November 14, 2026 — reject marks without an inter-cluster tether

New mark requests must produce a connection between different existing clusters.
The single and batch endpoints reject unsupported runs atomically (HTTP 422,
`flexible_connection_requires_distinct_clusters`), preserving marks, history,
revision, and undo. The context-menu action displays a modal with the user-requested
text: “flexible connections must be between two different cluster”. Success is
reported only after the server accepts the marks. Old intra-cluster marks remain
replayable and removable; their Relax actions are disabled without a connection.

The saved `Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc`
contains two marks at h_XY_5_2, reverse, bp 104–105; their flanking bases belong to
the same geometry cluster. This is an unsupported intra-cluster mark, not a
minimum-length restriction. A recorded two-nt inter-cluster example is covered by
`tests/test_short_flexible_import.py` and `frontend/e2e/short_flexible_import.spec.js`.
A read-only comparison against the original JSON in
`C:\Users\joshu\Google Drive\DNA Origami\NP_HInge` found exact agreement:
18,146 occupied slots, 17,875 directed backbone edges, and 139 loop/skip records;
74 occupied helices (one of the source's 75 vstrands is empty).
The saved JJ_Hinge layout is nonplanar, so the existing clash-aware Relax Origami
solver skips it. Import feedback now explicitly says “Imported without relaxation”
and includes the reason. This change does not add a 3D clearance solver.

## November 14, 2026 — relaxation must retain compact flexible flags

JJ_Hinge retained all 22 marks / 11 two-base connections after Relax all, but
the partial compact geometry response omitted `is_flexible_segment`. Replacing
those helices recreated rigid beads alongside the flexible arcs. The shared
compact serializer now carries sparse `flex` booleans and the shared frontend
codec restores the flag (false for older payloads). The native array shortcut
falls back to complete records for marked designs. No solver or geometry change.
Regression coverage checks partial relax responses, undo/redo, sparse alignment,
and the app's relax-all controller with ordinary and deleted-slot two-base runs.

## Key definition (got it wrong once)
"Unpaired" = **no Watson-Crick partner** at the same `(helix,bp)`, NOT `overhang_id`. mini_hinge's tethers are unpaired *scaffold* runs. `flexible_segments.unpaired_bead_keys(design)`.

## Architecture
- **Models** (`models.py`): `FlexibleSegmentMark{strand_id,domain_index,bp_index,direction}`, `FlexibleAnchor`, `FlexibleConnection{cluster_a_id,cluster_b_id,anchor_a,anchor_b,n_ss_bases,contour_length_nm=n×0.59,segment_bead_keys}`. `Design.flexible_segment_marks` (source of truth) + `Design.flexible_connections` (derived).
- **`backend/core/flexible_segments.py`**: `unpaired_bead_keys`; `_build_bead_graph` (backbone + forced-ligation + crossover edges); `derive_flexible_connections` (marked-component BFS → rigid neighbours grouped by owning EXISTING cluster via `_owning_cluster_id`; ≥2 clusters → a connection; crosses forced ligations because FL edges are in the graph); `cluster_flexible_gate`/`all_cluster_gates` (a cluster's inter-cluster crossing is flexible iff one endpoint is marked; gate = ≥1 crossing and no rigid crossing); `apply_marks` (recompute connections only — no cluster/topology mutation).
- **API** (`crud.py`): `is_flexible_segment` + `is_unpaired` per-bead geometry flags in `_strand_nucleotide_info`. Routes `POST/DELETE /design/flexible-segment`, `POST /design/flexible-segment/batch` (selective `marks=[...]`; `replace:true` w/ no marks clears all; NO "all ssDNA"), `GET /design/flexible-connections` (connections + per-cluster gates). Mark/unmark return full geometry (beads reclassify).
- **Frontend**:
  - `client.js`: markFlexibleSegment / unmarkFlexibleSegment / batchFlexibleSegment / getFlexibleConnections.
  - `helix_renderer.js`: `_isFlexibleSegmentNuc` excludes flexible beads from the rigid InstancedMeshes (same two filter sites as `_isSsLinkerBridgeNuc`).
  - `flexible_arcs.js` (NEW): `initFlexibleArcs(scene, designRenderer, getHelixAxes)` draws each connection as a circular arc of arc-length = contour_length (bows as chord shrinks; straightens when taut) between live anchor world positions (from `getBackboneEntries().pos`), beads sampled along it. `rebuild(design)` on design change; `applyLiveUpdate(helixIds, centerVec, dummyPos, incrQuat)` per drag frame (wired in main.js onLiveTransform). **Bow DIRECTION = cylinder repulsion**: away from nearby helix-axis centerlines (`store.currentHelixAxes`, within OBST_RADIUS=12nm), projected perp to the chord, so slack arcs bulge outward instead of diving through the structure. The moving cluster's axes are transformed by the live drag transform so obstacles share the arcs' frame. Hysteresis (BOW_SMOOTH=0.6 blend with previous) prevents mid-drag flips. Heuristic, not a true collision solve.
  - `selection_manager.js`: `_showFlexibleSegmentMenu` (gated on `nuc.is_unpaired`, frontmost over cone, non-linker) → Mark/Unmark flexible segment + Clear all; opt `onFlexibleSegmentRightClick`.
  - `main.js`: `_flexibleRunForBead` (contiguous unpaired run on the strand around the clicked bead → mark/unmark the whole run via batch replace). Move/rotate pivot dropdown gains "ssDNA constrained" when `_flexGates[clusterId].gate` (fetched via `_refreshFlexGates` on tool open / cluster switch); selecting it calls `clusterGizmo.setConstraint('ssdna', {connections, resolveWorldPos})` via `_buildSsdnaPayload`.
  - `cluster_gizmo.js`: `setConstraint('ssdna', {connections, resolveWorldPos})` (reuses normal translate/rotate TC — projection only). Armed at drag start (`_ssArmed` = per-tether {pM0 cloned, pF cloned, contour}). `_projectSsdnaConstraints()` runs in the `'change'` handler after `_incrQuat`: PBD rigid solve (6 iters), each iter = rotation about pivot from tether torque (clamped 0.25 rad/iter) + residual translation, gain 0.6. Candidate moving-anchor pos = `incrQuat·(pM0−startDummyPos)+dummyPos`. Free until taut (skips slack tethers). 1 taut → slide on sphere; 2+ → rotation about the taut-anchor line (emergent hinge axis). **The torque-rotation is a linearised no-SVD approx — most likely piece to need tuning.**

<a id="mini_hingenadoc-worked-example-verified"></a>
- [mini_hinge.nadoc (worked example, verified)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#mini_hingenadoc-worked-example-verified)

<a id="verification-2026-05-30"></a>
- [Verification (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#verification-2026-05-30)

<a id="drawstring-arc-fix-2026-05-30"></a>
- ["Drawstring" arc fix (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#drawstring-arc-fix-2026-05-30)

<a id="axis-stick-suppression-over-flexible-regions-2026-05-30"></a>
- [Axis-stick suppression over flexible regions (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#axis-stick-suppression-over-flexible-regions-2026-05-30)

<a id="base-slabs-on-the-flexible-arc-2026-05-30"></a>
- [Base slabs on the flexible arc (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#base-slabs-on-the-flexible-arc-2026-05-30)

<a id="feature-log--right-click-arc-unmark-2026-05-30"></a>
- [Feature-log + right-click-arc unmark (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#feature-log--right-click-arc-unmark-2026-05-30)

<a id="undo-fix-2026-05-30"></a>
- [Undo fix (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#undo-fix-2026-05-30)

<a id="undo-fix-2--non-marks-topology-change-drops-the-flag-2026-06-07"></a>
- [Undo fix #2 — non-marks topology change drops the flag (2026-06-07)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#undo-fix-2--non-marks-topology-change-drops-the-flag-2026-06-07)

<a id="relax-command-right-click--relax-2026-05-31"></a>
- [Relax command (right-click → "Relax", 2026-05-31)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#relax-command-right-click--relax-2026-05-31)

<a id="imported--overlapping-cluster-fix-2026-06-01"></a>
- [Imported / overlapping-cluster fix (2026-06-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#imported--overlapping-cluster-fix-2026-06-01)

<a id="headless-relax-port--jspython-parity-af-29-2026-06-25"></a>
- [Headless relax port + JS↔Python parity (AF-29, 2026-06-25)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#headless-relax-port--jspython-parity-af-29-2026-06-25)

<a id="duplex-child-cluster-must-be-transparent-to-the-ssdna-gate-2026-07-01"></a>
- [Duplex-child cluster must be TRANSPARENT to the ssDNA gate (2026-07-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#duplex-child-cluster-must-be-transparent-to-the-ssdna-gate-2026-07-01)

<a id="connected-overhangs-as-move-constraints--constrained-tethers-2026-07-01"></a>
- [Connected overhangs as move constraints — "Constrained (tethers)" (2026-07-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#connected-overhangs-as-move-constraints--constrained-tethers-2026-07-01)

<a id="movable-link-tethers-duplexds-linker-swing-live-during-a-drag-2026-07-01"></a>
- [Movable-link tethers: duplex/ds-linker swing live during a drag (2026-07-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#movable-link-tethers-duplexds-linker-swing-live-during-a-drag-2026-07-01)

<a id="unified-scaffold-context-menu-2026-07-01"></a>
- [Unified scaffold context menu (2026-07-01)](details/project_ssdna_ball_joints/02-unified-scaffold-context-menu-2026-07-01.md#unified-scaffold-context-menu-2026-07-01)

<a id="oxdna-seed--display-of-flexible-runs-2026-07-02"></a>
- [oxDNA seed + display of flexible runs (2026-07-02)](details/project_ssdna_ball_joints/02-unified-scaffold-context-menu-2026-07-01.md#oxdna-seed--display-of-flexible-runs-2026-07-02)

## Deferred / refine
Kabsch (SVD) rigid fit instead of linearised torque; bow direction from exit-tangents; refresh gate dropdown when marks change while tool already open; per-frame arc rebuild allocates geometry (fine for few tethers, optimize if many).

## Deleted-slot anchors (2026-11-14)

caDNAno short ssDNA domains can span three lattice slots with a deletion at one
end (JJ_Hinge helices 34/36/38). Flexible connectivity must walk actual beads:
`flexible_segments._deleted_slots` aggregates loop/skip deltas; unpaired lookup
and the backbone graph omit deleted slots. Previously a deleted endpoint became
a rigid anchor, so Full rendering hid the two marked beads but could not draw
their replacement arc. Existing legacy documents rederive connections on load.
Regression coverage includes recorded scadnano import/mark/replay with deletions
at either end, plus actual arc bead counts in the browser.

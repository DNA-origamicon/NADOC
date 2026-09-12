# Shared surface transforms

`backend/core/surface_transforms.py` provides engine-independent geometry for hard
barriers, graphene sheets/pores, and PEG coatings. All internal coordinates are nm;
a normal points toward the allowed half-space (signed distance ≥ 0).

`RigidTransform` applies `p' = R p + t`, validates proper rotations, composes in
application order with `then`, and provides an inverse. `SurfaceFrame` stores a
plane point, unit normal and registered tangent. Transform the original tangent
with the structure; reconstructing an arbitrary basis after rotation changes
patch orientation. Normals, tangents and periodic cell vectors rotate only.

`transform_surface` copies the descriptor and transforms declared world-space
`plane_point_nm`, `pore_center_nm`, `graft_sites_nm`, `peg_positions_nm`,
`periodic_cell_origin_nm`, and the graphene `_first_site_nm` reference. Local patch
dimensions, material, stiffness and particle identities are copied unchanged.
Engine-derived `position` and `min_proj` are invalidated and must be recomputed.
Unknown coordinate fields require explicit handling by their owning adapter.

Legacy Cartesian `dir` / `position_nm` descriptors remain supported, including
negative normals. Oblique planes require `plane_point_nm`. An oblique transformed
descriptor omits `position_nm`; no dominant-axis approximation is used.
`SurfaceFrame.oxdna_plane(nm_to_oxdna)` returns `dir·r + position = 0` in oxDNA
length units; `namd_plane()` returns plane geometry in Å. Neither converts stiffness.

## Handoff status (2026-09-11)

Geometry adapters, source inspection and their fast regression tests are ready for
review. This does not enable PEG-containing NAMD launches: the target PEG model,
chemical mapping/assets and full engine validation remain outstanding. Continue
with the [NAMD seed plan](peg_namd_seed_plan.md), retaining the recorded source
identities and common coordinate transform.

## Barrier disposition

### 1. Oblique periodic graphene — geometry adapter implemented

`namd_graphene.tile_graphene_to_cell(..., cell_vectors_nm=...)` now tiles in a
rotated orthorhombic cell. Cell vectors are rows in world nm; their norms must
match `box_nm`. It rotates the complete input PDB and registered surface into the
cell frame, uses the existing periodic lattice construction, and returns world
coordinates with `periodic_cell_vectors_nm` and a zero cell origin. Atom identities
are preserved. `graphene_cell_frame.namd_cell_basis` emits the corresponding NAMD
cell basis declarations in Å.

A periodic sheet must be parallel to a cell face. An arbitrary oblique sheet in an
unchanged Cartesian cell is generally incommensurate; the adapter explicitly
rejects it. `surface_periodic.surface_aligned_cell(points, surface, padding_nm=...)`
can instead rebox a whole, unsolvated assembly. It returns a common forward/inverse
transform, transformed coordinates/registered features, box lengths and source-frame
cell vectors. External field/restraint vectors must follow the same rotation;
solvent must be rebuilt in that cell. This explicit preparation API does not silently
rotate existing solvated jobs. Sheared/triclinic cells remain unsupported.

### 2. Oblique oxDNA walls — implemented in setup, batch and Live adapters

`physics/oxdna_surface_geometry.py` validates surface descriptors and resolves one
canonical wall. Explicit plane points take precedence over legacy positions;
offset-only walls are resolved against the supplied particle extent. Both PEG
setup and composed-run/Live requests carry `plane_point_nm` and `tangent_u`.
Run writers, deposition placement/forces, plane equality and persisted run metadata
use the shared adapter. PEG generation retains the existing patch tangent when
one is supplied, and otherwise preserves its original deterministic basis.
Deposited NAMD seed recentering also retains explicit oblique planes and off-center
pore locations. The existing sidebar still offers Cartesian controls; explicit
oblique descriptors are currently API inputs.

### 3. PEG source extraction — implemented; target chemistry/mapping still required

`POST /api/oxdna/peg/namd-seed` accepts:

```json
{"source_job_id": "666f5b417cee", "target_representation": "coarse_grained"}
```

The representation may be `coarse_grained`, `atomistic`, or omitted. This is a
read-only source review, never a launch-readiness assertion. `core/peg_seed_source.py`:

- Selects the latest available relaxed checkpoint and records its stage.
- Validates counts, finite complete particle records, the DNA topology against the
  frozen design snapshot, PEG chain connectivity/type, and graft/terminal identities.
- Maps every DNA particle to its design key and every PEG particle to its chain.
- Retrieves graft references from persisted trap anchors, or from the initial
  configuration and compact `trap_particles` metadata. Relaxed bead positions are
  never substituted for fixed graft references.
- Hashes the design, topology, checkpoint, initial configuration when used, and run
  configuration; detects source-file changes during inspection.
- Makes DNA connectivity and grafted PEG chains whole before common transforms.
  `transformed_peg_source` retains identities and records rotation, translation,
  source box, transformed cell vectors/origin and the explicit nm→Å factor.

`read_configuration_full_unwrapped(..., n_trailing_extra=...)` now excludes
appended PEG from DNA indexing. Production NAMD seed preflight and reconstruction
reject PEG sources until a complete target adapter exists, including sources whose
old UI toggle was disabled. They cannot silently discard the coating.

**Still blocked on scientific inputs:** target PEG representation, chemical chain
length/end groups for an atomistic target, target particle/atom mapping, PSF/PDB and
parameter assets, and validated DNA/PEG/surface cross interactions. The existing
`experiments/peg_namd/assets.example.json` contains null PEG/surface assets; its gold
surface cannot stand in for graphene or a hard wall. Statistical segments cannot
be assigned atom identities or chemical repeat counts from `segments` alone.
The API reports `target_representation`, `target_mapping`, `target_assets`, and
`engine_validation` barriers as applicable; target atom/particle mappings remain
explicitly null. See [the seed audit](peg_namd_seed_plan.md).

### 4. Whole-chain periodic unwrapping — implemented

`surface_periodic.unwrap_chains` accepts explicit ordered chain indices and an
orthorhombic box. Chains must partition the supplied points exactly once. Grafted
roots select the image nearest their recorded graft; subsequent beads follow
minimum-image bonds. Free roots retain their recorded image. There is no independent
chain-centroid alignment.

`unwrap_connected` handles explicit DNA connectivity, rejecting periodic winding
cycles instead of stretching a closing bond. Half-cell ambiguities, invalid cells,
invalid indices and nonfinite coordinates fail explicitly. DNA adjacency comes
from the existing design backbone/base-pair graph. Disconnected DNA components
retain their source root images; absolute intercomponent images cannot be inferred
without additional references. These are explicit representability limits, not
silent placement guesses.

### 5. Graphene clearance and coating registration — implemented

Finite graphene retains its existing clearance-distance and side-selection policy.
Its resulting translation now moves the plane, pore, grafts and PEG coordinates
together through `translate_coated_surface`, and refreshes `position_nm` for
Cartesian surfaces. Explicit patch tangents are respected. Periodic tiling likewise
carries attached coordinates through the PDB recentering translation. This does not
add new atomistic PEG placement or change graphene interaction parameters.

### 6. Molecular/engine validation — tests prepared; session still required

`tests/test_surface_engine_validation.py` adds user-session-only CPU/CUDA checks
that the PEG barrier force rotates with the surface and matches the unrotated
harmonic force. Existing molecular seed-recentering and PEG Live engine tests
remain under the same guard. No session marker or test guard was changed.

`CLAUDE.md` requires: “Heavy tests … run only in a user-opened `just test-session`.”
The user must open that session in their terminal. The focused commands are:

```bash
just test-slow tests/test_surface_engine_validation.py tests/test_peg_live.py
just test-slow tests/test_oxdna_relaxation.py -k recenters
```

An implementation or an engine import is not a physical-validation result. Full
atomistic PEG/graphene validation additionally depends on the target assets above.

## Review artifact

```bash
uv run python scripts/review_surface_transforms.py workspace/PEG_surface_review.nadoc \
  --output /tmp/nadoc-surface-barriers-review
```

The read-only review uses the same native oxDNA seed convention as job preparation,
without launching an engine. It renders source, transformed and inverse-overlay
views and reports inverse-coordinate and signed-distance errors. A run against the
representative saved PEG `.nadoc` was visually inspected: 32 DNA particles, 36 PEG
beads, maximum inverse error `2.22e-15 nm`, maximum plane-distance delta `8.88e-16 nm`.
The actual existing review job `666f5b417cee` was separately inventoried through its
latest `4_peg_production` checkpoint (four PEG chains); source files were read only.

## Verification (2026-09-11)

- Final focused surface/source/setup/Live/graphene checks: **133 passed**;
  four slow engine tests deselected by the guard.
- Latest `just test-smart` decision: **FAST**. **8214 passed, 109 skipped,
  11 failed**; the failures are the existing missing `BigO.nadoc`,
  `BigO-poly.nass`, and `smallO-poly.nass` fixtures in assembly/CanDo tests.
- Live backend request to `/api/oxdna/peg/namd-seed` for the existing PEG review job:
  HTTP 200, `source_review`, `launch_ready=false`.
- New modules/tests/review script pass Ruff; whitespace checks pass. The existing
  unused `seq` assignment in `routes_oxdna.py` remains a lint issue. No frontend
  code changed (`main.js` LOC delta: 0).
- Engine-validation session was expired. The test selector reported verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

Production oxDNA was running, so the guard suppressed timing-budget enforcement.
No guard, session marker, geometry lock, or visual golden was changed.

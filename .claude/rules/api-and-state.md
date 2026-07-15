---
name: api-and-state
description: Backend API mutation flow + routes index, frontend api client, undo/redo, stale-state diagnostics.
paths:
  - "backend/api/**/*.py"
  - "frontend/src/api/**/*.js"
---

# api-and-state

## Architecture

## Frontend: api/client.js
- All mutations call `_request(method, path, body)`
- On success: `_syncFromDesignResponse(json)` → `store.setState({currentDesign, validationReport, ...})`
- If `json.nucleotides` present: geometry embedded → single store update → single renderer rebuild
- If not: `getGeometry()` called separately (second round-trip)
- On error: `store.setState({ lastError: {status, message} })`; function returns `null`

## Backend: state.py
```python
mutate_and_validate(fn):
    [lock] _history.append(design.model_copy(deep=True))  # snapshot for undo
    [lock] _redo.clear()
    [lock] fn(_active_design)                              # mutate in-place
    [lock] report = validate_design(_active_design)
    return (_active_design, report)

set_design_silent(d):
    # Updates active design WITHOUT undo push
    # Use for intermediate steps inside snapshot() bracket

snapshot():
    # Push current design to undo stack WITHOUT changing it
    # Use BEFORE first step of multi-step op → entire op = single Ctrl-Z

undo() / redo(): standard stack swap, validates after
clear_history(): called on new bundle creation / new design load
```

## Backend: crud.py → state.py flow
```
HTTP request
  → FastAPI route handler
  → design = state.get_or_404()
  → state.mutate_and_validate(lambda d: modify_in_place(d))
  → _design_response(design, report)
     OR _design_response_with_geometry(design, report)  ← single round-trip
  → JSON response
```

## Response Shape
```json
{
  "design": { ... },          // full Design object
  "validation": { ... },      // ValidationReport
  "nucleotides": [ ... ],     // optional — geometry embedded
  "helix_axes": { ... }       // optional — helix axis endpoints
}
```

## Stale Server State Rule
If Python-level test shows correct output but `curl http://localhost:8000/api/...` returns wrong result → **stop debugging, ask user to reset the server**. Do NOT add logging or dig further into backend Python. The uvicorn `--reload` server keeps `design_state` in memory across requests; prior test ops leave stale state.

## Multi-Step Operation Pattern
```python
state.snapshot()                      # bracket: push undo checkpoint
state.set_design_silent(step1(d))     # step 1 — no undo push
state.set_design_silent(step2(d))     # step 2 — no undo push
design, report = state.mutate_and_validate(step3)  # step 3 — validate
# Result: entire op = single Ctrl-Z from user's perspective
```

## Key Files
- `frontend/src/api/client.js` — `_request()`, `_syncFromDesignResponse()`, all API functions
- `backend/api/state.py` — `mutate_and_validate`, `set_design_silent`, `snapshot`, `undo`, `redo`
- `backend/api/crud.py` — route handlers, `_design_response`, `_design_response_with_geometry`
- `backend/core/validator.py` — `validate_design(design)` → `ValidationReport`

## Diagnostics → [.claude/runbooks/RUNBOOK_API.md](../runbooks/RUNBOOK_API.md)

## Routes index

## Design Management
- `GET /design` — active design + validation report
- `POST /design` — create new empty design
- `PUT /design/metadata` — update name/description/author/tags
- `GET /design/export` — download .nadoc JSON
- `POST /design/load` — load .nadoc from server path
- `POST /design/undo` — revert to previous state
- `POST /design/redo` — re-apply last undone change
- `GET /design/geometry` — full nucleotide positions + helix axes
- `GET /design/surface` — surface rendering data

## Bundle Creation
- `POST /design/bundle` — create HC/SQ bundle (cells, length_bp, lattice_type)
- `POST /design/bundle-segment` — append segment (slice-plane extrude)
- `POST /design/bundle-continuation` — extend bundle (continuation mode)
- `POST /design/bundle-deformed-continuation` — extend using deformed cross-section frame
- `GET /design/deformed-frame` — deformed frame at source_bp

## Helices
- `GET /design/helices` — list all helices
- `POST /design/helices` — add helix
- `GET /design/helices/{id}` — helix + geometry
- `PUT /design/helices/{id}` — replace helix
- `DELETE /design/helices/{id}` — delete (409 if referenced)

## Strands & Domains
- `POST /design/strands` — add strand
- `PUT /design/strands/{id}` — replace strand
- `DELETE /design/strands/{id}` — delete strand
- `DELETE /design/strands/batch` — delete multiple atomically
- `PATCH /design/strand/{id}` — patch strand properties
- `POST /design/strands/{id}/domains` — append domain
- `DELETE /design/strands/{id}/domains/{idx}` — remove domain

## Automatic Routing
- `POST /design/prebreak` — nick at canonical grid positions (idempotent)
- `POST /design/auto-scaffold` — auto-generate scaffold strand
- `POST /design/auto-merge` — merge adjacent staple fragments
- `POST /design/scaffold-nick` — nick scaffold at bp
- `POST /design/scaffold-extrude-near` — extrude scaffold from near end
- `POST /design/scaffold-extrude-far` — extrude scaffold from far end
- `POST /design/strand-end-resize` — resize strand domain endpoints (drag arrows)

## Nicks & Modifications
- `POST /design/nick` — add nick
- `POST /design/nick/batch` — add multiple nicks atomically
- `POST /design/loop-skip/insert` — insert loop/skip (delta=0 removes)
- `POST /design/loop-skip/bend` — bend via loop/skip strain
- `POST /design/loop-skip/twist` — twist via loop/skip strain
- `POST /design/loop-skip/apply-deformations` — convert DeformationOps → LoopSkip entries
- `GET /design/loop-skip/limits` — min/max values

## Deformations (Bend/Twist)
- `POST /design/deformation` — add bend/twist op (push undo; ?preview=true = no undo)
- `PATCH /design/deformation/{id}` — update params (no undo push)
- `DELETE /design/deformation/{id}` — remove op

## Overhangs & Extensions
- `PATCH /design/overhang/{id}` — update overhang (sequence, label)
- `POST /design/overhang/extrude` — create single-stranded overhang
- `POST /design/extensions` — add 5'/3' strand extension
- `POST /design/extensions/batch` — upsert multiple extensions
- `PUT /design/extensions/{id}` — replace extension
- `PATCH /design/extensions/{id}` — partial update
- `DELETE /design/extensions/{id}` — remove
- `DELETE /design/extensions/batch` — remove multiple

## Clusters & Camera
- `POST /design/cluster` — create cluster
- `PATCH /design/cluster/{id}` — update transform
- `POST /design/cluster/{id}/begin-drag` — start interactive drag
- `DELETE /design/cluster/{id}` — remove
- `POST /design/camera-poses` — add camera pose
- `PATCH /design/camera-poses/{id}` — update pose
- `PUT /design/camera-poses/reorder` — reorder list
- `DELETE /design/camera-poses/{id}` — remove

## Configurations & Animations
- `POST /design/configurations` — add cluster config snapshot
- `PATCH /design/configurations/{id}` — update
- `PUT /design/configurations/reorder` — reorder
- `DELETE /design/configurations/{id}` — remove
- `POST /design/animations` — create animation
- `PATCH /design/animations/{id}` — update
- `POST /design/animations/{id}/keyframes` — add keyframe
- `PATCH /design/animations/{id}/keyframes/{kf_id}` — update keyframe
- `PUT /design/animations/{id}/keyframes/reorder` — reorder
- `DELETE /design/animations/{id}` — remove
- `DELETE /design/animations/{id}/keyframes/{kf_id}` — remove keyframe

## Sequences & Export
- `POST /design/assign-scaffold-sequence` — assign M13/p7560/p8064
- `POST /design/assign-staple-sequences` — Watson-Crick complements
- `POST /design/import` — import design from JSON/NADOC
- `POST /design/import/cadnano` — import caDNAno v2 JSON
- `GET /design/export/cadnano` — export to caDNAno v2 JSON
- `GET /design/export/sequence-csv` — CSV of strand sequences
- `GET /design/export/pdb` — PDB file (coarse-grained)
- `GET /design/export/psf` — PSF topology (NAMD)
- `GET /design/export/namd-complete` — full NAMD simulation bundle (.zip)
- `GET /design/atomistic` — all-atom coordinates
- `POST /design/oxdna/export` — oxDNA input files
- `POST /design/snapshot` — push current state to undo stack

## Debug
- `GET /design/debug/strand-stats` — strand length/type/sequence stats (diagnostic use — see `RUNBOOK_API.md`)

## Multi-Step Op Pattern (correct)
```python
state.snapshot()                           # one undo step for entire op
state.set_design_silent(step_1_result)
state.set_design_silent(step_2_result)
design, report = state.mutate_and_validate(step_3_fn)
```

## Files to Read
- `backend/api/state.py` — `mutate_and_validate`, `set_design_silent`, `snapshot`, `clear_history`
- `backend/api/crud.py` — find the route handler, check which state functions it uses
- `frontend/src/api/client.js` — `_syncFromDesignResponse()`, error handling

## Related
- `MAP_API_FLOW.md` — full API mutation flow


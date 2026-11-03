# Test-design builders — `tests/conftest.py` — supporting detail

[Topic head](../../project_headless_build.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Test-design builders — `tests/conftest.py`

`make_teeth_design` / `make_6hb_design` / `make_18hb_design` /
`make_mini_hinge_base_design` + the general `build_extruded_bundle` (delegates to
`headless_build.build_bundle`). Cell layouts lifted verbatim from real designs'
feature logs (cited per constant) — never hand-derived (topology "ask first").

These rebuild common bundles from their own 6-op (teeth) / 1-op feature logs.
Replaces opening committed `.nadoc` blobs, killing the fixture-mutation
corruption surface. Pinned in `tests/test_section_router.py`:
`test_teeth_builder_matches_fixture` (canonical topology + identical
seamed/seamless routed output) and `test_18hb_builder_matches_fixture`. teeth
and 18hb have clean single-construction references; 6hb / mini_hinge-base do not
(real files carry extra routing/overhang ops), so they're construction-validated
+ visual only. mini_hinge here is the **base bundle only** (two 4×2 SQUARE
blocks → 2 clusters); the file's routing/flexible/overhang steps are not replayed.

Visual-validation tiles (gitignored scratch): `workspace/builder_tests/*.nadoc`
+ `builder_validation.png` (cross-sections + axial profiles). Regenerate from the
conftest makers.

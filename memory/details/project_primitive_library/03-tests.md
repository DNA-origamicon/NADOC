# Tests — supporting detail

[Topic head](../../project_primitive_library.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Tests

- Backend `tests/test_primitives_router.py` (9): derive_metadata (incl. stem
  ignore), scan/sort/skip-broken/asset-flags, list + asset-serve + 404 + safe-id.
- Frontend: `primitive_catalog.test.js`, `primitive_library.test.js` (fallback →
  API upgrade, poster thumb, hover swap, selection survives re-render),
  `primitive_preview_capture.test.js` (buildCameraPath).

# Element visibility

NADOC uses one base-addressed visibility system for individual nucleotides,
domains, strands, groups, and clusters. Higher-level selections are expanded to
nucleotide keys by `frontend/src/scene/visibility_controller.js`; the resulting
set drives the full, bead, cylinder, atomistic, and surface renderers as well as
crossover arcs, crossover extra bases, and strand extensions.

## Persistence

Visibility is display metadata, not a topology operation. A design stores a
`visibility_state` object containing:

- `hidden_base_keys`: explicitly hidden nucleotide addresses.
- `shown_base_keys`: explicit exceptions to a hidden cluster.
- `hidden_cluster_ids`: clusters whose current nucleotides should be hidden.

Old `.nadoc` files default to empty lists. `PUT /api/design/visibility` replaces
the display state without adding a feature-log entry or rebuilding geometry.
Hide, show, visibility undo/redo, and Unhide All are serialized through this
endpoint so rapid actions cannot arrive out of order. Explicit saves and Close
Session wait for pending visibility writes before writing the `.nadoc` file.
Unhide All also fits the restored full structure using the finite-safe camera
path, so an older poisoned/off-structure camera cannot leave restored elements
apparently missing.

On load, the controller hydrates metadata before geometry is available and
reapplies it after renderer meshes are rebuilt. Initial hydration deliberately
does not notify sidebar consumers that have not yet completed startup.

## Camera and reload safety

Hidden instanced objects are represented with zero-scale matrices. Fit-to-view
therefore uses raw nucleotide positions rather than renderer object bounds. The
camera calculation also rejects non-finite bounds and recovers a non-finite or
zero-length camera direction with a known forward direction. This prevents a
poisoned `NaN` camera/orbit target from surviving close-and-reopen and making a
healthy design appear empty.

Close Session follows this order for parts:

1. Drain pending visibility persistence.
2. Save the active workspace file.
3. Reset renderers, camera, controls, and store state.
4. Close the backend document and show the library.

## Regression coverage

- `frontend/src/scene/visibility_controller.test.js` covers expansion,
  persistence ordering, hydration, cluster re-expansion, and visibility history.
- `frontend/src/scene/fit_view_math.test.js` covers recovery from a non-finite
  camera and rejection of invalid bounds.
- `tests/test_visibility_persistence.py` covers old-file defaults, JSON/file
  round trips, and the absence of feature-log entries.
- `frontend/e2e/strand_visibility.spec.js` uses `2hb_2xT.nadoc` to verify strand
  rendering across representations and the library workflow: hide, close the
  session immediately, reopen the same part, retain hidden state, display the
  remaining geometry, recover orbit controls, and unhide successfully.

# Clusters exclude reference geometry (2026-05-23) — supporting detail

[Topic head](../../project_reference_geometry.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Clusters exclude reference geometry (2026-05-23)
Reference geometry must never be a cluster member or enter cluster/deformation
calculations — it's a fixed backdrop at its BASE (topological) position, immune to
cluster joints/drags AND deformations. Mechanism = MEMBERSHIP exclusion (not a
per-helix application-time filter — `_clusters_for_helix` is in the geometry hot path,
too costly to check per call):
- `Design.reference_helix_ids()` (models.py) = helices with ≥1 reference domain and 0
  active domains (reference-ONLY; a mixed active+ref helix is NOT excluded — the active
  part needs it; ref rows on it still get cluster transforms = mixed-helix caveat).
- `_ensure_default_cluster` (crud.py) excludes ref helices from the default cluster.
- `cluster_reconcile._compute_helix_membership` drops ref-only helices from `kept` and
  never assigns new ref helices → every mutation keeps clusters clean.
- `patch_strands_reference` route PRUNES ref-only helices from `helix_ids` and reference
  strands' `DomainRef`s from `domain_ids` of every cluster (immediate effect on toggle).
- `deformation._arm_helices_for` excludes ref helices (unioned into `overhang_helix_ids`)
  so the bend/twist bundle centroid/tangent isn't skewed by the frozen reference part.
- **Autodetect builders (`_autodetect_clusters` + `_cluster_by_*`) were NOT changed** —
  they only run on cadnano/scadnano IMPORT, and imported designs have no reference strands
  (the user marks reference afterward). Reconcile + toggle-prune cover the post-import flow.
- All guarded by empty `reference_helix_ids()` → ZERO behavior change for reference-free
  designs (verified: full suite green vs the 2 pre-existing teeth-fixture failures).
- Side effect: marking a cluster-POSED part reference snaps it to base (loses the pose),
  because membership exclusion drops it from the transform. Acceptable — reference parts
  are normally imported with identity cluster transforms. Loaded `.nadoc` with a ref helix
  saved inside a cluster keeps it until the next toggle/mutation (no prune-on-load — would
  violate native-load preserve-positions).

## Route + payload
`PATCH /design/strands/reference {strand_ids, is_reference}` → returns
partial compact geometry for only the toggled strands' real helices (NOT metadata-only —
the freeze can move those nucleotides). Synthetic `__lnk__` bridge helices need no
geometry response. The route also slims old feature-log bodies, so large designs do not
re-ship their entire recovery history. On `VoltronCoreArm.nadoc` this reduced the measured
request from ~3.28 s + 394 ms browser JSON parse to ~0.22 s and ~0.74 MB. The frontend
patches the retained renderer in place, refreshes its reference ID/alpha state immediately,
and completes operation timing after the next paint (no reload or fallback-timeout wait).
`op_subtype='strands-reference'` had to be ADDED to the `MinorMutationLogEntry`
Literal in models.py (~line 1098) — forgetting it 500s the route. Per-nucleotide
`is_reference` added to `_strand_nucleotide_info` payload.

Same-path workspace autosaves now return acknowledgment metadata only. The frontend already
discarded the returned design for `identity_disposition='confirmed'`; omitting that multi-MB
body avoids a second unnecessary parse. Simulation recommendation/job-list refreshes are
likewise gated to the open, expanded Simulations tab rather than running after every edit.

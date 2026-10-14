"""Explore, create and edit Sweep through the native document transactions.

Request options are validated by ``SweepRequest`` itself, so authored point
orientations, movable origins, detachment, identity and optimistic guards have
the same defaults and behavior as desktop/VR. No geometry is computed here.
Like the original ``headless_build.sweep``, these functions return the native
response dictionaries; the committed Design remains in the active document.
"""

from fastapi import HTTPException

from backend.api import state
from backend.api.crud import EditFeatureBody, edit_feature
from backend.api.routes_sweep import create_sweep as _create_sweep
from backend.api.routes_sweep import preview_sweep as _preview_sweep
from backend.core.sweep import SweepRequest


def sweep(cells, points_nm, **options) -> dict:
    """Create an editable Sweep, returning the native creation response.

    ``options`` accepts every remaining :class:`SweepRequest` field:
    ``sweep_id``, ``orientations_deg``, ``plane``, ``strand_filter``,
    ``ligate_adjacent``, ``source_helix_id``, ``source_end``, ``detach_source``,
    ``expected_design_id`` and ``expected_revision``. Unknown fields fail native
    request validation instead of being ignored.

    Points are world-nm offsets in the native Sweep reference frame. A new
    origin may move and rotate. Moving an attached origin detaches it through
    the existing builder, preserving the source. Use :func:`preview_sweep`
    before committing; its revision can guard this mutation.
    """
    return _create_sweep(SweepRequest(cells=cells, points_nm=points_nm, **options))


def preview_sweep(
    cells, points_nm, *, feature_index=None, include_geometry=True, **options
) -> dict:
    """Read-only native preview, including feasibility, BP counts and revision.

    Accepts the same request options as :func:`sweep`. ``include_geometry=False``
    requests the native lightweight creation preview. ``feature_index`` previews
    a full edit request; :func:`preview_sweep_edit` is convenient for a patch to
    an existing feature and retains its saved attachment, orientation and ID.
    """
    return _preview_sweep(
        SweepRequest(cells=cells, points_nm=points_nm, **options),
        feature_index=feature_index,
        include_geometry=include_geometry,
    )


def _sweep_entry(feature_index):
    design = state.get_or_404()
    if not 0 <= feature_index < len(design.feature_log):
        raise HTTPException(404, detail="Sweep feature no longer exists")
    entry = design.feature_log[feature_index]
    if getattr(entry, "op_kind", None) != "sweep":
        raise HTTPException(422, detail="Select a sweep feature")
    return entry


def preview_sweep_edit(feature_index, **changes) -> dict:
    """Preview changed request fields without committing or advancing revision.

    Saved authored fields are retained, including an explicit detached-source
    state. Creation-time concurrency guards are not reused; supply current
    ``expected_design_id`` / ``expected_revision`` for this preview if needed.
    Geometry and downstream attachment/routing previews come from the native
    history evaluator. The feature's existing sweep identity is preserved by
    native editing even when a patch contains a different ``sweep_id``.
    """
    entry = _sweep_entry(feature_index)
    params = {
        k: v for k, v in entry.params.items()
        if k in SweepRequest.model_fields and k not in {"expected_design_id", "expected_revision"}
    }
    params.update(changes)
    params["sweep_id"] = entry.params["sweep_id"]
    return _preview_sweep(SweepRequest.model_validate(params), feature_index=feature_index)


def edit_sweep(feature_index, **changes) -> dict:
    """Commit a Sweep parameter patch through native feature editing.

    Preserves feature/helix identity, downstream operations and ordinary undo
    history. Pass ``expected_design_id`` and ``expected_revision`` to reject a
    stale draft. Returns the native replacement response, including placement
    warnings; native edit restrictions and validation errors are unchanged.
    """
    _sweep_entry(feature_index)
    return edit_feature(feature_index, EditFeatureBody(params=changes))

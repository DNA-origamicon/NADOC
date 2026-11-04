"""Apply optional import fitting through recorded user-facing group operations."""


def prepare(design, *, enabled):
    from backend.core.import_relaxation import relax_imported_design

    fitted, report = relax_imported_design(design, enabled=enabled)
    if report is None or report['status'] != 'applied':
        return design, report

    return record_fit(design, fitted), report


def record_fit(design, fitted):
    """Record the solver's absolute poses using ordinary authoring commands."""
    from backend.api import headless_build as author, state
    from backend.api.part_proof_commands import execute, dependencies
    from backend.core.part_history_contract import assess_part_history
    from fastapi import HTTPException

    # Work privately: a failed command/proof must not replace the active document.
    # The fit supplies absolute Move/Rotate inputs; replay never reruns a solver.
    with author.scratch_session():
        state.load_design(design)
        for group in fitted.cluster_transforms:
            current = state.get_or_404()
            identity = group.id
            if not any(owner.id == identity for owner in current.cluster_transforms):
                current = author.add_cluster(group.name, group.helix_ids,
                                             domain_ids=group.domain_ids)
                identity = current.cluster_transforms[-1].id
            author.transform_cluster(identity, translation=group.translation,
                                     rotation=group.rotation, pivot=group.pivot, log=True)
        recorded = state.get_or_404()
        proof = assess_part_history(recorded, execute=execute, dependencies=dependencies)
        if proof['status'] not in {'verified', 'reproduced_import'}:
            raise HTTPException(409, detail={"code": "import_relaxation_process_required",
                                            "message": "Relaxed import failed construction replay.",
                                            "issues": proof['issues']})
        return recorded


def apply_native():
    """One undoable publication for Relax Origami on an existing native recipe."""
    from backend.api import state
    from backend.api.part_group_recording import (
        capture_group_source, require_group_source_current, _publish,
    )
    from backend.core.origami_relax import relax_origami
    from fastapi import HTTPException

    admission = capture_group_source("relax_origami")
    try:
        fitted, report = relax_origami(admission.source)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    recorded = record_fit(admission.source, fitted)
    with state._lock:
        require_group_source_current(admission)
        updated, validation = _publish(admission.session, admission.source,
            admission.revision, admission.identity, recorded)
    return updated, validation, report

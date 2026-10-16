"""Record routing against a source owned by its mutation transaction.

The existing recorders own undo, reconciliation, retry and publication. Expensive
automatic routing uses a detached capture and rejects a changed source at commit.
"""

from uuid import uuid4

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api.feature_recording import record_feature, record_minor
from backend.api.part_ligation_commands import build
from backend.api.part_command_references import build_strict_nick_batch, validate_command_references
from backend.core.part_command_errors import ReferenceResolutionError


def record_auto_crossover():
    """Build privately outside the lock, then record only the captured source.

    This deliberately adds one full source copy to the recorder's undo copy.
    It does not impose a new capture budget or make a latency guarantee.
    """
    from backend.api.part_auto_commands import crossovers

    with state._lock:
        policy_generation = state._require_compatibility_write("auto_crossover").generation
        session = state._session()
        source = session.design
        if source is None:
            raise HTTPException(404, detail="No active design.")
        state._assert_active_loadout_editable(source)
        doc_id = doc_context.get_current_doc()
        revision, identity = session.revision, session.identity
        captured = state._snapshot_copy(source)
        history_seed = str(uuid4())

    updated, stats = crossovers(captured, history_seed=history_seed)

    with state._lock:
        current_policy = state._require_compatibility_write("auto_crossover")
        if (doc_context.get_current_doc() != doc_id
                or state._sessions.get(doc_id) is not session
                or session.identity != identity or session.revision != revision
                or session.design is not source
                or current_policy.generation != policy_generation):
            raise HTTPException(409, detail="Automatic crossover source changed before recording.")
        state._assert_active_loadout_editable(source)

        def native(design):
            if design is not source:
                raise HTTPException(409, detail="Automatic crossover source changed before recording.")
            return updated

        current, report, _entry = record_feature(
            session, "auto-crossover", "Auto-crossover",
            {"history_seed": history_seed, "sites_considered": stats["sites_considered"],
             "placed": stats["placed"]}, native,
        )
        return current, report, stats


def record_forced_ligation(body):
    """Return the recorded design, validation and original affected-helix scope."""
    from backend.api.crud import _helix_label

    with state._lock:
        state._require_compatibility_write("forced_ligation")
        session = state._session()
        source = session.design
        if source is None:
            raise HTTPException(404, detail="No active design.")
        state._assert_active_loadout_editable(source)
        doc_id = doc_context.get_current_doc()
        revision, identity = session.revision, session.identity

        first = source.find_strand(body.three_prime_strand_id)
        second = source.find_strand(body.five_prime_strand_id)
        if first is None:
            raise HTTPException(404, detail=f"3' strand {body.three_prime_strand_id!r} not found.")
        if second is None:
            raise HTTPException(404, detail=f"5' strand {body.five_prime_strand_id!r} not found.")
        if first.id == second.id:
            raise HTTPException(
                409, detail="Cannot ligate a strand to itself (would create circular strand).",
            )

        three_dom, five_dom = first.domains[-1], second.domains[0]
        label = (
            f"Forced ligation · h{_helix_label(source, three_dom.helix_id)}:{three_dom.end_bp} "
            f"→ h{_helix_label(source, five_dom.helix_id)}:{five_dom.start_bp}"
        )
        # Ligation retags nucleotide ownership without moving it. Extensions
        # can be dropped/remapped by the native builder and need a full response.
        touches_extension = any(ext.strand_id in (first.id, second.id) for ext in source.extensions)
        changed_helix_ids = (
            None if touches_extension
            else list({domain.helix_id for domain in (*first.domains, *second.domains)})
        )
        params = {**body.model_dump(mode="json"), "_fl_id": str(uuid4())}

        def native(design):
            if (doc_context.get_current_doc() != doc_id
                    or state._sessions.get(doc_id) is not session
                    or session.identity != identity or session.revision != revision
                    or session.design is not source or design is not source):
                raise HTTPException(409, detail="Forced ligation source changed before recording.")
            return build("forced-ligation-create", design, params)

        updated, report, _entry = record_minor(
            session, "forced-ligation-create", label, params, native,
        )
        return updated, report, changed_helix_ids


def record_nick_batch(body):
    """Record every requested nick or reject the batch without partial effects."""
    return _record_checked_batch("nick-batch", body)


def record_strand_end_resize(body):
    """Require each selected strand end to belong to its declared live helix."""
    return _record_checked_batch("strand-end-resize", body)


def _record_checked_batch(kind, body):
    from backend.api.crud import _build_strand_end_resize
    from backend.core.lattice import _find_strand_at

    with state._lock:
        state._require_compatibility_write(kind)
        session = state._session()
        source = session.design
        if source is None:
            raise HTTPException(404, detail="No active design.")
        state._assert_active_loadout_editable(source)
        doc_id = doc_context.get_current_doc()
        revision, identity = session.revision, session.identity
        params = body.model_dump(mode="json")
        n = len(body.nicks) if kind == "nick-batch" else len(body.entries)
        label = (f"{n} nick{'s' if n != 1 else ''} (batch)" if kind == "nick-batch"
                 else f"Resize {n} strand end{'s' if n != 1 else ''}")
        changed_helix_ids = None

        def native(design):
            nonlocal changed_helix_ids
            if (doc_context.get_current_doc() != doc_id
                    or state._sessions.get(doc_id) is not session
                    or session.identity != identity or session.revision != revision
                    or session.design is not source or design is not source):
                raise HTTPException(409, detail="Routing source changed before recording.")
            if kind == "nick-batch":
                updated = build_strict_nick_batch(design, params)
                # A cross-helix split retags every domain in the original strand.
                # Derive the response scope from the same source used by the
                # successful sequential builder, not an earlier unlocked read.
                changed = set()
                for nick in body.nicks:
                    strand, _ = _find_strand_at(
                        design, nick.helix_id, nick.bp_index, nick.direction,
                    )
                    changed.update(domain.helix_id for domain in strand.domains)
                changed_helix_ids = list(changed) if changed else None
            else:
                updated = _build_strand_end_resize(design, body)
                changed_helix_ids = list({entry.helix_id for entry in body.entries})
            return updated

        try:
            # Missing/invalid references are cheap to reject before snapshotting.
            # Sequential nick applicability remains inside the atomic recorder.
            validate_command_references(kind, source, params)
            updated, report, _entry = record_minor(session, kind, label, params, native)
        except ReferenceResolutionError as exc:
            raise HTTPException(
                404 if exc.code == "missing_reference" else 422, detail=exc.as_issue(),
            ) from exc
        return updated, report, changed_helix_ids

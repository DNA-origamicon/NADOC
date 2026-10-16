"""Record forced ligation against the source owned by its mutation transaction.

The existing minor recorder owns snapshots, reconciliation, retry and publication.
Only selection, authored identity and partial-response scope are prepared here.
"""

from uuid import uuid4

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api.feature_recording import record_minor
from backend.api.part_ligation_commands import build


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

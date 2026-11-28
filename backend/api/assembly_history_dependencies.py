"""Read-only bounded dependency inspection for a captured assembly revision."""
from time import monotonic
from fastapi import HTTPException

from backend.api import assembly_state
from backend.core.assembly_dependencies import dependencies
from backend.core.part_dependencies import DependencyIndex


def current_dependencies():
    # Only small saved-input headers are read. No source design traversal,
    # geometry, snapshot decoding or command execution belongs in this route.
    with assembly_state._lock:
        session = assembly_state._session()
        source = session.assembly
        if source is None:
            raise HTTPException(404, detail='No active assembly')
        deadline = monotonic() + .5
        graph, features = DependencyIndex(), []
        for position, entry in enumerate(source.feature_log):
            if position >= 10000 or monotonic() > deadline:
                raise HTTPException(413, detail='Assembly dependency inspection exceeds its bounded allowance')
            if not isinstance(entry.id, str) or not entry.id or len(entry.id) > 512:
                raise HTTPException(409, detail='Invalid history feature identity')
            contract = dependencies(getattr(entry, 'op_kind', None), getattr(entry, 'params', None), suppressed=entry.suppressed)
            try:
                graph.append(entry.id, contract)
            except ValueError as error:
                raise HTTPException(409, detail='Assembly history feature identities are ambiguous') from error
            features.append({'id': entry.id, 'row_index': position,
                'label': str(getattr(entry, 'label', None) or getattr(entry, 'op_kind', None) or entry.feature_type)[:256],
                'known': contract.known, 'conservative': contract.barrier or not contract.known,
                'suppressed': entry.suppressed})
        for feature in features:
            feature.update(parents=sorted(graph.parents[feature['id']]), children=sorted(graph.children[feature['id']]))
        return {'assembly_id': source.id, 'revision': session.revision, 'complete': graph.complete, 'features': features}

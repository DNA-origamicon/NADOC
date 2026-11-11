"""Independent verification of semantic document operations and every branch."""
from backend.core.document_operations import (
    apply_metadata_edits, branch_value, content_digest, verify_document, replay,
)
from backend.core.document_revision_evidence import verify as verify_revision
from backend.core.design_loadouts import decode_snapshot
from backend.core.part_history_contract import PartRecipeRoot
from backend.core.part_history_proof import root_design
from experiments.recorded_review_process import Process, ProcessRequired, verify


def _replay_input(source, edits, design):
    from backend.core.models import Design
    if set(source) != {'root', 'input_sources', 'commands', 'state_sha256'}:
        raise ProcessRequired('Document operation lacks its exact construction inputs')
    root = PartRecipeRoot.model_validate(source['root'])
    if root.kind != 'empty':
        raise ProcessRequired('Document source requires native construction')
    process = Process(root.initial_name, root.lattice_type)
    process.design = Design.model_validate(root_design(root, input_sources=source['input_sources']).model_dump())
    for command in source['commands']:
        if set(command) != {'id', 'kind', 'params'}:
            raise ProcessRequired('Invalid document construction input')
        if command['kind'] == 'diagnostic-process' or command['kind'].startswith('assembly-'):
            raise ProcessRequired('Document input is not a user-facing part operation')
        process.apply(command['kind'], command['params'])
    replayed = apply_metadata_edits(process.design, edits)
    from scripts.agent_schema_receipts import matches_source_receipt
    expected = branch_value(replayed)
    if (content_digest(expected) != source['state_sha256']
            and not matches_source_receipt(design, expected, source['state_sha256'])):
        raise ProcessRequired('Document operation source does not independently reproduce')


def verify_inputs(design):
    prefix, commands = [], 0
    if len(design.document_history) > 2000:
        raise ProcessRequired('Document operation allowance exceeded')
    for entry in design.document_history:
        sources = [(entry.source_recipe, replay(prefix)['metadata'])]
        if entry.kind == 'loadout-select' or (entry.kind == 'loadout-delete' and entry.params['target_recipe'] is not None):
            sources.append((entry.params['target_recipe'], entry.params['target_metadata']))
        for source, metadata in sources:
            if design.recipe_root is None or source.get('root') != design.recipe_root.model_dump(mode='json'):
                raise ProcessRequired('Document operation input belongs to a different recipe root')
            commands += len(source.get('commands', []))
            if commands > 10000:
                raise ProcessRequired('Document source replay allowance exceeded')
            _replay_input(source, metadata, design)
        prefix.append(entry)


def audit(design, audit_part):
    try:
        verify_inputs(design)
        if not design.loadouts:
            # Metadata-only operations have no wrapper to materialize.
            verify_document(design)
            return verify(design)
        verify_document(design)
        if any(branch.protected or branch.simulation_engine or branch.simulation_job_id
               for branch in design.loadouts):
            raise ProcessRequired('Protected simulation loadout provenance is not implemented')
        bare = design.model_copy(update={'loadouts': [], 'active_loadout_id': None,
                                        'last_editable_loadout_id': None})
        result = verify(bare)
        for branch in design.loadouts:
            snapshot = decode_snapshot(branch.design_snapshot_gz_b64)
            if snapshot.id != design.id or snapshot.recipe_root != design.recipe_root:
                raise ProcessRequired('Loadout snapshot belongs to a different document')
            if snapshot.loadouts or snapshot.active_loadout_id is not None:
                raise ProcessRequired('Nested loadout wrapper is not a branch construction')
            # Audit the exact saved branch independently, including all physical fields.
            audit_part(snapshot.model_copy(update={'last_editable_loadout_id': None}), document=False)
            from scripts.agent_schema_receipts import raw_snapshot
            if branch.snapshot_size_bytes != len(raw_snapshot(branch.design_snapshot_gz_b64)):
                raise ProcessRequired('Loadout snapshot size does not match its contents')
            verify_revision(design, branch, snapshot)
            if branch.id == design.active_loadout_id and branch_value(snapshot) != branch_value(design):
                raise ProcessRequired('Active loadout snapshot is stale; persist the current branch')
        return {**result, 'document_operations': len(design.document_history),
                'loadouts_checked': len(design.loadouts)}
    except ProcessRequired:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise ProcessRequired(str(exc)) from exc

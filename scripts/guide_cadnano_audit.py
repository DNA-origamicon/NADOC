"""Verify the complete source-part → UI cadnano export → imported-part chain.

The two part histories remain separate, as in the user's actual workflow.
The source is never replaced by the import root. Retain the example family.
"""
import hashlib
import json
from backend.core.models import Design
from backend.core.cadnano import export_cadnano
from backend.core.part_input_sources import EmbeddedResolver, InputSource
from scripts.agent_structure_guard import audit, publish
from experiments.recorded_review_process import ProcessRequired


def publish_source(source_file, imported, export_file, directory):
    source = Design.model_validate_json(source_file.read_text())
    source_proof = publish(source, directory / 'source.nadoc')
    reopened = Design.model_validate_json((directory / 'source.nadoc').read_text())
    audit(reopened)
    raw = export_file.read_bytes()
    expected = json.dumps(export_cadnano(reopened), separators=(',', ':')).encode('utf-8')
    if raw != expected:
        raise ProcessRequired('cadnano download differs from export of replay-audited source part')
    if not imported.feature_log or imported.feature_log[0].op_kind != 'cadnano-import':
        raise ProcessRequired('Expected recorded import as first feature of the derived part')
    row = imported.feature_log[0]
    descriptor = InputSource.model_validate(row.params['source'])
    if EmbeddedResolver(imported.input_sources)(descriptor) != raw:
        raise ProcessRequired('Imported part does not pin the audited source export bytes')
    audit(imported)
    return {'status': 'verified', 'source_publication': {**source_proof, 'path': 'source.nadoc'},
            'source_part': 'source.nadoc', 'export': '6hb84-cadnano.json',
            'export_sha256': hashlib.sha256(raw).hexdigest(),
            'export_operation': 'GET /api/design/export/cadnano',
            'import_operation': row.op_kind, 'import_source': descriptor.model_dump(mode='json'),
            'upstream_history_preserved': True, 'recovery_snapshots_used': False}

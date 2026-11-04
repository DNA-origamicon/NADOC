"""Bounded portable evidence for current loadout revision pointers.

These are storage receipts, not user-visible operations or construction inputs.
Only current head/base records travel with a loadout, not every autosave.
"""
import hashlib
import json


def attach(workspace, design):
    from backend.core.project_revisions import ProjectRevisionStore
    store = ProjectRevisionStore(workspace)
    loadouts = []
    for branch in design.loadouts:
        records = {}
        for identity in {branch.head_revision_id, branch.base_revision_id} - {None}:
            path = store.object_path(design.id, identity)
            if path.is_file():
                records[identity] = json.loads(path.read_text())
            elif identity in branch.revision_records:
                records[identity] = branch.revision_records[identity]
        loadouts.append(branch.model_copy(update={'revision_records': records}))
    return design.model_copy(update={'loadouts': loadouts})


def verify(design, branch, snapshot):
    from backend.core.project_revisions import SCHEMA_VERSION, FORMAT
    if branch.snapshot_dirty:
        raise ValueError('Loadout snapshot has not been persisted to its recorded revision')
    pointers = {branch.head_revision_id, branch.base_revision_id} - {None}
    if set(branch.revision_records) != pointers:
        raise ValueError('Loadout revision pointers lack portable evidence')
    for identity in pointers:
        record = branch.revision_records[identity]
        if set(record) != {'format', 'schema_version', 'project_id', 'loadout_id',
                           'parent_revision_id', 'snapshot_sha256', 'revision_id',
                           'created_at', 'created_by', 'application_version', 'protected'}:
            raise ValueError('Unknown loadout revision record fields')
        if (record.get('format') != FORMAT or record.get('schema_version') != SCHEMA_VERSION or record.get('project_id') != design.id
                or record.get('loadout_id') != branch.id or record.get('revision_id') != identity
                or record.get('protected') != branch.protected):
            raise ValueError('Loadout revision ownership mismatch')
        header = {key: record.get(key) for key in
                  ('schema_version', 'project_id', 'loadout_id', 'parent_revision_id', 'snapshot_sha256')}
        digest = hashlib.sha256(json.dumps(header, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if digest != identity:
            raise ValueError('Loadout revision identity mismatch')
    if branch.head_revision_id:
        stripped = snapshot.model_copy(update={'loadouts': [], 'active_loadout_id': None,
                                                'last_editable_loadout_id': None})
        digest = hashlib.sha256(stripped.model_dump_json().encode()).hexdigest()
        if branch.revision_records[branch.head_revision_id]['snapshot_sha256'] != digest:
            raise ValueError('Loadout revision does not bind its embedded snapshot')

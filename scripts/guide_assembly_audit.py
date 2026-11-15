"""Replay the guide's add-part/periodic-polymer commands without saved snapshots.

Deliberately narrow: reject unsupported operations and every unexplained assembly
field. Parts are audited independently; file references must be portable siblings.
Random clone/joint IDs are matched to the IDs recorded by the actual command.
"""
from pathlib import Path
import hashlib
import numpy as np
from backend.core.models import Assembly, Design, PartInstance
from scripts.agent_structure_guard import audit as audit_part
from experiments.recorded_review_process import ProcessRequired


def audit(assembly, directory):
    from backend.core.assembly_polymer import build_periodic_chain
    from backend.core.periodic_polymer import derive_periodic_delta, principal_seam_connectors
    directory = Path(directory)
    sources = {}

    def part(source):
        if source.type == 'inline':
            design = source.design
            key = design.id
        else:
            path = Path(source.path)
            if path.is_absolute() or len(path.parts) != 1:
                raise ProcessRequired('Guide assembly source must be a sibling part')
            key = str(path)
            design = Design.model_validate_json((directory / path).read_text())
        if key not in sources:
            sources[key] = audit_part(design)
        return design

    replayed = Assembly(id=assembly.id, metadata=assembly.metadata)
    if assembly.feature_log_cursor != -1 or not assembly.feature_log:
        raise ProcessRequired('Guide assembly requires its complete active command log')
    for entry in assembly.feature_log:
        p = entry.params
        if entry.op_kind == 'assembly-add-instance':
            inst = PartInstance(id=p['instance_id'], name=p['name'], source=p['source'], transform=p['transform'])
            part(inst.source)
            replayed.instances.append(inst)
        elif entry.op_kind == 'assembly-polymerize-periodic':
            seed = next(i for i in replayed.instances if i.id == p['instance_id'])
            design = part(seed.source)
            delta = derive_periodic_delta(design)
            existing, added, joints = build_periodic_chain(seed, delta, np.linalg.inv(delta),
                principal_seam_connectors(design), p['count'], p['direction'], replayed.instances)
            if len(added) != len(p['new_instance_ids']) or len(joints) != len(p['new_joint_ids']):
                raise ProcessRequired('Recorded polymer output IDs do not match replay')
            mapping = dict(zip([i.id for i in added], p['new_instance_ids']))
            for inst in added:
                inst.id = mapping[inst.id]
            for joint, recorded_id in zip(joints, p['new_joint_ids']):
                joint.id = recorded_id
                joint.instance_a_id = mapping.get(joint.instance_a_id, joint.instance_a_id)
                joint.instance_b_id = mapping.get(joint.instance_b_id, joint.instance_b_id)
            replayed.instances = existing + added
            replayed.joints.extend(joints)
        else:
            raise ProcessRequired(f'Guide assembly replay unsupported: {entry.op_kind}')

    def content(value):
        data = value.model_dump(mode='json', exclude={'feature_log', 'feature_log_cursor'})
        # Working representation/visibility are display preferences, not construction.
        for inst in data['instances']:
            for key in ('representation', 'visible'):
                inst.pop(key, None)
        data.pop('export_representation', None)
        return data

    def equal(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        if isinstance(a, float) or isinstance(b, float):
            return isinstance(a, (float, int)) and isinstance(b, (float, int)) and abs(a-b) < 1e-9
        return a == b

    if not equal(content(replayed), content(assembly)):
        raise ProcessRequired('Assembly state differs from independent command replay')
    return {'status': 'verified', 'commands': len(assembly.feature_log),
            'instances': len(assembly.instances), 'joints': len(assembly.joints),
            'upstream_parts': sources, 'recovery_snapshots_used': False}


def publish(assembly, path):
    path = Path(path)
    proof = audit(assembly, path.parent)
    raw = assembly.to_json()
    audit(Assembly.from_json(raw), path.parent)
    with path.open('x') as stream:
        stream.write(raw)
    return {**proof, 'path': path.name, 'sha256': hashlib.sha256(raw.encode()).hexdigest()}

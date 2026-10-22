"""Create one editable native Move/Rotate example with a narrated build animation."""
from pathlib import Path
from uuid import UUID

from scipy.spatial.transform import Rotation

from backend.api import crud, part_proof_commands as commands
from backend.api.state import encode_design_snapshot
from backend.core.models import (
    AnimationKeyframe, ClusterCreateLogEntry, ClusterRigidTransform, Design,
    DesignAnimation, Direction, DomainRef, SnapshotLogEntry,
)
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_overlay_commands import command_input
from tests.test_part_member_motion_order import D, M, N


def build():
    design = create_empty_part('Move Rotate — step through the operations', 'HONEYCOMB')
    stages = []

    def append(kind, params, label):
        nonlocal design
        before, before_size = encode_design_snapshot(design)
        params = {**params, '_proof_version': 1}
        updated = commands.execute(kind, design, params)
        after, after_size = encode_design_snapshot(updated)
        entry = SnapshotLogEntry(
            op_kind=kind, label=label, params=params,
            design_snapshot_gz_b64=before, snapshot_size_bytes=before_size,
            post_state_gz_b64=after, post_state_size_bytes=after_size,
        )
        design = updated.copy_with(id=design.id, recipe_root=design.recipe_root,
                                   feature_log=[*design.feature_log, entry])
        stages.append(label)
        verify(design)

    def delta(entry, label):
        nonlocal design
        kind, params = command_input(entry)
        updated = commands.execute(kind, design, params)
        design = updated.copy_with(id=design.id, recipe_root=design.recipe_root,
                                   feature_log=[*design.feature_log, entry])
        stages.append(label)
        verify(design)

    def owner(identity, name, label, pose, domain):
        cluster = ClusterRigidTransform(id=identity, name=name,
            helix_ids=[helix], domain_ids=[DomainRef(strand_id=domain, domain_index=0)])
        delta(ClusterCreateLogEntry(proof_version=2, cluster_id=identity, name=name,
            helix_ids=cluster.helix_ids, domain_ids=cluster.domain_ids, cluster_snapshot=cluster),
            f'Make Cluster — {name}; select bases 0–3 without moving them')
        nonlocal design
        from backend.api.part_group_recording import prepare_group_update
        design, _ = prepare_group_update(design, identity, pose)
        stages.append(label)
        verify(design)

    append('bundle-create', crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=8,
        ligate_adjacent=False, history_seed=UUID(int=26001)).model_dump(mode='json'),
        '01 Build two helices, 8 base pairs long')
    helix = design.helices[0].id
    append('nick', dict(helix_id=helix, bp_index=3, direction='FORWARD'),
           '02 Nick forward strand at base 3 — select bases 0–3 for group moves')
    target = dict(kind='base', helix_id=helix, bp_index=3, direction='FORWARD', copy_k=0)
    def base(pose, compose, label):
        append('nucleotide-transform', dict(**target, **pose, compose=compose,
            history_seed=str(UUID(int=26002)), reclassify_unpaired=True), label)

    base(N, False, '03 Rotate base 3 about X by 90 degrees, then translate — expose OH1')
    strand = next(s for s in design.strands if any(d.helix_id == helix
        and d.direction == Direction.FORWARD and min(d.start_bp, d.end_bp) <= 3 <= max(d.start_bp, d.end_bp)
        for d in s.domains))
    owner('first-group-move', 'Bases 0–3, first cluster', '05 Move bases 0–3 together: Z rotation 90 degrees + translation — extend OH1', M, strand.id)
    base(D, True, '06 Move base 3 by (3, -2, 1) nm')
    saved = next(p for p in design.nucleotide_transforms if p.helix_id == helix and p.bp_index == 3)
    append('nucleotide-transform-delete', dict(transform_id=saved.id),
           '07 Reset base 3 — remove its saved pose')
    base(dict(rotation=Rotation.from_euler('y', 37, degrees=True).as_quat().tolist(),
        pivot=[-2, 3, .7], translation=[1, 2, -.5]), False,
        '08 Set base 3 pose: Y rotation 37 degrees + translation')
    owner('second-group-move', 'Bases 0–3, second cluster', '10 Move bases 0–3 again: X rotation -25 degrees + translation',
        dict(rotation=Rotation.from_euler('x', -25, degrees=True).as_quat().tolist(),
             pivot=[1, -.5, .3], translation=[.4, -.2, .6]), strand.id)
    base(D, True, '11 Move base 3 again by (3, -2, 1) nm')
    design.animations = [DesignAnimation(name='Watch construction, Make Cluster and Move/Rotate', keyframes=[
        AnimationKeyframe(name=label, feature_log_index=index, hold_duration_s=2,
                          transition_duration_s=0 if index == 0 else 2, easing='linear')
        for index, label in enumerate(stages)])]
    verify(Design.from_json(design.to_json()))
    return design


def verify(design):
    report = assess_part_history(design, execute=commands.execute, dependencies=commands.dependencies)
    if report['status'] != 'verified' or not report['native_editable']:
        raise ValueError(report)


if __name__ == '__main__':
    destination = Path('workspace/move_rotate_axes_overhang.nadoc')
    result = build()
    with destination.open('x') as stream:
        stream.write(result.to_json())
    print(f'{destination}: {len(result.feature_log)} verified native features, one saved animation')

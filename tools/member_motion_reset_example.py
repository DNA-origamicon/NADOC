"""Append one pose reset to the five-step axes/OH1 manual example."""
from pathlib import Path

from backend.api import part_proof_commands as commands
from backend.api.state import encode_design_snapshot
from backend.core.models import AnimationKeyframe, Design, SnapshotLogEntry
from backend.core.part_history_proof import root_design
from backend.core.part_overlay_commands import command_input
from tools.member_motion_native_example import verify


def build(source):
    before = root_design(source.recipe_root)
    for entry in source.feature_log[:5]:
        kind, params = command_input(entry)
        before = commands.execute(kind, before, params)
    before = before.copy_with(id=source.id, recipe_root=source.recipe_root,
                              feature_log=source.feature_log[:5], feature_log_cursor=-1)
    assert len(before.nucleotide_transforms) == 1
    params = {'transform_id': before.nucleotide_transforms[0].id, '_proof_version': 1}
    after = commands.execute('nucleotide-transform-delete', before, params)
    pre, pre_size = encode_design_snapshot(before)
    post, post_size = encode_design_snapshot(after)
    entry = SnapshotLogEntry(op_kind='nucleotide-transform-delete',
        label='Reset base 3 pose; retain the cluster move', params=params,
        design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size)
    animation = source.animations[0].model_copy(deep=True)
    animation.name = 'Reset base 3 after moving its cluster'
    animation.keyframes = animation.keyframes[:5] + [AnimationKeyframe(
        name='06 Move/Rotate — reset base 3; retain the cluster move',
        feature_log_index=5, hold_duration_s=3, transition_duration_s=2, easing='linear')]
    result = after.copy_with(id=source.id, recipe_root=source.recipe_root,
        feature_log=[*before.feature_log, entry], feature_log_cursor=-1, animations=[animation])
    verify(Design.from_json(result.to_json()))
    return result


if __name__ == '__main__':
    source = Design.from_json(Path('workspace/move_rotate_axes_overhang_focused.nadoc').read_text())
    destination = Path('workspace/move_rotate_pose_reset.nadoc')
    result = build(source)
    with destination.open('x') as stream:
        stream.write(result.to_json())
    print(f'{destination}: six verified features; compare F5 with F6')

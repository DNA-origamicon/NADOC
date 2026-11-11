"""Atomic keyframe capture and exact duplication for both document hosts."""
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.models import CameraPose


class CaptureKeyframeBody(BaseModel):
    pose: CameraPose
    annotation_ids: list[str]
    view_volume_ids: list[str]
    zoom_volume_ids: list[str]
    feature_log_index: int | None = None


def keyframe_actions_router(host, state):
    router = APIRouter()

    def locate(document, animation_id, keyframe_id):
        animation = next((a for a in document.animations if a.id == animation_id), None)
        if animation is None:
            raise HTTPException(404, 'Animation not found')
        index = next((i for i, k in enumerate(animation.keyframes) if k.id == keyframe_id), None)
        if index is None:
            raise HTTPException(404, 'Keyframe not found')
        return animation, index

    def publish(document):
        if host == 'design':
            state.set_design(document)
        else:
            state.set_assembly(document)
        fields = ('animations', 'camera_poses', 'configurations') if host == 'assembly' else ('animations', 'camera_poses')
        return {host: {'id': document.id, **{field: [value.model_dump(mode='json') for value in getattr(document, field)] for field in fields}}, 'revision': state.revision()}

    @router.post(f'/{host}/animations/{{anim_id}}/keyframes/{{kf_id}}/duplicate')
    def duplicate(anim_id: str, kf_id: str):
        source = state.get_or_404()
        locate(source, anim_id, kf_id)
        updated = source.model_copy(deep=True)
        animation, index = locate(updated, anim_id, kf_id)
        animation.keyframes.insert(index + 1, animation.keyframes[index].model_copy(deep=True, update={'id': str(uuid4())}))
        return publish(updated)

    @router.post(f'/{host}/animations/{{anim_id}}/keyframes/{{kf_id}}/capture')
    def capture(anim_id: str, kf_id: str, body: CaptureKeyframeBody):
        source = state.get_or_404()
        locate(source, anim_id, kf_id)
        if host == 'design' and body.feature_log_index is not None and not -2 <= body.feature_log_index < max(0, len(source.feature_log)):
            raise HTTPException(422, 'Feature state is outside the current log')
        updated = source.model_copy(deep=True)
        animation, index = locate(updated, anim_id, kf_id)
        keyframe = animation.keyframes[index]
        pose = body.pose.model_copy(deep=True, update={'id': str(uuid4())})
        updated.camera_poses.append(pose)
        keyframe.camera_pose_id = pose.id
        for field in ('annotation_ids', 'view_volume_ids', 'zoom_volume_ids'):
            setattr(keyframe, field, list(getattr(body, field)))
        if host == 'design':
            keyframe.feature_log_index = body.feature_log_index
        else:
            from backend.api.routes_assembly_configs import _capture_assembly_configuration
            configuration = _capture_assembly_configuration(updated, pose.name)
            updated.configurations.append(configuration)
            keyframe.configuration_id = configuration.id
            keyframe.joint_values = {j.id: j.current_value for j in updated.joints}
        return publish(updated)

    return router

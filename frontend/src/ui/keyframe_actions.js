import { captureNamedPose } from './saved_pose_capture.js'

/** Capture a normal saved pose and select it without changing other keyframe settings. */
export function createKeyframeActions({ getContext, captureCurrentCamera, captureThumbnail, player, api }) {
  async function commit(action, keyframe, body) {
    const { document, animationId, assembly, patchPart } = getContext()
    if (!document || !animationId) throw new Error('Select an animation first.')
    if (!patchPart) {
      if (!await api.keyframeAction(assembly, action, animationId, keyframe.id, body)) throw new Error(`Could not ${action} keyframe.`)
      return
    }
    const result = await patchPart(d => {
      const animation = d.animations?.find(a => a.id === animationId)
      const index = animation?.keyframes.findIndex(k => k.id === keyframe.id) ?? -1
      if (index < 0) throw new Error('The keyframe is no longer available.')
      if (action === 'duplicate') {
        animation.keyframes.splice(index + 1, 0, { ...structuredClone(animation.keyframes[index]), id: crypto.randomUUID() })
      } else {
        const { pose, ...patch } = body
        const savedPose = { ...pose, id: crypto.randomUUID() }
        d.camera_poses = [...(d.camera_poses ?? []), savedPose]
        Object.assign(animation.keyframes[index], patch, { camera_pose_id: savedPose.id })
      }
    }, { optimistic: false })
    if (result === false || result === null) throw new Error(`Could not ${action} keyframe.`)
  }
  return {
    duplicate: keyframe => commit('duplicate', keyframe),
    async capture(keyframe) {
      if (player.isPlaying?.()) player.pause()
      const context = getContext()
      const { document, animationId, assembly, patchPart } = context
      if (!document || !animationId) throw new Error('Select an animation first.')
      const { name, state } = captureNamedPose(document, captureCurrentCamera, captureThumbnail)
      if (patchPart) return commit('capture', keyframe, {
        pose: { ...state, name, orbit_mode: state.orbitMode ?? 'trackball' },
      })
      const existing = new Set((document.camera_poses ?? []).map(pose => pose.id))
      const response = await (assembly ? api.createAssemblyCameraPose : api.createCameraPose)(name, state)
      const saved = response?.[assembly ? 'assembly' : 'design']
      const current = getContext()
      if (saved?.id !== document.id || current.document?.id !== document.id ||
          current.animationId !== animationId || current.assembly !== assembly || current.patchPart !== patchPart) {
        throw new Error('The active document or animation changed while saving the pose.')
      }
      const pose = saved.camera_poses?.at(-1)
      if (!pose || existing.has(pose.id)) throw new Error('Could not save camera pose.')
      const update = assembly ? api.updateAssemblyKeyframe : api.updateKeyframe
      if (!await update(animationId, keyframe.id, { camera_pose_id: pose.id })) {
        throw new Error('Pose saved, but could not select it for the keyframe.')
      }
    },
  }
}

import { captureSceneAnnotations } from '../scene/annotation_overlay.js'

export function capturedFeatureIndex(document, displayedIndex) {
  const index = displayedIndex ?? document.feature_log_cursor ?? -1
  return index === -1 ? ((document.feature_log?.length ?? 0) ? document.feature_log.length - 1 : -2) : index
}

/** Capture references to visible presentation entries, plus a new independent pose. */
export function createKeyframeActions({ getContext, captureCurrentCamera, player, api, scene, viewVolumes, zoomVolume }) {
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
    capture(keyframe) {
      if (player.isPlaying?.()) player.pause()
      const { document, patchPart } = getContext()
      const pose = captureCurrentCamera()
      const owned = (ids, field) => patchPart ? ids.filter(id => (document[field] ?? []).some(e => e.id === id)) : ids
      return commit('capture', keyframe, {
        pose: { ...pose, orbit_mode: pose.orbit_mode ?? pose.orbitMode ?? 'trackball', name: `${keyframe.name || 'Keyframe'} pose ${(document.camera_poses?.length ?? 0) + 1}` },
        annotation_ids: owned(captureSceneAnnotations(scene).map(entry => entry.id), 'annotations'),
        view_volume_ids: owned(viewVolumes?.visibleIds() ?? (document.view_volumes ?? []).filter(v => v.enabled !== false).map(v => v.id), 'view_volumes'),
        zoom_volume_ids: owned(zoomVolume?.visibleIds() ?? [], 'zoom_volumes'),
        feature_log_index: capturedFeatureIndex(document, player.getCapturedFeatureIndex?.()),
      })
    },
  }
}

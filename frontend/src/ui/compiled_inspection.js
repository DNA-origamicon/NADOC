/** Video timestamps refer to the encoded sampling grid, not wall-clock playback. */
export function compiledTimelineTime(compiled, state) {
  const range = Number.isInteger(state?.index) && compiled.ranges[state.index]
  if (!range || !Number.isFinite(state.time) || state.time < 0) throw new Error('Invalid compiled playback position')
  if (state.atEnd) return range.end
  const fps = Math.max(1, Math.min(60, Number(compiled.animation.fps) || 30))
  return range.start + Math.min(range.end - range.start, Math.floor(state.time * fps + 1e-6) / fps)
}

/** Live scene ownership is independent of the embedded video lifetime. */
export function createCompiledInspection({ player, captureCamera, applyCamera, isCurrent, sameDocument = () => true, getPlayOptions = () => ({}) }) {
  let generation = 0, owned = false, preparing = false, starting = false, saved = null
  function release() {
    generation++
    if (!saved) return
    const previous = saved; saved = null
    if (owned) { owned = false; player.cancelBake?.(); player.stop() }
    if (preparing && sameDocument(previous.compiled)) applyCamera(previous.camera)
    preparing = false
    player.setBounce(previous.bounce); player.setLoopMode(previous.loop); player.setDisablePoses(previous.poses)
  }
  async function inspect(compiled, state) {
    const time = compiledTimelineTime(compiled, state)
    release()
    const token = ++generation
    const current = await isCurrent(compiled)
    if (token !== generation) return false
    if (!current) throw new Error('Load the matching source document to inspect this presentation. If the source changed, recompile it.')
    saved = { compiled, camera: captureCamera(), bounce: player.getBounce(), loop: player.getLoopMode(), poses: player.getDisablePoses() }
    owned = preparing = true
    try {
      applyCamera(compiled.initialCamera)
      player.setBounce(false); player.setDisablePoses(false)
      let work
      starting = true
      const animation = compiled.initialJointValues && Object.keys(compiled.initialJointValues).length
        ? { ...compiled.animation, keyframes: [{ id: '__compiled_initial_joints__', transition_duration_s: 0,
          hold_duration_s: 0, joint_values: compiled.initialJointValues }, ...compiled.animation.keyframes] }
        : compiled.animation
      try { work = player.play(animation, { ...getPlayOptions(), holdKeyframeText: true }) }
      finally { starting = false }
      await work
      if (token !== generation) return false
      player.pause()
      const range = player.getKeyframeRange?.(compiled.clipKeyframeIds?.[state.index] ?? compiled.animation.keyframes[state.index].id)
      const expected = compiled.ranges[state.index]
      if (player.getKeyframeRange && (!range || Math.abs(range.start - expected.start) > 1e-6 || Math.abs(range.end - expected.end) > 1e-6)) {
        throw new Error('Live preparation was interrupted. Retry inspection when the app is ready.')
      }
      if (!await isCurrent(compiled)) throw new Error('Source changed while preparing live inspection.')
      if (token !== generation) return false
      player.seekTo(time)
      if (await player.settleFrame() === false) throw new Error('Live trajectory frame is not ready. The prepared video is still available.')
      if (token !== generation) return false
      if (!await isCurrent(compiled)) throw new Error('Source changed while preparing live inspection.')
      if (token !== generation) return false
      player.setDisablePoses(true)
      preparing = false
      return true
    } catch (error) {
      if (token !== generation) return false
      release()
      throw error
    }
  }
  return { inspect, release,
    onPlayerEvent(event) {
      // play() first stops its previous schedule synchronously. Any later Stop
      // can be a normal editor action and relinquishes our scene ownership.
      if (event.type === 'stopped' && owned && !starting) {
        const wasPreparing = preparing, previous = saved
        generation++; owned = preparing = false; saved = null
        if (previous) {
          if (wasPreparing && sameDocument(previous.compiled)) applyCamera(previous.camera)
          player.setBounce(previous.bounce); player.setLoopMode(previous.loop); player.setDisablePoses(previous.poses)
        }
        return wasPreparing
      }
      return preparing
    },
  }
}

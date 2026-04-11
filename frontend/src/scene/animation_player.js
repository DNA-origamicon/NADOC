/**
 * Animation player — drives camera and cluster-config state through a sequence
 * of AnimationKeyframes.
 *
 * Each keyframe has:
 *   - camera_pose_id   → target camera position/target/up/fov (null = no camera move)
 *   - feature_log_index → feature log position to seek to (null = no cluster move)
 *   - transition_duration_s → time to tween from the previous state into this keyframe
 *   - hold_duration_s  → time to hold at this keyframe after arriving
 *   - easing           → interpolation curve for the transition
 *
 * Timeline per keyframe:
 *   [── transition_duration_s ──][── hold_duration_s ──]
 *
 * The player emits events via the callback returned from initAnimationPlayer:
 *   { type: 'baking'   }                              — geometry batch fetch started
 *   { type: 'baking_done' }                           — fetch complete, playback starting
 *   { type: 'tick',     currentTime, totalDuration }
 *   { type: 'finished' }
 *   { type: 'stopped'  }
 *   { type: 'paused',  currentTime }
 */

import * as THREE from 'three'

// ── Easing functions ─────────────────────────────────────────────────────────
function _ease(t, curve) {
  switch (curve) {
    case 'linear':     return t
    case 'ease-in':    return t * t
    case 'ease-out':   return t * (2 - t)
    case 'ease-in-out':
    default:           return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t
  }
}

/**
 * @param {object} opts
 * @param {THREE.PerspectiveCamera} opts.camera
 * @param {*}      opts.controls          — OrbitControls/TrackballControls proxy
 * @param {function(): object[]} opts.getCameraPoses       — returns current camera_poses array
 * @param {function(): object}   opts.getDesign            — returns current design (for feature log replay)
 * @param {function(): object[]} opts.getClusterTransforms — returns current cluster_transforms array
 * @param {function(): object|null} opts.getHelixCtrl      — returns the live helix renderer controller
 * @param {function(number[]): Promise} [opts.onFetchGeometryBatch] — fetches geometry for multiple feature-log positions
 * @param {function(object): void} [opts.onEvent]          — receives player events
 */
export function initAnimationPlayer({ camera, controls, getCameraPoses, getDesign, getClusterTransforms, getHelixCtrl, getBluntEnds, getUnfoldView, getDesignRenderer, onFetchGeometryBatch, onEvent }) {
  let _raf          = null
  let _playing      = false
  let _direction    = 1       // 1 = forward, -1 = reverse
  let _bounce       = false   // ping-pong: flip direction at each boundary
  let _startTime    = 0
  let _seekOffset   = 0
  let _animation    = null
  let _schedule     = []
  let _totalDur     = 0
  let _baseClusters = null    // cluster transforms at play() time (for incremental lerp base)
  let _lastSeekKfId = null    // kfId of last segment entered (unused but kept for symmetry)

  // Pre-baked geometry states: Map<featureLogIndex, BakedGeometry>
  // BakedGeometry = { posMap, axesMap, bnMap }
  let _bakedStates  = new Map()
  let _baking       = false

  // ── State helpers ────────────────────────────────────────────────────────────

  /** Capture the live scene state (camera + cluster transforms + feature log index). */
  function _liveState() {
    return {
      position: camera.position.clone(),
      target:   controls.target.clone(),
      up:       camera.up.clone(),
      fov:      camera.fov,
      clusterTransforms: getClusterTransforms().map(c => ({
        cluster_id: c.id,
        translation: [...c.translation],
        rotation:    [...c.rotation],
      })),
      featureLogIndex: getDesign()?.feature_log_cursor ?? -1,
    }
  }

  /**
   * Compute cluster transforms at a given feature log index by replaying the log
   * client-side (mirrors _seek_feature_log on the backend).
   * idx: -2 = empty (no features), -1 = all active, ≥0 = up to that log entry.
   */
  function _clusterStateAtIndex(idx, design) {
    const log      = design.feature_log ?? []
    const clusters = design.cluster_transforms ?? []
    const active   = idx === -2 ? [] : idx === -1 ? log : log.slice(0, idx + 1)
    const last     = {}
    for (const e of active) {
      if (e.feature_type === 'cluster_op') last[e.cluster_id] = e
    }
    const withOps = new Set(log.filter(e => e.feature_type === 'cluster_op').map(e => e.cluster_id))
    return clusters.map(c =>
      last[c.id]
        ? { cluster_id: c.id, translation: [...last[c.id].translation], rotation: [...last[c.id].rotation] }
        : withOps.has(c.id)
          ? { cluster_id: c.id, translation: [0, 0, 0], rotation: [0, 0, 0, 1] }
          : { cluster_id: c.id, translation: [...c.translation], rotation: [...c.rotation] }
    )
  }

  /** Resolve a keyframe's target state using stored camera poses and feature log replay. */
  function _kfState(kf) {
    const poses = getCameraPoses()
    const pose  = kf.camera_pose_id ? poses.find(p => p.id === kf.camera_pose_id) : null

    const clusterTransforms = (kf.feature_log_index != null)
      ? _clusterStateAtIndex(kf.feature_log_index, getDesign())
      : null

    return {
      position: pose ? new THREE.Vector3(...pose.position) : null,
      target:   pose ? new THREE.Vector3(...pose.target)   : null,
      up:       pose ? new THREE.Vector3(...pose.up)        : null,
      fov:      pose ? pose.fov                             : null,
      clusterTransforms,
    }
  }

  /**
   * Build the playback schedule from the animation keyframes.
   * Each segment covers one keyframe: [transition → hold].
   * The "from" state of segment 0 is the live scene at play time.
   *
   * fromFeatureLogIndex / toFeatureLogIndex are carried forward when a keyframe
   * has no explicit feature_log_index — so geometry always has a valid from/to pair.
   */
  function _buildSchedule(anim, initialState) {
    const segments = []
    let cursor    = 0
    let prevState = initialState
    let prevFLI   = initialState.featureLogIndex

    for (const kf of anim.keyframes) {
      const toState  = _kfState(kf)
      const transDur = Math.max(0, kf.transition_duration_s)
      const holdDur  = Math.max(0, kf.hold_duration_s)
      const toFLI    = kf.feature_log_index ?? prevFLI   // carry forward if null
      segments.push({
        kfId:                kf.id,
        fromFeatureLogIndex: prevFLI,
        toFeatureLogIndex:   toFLI,
        startT:              cursor,
        transEnd:            cursor + transDur,
        endT:                cursor + transDur + holdDur,
        fromState:           prevState,
        toState,
        easing:              kf.easing ?? 'ease-in-out',
      })
      cursor += transDur + holdDur
      prevState = {
        position:          toState.position          ?? prevState.position,
        target:            toState.target            ?? prevState.target,
        up:                toState.up                ?? prevState.up,
        fov:               toState.fov               ?? prevState.fov,
        clusterTransforms: toState.clusterTransforms ?? prevState.clusterTransforms,
      }
      prevFLI = toFLI
    }
    return { segments, totalDur: cursor }
  }

  // ── Pre-bake geometry ────────────────────────────────────────────────────────

  /**
   * Fetch geometry for all unique feature-log positions referenced in the animation.
   * Populates _bakedStates (Map<featureLogIndex, BakedGeometry>) in-place.
   * Stateless — does NOT change the design cursor.
   */
  async function _bakeStates(animation, liveFeatureLogIndex) {
    _baking = true
    try {
      const positionSet = new Set([liveFeatureLogIndex])
      for (const kf of animation.keyframes) {
        if (kf.feature_log_index != null) positionSet.add(kf.feature_log_index)
      }
      if (!onFetchGeometryBatch) return
      const batch = await onFetchGeometryBatch([...positionSet])
      if (!batch) return

      _bakedStates = new Map()
      for (const [posStr, geo] of Object.entries(batch)) {
        const pos    = parseInt(posStr, 10)
        const posMap = new Map()
        const bnMap  = new Map()
        for (const nuc of geo.nucleotides) {
          const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
          posMap.set(key, new THREE.Vector3(...nuc.backbone_position))
          if (nuc.base_normal) bnMap.set(key, new THREE.Vector3(...nuc.base_normal))
        }
        const axesMap = new Map()
        for (const ax of geo.helix_axes ?? []) {
          axesMap.set(ax.helix_id, {
            start: new THREE.Vector3(...ax.start),
            end:   new THREE.Vector3(...ax.end),
          })
        }
        _bakedStates.set(pos, { posMap, axesMap, bnMap })
      }
    } finally {
      _baking = false
    }
  }

  // ── Cluster config interpolation ─────────────────────────────────────────────

  /**
   * Capture base positions for all clusters referenced in the animation.
   * Uses append mode so all clusters are captured in a single logical snapshot.
   */
  function _captureAllBases() {
    const helixCtrl = getHelixCtrl()
    if (!helixCtrl) return
    const clusters = getClusterTransforms()
    if (!clusters.length) return
    const bluntEnds = getBluntEnds?.()
    let first = true
    for (const c of clusters) {
      helixCtrl.captureClusterBase(c.helix_ids, c.domain_ids?.length ? c.domain_ids : null, !first)
      bluntEnds?.captureClusterBase(c.helix_ids, !first)
      first = false
    }
    const design = getDesign()
    _baseClusters = clusters.map(c => ({
      id:          c.id,
      translation: [...c.translation],
      rotation:    [...c.rotation],
      pivot:       [...c.pivot],
      helix_ids:   [...c.helix_ids],
      domain_ids:  c.domain_ids ? [...c.domain_ids] : [],
      joint:       design?.cluster_joints?.find(j => j.cluster_id === c.id) ?? null,
    }))
  }

  /**
   * Apply interpolated cluster transforms for a given lerp fraction t.
   * Always applied relative to the base captured at play() time.
   */
  function _applyClusterLerp(fromClusters, toClusters, t) {
    if (!toClusters || !_baseClusters) return
    const helixCtrl = getHelixCtrl()
    if (!helixCtrl) return

    const affectedHelixIds = []

    for (const toEntry of toClusters) {
      const base = _baseClusters.find(c => c.id === toEntry.cluster_id)
      if (!base) {
        console.debug(`[anim] cluster ${toEntry.cluster_id} not in scene base — skipping`)
        continue
      }
      const fromEntry = fromClusters?.find(e => e.cluster_id === toEntry.cluster_id)
      const fromTrans = fromEntry?.translation ?? base.translation
      const fromRot   = fromEntry?.rotation    ?? base.rotation

      // Slerp rotation
      const qFrom   = new THREE.Quaternion(fromRot[0], fromRot[1], fromRot[2], fromRot[3])
      const qTo     = new THREE.Quaternion(toEntry.rotation[0], toEntry.rotation[1], toEntry.rotation[2], toEntry.rotation[3])
      const qInterp = qFrom.clone().slerp(qTo, t)

      // Incremental rotation: qInterp * qBase^-1
      const qBase   = new THREE.Quaternion(base.rotation[0], base.rotation[1], base.rotation[2], base.rotation[3])
      const incrRot = qInterp.multiply(qBase.clone().invert())

      // center = pivot + base_translation
      const pivot  = new THREE.Vector3(...base.pivot)
      const center = pivot.clone().add(new THREE.Vector3(...base.translation))

      // dummy (new centroid position):
      //   Joint present → pure rotation about J: dummy = J + incrRot @ (center − J)
      //   This ensures J stays fixed at all intermediate t, not just at t=0 and t=1.
      //   No joint → naive linear lerp of translation.
      let dummy
      if (base.joint) {
        const J = new THREE.Vector3(...base.joint.axis_origin)
        dummy = center.clone().sub(J).applyQuaternion(incrRot).add(J)
      } else {
        const tx = fromTrans[0] + (toEntry.translation[0] - fromTrans[0]) * t
        const ty = fromTrans[1] + (toEntry.translation[1] - fromTrans[1]) * t
        const tz = fromTrans[2] + (toEntry.translation[2] - fromTrans[2]) * t
        dummy = pivot.clone().add(new THREE.Vector3(tx, ty, tz))
      }

      helixCtrl.applyClusterTransform(
        base.helix_ids,
        center,
        dummy,
        incrRot,
        base.domain_ids?.length ? base.domain_ids : null,
      )
      getBluntEnds?.()?.applyClusterTransform(base.helix_ids, center, dummy, incrRot)
      affectedHelixIds.push(...base.helix_ids)
    }

    // Keep crossover arcs, extension beads, and 3D crossover lines in sync.
    if (affectedHelixIds.length) {
      getUnfoldView?.()?.applyClusterArcUpdate(affectedHelixIds)
      getUnfoldView?.()?.applyClusterExtArcUpdate(affectedHelixIds)
      getDesignRenderer?.()?.applyClusterCrossoverUpdate(affectedHelixIds)
    }
  }

  /** Restore all clusters to their base (design) positions after stop. */
  function _restoreBaseClusters() {
    if (!_baseClusters) return
    const helixCtrl = getHelixCtrl()
    if (!helixCtrl) return
    const bluntEnds = getBluntEnds?.()
    const allHelixIds = []
    for (const base of _baseClusters) {
      const pivot  = new THREE.Vector3(...base.pivot)
      const center = pivot.clone().add(new THREE.Vector3(...base.translation))
      const identQ = new THREE.Quaternion()
      helixCtrl.applyClusterTransform(
        base.helix_ids,
        center,
        center.clone(),   // dummy = center → identity transform → restores base positions
        identQ,
        base.domain_ids?.length ? base.domain_ids : null,
      )
      bluntEnds?.applyClusterTransform(base.helix_ids, center, center.clone(), identQ)
      allHelixIds.push(...base.helix_ids)
    }
    // Restore crossover arcs, extension beads, and 3D crossover lines.
    if (allHelixIds.length) {
      getUnfoldView?.()?.applyClusterArcUpdate(allHelixIds)
      getUnfoldView?.()?.applyClusterExtArcUpdate(allHelixIds)
      getDesignRenderer?.()?.applyClusterCrossoverUpdate(allHelixIds)
    }
    _baseClusters = null
  }

  // ── Apply at time ────────────────────────────────────────────────────────────

  /** Apply the interpolated state for a given elapsed time. */
  function _applyAt(elapsed) {
    if (!_schedule.length) return

    let seg = _schedule[_schedule.length - 1]
    for (const s of _schedule) {
      if (elapsed <= s.endT) { seg = s; break }
    }

    const { fromState, toState, startT, transEnd, easing, fromFeatureLogIndex, toFeatureLogIndex } = seg

    const inTransition = elapsed < transEnd
    const rawT = inTransition
      ? (transEnd > startT ? (elapsed - startT) / (transEnd - startT) : 1)
      : 1
    const t = _ease(Math.min(rawT, 1), easing)

    // Camera
    if (toState.position) camera.position.lerpVectors(fromState.position, toState.position, t)
    if (toState.target)   controls.target.lerpVectors(fromState.target, toState.target, t)
    if (toState.up)       camera.up.lerpVectors(fromState.up, toState.up, t).normalize()
    if (toState.fov != null && fromState.fov != null) {
      camera.fov = fromState.fov + (toState.fov - fromState.fov) * t
      camera.updateProjectionMatrix()
    }
    controls.update()

    // Cluster configs
    let clusterHelixIds = null
    if (toState.clusterTransforms) {
      _applyClusterLerp(fromState.clusterTransforms, toState.clusterTransforms, t)
      // Build exclusion set so applyPositionLerp skips helices owned by rigid-body
      // cluster transforms. Linear position lerp on rotated clusters causes compression
      // (chord path instead of arc); applyClusterTransform already handles them correctly.
      if (_baseClusters?.length) {
        clusterHelixIds = new Set()
        for (const base of _baseClusters) base.helix_ids.forEach(id => clusterHelixIds.add(id))
      }
    }

    // Deform geometry lerp — pure client-side from pre-baked states.
    // Pass clusterHelixIds so cluster helices are handled by applyClusterTransform above.
    const fromBaked = _bakedStates.get(fromFeatureLogIndex)
    const toBaked   = _bakedStates.get(toFeatureLogIndex)
    if (fromBaked && toBaked) {
      getHelixCtrl()?.applyPositionLerp(fromBaked, toBaked, t, clusterHelixIds)
    }
  }

  // ── RAF loop ─────────────────────────────────────────────────────────────────

  function _loop(now) {
    if (!_playing) return
    const elapsed  = _seekOffset + _direction * (now - _startTime) / 1000
    const atBound  = _direction === 1 ? elapsed >= _totalDur : elapsed <= 0

    if (atBound) {
      const boundTime = _direction === 1 ? _totalDur : 0
      _applyAt(boundTime)
      if (_bounce) {
        _direction    = -_direction
        _seekOffset   = boundTime
        _startTime    = now
        _lastSeekKfId = null
        _raf = requestAnimationFrame(_loop)
      } else if (_animation?.loop) {
        _seekOffset   = _direction === 1 ? 0 : _totalDur
        _startTime    = now
        _lastSeekKfId = null
        _raf = requestAnimationFrame(_loop)
      } else {
        _playing = false
        _raf     = null
        onEvent?.({ type: 'tick', currentTime: boundTime, totalDuration: _totalDur })
        onEvent?.({ type: 'finished' })
      }
    } else {
      _applyAt(elapsed)
      onEvent?.({ type: 'tick', currentTime: elapsed, totalDuration: _totalDur })
      _raf = requestAnimationFrame(_loop)
    }
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  /**
   * Start forward playback from the beginning.
   * Fires 'baking' event immediately, then fetches all geometry states, then
   * fires 'baking_done' and starts the RAF loop.  All geometry lerps during
   * playback are purely client-side — zero HTTP calls after baking completes.
   */
  function play(animation) {
    stop()
    if (!animation?.keyframes?.length) return

    _animation = animation
    onEvent?.({ type: 'baking' })

    const liveFLI = getDesign()?.feature_log_cursor ?? -1

    _bakeStates(animation, liveFLI).then(() => {
      if (_animation !== animation) return   // user stopped while baking

      _direction    = 1
      _lastSeekKfId = null
      const initialState           = _liveState()
      const { segments, totalDur } = _buildSchedule(animation, initialState)
      _schedule   = segments
      _totalDur   = totalDur
      _seekOffset = 0
      _startTime  = performance.now()
      _playing    = true

      _captureAllBases()

      onEvent?.({ type: 'baking_done' })
      _raf = requestAnimationFrame(_loop)
    })
  }

  /** Pause (saves current position; direction preserved for resume). */
  function pause() {
    if (!_playing) return
    _seekOffset = Math.max(0, Math.min(
      _seekOffset + _direction * (performance.now() - _startTime) / 1000,
      _totalDur,
    ))
    _playing = false
    if (_raf) { cancelAnimationFrame(_raf); _raf = null }
    onEvent?.({ type: 'paused', currentTime: _seekOffset })
  }

  /** Resume in the same direction from the paused position. */
  function resume() {
    if (_playing || !_animation || !_schedule.length) return
    _startTime = performance.now()
    _playing   = true
    _raf = requestAnimationFrame(_loop)
  }

  /** Stop completely, reset position, and restore cluster visual state. */
  function stop() {
    _restoreBaseClusters()
    _playing      = false
    _direction    = 1
    _animation    = null
    _schedule     = []
    _totalDur     = 0
    _seekOffset   = 0
    _lastSeekKfId = null
    _bakedStates  = new Map()
    _baking       = false
    if (_raf) { cancelAnimationFrame(_raf); _raf = null }

    onEvent?.({ type: 'stopped' })
  }

  function setBounce(enabled) { _bounce = enabled }
  function getBounce()        { return _bounce }

  /**
   * Jump to a specific time position (seconds).
   * Keeps playing in the current direction if active.
   */
  function seekTo(seconds) {
    const wasPlaying = _playing
    if (_playing) {
      _playing = false
      if (_raf) { cancelAnimationFrame(_raf); _raf = null }
    }
    _seekOffset = Math.max(0, Math.min(seconds, _totalDur))
    _applyAt(_seekOffset)
    onEvent?.({ type: 'tick', currentTime: _seekOffset, totalDuration: _totalDur })
    if (wasPlaying) {
      _startTime = performance.now()
      _playing   = true
      _raf = requestAnimationFrame(_loop)
    }
  }

  function isPlaying()        { return _playing }
  function getDirection()     { return _direction }
  function getCurrentTime()   {
    if (!_playing) return _seekOffset
    return Math.max(0, Math.min(
      _seekOffset + _direction * (performance.now() - _startTime) / 1000,
      _totalDur,
    ))
  }
  function getTotalDuration() { return _totalDur }

  return { play, pause, resume, stop, seekTo, setBounce, getBounce, isPlaying, getDirection, getCurrentTime, getTotalDuration }
}

/**
 * Animation player — drives camera and cluster-config state through a sequence
 * of AnimationKeyframes.
 *
 * Each keyframe has:
 *   - camera_pose_id   → target camera position/target/up/fov (null = no camera move)
 *   - config_id        → target DesignConfiguration (null = no cluster move)
 *   - transition_duration_s → time to tween from the previous state into this keyframe
 *   - hold_duration_s  → time to hold at this keyframe after arriving
 *   - easing           → interpolation curve for the transition
 *
 * Timeline per keyframe:
 *   [── transition_duration_s ──][── hold_duration_s ──]
 *
 * The player emits events via the callback returned from initAnimationPlayer:
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
 * @param {function(): object[]} opts.getCameraPoses   — returns current camera_poses array
 * @param {function(): object[]} opts.getConfigurations — returns current configurations array
 * @param {function(): object[]} opts.getClusterTransforms — returns current cluster_transforms array
 * @param {function(): object|null} opts.getHelixCtrl  — returns the live helix renderer controller
 * @param {function(object): void} [opts.onEvent]      — receives player events
 */
export function initAnimationPlayer({ camera, controls, getCameraPoses, getConfigurations, getClusterTransforms, getHelixCtrl, onEvent }) {
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

  // ── State helpers ────────────────────────────────────────────────────────────

  /** Capture the live scene state (camera + cluster transforms). */
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
    }
  }

  /** Resolve a keyframe's target state using stored camera poses and configurations. */
  function _kfState(kf) {
    const poses = getCameraPoses()
    const pose  = kf.camera_pose_id ? poses.find(p => p.id === kf.camera_pose_id) : null

    const configs = getConfigurations()
    const config  = kf.config_id ? configs.find(c => c.id === kf.config_id) : null

    return {
      position: pose ? new THREE.Vector3(...pose.position) : null,
      target:   pose ? new THREE.Vector3(...pose.target)   : null,
      up:       pose ? new THREE.Vector3(...pose.up)        : null,
      fov:      pose ? pose.fov                             : null,
      clusterTransforms: config ? config.entries.map(e => ({
        cluster_id:  e.cluster_id,
        translation: [...e.translation],
        rotation:    [...e.rotation],
      })) : null,
    }
  }

  /**
   * Build the playback schedule from the animation keyframes.
   * Each segment covers one keyframe: [transition → hold].
   * The "from" state of segment 0 is the live scene at play time.
   */
  function _buildSchedule(anim, initialState) {
    const segments = []
    let cursor    = 0
    let prevState = initialState

    for (const kf of anim.keyframes) {
      const toState  = _kfState(kf)
      const transDur = Math.max(0, kf.transition_duration_s)
      const holdDur  = Math.max(0, kf.hold_duration_s)
      segments.push({
        kfId:      kf.id,
        startT:    cursor,
        transEnd:  cursor + transDur,
        endT:      cursor + transDur + holdDur,
        fromState: prevState,
        toState,
        easing:    kf.easing ?? 'ease-in-out',
      })
      cursor += transDur + holdDur
      prevState = {
        position:          toState.position          ?? prevState.position,
        target:            toState.target            ?? prevState.target,
        up:                toState.up                ?? prevState.up,
        fov:               toState.fov               ?? prevState.fov,
        clusterTransforms: toState.clusterTransforms ?? prevState.clusterTransforms,
      }
    }
    return { segments, totalDur: cursor }
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
    let first = true
    for (const c of clusters) {
      helixCtrl.captureClusterBase(c.helix_ids, c.domain_ids?.length ? c.domain_ids : null, !first)
      first = false
    }
    _baseClusters = clusters.map(c => ({
      id:         c.id,
      translation: [...c.translation],
      rotation:    [...c.rotation],
      pivot:       [...c.pivot],
      helix_ids:   [...c.helix_ids],
      domain_ids:  c.domain_ids ? [...c.domain_ids] : [],
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

    for (const toEntry of toClusters) {
      const base = _baseClusters.find(c => c.id === toEntry.cluster_id)
      if (!base) {
        console.debug(`[anim] cluster ${toEntry.cluster_id} not in scene base — skipping`)
        continue
      }
      const fromEntry = fromClusters?.find(e => e.cluster_id === toEntry.cluster_id)
      const fromTrans = fromEntry?.translation ?? base.translation
      const fromRot   = fromEntry?.rotation    ?? base.rotation

      // Lerp translation
      const tx = fromTrans[0] + (toEntry.translation[0] - fromTrans[0]) * t
      const ty = fromTrans[1] + (toEntry.translation[1] - fromTrans[1]) * t
      const tz = fromTrans[2] + (toEntry.translation[2] - fromTrans[2]) * t

      // Slerp rotation
      const qFrom   = new THREE.Quaternion(fromRot[0], fromRot[1], fromRot[2], fromRot[3])
      const qTo     = new THREE.Quaternion(toEntry.rotation[0], toEntry.rotation[1], toEntry.rotation[2], toEntry.rotation[3])
      const qInterp = qFrom.clone().slerp(qTo, t)

      // Incremental rotation: qInterp * qBase^-1
      const qBase   = new THREE.Quaternion(base.rotation[0], base.rotation[1], base.rotation[2], base.rotation[3])
      const incrRot = qInterp.multiply(qBase.clone().invert())

      // center = pivot + base_translation; dummy = pivot + interpolated_translation
      const pivot  = new THREE.Vector3(...base.pivot)
      const center = pivot.clone().add(new THREE.Vector3(...base.translation))
      const dummy  = pivot.clone().add(new THREE.Vector3(tx, ty, tz))

      helixCtrl.applyClusterTransform(
        base.helix_ids,
        center,
        dummy,
        incrRot,
        base.domain_ids?.length ? base.domain_ids : null,
      )
    }
  }

  /** Restore all clusters to their base (design) positions after stop. */
  function _restoreBaseClusters() {
    if (!_baseClusters) return
    const helixCtrl = getHelixCtrl()
    if (!helixCtrl) return
    for (const base of _baseClusters) {
      const pivot  = new THREE.Vector3(...base.pivot)
      const center = pivot.clone().add(new THREE.Vector3(...base.translation))
      helixCtrl.applyClusterTransform(
        base.helix_ids,
        center,
        center.clone(),   // dummy = center → identity transform → restores base positions
        new THREE.Quaternion(),
        base.domain_ids?.length ? base.domain_ids : null,
      )
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

    const { fromState, toState, startT, transEnd, easing } = seg

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
    if (toState.clusterTransforms) {
      _applyClusterLerp(fromState.clusterTransforms, toState.clusterTransforms, t)
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
        _direction  = -_direction
        _seekOffset = boundTime
        _startTime  = now
        _raf = requestAnimationFrame(_loop)
      } else if (_animation?.loop) {
        _seekOffset = _direction === 1 ? 0 : _totalDur
        _startTime  = now
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

  /** Start forward playback from the beginning. */
  function play(animation) {
    stop()
    if (!animation?.keyframes?.length) return

    _animation  = animation
    _direction  = 1
    const initialState           = _liveState()
    const { segments, totalDur } = _buildSchedule(animation, initialState)
    _schedule   = segments
    _totalDur   = totalDur
    _seekOffset = 0
    _startTime  = performance.now()
    _playing    = true

    _captureAllBases()

    _raf = requestAnimationFrame(_loop)
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
    _playing    = false
    _direction  = 1
    _animation  = null
    _schedule   = []
    _totalDur   = 0
    _seekOffset = 0
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

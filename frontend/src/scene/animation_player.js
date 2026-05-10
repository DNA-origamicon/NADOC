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

import { clampQuatToJointBounds } from './assembly_revolute_math.js'

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
export function initAnimationPlayer({ camera, controls, getCameraPoses, getDesign, getClusterTransforms, getHelixCtrl, getBluntEnds, getUnfoldView, getDesignRenderer, getOverhangLinkArcs, onFetchGeometryBatch, onFetchAtomisticBatch, getAtomisticRenderer, onFetchSurfaceBatch, getSurfaceRenderer, onEvent, onTextOverlayUpdate }) {
  let _raf          = null
  let _playing      = false
  let _direction    = 1       // 1 = forward, -1 = reverse
  let _bounce       = false   // ping-pong: flip direction at each boundary
  let _loopMode     = false   // when true, restart at the opposite boundary instead of stopping
  let _disablePoses = false   // when true, camera-pose lerp is skipped so the user can orbit freely
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
  // Pre-baked atomistic position arrays: Map<featureLogIndex, number[]>
  // Each value is a flat [x0,y0,z0, x1,y1,z1, ...] array indexed by atom serial.
  let _bakedAtomistic = new Map()
  // Play-start atomistic positions — used as the rigid-body base for cluster atoms.
  let _liveAtomistic  = null
  // Pre-baked surface vertex arrays: Map<featureLogIndex, number[]>
  // Each value is a flat [x,y,z, ...] vertex array (same order as the live mesh).
  let _bakedSurface   = new Map()
  let _baking         = false

  // Joint update callback — set by play() when assemblyActive
  let _onJointUpdate  = null   // (jointId: string, value: number) => void
  let _liveJointValues = null  // { [jointId]: number } — snapshot at play() time for restore on stop

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
      // jointValues from live assembly state, if provided via liveJointValues
      jointValues: _liveJointValues ? { ..._liveJointValues } : null,
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
      // joint_values is non-null only when the keyframe explicitly stores joints
      jointValues: kf.joint_values && Object.keys(kf.joint_values).length > 0
        ? { ...kf.joint_values }
        : null,
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
        text: (kf.text && kf.text.trim()) ? {
          text:        kf.text,
          fontFamily:  kf.text_font_family  ?? 'sans-serif',
          fontSizePx:  kf.text_font_size_px ?? 24,
          color:       kf.text_color        ?? '#ffffff',
          bold:        !!kf.text_bold,
          italic:      !!kf.text_italic,
          align:       kf.text_align        ?? 'center',
        } : null,
      })
      cursor += transDur + holdDur
      prevState = {
        position:          toState.position          ?? prevState.position,
        target:            toState.target            ?? prevState.target,
        up:                toState.up                ?? prevState.up,
        fov:               toState.fov               ?? prevState.fov,
        clusterTransforms: toState.clusterTransforms ?? prevState.clusterTransforms,
        jointValues:       toState.jointValues        ?? prevState.jointValues,
      }
      prevFLI = toFLI
    }
    return { segments, totalDur: cursor }
  }

  // ── Pre-bake geometry ────────────────────────────────────────────────────────

  /** AbortController for the current bake — set by _bakeStates, cleared on
   *  completion or cancel. cancelBake() aborts it. Per-position fetches share
   *  this signal so any in-flight HTTP call gets cancelled together. */
  let _bakeAbort = null

  /** Cancel an in-flight bake. The pending fetch promises reject with
   *  AbortError; play() catches and bails out cleanly. Safe to call when no
   *  bake is running. */
  function cancelBake() {
    _bakeAbort?.abort()
    _bakeAbort = null
  }

  /** Convert a single compact-format geometry response into the lookup-map
   *  shape the player consumes (posMap / bnMap / strandSet / helixSet). */
  function _bakedFromGeo(geo) {
    const posMap    = new Map()
    const bnMap     = new Map()
    const strandSet = new Set()
    const helixSet  = new Set()
    const compact = geo?.nucleotides_compact
    if (compact) {
      for (const helixId of Object.keys(compact)) {
        const byDir = compact[helixId]
        for (const dir of Object.keys(byDir)) {
          const b = byDir[dir]
          if (!b || !Array.isArray(b.bp)) continue
          const M = b.bp.length
          for (let i = 0; i < M; i++) {
            const key = `${helixId}:${b.bp[i]}:${dir}`
            const bb  = b.bb[i]
            posMap.set(key, new THREE.Vector3(bb[0], bb[1], bb[2]))
            const bn = b.bn?.[i]
            if (bn) bnMap.set(key, new THREE.Vector3(bn[0], bn[1], bn[2]))
            const sid = b.sid?.[i]
            if (sid) strandSet.add(sid)
          }
          helixSet.add(helixId)
        }
      }
    } else if (Array.isArray(geo?.nucleotides)) {
      // Legacy dict-list path — kept for safety in case some endpoint still
      // emits the old format.
      for (const nuc of geo.nucleotides) {
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        posMap.set(key, new THREE.Vector3(...nuc.backbone_position))
        if (nuc.base_normal) bnMap.set(key, new THREE.Vector3(...nuc.base_normal))
        if (nuc.strand_id)   strandSet.add(nuc.strand_id)
        if (nuc.helix_id)    helixSet.add(nuc.helix_id)
      }
    }
    const axesMap = new Map()
    for (const ax of geo?.helix_axes ?? []) {
      axesMap.set(ax.helix_id, {
        start: new THREE.Vector3(...ax.start),
        end:   new THREE.Vector3(...ax.end),
      })
      helixSet.add(ax.helix_id)
    }
    return { posMap, axesMap, bnMap, strandSet, helixSet }
  }

  /**
   * Fetch geometry for all unique feature-log positions referenced in the animation.
   * Populates _bakedStates (Map<featureLogIndex, BakedGeometry>) in-place.
   * Stateless — does NOT change the design cursor.
   *
   * Issues ONE backend call per position so the panel can show
   * "Rendering frame X of Y" progress and the user can cancel mid-bake.
   * Backend compute is sequential per call (FastAPI worker = single thread
   * for CPU-bound numpy), so total wall-clock is the same as the legacy
   * single-batch call — but the user sees incremental progress.
   */
  async function _bakeStates(animation, liveFeatureLogIndex) {
    _baking = true
    _bakeAbort = new AbortController()
    const signal = _bakeAbort.signal
    try {
      const positionSet = new Set([liveFeatureLogIndex])
      for (const kf of animation.keyframes) {
        if (kf.feature_log_index != null) positionSet.add(kf.feature_log_index)
      }
      const positions = [...positionSet]

      const atomisticActive = getAtomisticRenderer?.()?.getMode?.() !== 'off'
      const surfaceActive   = getSurfaceRenderer?.()?.getMode?.()   !== 'off'

      // One unit of work = one position × one renderer (CG always; atomistic
      // and surface only when those reps are visible). Frontend reports
      // progress as (units complete) / (units total).
      const unitsPerPos = 1 + (atomisticActive ? 1 : 0) + (surfaceActive ? 1 : 0)
      const totalUnits  = positions.length * unitsPerPos
      let doneUnits = 0
      const _tick = () => {
        doneUnits += 1
        onEvent?.({
          type:    'baking_progress',
          done:    doneUnits,
          total:   totalUnits,
          frame:   Math.min(doneUnits, totalUnits),
          frames:  totalUnits,
        })
      }

      _bakedStates    = new Map()
      _bakedAtomistic = new Map()
      _bakedSurface   = new Map()

      const tasks = []
      for (const pos of positions) {
        // CG geometry — always.
        tasks.push(
          (onFetchGeometryBatch ? onFetchGeometryBatch([pos], { signal, suppressBusy: true })
                                : Promise.resolve(null))
            .then(batch => {
              if (batch && batch[String(pos)]) {
                _bakedStates.set(pos, _bakedFromGeo(batch[String(pos)]))
              }
              _tick()
            })
            .catch(err => { if (err?.name !== 'AbortError') _tick() })
        )
        if (onFetchAtomisticBatch && atomisticActive) {
          tasks.push(
            onFetchAtomisticBatch([pos], { signal, suppressBusy: true })
              .then(batch => {
                if (batch && batch[String(pos)] !== undefined) {
                  _bakedAtomistic.set(pos, batch[String(pos)])
                }
                _tick()
              })
              .catch(err => { if (err?.name !== 'AbortError') _tick() })
          )
        }
        if (onFetchSurfaceBatch && surfaceActive) {
          tasks.push(
            onFetchSurfaceBatch([pos], { signal, suppressBusy: true })
              .then(batch => {
                if (batch && batch[String(pos)] !== undefined) {
                  _bakedSurface.set(pos, batch[String(pos)])
                }
                _tick()
              })
              .catch(err => { if (err?.name !== 'AbortError') _tick() })
          )
        }
      }

      await Promise.all(tasks)
    } finally {
      _baking = false
      _bakeAbort = null
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
      helixCtrl.captureClusterBase(c.helix_ids, c.domain_ids?.length ? c.domain_ids : null, !first, { forceAxes: true })
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
   *
   * Returns an array of { helix_ids, center, dummy, incrRot } — one entry per
   * cluster — so the atomistic renderer can apply the same rigid-body transform
   * to its atoms without re-computing the quaternion math.
   */
  function _applyClusterLerp(fromClusters, toClusters, t) {
    if (!toClusters || !_baseClusters) return []
    const helixCtrl = getHelixCtrl()
    if (!helixCtrl) return []

    const affectedHelixIds = []
    const clusterTransforms = []   // collected for atomistic rigid-body lerp

    for (const toEntry of toClusters) {
      const base = _baseClusters.find(c => c.id === toEntry.cluster_id)
      if (!base) {
        console.debug(`[anim] cluster ${toEntry.cluster_id} not in scene base — skipping`)
        continue
      }
      const fromEntry = fromClusters?.find(e => e.cluster_id === toEntry.cluster_id)
      const fromTrans = fromEntry?.translation ?? base.translation
      const fromRot   = fromEntry?.rotation    ?? base.rotation

      // Slerp rotation, then clamp the twist component around the joint axis
      // to the joint's mechanical limits — same window the linker-relax
      // optimizer and the rotate gizmo enforce.
      const qFrom   = new THREE.Quaternion(fromRot[0], fromRot[1], fromRot[2], fromRot[3])
      const qTo     = new THREE.Quaternion(toEntry.rotation[0], toEntry.rotation[1], toEntry.rotation[2], toEntry.rotation[3])
      let   qInterp = qFrom.clone().slerp(qTo, t)
      if (base.joint) qInterp = clampQuatToJointBounds(qInterp, base.joint)

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
        { forceAxes: true },
      )
      getBluntEnds?.()?.applyClusterTransform(base.helix_ids, center, dummy, incrRot)
      affectedHelixIds.push(...base.helix_ids)
      clusterTransforms.push({ helix_ids: base.helix_ids, center, dummy, incrRot })
    }

    // Keep crossover arcs, extension beads, and 3D crossover lines in sync.
    if (affectedHelixIds.length) {
      getUnfoldView?.()?.applyClusterArcUpdate(affectedHelixIds)
      getUnfoldView?.()?.applyClusterExtArcUpdate(affectedHelixIds)
      getDesignRenderer?.()?.applyClusterCrossoverUpdate(affectedHelixIds)
    }

    return clusterTransforms
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
        { forceAxes: true },
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

  // ── Text overlay ─────────────────────────────────────────────────────────────

  // Fade in/out duration in seconds at each edge of a text-bearing segment.
  const TEXT_FADE_S = 0.1

  /**
   * Compute the live text overlay state for a given elapsed time.
   * Returns null if no text is active (or has fully faded), otherwise:
   *   { text, fontFamily, fontSizePx, color, bold, italic, align, opacity }
   */
  function _textOverlayAt(elapsed) {
    if (!_schedule.length) return null
    // Find the segment containing this time (clamp to last segment past total).
    let seg = _schedule[_schedule.length - 1]
    for (const s of _schedule) {
      if (elapsed <= s.endT) { seg = s; break }
    }
    if (!seg.text) return null
    const segDur = Math.max(0, seg.endT - seg.startT)
    if (segDur <= 0) return null
    const inSeg = Math.max(0, Math.min(elapsed - seg.startT, segDur))
    // Trapezoidal envelope: ramp up over TEXT_FADE_S, plateau, ramp down over TEXT_FADE_S.
    // For very short segments, this naturally degenerates to a triangle.
    const opacity = Math.max(0, Math.min(
      inSeg / TEXT_FADE_S,
      (segDur - inSeg) / TEXT_FADE_S,
      1,
    ))
    if (opacity <= 0) return null
    return { ...seg.text, opacity }
  }

  // ── Apply at time ────────────────────────────────────────────────────────────

  /** Apply the interpolated state for a given elapsed time. */
  function _applyAt(elapsed) {
    if (!_schedule.length) return

    let seg = _schedule[_schedule.length - 1]
    for (const s of _schedule) {
      if (elapsed <= s.endT) { seg = s; break }
    }

    onTextOverlayUpdate?.(_textOverlayAt(elapsed))

    const { fromState, toState, startT, transEnd, easing, fromFeatureLogIndex, toFeatureLogIndex } = seg

    const inTransition = elapsed < transEnd
    const rawT = inTransition
      ? (transEnd > startT ? (elapsed - startT) / (transEnd - startT) : 1)
      : 1
    const t = _ease(Math.min(rawT, 1), easing)

    // Camera — skipped when _disablePoses is on, so the user can orbit/zoom
    // freely while the design topology + clusters keep playing.
    if (!_disablePoses) {
      if (toState.position) camera.position.lerpVectors(fromState.position, toState.position, t)
      if (toState.target)   controls.target.lerpVectors(fromState.target, toState.target, t)
      if (toState.up)       camera.up.lerpVectors(fromState.up, toState.up, t).normalize()
      if (toState.fov != null && fromState.fov != null) {
        camera.fov = fromState.fov + (toState.fov - fromState.fov) * t
        camera.updateProjectionMatrix()
      }
      controls.update()
    }

    // Cluster configs
    let clusterHelixIds    = null
    let clusterTransforms  = []
    if (toState.clusterTransforms) {
      clusterTransforms = _applyClusterLerp(fromState.clusterTransforms, toState.clusterTransforms, t)
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
      // Fade-in / fade-out diff for "this is how I made this" reveal:
      // strands or helices in to-state but not from-state ⇒ scale by t (grow in).
      // strands or helices in from-state but not to-state ⇒ scale by (1 - t) (shrink out).
      // Symmetric — works for both forward and reverse playback because the
      // formulas use t directly (= "progress toward to-state").
      let fadeOpts = null
      if ((fromBaked.strandSet || fromBaked.helixSet)
          && (toBaked.strandSet || toBaked.helixSet)) {
        const fromS = fromBaked.strandSet ?? new Set()
        const toS   = toBaked.strandSet   ?? new Set()
        const fromH = fromBaked.helixSet  ?? new Set()
        const toH   = toBaked.helixSet    ?? new Set()
        const revealInStrandIds  = new Set([...toS].filter(s => !fromS.has(s)))
        const revealOutStrandIds = new Set([...fromS].filter(s => !toS.has(s)))
        const revealInHelixIds   = new Set([...toH].filter(h => !fromH.has(h)))
        const revealOutHelixIds  = new Set([...fromH].filter(h => !toH.has(h)))
        if (revealInStrandIds.size || revealOutStrandIds.size
            || revealInHelixIds.size || revealOutHelixIds.size) {
          fadeOpts = { revealInStrandIds, revealOutStrandIds, revealInHelixIds, revealOutHelixIds }
        }
      }
      getHelixCtrl()?.applyPositionLerp(fromBaked, toBaked, t, clusterHelixIds, fadeOpts)
    }

    // Overhang link arcs (linker bridge tubes + connector arcs) are rendered
    // by overhangLinkArcs from the LIVE design — they don't follow keyframe
    // playback automatically. Drive a per-connection scale here based on
    // whether each linker's complement strand is present in the from / to
    // baked states. Connections in both → scale 1; only-to → t (fade in);
    // only-from → 1-t (fade out); neither → 0. Mirrors the strand-level fade
    // applyPositionLerp does for backbone beads, so beads + arcs grow/shrink
    // together when keyframes cross a linker creation/deletion point.
    const overhangArcs = getOverhangLinkArcs?.()
    if (overhangArcs?.setConnectionScales && (fromBaked || toBaked)) {
      const conns = getDesign()?.overhang_connections ?? []
      if (conns.length) {
        const fromS = fromBaked?.strandSet ?? new Set()
        const toS   = toBaked?.strandSet   ?? new Set()
        const scales = new Map()
        for (const c of conns) {
          const a = `__lnk__${c.id}__a`
          const b = `__lnk__${c.id}__b`
          const inFrom = fromS.has(a) || fromS.has(b)
          const inTo   = toS.has(a)   || toS.has(b)
          let s
          if (inFrom && inTo)  s = 1
          else if (inTo)       s = t
          else if (inFrom)     s = 1 - t
          else                 s = 0
          scales.set(c.id, s)
        }
        overhangArcs.setConnectionScales(scales)
      }
    }

    // Atomistic lerp — lerp flat xyz arrays between pre-baked deformed states.
    // Cluster atoms use rigid-body rotation (same formula as CG applyClusterTransform)
    // rather than linear lerp, with the play-start positions as the rotation base.
    const fromAtom = _bakedAtomistic.get(fromFeatureLogIndex)
    const toAtom   = _bakedAtomistic.get(toFeatureLogIndex)
    if (fromAtom && toAtom) {
      getAtomisticRenderer?.()?.applyPositionLerp(
        fromAtom, toAtom, t,
        _liveAtomistic, clusterTransforms, clusterHelixIds,
      )
    }

    // Surface lerp — lerp vertex positions of the live mesh between pre-baked states.
    // Skipped automatically when vertex counts differ (topology mismatch).
    const fromSurf = _bakedSurface.get(fromFeatureLogIndex)
    const toSurf   = _bakedSurface.get(toFeatureLogIndex)
    if (fromSurf && toSurf) {
      getSurfaceRenderer?.()?.applyPositionLerp(fromSurf, toSurf, t)
    }

    // Assembly joint lerp — interpolate joint_values from keyframe to keyframe.
    if (_onJointUpdate && fromState.jointValues && toState.jointValues) {
      for (const [jointId, toVal] of Object.entries(toState.jointValues)) {
        const fromVal = fromState.jointValues[jointId] ?? toVal
        _onJointUpdate(jointId, fromVal + (toVal - fromVal) * t)
      }
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
      } else if (_loopMode || _animation?.loop) {
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
   *
   * opts.onJointUpdate — optional (jointId, value) callback fired each frame
   *   during joint lerp; used by assembly mode to drive patchAssemblyJoint.
   * opts.liveJointValues — snapshot of joint values at play time, used to
   *   restore state on stop().
   */
  function play(animation, opts = {}) {
    stop()
    if (!animation?.keyframes?.length) return Promise.resolve()

    _onJointUpdate   = opts.onJointUpdate   ?? null
    _liveJointValues = opts.liveJointValues ?? null

    _animation = animation
    // Initialize _loopMode from the animation's persisted flag — the panel
    // can later override via setLoopMode without waiting for an API
    // roundtrip + store replacement.
    _loopMode  = !!animation.loop
    const hasSlow = (getAtomisticRenderer?.()?.getMode?.() !== 'off') ||
                    (getSurfaceRenderer?.()?.getMode?.()   !== 'off')
    onEvent?.({ type: 'baking', hasSlow })

    const liveFLI = getDesign()?.feature_log_cursor ?? -1

    return _bakeStates(animation, liveFLI).then(() => {
      if (_animation !== animation) return   // user stopped while baking

      // Capture play-start atomistic positions as the rigid-body base for cluster atoms.
      _liveAtomistic = _bakedAtomistic.get(liveFLI) ?? null

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
    }).catch(err => {
      // User cancelled during bake — propagate as a cancelled event so the
      // panel can drop its progress popup and revert button state.
      if (err?.name === 'AbortError') {
        onEvent?.({ type: 'baking_cancelled' })
        return
      }
      throw err
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
    // Restore overhang link arcs to full visibility — playback may have
    // scaled them down for linker creation/deletion fade-outs.
    getOverhangLinkArcs?.()?.resetConnectionScales?.()

    // Restore assembly joints to pre-play values if callback is set
    if (_onJointUpdate && _liveJointValues) {
      for (const [jointId, val] of Object.entries(_liveJointValues)) {
        _onJointUpdate(jointId, val)
      }
    }

    _playing         = false
    _direction       = 1
    _animation       = null
    _schedule        = []
    _totalDur        = 0
    _seekOffset      = 0
    _lastSeekKfId    = null
    _bakedStates     = new Map()
    _bakedAtomistic  = new Map()
    _liveAtomistic   = null
    _bakedSurface    = new Map()
    _baking          = false
    _onJointUpdate   = null
    _liveJointValues = null
    if (_raf) { cancelAnimationFrame(_raf); _raf = null }

    onTextOverlayUpdate?.(null)
    onEvent?.({ type: 'stopped' })
  }

  function setBounce(enabled) { _bounce = enabled }
  function getBounce()        { return _bounce }

  /**
   * Loop-mode setter. Mirrors the per-animation `loop` flag but updates
   * synchronously so a mid-playback toggle takes effect at the next
   * boundary without waiting for the API roundtrip + store replacement.
   */
  function setLoopMode(enabled) { _loopMode = !!enabled }
  function getLoopMode()        { return _loopMode }

  /**
   * When true, _applyAt skips the camera-pose lerp so the user can orbit
   * freely with OrbitControls while the design topology + cluster
   * transforms continue to animate.
   */
  function setDisablePoses(enabled) { _disablePoses = !!enabled }
  function getDisablePoses()        { return _disablePoses }

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

  /** Synchronous read of the current overlay state — used by the export pipeline. */
  function getActiveTextOverlay() { return _textOverlayAt(getCurrentTime()) }

  return { play, pause, resume, stop, seekTo, cancelBake, setBounce, getBounce, setLoopMode, getLoopMode, setDisablePoses, getDisablePoses, isPlaying, getDirection, getCurrentTime, getTotalDuration, getActiveTextOverlay }
}

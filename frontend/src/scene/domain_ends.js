/**
 * Domain end indicators — rings at bp-index positions where a strand has no
 * neighbor on one side (hasPlus XOR hasMinus on the (helix, direction) coverage map).
 *
 * A domain end is defined by a coverage-map scan over all strand domains:
 *   hasPlus  = covMap[helix:dir].has(bp + 1)
 *   hasMinus = covMap[helix:dir].has(bp - 1)
 * Overhang domains use strand-local coverage so adjacent unrelated staples in
 * dense imported designs do not hide terminal overhang labels.
 *   isDomainEnd = hasPlus XOR hasMinus
 *   openSide = +1 if !hasPlus, -1 otherwise
 *
 * Staple domain ends are suppressed when the open side has scaffold coverage.
 * Deduplication key = (helix_id, disk_bp) where disk_bp = bp + openSide.
 * Transform key = overhang_id ?? helix_id — enables per-domain independent transforms.
 *
 * Click callback payload: { helixId, bp, diskBp, openSide, transformKey, plane, offsetNm }
 */

import * as THREE from 'three'
import { store }  from '../state/store.js'
import { BDNA_RISE_PER_BP, CADNANO_TRACK_OFFSET } from '../constants.js'

const RING_INNER    = 0.35
const RING_OUTER    = 1.15
const HIT_RADIUS    = RING_OUTER * 1.25
const RING_SEGS     = 32
const RING_COLOR    = 0x58a6ff
const RING_OPACITY  = 0.45
const LABEL_OPACITY   = 0.72
const LABEL_OPACITY_H = 1.00
const LABEL_GAP_NM    = 1.0
const CADNANO_LABEL_GAP_BP = 1
const _Z_HAT        = new THREE.Vector3(0, 0, 1)
const _clusterV     = new THREE.Vector3()
const _clusterQ     = new THREE.Quaternion()

// ── Geometry helpers ───────────────────────────────────────────────────────────

/**
 * Compute a position along a per-overhang-domain axis entry (from ovhg_axes).
 * ovhgAx = { bp_min, bp_max, start: [x,y,z], end: [x,y,z] }
 * where start = position at bp_min and end = position at bp_max+1.
 * Extrapolates naturally for bp outside the domain.
 */
function _axisPointOvhg(ovhgAx, bp) {
  const s = new THREE.Vector3(...ovhgAx.start)
  const e = new THREE.Vector3(...ovhgAx.end)
  // Domain spans bp_min … bp_max (bpSpan bps); end is placed one bp beyond bp_max.
  const bpSpan = ovhgAx.bp_max - ovhgAx.bp_min + 1
  const t = (bp - ovhgAx.bp_min) / bpSpan
  return s.addScaledVector(e.clone().sub(s), t)
}

/** Axis tangent direction for a per-overhang-domain axis entry. */
function _axisDirOvhg(ovhgAx) {
  return new THREE.Vector3(...ovhgAx.end).sub(new THREE.Vector3(...ovhgAx.start)).normalize()
}

function _planeFromHelixId(helixId) {
  const m = helixId.match(/^h_(XY|XZ|YZ)_/)
  return m ? m[1] : 'XY'
}

function _offsetFromPos(pos, plane) {
  if (plane === 'XY') return pos.z
  if (plane === 'XZ') return pos.y
  return pos.x
}

/**
 * Compute the 3-D position on (or extrapolated beyond) a helix axis at disk_bp.
 * axDef = { start, end, samples? } from helixAxes map, or null for straight axis.
 * Returns THREE.Vector3.
 */
function _axisPoint(h, axDef, diskBp) {
  const sx = axDef ? axDef.start[0] : h.axis_start.x
  const sy = axDef ? axDef.start[1] : h.axis_start.y
  const sz = axDef ? axDef.start[2] : h.axis_start.z
  const ex = axDef ? axDef.end[0] : h.axis_end.x
  const ey = axDef ? axDef.end[1] : h.axis_end.y
  const ez = axDef ? axDef.end[2] : h.axis_end.z
  const dLen = Math.sqrt((ex-sx)**2 + (ey-sy)**2 + (ez-sz)**2)
  const physLen = Math.max(1, Math.round(dLen / BDNA_RISE_PER_BP) + 1)
  const t = physLen > 1 ? (diskBp - (h.bp_start ?? 0)) / (physLen - 1) : 0

  const samples = axDef?.samples
  if (samples?.length >= 2) {
    if (t <= 0) {
      const s0 = new THREE.Vector3(...samples[0])
      const s1 = new THREE.Vector3(...samples[1])
      const tang = s1.clone().sub(s0).normalize()
      return s0.addScaledVector(tang, t * (physLen - 1) * BDNA_RISE_PER_BP)
    }
    if (t >= 1) {
      const n = samples.length
      const sA = new THREE.Vector3(...samples[n - 2])
      const sB = new THREE.Vector3(...samples[n - 1])
      const tang = sB.clone().sub(sA).normalize()
      return sB.clone().addScaledVector(tang, (t - 1) * (physLen - 1) * BDNA_RISE_PER_BP)
    }
    const sf  = t * (samples.length - 1)
    const si  = Math.min(Math.floor(sf), samples.length - 2)
    const sfr = sf - si
    return new THREE.Vector3(...samples[si]).lerp(new THREE.Vector3(...samples[si + 1]), sfr)
  }

  // Straight helix — lerp extrapolates naturally for t outside [0, 1]
  const start = new THREE.Vector3(sx, sy, sz)
  const end   = new THREE.Vector3(ex, ey, ez)
  return start.lerp(end, t)
}

/** Axis tangent direction at disk_bp (normalized). */
function _axisDir(h, axDef, diskBp) {
  const sx = axDef ? axDef.start[0] : h.axis_start.x
  const sy = axDef ? axDef.start[1] : h.axis_start.y
  const sz = axDef ? axDef.start[2] : h.axis_start.z
  const ex = axDef ? axDef.end[0] : h.axis_end.x
  const ey = axDef ? axDef.end[1] : h.axis_end.y
  const ez = axDef ? axDef.end[2] : h.axis_end.z
  const dLen = Math.sqrt((ex-sx)**2 + (ey-sy)**2 + (ez-sz)**2)
  const physLen = Math.max(1, Math.round(dLen / BDNA_RISE_PER_BP) + 1)
  const t = physLen > 1 ? (diskBp - (h.bp_start ?? 0)) / (physLen - 1) : 0

  const samples = axDef?.samples
  if (samples?.length >= 2) {
    if (t <= 0) {
      return new THREE.Vector3(...samples[1]).sub(new THREE.Vector3(...samples[0])).normalize()
    }
    if (t >= 1) {
      const n = samples.length
      return new THREE.Vector3(...samples[n - 1]).sub(new THREE.Vector3(...samples[n - 2])).normalize()
    }
    const sf = t * (samples.length - 1)
    const si = Math.min(Math.floor(sf), samples.length - 2)
    return new THREE.Vector3(...samples[si + 1]).sub(new THREE.Vector3(...samples[si])).normalize()
  }
  return new THREE.Vector3(ex - sx, ey - sy, ez - sz).normalize()
}

function _cadnanoTrackOffset(strandType, scaffoldDir) {
  const isScaffold = strandType === 'scaffold'
  const scaffoldIsForward = (scaffoldDir ?? 'FORWARD') === 'FORWARD'
  return (isScaffold === scaffoldIsForward)
    ? CADNANO_TRACK_OFFSET
    : -CADNANO_TRACK_OFFSET
}

function _domainEndPose3d(rec, h, axDef) {
  const ovhgAx = rec.overhangId ? (axDef?.ovhgAxes?.[rec.overhangId] ?? null) : null
  const diskPos = ovhgAx ? _axisPointOvhg(ovhgAx, rec.diskBp) : _axisPoint(h, axDef, rec.diskBp)
  const endPos  = ovhgAx ? _axisPointOvhg(ovhgAx, rec.bp)     : _axisPoint(h, axDef, rec.bp)
  const dir     = ovhgAx ? _axisDirOvhg(ovhgAx)                : _axisDir(h, axDef, rec.diskBp)
  const quat    = new THREE.Quaternion().setFromUnitVectors(_Z_HAT, dir)
  const labelPos = diskPos.clone().addScaledVector(dir, rec.openSide * LABEL_GAP_NM)
  return { diskPos, endPos, dir, quat, labelPos, ovhgAx }
}

function _domainEndPoseCadnano(rec, rowMap, spacing, midX) {
  const row = rowMap.get(rec.helixId)
  if (row == null) return null
  const y = -row * spacing + _cadnanoTrackOffset(rec.strandType, rec.scaffoldDir)
  const z = rec.diskBp * BDNA_RISE_PER_BP
  const diskPos = new THREE.Vector3(midX, y, z)
  const labelPos = new THREE.Vector3(
    midX,
    y,
    z + rec.openSide * CADNANO_LABEL_GAP_BP * BDNA_RISE_PER_BP,
  )
  return { diskPos, labelPos }
}

function _applyDomainEndPose(end, pose) {
  end.ringMesh.position.copy(pose.diskPos)
  end.hitMesh.position.copy(pose.diskPos)
  if (pose.quat) {
    end.ringMesh.quaternion.copy(pose.quat)
    end.hitMesh.quaternion.copy(pose.quat)
  }
  if (end.labelSprite) end.labelSprite.position.copy(pose.labelPos)
}

// ── Detection (pure — no Three.js) ────────────────────────────────────────────

function _computeDomainEnds(design) {
  const helices  = design.helices ?? []
  const hmap     = new Map(helices.map(h => [h.id, h]))
  const labelMap = new Map(helices.map((h, i) => [h.id, h.label ?? i]))
  const scaffoldDirByHelix = new Map()
  for (const strand of design.strands ?? []) {
    const st = strand.strand_type?.value ?? String(strand.strand_type)
    if (st !== 'scaffold') continue
    for (const d of strand.domains ?? []) {
      if (!scaffoldDirByHelix.has(d.helix_id)) {
        scaffoldDirByHelix.set(d.helix_id, d.direction?.value ?? String(d.direction))
      }
    }
  }

  // Build coverage maps.  Regular domains keep the historical global
  // helix+direction continuity.  Overhang domains consult strand-local coverage
  // below so unrelated neighboring strands do not hide terminal overhang labels.
  const cov       = new Map()   // "helixId:dir" → Set<bp>
  const strandCov = new Map()   // "strandId:helixId:dir" → Set<bp>
  const scafCov = new Map()   // helixId → Set<bp>
  for (const strand of design.strands ?? []) {
    const st = strand.strand_type?.value ?? String(strand.strand_type)
    for (const d of strand.domains ?? []) {
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      const dir = d.direction?.value ?? String(d.direction)
      const ck  = `${d.helix_id}:${dir}`
      if (!cov.has(ck)) cov.set(ck, new Set())
      const cs = cov.get(ck)
      for (let b = lo; b <= hi; b++) cs.add(b)
      const sk = `${strand.id}:${d.helix_id}:${dir}`
      if (!strandCov.has(sk)) strandCov.set(sk, new Set())
      const ss = strandCov.get(sk)
      for (let b = lo; b <= hi; b++) ss.add(b)
      if (st === 'scaffold') {
        if (!scafCov.has(d.helix_id)) scafCov.set(d.helix_id, new Set())
        const sc = scafCov.get(d.helix_id)
        for (let b = lo; b <= hi; b++) sc.add(b)
      }
    }
  }

  // Domain end detection — result keyed by "helixId:diskBp"
  const results = new Map()   // "helixId:diskBp" → entry

  for (const strand of design.strands ?? []) {
    const st = strand.strand_type?.value ?? String(strand.strand_type)
    const domains = strand.domains ?? []
    for (let di = 0; di < domains.length; di++) {
      const d = domains[di]
      const h = hmap.get(d.helix_id)
      if (!h) continue
      const lo     = Math.min(d.start_bp, d.end_bp)
      const hi     = Math.max(d.start_bp, d.end_bp)
      const dir    = d.direction?.value ?? String(d.direction)
      const scaf   = scafCov.get(d.helix_id) ?? new Set()
      const ovhgId = d.overhang_id ?? null
      const covSet = ovhgId
        ? (strandCov.get(`${strand.id}:${d.helix_id}:${dir}`) ?? new Set())
        : (cov.get(`${d.helix_id}:${dir}`) ?? new Set())

      for (const bp of [lo, hi]) {
        const hasPlus  = covSet.has(bp + 1)
        const hasMinus = covSet.has(bp - 1)
        if (hasPlus === hasMinus) continue           // both covered (nick) or isolated

        const openSide = hasPlus ? -1 : 1
        const diskBp   = bp + openSide

        if (st === 'staple' && scaf.has(diskBp)) continue  // scaffold on open side

        const key      = `${d.helix_id}:${diskBp}`
        const existing = results.get(key)
        if (existing) {
          if (ovhgId && !existing.overhangId) {
            existing.overhangId = ovhgId
            existing.transformKey = ovhgId
            existing.direction = dir
            existing.strandType = st
            existing.strandId = strand.id
            existing.domainIndex = di
          }
          continue
        }

        results.set(key, {
          helixId:      d.helix_id,
          helixLabel:   labelMap.get(d.helix_id),
          bpStart:      h.bp_start ?? 0,
          bp,
          diskBp,
          openSide,
          direction:    dir,
          scaffoldDir:  scaffoldDirByHelix.get(d.helix_id) ?? 'FORWARD',
          overhangId:   ovhgId,
          transformKey: ovhgId ?? d.helix_id,
          strandType:   st,
          // Owning strand-domain for the strand-end this blunt-end ring caps.
          // Lets sub-cluster cluster transforms (clusters with `domain_ids`)
          // pick out which blunt ends belong to the moved subset rather than
          // skipping every blunt end on a partially-moved helix.
          strandId:     strand.id,
          domainIndex:  di,
        })
      }
    }
  }

  return Array.from(results.values())
}

// ── Number sprite ──────────────────────────────────────────────────────────────

function _makeNumberSprite(num) {
  const size = 128, cv = document.createElement('canvas')
  cv.width = size; cv.height = size
  const ctx = cv.getContext('2d'), r = size / 2
  ctx.beginPath(); ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(13,17,23,0.80)'; ctx.fill()
  ctx.beginPath(); ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
  ctx.strokeStyle = 'rgba(88,166,255,0.65)'; ctx.lineWidth = r * 0.13; ctx.stroke()
  const str = String(num)
  ctx.fillStyle = '#e6edf3'
  ctx.font = `bold ${str.length > 2 ? r * 0.68 : r * 0.84}px monospace`
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(str, r, r + 1)
  const tex = new THREE.CanvasTexture(cv)
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
  const spr = new THREE.Sprite(mat)
  spr.scale.set(0.90, 0.90, 1)
  return spr
}

// ── Main initialiser ───────────────────────────────────────────────────────────

export function initDomainEnds(scene, camera, canvas, {
  onDomainEndClick,
  onDomainEndRightClick,
  isDisabled,
  getUnfoldView,
} = {}) {

  const _group  = new THREE.Group()
  scene.add(_group)

  const _ringGeo = new THREE.RingGeometry(RING_INNER, RING_OUTER, RING_SEGS)
  const _hitGeo  = new THREE.CircleGeometry(HIT_RADIUS, RING_SEGS)

  let _ends         = []           // DomainEnd records with Three.js objects attached
  let _cbEnds       = new Map()    // entry → { pos, labelPos, quat }
  let _hoveredIdx   = -1
  let _pendingIdx   = -1
  let _pendingPos   = null
  let _pendingRightIdx = -1
  let _pendingRightPos = null
  let _lastCadnanoParams = null

  const _raycaster = new THREE.Raycaster()
  const _ndc       = new THREE.Vector2()

  // ── Rebuild ──────────────────────────────────────────────────────────────────

  function _rebuild(design, helixAxes) {
    for (const e of _ends) {
      e.ringMesh.material.dispose()
      e.hitMesh.material.dispose()
      if (e.labelSprite) {
        e.labelSprite.material.map?.dispose()
        e.labelSprite.material.dispose()
        _group.remove(e.labelSprite)
      }
      _group.remove(e.ringMesh)
      _group.remove(e.hitMesh)
    }
    _ends = []; _cbEnds.clear()
    _hoveredIdx = -1; _pendingIdx = -1; _pendingPos = null

    if (!design?.helices?.length) return

    const helixById  = new Map(design.helices.map(h => [h.id, h]))
    const showLabels = store.getState().showHelixLabels

    for (const rec of _computeDomainEnds(design)) {
      const h     = helixById.get(rec.helixId)
      if (!h) continue
      const axDef  = helixAxes?.[rec.helixId] ?? null
      const pose = _domainEndPose3d(rec, h, axDef)

      const plane    = _planeFromHelixId(rec.helixId)
      const offsetNm = _offsetFromPos(pose.diskPos, plane)

      // Ring mesh
      const ringMat = new THREE.MeshBasicMaterial({
        color: RING_COLOR, transparent: true, opacity: 0,
        side: THREE.DoubleSide, depthWrite: false,
      })
      const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
      ringMesh.position.copy(pose.diskPos)
      ringMesh.quaternion.copy(pose.quat)

      // Hit mesh
      const hitMat = new THREE.MeshBasicMaterial({
        transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false,
      })
      const hitMesh = new THREE.Mesh(_hitGeo, hitMat)
      hitMesh.position.copy(pose.diskPos)
      hitMesh.quaternion.copy(pose.quat)

      const labelSprite = _makeNumberSprite(rec.helixLabel)
      labelSprite.position.copy(pose.labelPos)
      labelSprite.material.depthTest = false
      labelSprite.renderOrder = 5
      labelSprite.material.opacity = showLabels ? LABEL_OPACITY : 0

      _group.add(ringMesh)
      _group.add(hitMesh)
      _group.add(labelSprite)

      _ends.push({
        ...rec,
        plane, offsetNm,
        ringMesh, hitMesh, labelSprite,
        basePos:      pose.diskPos.clone(),
        baseLabelPos: pose.labelPos.clone(),
        baseQuat:     pose.quat.clone(),
        endPos:       pose.endPos.clone(),
        _cbPos: null, _cbLabelPos: null, _cbQuat: null,
      })
    }
  }

  // ── Hover / click ─────────────────────────────────────────────────────────────

  function _setNDC(e) {
    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  *  2 - 1,
      -((e.clientY - rect.top) / rect.height) *  2 + 1,
    )
    _raycaster.setFromCamera(_ndc, camera)
  }

  function _getHitIndex(e) {
    if (!_ends.length) return -1
    _setNDC(e)
    const hits = _raycaster.intersectObjects(_ends.map(r => r.hitMesh))
    if (!hits.length) return -1
    return _ends.findIndex(r => r.hitMesh === hits[0].object)
  }

  function _setHovered(idx) {
    if (idx === _hoveredIdx) return
    if (_hoveredIdx >= 0) {
      _ends[_hoveredIdx].ringMesh.material.opacity = 0
      if (_ends[_hoveredIdx].labelSprite)
        _ends[_hoveredIdx].labelSprite.material.opacity =
          store.getState().showHelixLabels ? LABEL_OPACITY : 0
    }
    _hoveredIdx = idx
    if (_hoveredIdx >= 0) {
      _ends[_hoveredIdx].ringMesh.material.opacity = RING_OPACITY
      if (_ends[_hoveredIdx].labelSprite)
        _ends[_hoveredIdx].labelSprite.material.opacity = LABEL_OPACITY_H
    }
  }

  function _updateLabelVisibility() {
    const show = store.getState().showHelixLabels
    for (const { labelSprite } of _ends) {
      if (!labelSprite) continue
      labelSprite.material.opacity = show ? LABEL_OPACITY : 0
    }
    if (_hoveredIdx >= 0 && show && _ends[_hoveredIdx]?.labelSprite)
      _ends[_hoveredIdx].labelSprite.material.opacity = LABEL_OPACITY_H
  }

  function _hasEffectiveTransform(helixId, design) {
    return design?.cluster_transforms?.some(ct => {
      if (!ct.helix_ids.includes(helixId)) return false
      const [x, y, z, w] = ct.rotation
      const [tx, ty, tz] = ct.translation
      return Math.abs(x) > 1e-9 || Math.abs(y) > 1e-9 || Math.abs(z) > 1e-9 || Math.abs(w - 1) > 1e-9
          || Math.abs(tx) > 1e-9 || Math.abs(ty) > 1e-9 || Math.abs(tz) > 1e-9
    }) ?? false
  }

  function _fireLeft(idx) {
    const e = _ends[idx]
    const design = store.getState().currentDesign
    const hasDeformations = !!(design?.deformations?.length) || _hasEffectiveTransform(e.helixId, design)
    onDomainEndClick?.({ helixId: e.helixId, bp: e.bp, diskBp: e.diskBp, openSide: e.openSide,
      transformKey: e.transformKey, plane: e.plane, offsetNm: e.offsetNm, hasDeformations })
  }

  function _fireRight(idx, x, y) {
    const e = _ends[idx]
    const design = store.getState().currentDesign
    const hasDeformations = !!(design?.deformations?.length) || _hasEffectiveTransform(e.helixId, design)
    onDomainEndRightClick?.({ helixId: e.helixId, bp: e.bp, diskBp: e.diskBp, openSide: e.openSide,
      transformKey: e.transformKey, plane: e.plane, offsetNm: e.offsetNm, hasDeformations,
      clientX: x, clientY: y })
  }

  function _isBlocked() {
    return isDisabled?.() || !store.getState().toolFilters.bluntEnds
  }

  function _onPointerMove(e) {
    if (_isBlocked()) { _setHovered(-1); return }
    _setHovered(_getHitIndex(e))
  }

  function _onPointerDown(e) {
    if (_isBlocked()) return
    const idx = _hoveredIdx
    if (idx < 0) return
    if (e.button === 0) {
      e.stopImmediatePropagation()
      _pendingIdx = idx; _pendingPos = { x: e.clientX, y: e.clientY }
    } else if (e.button === 2) {
      _pendingRightIdx = idx; _pendingRightPos = { x: e.clientX, y: e.clientY }
    }
  }

  function _onPointerUp(e) {
    if (e.button !== 0) return
    if (_pendingIdx < 0) return
    const idx = _pendingIdx; _pendingIdx = -1
    const moved = _pendingPos ? Math.hypot(e.clientX - _pendingPos.x, e.clientY - _pendingPos.y) : 999
    _pendingPos = null
    if (moved > 4) return
    e.stopImmediatePropagation()
    _fireLeft(idx)
  }

  function _onContextMenu(e) {
    if (e.ctrlKey) return
    if (_isBlocked()) return
    if (_pendingRightIdx < 0) return
    const idx = _pendingRightIdx; _pendingRightIdx = -1
    const moved = _pendingRightPos
      ? Math.hypot(e.clientX - _pendingRightPos.x, e.clientY - _pendingRightPos.y) : 999
    _pendingRightPos = null
    if (moved > 4) return
    e.preventDefault(); e.stopImmediatePropagation()
    _fireRight(idx, e.clientX, e.clientY)
  }

  canvas.addEventListener('pointermove', _onPointerMove)
  canvas.addEventListener('pointerdown', _onPointerDown, { capture: true })
  canvas.addEventListener('pointerup',   _onPointerUp,   { capture: true })
  canvas.addEventListener('contextmenu', _onContextMenu, { capture: true })

  // ── Store subscription ─────────────────────────────────────────────────────────

  store.subscribe((newState, prevState) => {
    if (
      newState.currentDesign    !== prevState.currentDesign ||
      newState.currentHelixAxes !== prevState.currentHelixAxes
    ) {
      // Skip rebuild when currentDesign changes due to a cluster-transform patch
      if (newState.currentHelixAxes === prevState.currentHelixAxes) {
        const p = prevState.currentDesign, n = newState.currentDesign
        if (p && n &&
            p.helices.length         === n.helices.length       &&
            p.strands.length         === n.strands.length       &&
            p.deformations.length    === n.deformations.length  &&
            p.extensions.length      === n.extensions.length    &&
            p.overhangs.length       === n.overhangs.length     &&
            p.helices.every((ph, i) => {
              const nh = n.helices[i]
              return nh && ph.length_bp === nh.length_bp && ph.bp_start === nh.bp_start
            })) return
      }
      _rebuild(newState.currentDesign, newState.currentHelixAxes)
      if (store.getState().cadnanoActive && _lastCadnanoParams) {
        _applyCadnanoPositions(_lastCadnanoParams.rowMap, _lastCadnanoParams.spacing, _lastCadnanoParams.midX)
      }
      if (!store.getState().cadnanoActive) getUnfoldView?.()?.reapplyIfActive()
    } else if (
      newState.toolFilters     !== prevState.toolFilters ||
      newState.showHelixLabels !== prevState.showHelixLabels
    ) {
      _updateLabelVisibility()
    }
  })

  // ── Transform matching ─────────────────────────────────────────────────────────
  // An entry matches a key set if its transformKey OR helixId is in the set.
  // This allows cluster gizmo (passes helixIds) to move all ends on a helix,
  // while overhang drag (passes ovhgId) moves only that domain's ends.
  //
  // For SUB-CLUSTER moves (cluster has `domain_ids`), a second filter on
  // ``domainKeySet`` (set of "strand_id:domain_index" strings) is enforced —
  // an end matches only if the strand-domain it caps is also in the moved
  // subset. Without this, scadnano-imported designs (which routinely produce
  // split-domain clusters) would skip every blunt end on a partially-moved
  // helix.

  function _matches(entry, keySet, domainKeySet = null) {
    const helixMatch = keySet.has(entry.transformKey) || keySet.has(entry.helixId)
    if (!helixMatch) return false
    if (!domainKeySet) return true
    if (entry.strandId == null || entry.domainIndex == null) return false
    return domainKeySet.has(`${entry.strandId}:${entry.domainIndex}`)
  }

  // ── Cadnano positions (internal) ────────────────────────────────────────────

  function _applyCadnanoPositions(rowMap, spacing, midX) {
    _lastCadnanoParams = { rowMap, spacing, midX }
    for (const end of _ends) {
      const pose = _domainEndPoseCadnano(end, rowMap, spacing, midX)
      if (pose) _applyDomainEndPose(end, pose)
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────────

  return {
    clear() { _rebuild(null, null) },

    setVisible(bool) { _group.visible = bool },

    /**
     * Lerp rings and labels from straight to deformed axis positions.
     * straightAxesMap: Map<helixId, {start: THREE.Vector3, end: THREE.Vector3}>
     * t: 0 = straight, 1 = deformed
     */
    applyDeformLerp(straightAxesMap, t) {
      for (const end of _ends) {
        if (end.overhangId) continue  // overhang stubs don't participate in bend deformations
        const sa = straightAxesMap?.get(end.helixId)
        if (!sa) continue
        const dLen = sa.start.distanceTo(sa.end)
        const physLen = Math.max(1, Math.round(dLen / BDNA_RISE_PER_BP) + 1)
        const tDisk = physLen > 1 ? (end.diskBp - end.bpStart) / (physLen - 1) : 0
        const sp = sa.start.clone().lerp(sa.end, tDisk)
        end.ringMesh.position.set(
          sp.x + (end.basePos.x - sp.x) * t,
          sp.y + (end.basePos.y - sp.y) * t,
          sp.z + (end.basePos.z - sp.z) * t,
        )
        end.hitMesh.position.copy(end.ringMesh.position)
        if (!end.labelSprite) continue
        // Label straight pos = sp + openSide * straightDir
        const straightDir = sa.end.clone().sub(sa.start).normalize()
        const spL = sp.clone().addScaledVector(straightDir, end.openSide * LABEL_GAP_NM)
        end.labelSprite.position.set(
          spL.x + (end.baseLabelPos.x - spL.x) * t,
          spL.y + (end.baseLabelPos.y - spL.y) * t,
          spL.z + (end.baseLabelPos.z - spL.z) * t,
        )
        // Slerp ring orientation: straight → deformed
        const sDir    = sa.end.clone().sub(sa.start).normalize()
        const straightQ = new THREE.Quaternion().setFromUnitVectors(_Z_HAT, sDir)
        const lerpedQ   = straightQ.slerp(end.baseQuat, t)
        end.ringMesh.quaternion.copy(lerpedQ)
        end.hitMesh.quaternion.copy(lerpedQ)
      }
    },

    /** Translate rings by per-helix unfold offset at lerp factor t. */
    applyUnfoldOffsets(helixOffsets, t, straightAxesMap) {
      for (const end of _ends) {
        const off = helixOffsets.get(end.helixId)
        const ox = off ? off.x * t : 0
        const oy = off ? off.y * t : 0
        const oz = off ? off.z * t : 0
        let bx, by, bz
        if (straightAxesMap) {
          const sa = straightAxesMap.get(end.helixId)
          if (sa) {
            const dLen = sa.start.distanceTo(sa.end)
            const physLen = Math.max(1, Math.round(dLen / BDNA_RISE_PER_BP) + 1)
            const tDisk = physLen > 1 ? (end.diskBp - end.bpStart) / (physLen - 1) : 0
            const sp = sa.start.clone().lerp(sa.end, tDisk)
            bx = sp.x; by = sp.y; bz = sp.z
          } else {
            bx = end.basePos.x; by = end.basePos.y; bz = end.basePos.z
          }
        } else {
          bx = end.basePos.x; by = end.basePos.y; bz = end.basePos.z
        }
        end.ringMesh.position.set(bx + ox, by + oy, bz + oz)
        end.hitMesh.position.set(bx + ox, by + oy, bz + oz)
        if (end.labelSprite && end.baseLabelPos) {
          const lox = end.baseLabelPos.x - end.basePos.x
          const loy = end.baseLabelPos.y - end.basePos.y
          const loz = end.baseLabelPos.z - end.basePos.z
          end.labelSprite.position.set(bx + ox + lox, by + oy + loy, bz + oz + loz)
        }
      }
    },

    applyCadnanoPositions(rowMap, spacing, midX) {
      _applyCadnanoPositions(rowMap, spacing, midX)
    },

    /**
     * Move rings to follow XPBD backbone positions.
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    applyPhysicsPositions(updates) {
      const posMap = new Map()
      for (const u of updates) posMap.set(`${u.helix_id}:${u.bp_index}:${u.direction}`, u.backbone_position)
      for (const end of _ends) {
        const f = posMap.get(`${end.helixId}:${end.bp}:FORWARD`)
        const r = posMap.get(`${end.helixId}:${end.bp}:REVERSE`)
        let px, py, pz
        if (f && r) { px = (f[0]+r[0])*.5; py = (f[1]+r[1])*.5; pz = (f[2]+r[2])*.5 }
        else if (f || r) { const p = f ?? r; px = p[0]; py = p[1]; pz = p[2] }
        else continue
        end.ringMesh.position.set(px, py, pz)
        end.hitMesh.position.set(px, py, pz)
        if (end.labelSprite && end.baseLabelPos) {
          const lox = end.baseLabelPos.x - end.basePos.x
          const loy = end.baseLabelPos.y - end.basePos.y
          const loz = end.baseLabelPos.z - end.basePos.z
          end.labelSprite.position.set(px + lox, py + loy, pz + loz)
        }
      }
    },

    revertPhysics() {
      for (const end of _ends) {
        end.ringMesh.position.copy(end.basePos)
        end.hitMesh.position.copy(end.basePos)
        end.ringMesh.quaternion.copy(end.baseQuat)
        end.hitMesh.quaternion.copy(end.baseQuat)
        end.labelSprite?.position.copy(end.baseLabelPos)
      }
    },

    /**
     * Snapshot ring/label positions for entries matching transformKeys.
     * transformKeys: Set or Array of transform keys (ovhgId or helixId strings).
     * Match: entry.transformKey ∈ keys  OR  entry.helixId ∈ keys.
     * domainIds: optional list of {strand_id, domain_index} for sub-cluster
     * mode — when provided, only ends whose owning strand-domain is in the
     * set are snapshotted.
     */
    captureClusterBase(transformKeys, append = false, domainIds = null) {
      const keySet = transformKeys instanceof Set ? transformKeys : new Set(transformKeys)
      const domainKeySet = domainIds?.length
        ? new Set(domainIds.map(d => `${d.strand_id}:${d.domain_index}`))
        : null
      if (!append) _cbEnds.clear()
      for (const end of _ends) {
        if (!_matches(end, keySet, domainKeySet)) continue
        _cbEnds.set(end, {
          pos:      end.ringMesh.position.clone(),
          labelPos: end.labelSprite ? end.labelSprite.position.clone() : null,
          quat:     end.ringMesh.quaternion.clone(),
        })
      }
    },

    /**
     * Apply incremental cluster transform to matching entries and shafts.
     * transformKeys: Set or Array of transform keys.
     * domainIds: optional list of {strand_id, domain_index} for sub-cluster mode.
     */
    applyClusterTransform(transformKeys, centerVec, dummyPosVec, incrRotQuat, domainIds = null) {
      const keySet = transformKeys instanceof Set ? transformKeys : new Set(transformKeys)
      const domainKeySet = domainIds?.length
        ? new Set(domainIds.map(d => `${d.strand_id}:${d.domain_index}`))
        : null
      for (const end of _ends) {
        if (!_matches(end, keySet, domainKeySet)) continue
        const snap = _cbEnds.get(end)
        if (!snap) continue
        _clusterV.copy(snap.pos).sub(centerVec).applyQuaternion(incrRotQuat)
        const nx = _clusterV.x + dummyPosVec.x
        const ny = _clusterV.y + dummyPosVec.y
        const nz = _clusterV.z + dummyPosVec.z
        end.ringMesh.position.set(nx, ny, nz)
        end.hitMesh.position.set(nx, ny, nz)
        _clusterQ.multiplyQuaternions(incrRotQuat, snap.quat)
        end.ringMesh.quaternion.copy(_clusterQ)
        end.hitMesh.quaternion.copy(_clusterQ)
        if (snap.labelPos && end.labelSprite) {
          _clusterV.copy(snap.labelPos).sub(centerVec).applyQuaternion(incrRotQuat)
          end.labelSprite.position.set(
            _clusterV.x + dummyPosVec.x,
            _clusterV.y + dummyPosVec.y,
            _clusterV.z + dummyPosVec.z,
          )
        }
      }
    },

    /** Diagnostic table: one row per domain end. */
    getEndTable() {
      return _ends.map(e => ({
        helixId:      e.helixId,
        helixLabel:   e.helixLabel,
        bp:           e.bp,
        diskBp:       e.diskBp,
        openSide:     e.openSide,
        direction:    e.direction,
        scaffoldDir:  e.scaffoldDir,
        transformKey: e.transformKey,
        overhangId:   e.overhangId,
        strandType:   e.strandType,
        plane:        e.plane,
        offsetNm:     e.offsetNm,
        ringPos3d:    e.ringMesh.position.toArray(),
        labelPos3d:   e.labelSprite?.position.toArray() ?? null,
        endPos3d:     e.endPos.toArray(),
      }))
    },

    /** Diagnostic table: one row per rendered helix label sprite. */
    getHelixLabelTable() {
      return _ends
        .filter(e => !!e.labelSprite)
        .map(e => ({
          helixId:      e.helixId,
          helixLabel:   e.helixLabel,
          domainBp:     e.bp,
          ringBp:       e.diskBp,
          openSide:     e.openSide,
          direction:    e.direction,
          scaffoldDir:  e.scaffoldDir,
          transformKey: e.transformKey,
          overhangId:   e.overhangId,
          strandType:   e.strandType,
          visible:      e.labelSprite.visible && e.labelSprite.material.opacity > 0,
          opacity:      e.labelSprite.material.opacity,
          labelPos3d:   e.labelSprite.position.toArray(),
          ringPos3d:    e.ringMesh.position.toArray(),
        }))
    },

    dispose() {
      canvas.removeEventListener('pointermove', _onPointerMove)
      canvas.removeEventListener('pointerdown', _onPointerDown, { capture: true })
      canvas.removeEventListener('pointerup',   _onPointerUp,   { capture: true })
      canvas.removeEventListener('contextmenu', _onContextMenu, { capture: true })
      for (const { ringMesh, hitMesh, labelSprite } of _ends) {
        ringMesh.material.dispose()
        hitMesh.material.dispose()
        if (labelSprite) {
          labelSprite.material.map?.dispose()
          labelSprite.material.dispose()
          _group.remove(labelSprite)
        }
        _group.remove(ringMesh)
        _group.remove(hitMesh)
      }
      _ends = []
      _ringGeo.dispose()
      _hitGeo.dispose()
      scene.remove(_group)
    },
  }
}

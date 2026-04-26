/**
 * Blunt end indicators — rings at free helix endpoints, visible only on hover.
 *
 * A helix endpoint is "free" when no other helix in the design starts or ends
 * at the same 3-D position (within 1 pm tolerance).
 *
 * Each blunt end has:
 *  - an invisible hit disk (CircleGeometry) that absorbs raycasts for hover detection
 *  - a visible ring (RingGeometry) that fades in when the cursor is over the hit disk
 *
 * Clicking a ring (pointerdown+up without drag) opens the slice plane at that
 * exact offset in continuation mode.  The pointerdown is intercepted in the
 * CAPTURE phase so OrbitControls never sees it, preventing unwanted rotation.
 */

import * as THREE from 'three'
import { store }  from '../state/store.js'
import { BDNA_RISE_PER_BP } from '../constants.js'

const RING_INNER      = 0.35
const RING_OUTER      = 1.15
const HIT_RADIUS      = RING_OUTER * 1.25   // slightly larger than ring for comfortable clicking
const RING_SEGS       = 32
const RING_COLOR      = 0x58a6ff
const _Z_HAT          = new THREE.Vector3(0, 0, 1)
const _bluntAxisDir   = new THREE.Vector3()
const _bluntStraightQ = new THREE.Quaternion()
const _bluntLerpedQ   = new THREE.Quaternion()
const _bluntLabelOff  = new THREE.Vector3()   // scratch for lerped label offset
const _bluntClusterV  = new THREE.Vector3()   // scratch for cluster transform
const _bluntClusterQ  = new THREE.Quaternion()
const RING_OPACITY    = 0.45
const TOL             = 0.001               // nm — two endpoints at the same position
const LABEL_OPACITY   = 0.72               // always-visible label opacity
const LABEL_OPACITY_H = 1.00               // label opacity when ring is hovered

export function initBluntEnds(scene, camera, canvas, { onBluntEndClick, onBluntEndRightClick, isDisabled, getUnfoldView } = {}) {

  const _group   = new THREE.Group()
  scene.add(_group)

  const _ringGeo = new THREE.RingGeometry(RING_INNER, RING_OUTER, RING_SEGS)
  const _hitGeo  = new THREE.CircleGeometry(HIT_RADIUS, RING_SEGS)

  // ── Number sprite helper ──────────────────────────────────────────────────
  function _makeNumberSprite(num) {
    const size = 128
    const cv   = document.createElement('canvas')
    cv.width   = size; cv.height = size
    const ctx  = cv.getContext('2d')
    const r    = size / 2
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(13,17,23,0.80)'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(88,166,255,0.65)'
    ctx.lineWidth   = r * 0.13
    ctx.stroke()
    const str = String(num)
    ctx.fillStyle = '#e6edf3'
    ctx.font      = `bold ${str.length > 2 ? r * 0.68 : r * 0.84}px monospace`
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(str, r, r + 1)
    const tex = new THREE.CanvasTexture(cv)
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
    const spr = new THREE.Sprite(mat)
    spr.scale.set(0.90, 0.90, 1)
    return spr
  }

  // Each entry: { ringMesh, hitMesh, labelSprite, plane, offsetNm }
  let _ends = []
  let _hoveredIdx = -1   // index into _ends, -1 = none
  let _cbEnds = new Map()  // end entry → { pos, labelPos, quat } snapshots for cluster transforms
  // Cached parameters from the last applyCadnanoPositions() call.
  // Re-applied after _rebuild() when cadnano is active so new label sprites
  // land at 2D cadnano positions rather than 3D helix axis endpoints.
  let _lastCadnanoParams = null

  const _raycaster = new THREE.Raycaster()
  const _ndc       = new THREE.Vector2()

  // pending click: set on pointerdown when hovering a ring
  let _pendingIdx      = -1
  let _pendingPos      = null
  let _pendingRightIdx = -1
  let _pendingRightPos = null

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _planeFromHelixId(helixId) {
    const m = helixId.match(/^h_(XY|XZ|YZ)_/)
    return m ? m[1] : 'XY'
  }

  function _offsetFromEndpoint(endpoint, plane) {
    if (plane === 'XY') return endpoint.z
    if (plane === 'XZ') return endpoint.y
    return endpoint.x
  }

  function _setNDC(e) {
    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  *  2 - 1,
      -((e.clientY - rect.top) / rect.height) *  2 + 1,
    )
    _raycaster.setFromCamera(_ndc, camera)
  }

  // ── Rebuild ────────────────────────────────────────────────────────────────

  /**
   * @param {object|null} design
   * @param {Record<string,{start:number[],end:number[],samples:number[][]}>|null} helixAxes
   *   Deformed axis positions from store.currentHelixAxes.  When provided, rings
   *   are placed at the deformed endpoint positions with deformed axis orientation.
   *   offsetNm still uses original axis coordinates for backend compatibility.
   */
  function _rebuild(design, helixAxes) {
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
    _ends       = []
    _hoveredIdx = -1
    _pendingIdx = -1
    _pendingPos = null

    if (!design?.helices?.length) return

    const helices = design.helices

    // Precompute physical bp count per helix from ORIGINAL axis geometry.
    // For cadnano imports, h.length_bp = full array length (e.g. 832) while the helix
    // only occupies a sub-range.  All bp arithmetic that depends on "how long is this
    // helix physically" must use physLen, not h.length_bp.
    const physLenMap = new Map()
    for (const h of helices) {
      const dx = h.axis_end.x - h.axis_start.x
      const dy = h.axis_end.y - h.axis_start.y
      const dz = h.axis_end.z - h.axis_start.z
      const axisNm = Math.sqrt(dx * dx + dy * dy + dz * dz)
      physLenMap.set(h.id, Math.max(1, Math.round(axisNm / BDNA_RISE_PER_BP) + 1))
    }

    // armBpStart: minimum global bp_start across all helices.  Used to encode sourceBp
    // so that deformation_editor.startToolAtBp correctly recovers the global endpoint bp:
    //   globalB = armBpStart + sourceBp − 1
    const armBpStart = Math.min(...helices.map(h => h.bp_start ?? 0))

    // Strand termini: "helixId:bp" pairs where a strand genuinely starts or ends.
    // Used in Loop 1 to reject axis endpoints that are only crossover entry/exit points
    // (e.g. imported ovhg_inline_ stub helices where a strand enters mid-flight and the
    // junction bp has no nick — no actual free end at axis_start of the stub).
    const strandTerminiBps = new Set()
    if (design.strands) {
      for (const strand of design.strands) {
        const d0 = strand.domains?.[0]
        const dN = strand.domains?.at(-1)
        if (d0?.helix_id != null) strandTerminiBps.add(`${d0.helix_id}:${d0.start_bp}`)
        if (dN?.helix_id != null) strandTerminiBps.add(`${dN.helix_id}:${dN.end_bp}`)
      }
    }

    // Build deformed-position lookup so _isEndFree can compare deformed endpoints
    const deformedPos = {}  // helix_id → { start: THREE.Vector3, end: THREE.Vector3 }
    for (const h of helices) {
      const axDef = helixAxes?.[h.id]
      deformedPos[h.id] = {
        start: axDef ? new THREE.Vector3(...axDef.start)
                     : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z),
        end:   axDef ? new THREE.Vector3(...axDef.end)
                     : new THREE.Vector3(h.axis_end.x,   h.axis_end.y,   h.axis_end.z),
      }
    }

    function _isEndFreeDeformed(hId, testPos) {
      for (const h of helices) {
        if (h.id === hId) continue
        const dp = deformedPos[h.id]
        if (dp.start.distanceTo(testPos) < TOL) return false
        if (dp.end.distanceTo(testPos)   < TOL) return false
      }
      return true
    }

    for (const h of helices) {
      const axDef  = helixAxes?.[h.id]
      const dp     = deformedPos[h.id]
      const plane  = _planeFromHelixId(h.id)

      // Straight-axis fallback direction (used when no samples available)
      const straightDir = dp.end.clone().sub(dp.start).normalize()

      // Pair: [deformed 3-D position, original topological endpoint (for offsetNm), isStart]
      const endpointPairs = [
        { deformed: dp.start, original: h.axis_start, isStart: true  },
        { deformed: dp.end,   original: h.axis_end,   isStart: false },
      ]

      for (const { deformed, original, isStart } of endpointPairs) {
        if (!_isEndFreeDeformed(h.id, deformed)) continue
        // Require a genuine strand terminus at this bp.  Crossover entry/exit points
        // (e.g. cadnano imported stubs) have no nick here — skip them.
        const physLen  = physLenMap.get(h.id) ?? h.length_bp
        const endBp    = isStart ? (h.bp_start ?? 0) : (h.bp_start ?? 0) + physLen - 1
        if (!strandTerminiBps.has(`${h.id}:${endBp}`)) continue

        // Per-endpoint tangent: start uses first segment, end uses last segment
        let axisDir
        if (axDef?.samples?.length >= 2) {
          const n = axDef.samples.length
          if (isStart) {
            axisDir = new THREE.Vector3(...axDef.samples[1])
              .sub(new THREE.Vector3(...axDef.samples[0])).normalize()
          } else {
            axisDir = new THREE.Vector3(...axDef.samples[n - 1])
              .sub(new THREE.Vector3(...axDef.samples[n - 2])).normalize()
          }
        } else {
          axisDir = straightDir
        }
        const quat = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 0, 1),
          axisDir,
        )

        // offsetNm uses original axis coordinates — backend continuation lookup relies on these
        const offsetNm = _offsetFromEndpoint(original, plane)

        const ringMat = new THREE.MeshBasicMaterial({
          color:       RING_COLOR,
          transparent: true,
          opacity:     0,
          side:        THREE.DoubleSide,
          depthWrite:  false,
        })
        const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
        ringMesh.position.copy(deformed)
        ringMesh.quaternion.copy(quat)

        const hitMat = new THREE.MeshBasicMaterial({
          transparent: true,
          opacity:     0,
          side:        THREE.DoubleSide,
          depthWrite:  false,
        })
        const hitMesh = new THREE.Mesh(_hitGeo, hitMat)
        hitMesh.position.copy(deformed)
        hitMesh.quaternion.copy(quat)

        // sourceBp encodes the endpoint position for startToolAtBp.  That function
        // computes globalB = armBpStart + sourceBp − 1, so:
        //   start end → sourceBp = 0  (triggers the start-end branch, globalB ignored)
        //   end end   → sourceBp = h.bp_start − armBpStart + physLen
        //              so globalB = h.bp_start + physLen − 1 = physical last bp  ✓
        const sourceBp = isStart ? 0 : h.bp_start - armBpStart + physLen

        // Number label — shows 0-based helix index (position in design.helices array).
        // Offset outward (away from helix body) to clear the axis arrow cone:
        //   isStart: axisDir points INTO helix → negate to go outward
        //   isEnd:   axisDir points OUT of helix → use as-is
        // The cone head (AXIS_HEAD_LEN=0.55 nm, centered at endpoint) extends
        // 0.275 nm beyond the endpoint; sprite radius ≈ 0.45 nm → need > 0.72 nm clear.
        const helixNum  = h.label ?? helices.indexOf(h)
        const labelSprite = _makeNumberSprite(helixNum)
        const outward = isStart ? axisDir.clone().negate() : axisDir.clone()
        labelSprite.position.copy(deformed).addScaledVector(outward, 1.0)
        labelSprite.material.depthTest = false
        labelSprite.renderOrder = 5
        const showLabels = store.getState().showHelixLabels
        labelSprite.material.opacity = showLabels ? LABEL_OPACITY : 0

        _group.add(ringMesh)
        _group.add(hitMesh)
        _group.add(labelSprite)
        _ends.push({
          ringMesh, hitMesh, labelSprite, plane, offsetNm, helixId: h.id, sourceBp,
          isStart,
          helixLabel: helixNum,
          // Global bp_start of this helix (needed to convert local physicsBp → global bp_index).
          bpStart: h.bp_start ?? 0,
          // LOCAL bp index of the terminus particle (0 = first bp, physLen-1 = last bp).
          // Add bpStart to convert to global bp_index for posMap / cadnano z-position.
          physicsBp: isStart ? 0 : physLen - 1,
          // Store original world positions for unfold/deform translation.
          basePos:      deformed.clone(),
          baseLabelPos: labelSprite.position.clone(),
          baseQuat:     ringMesh.quaternion.clone(),  // deformed orientation (t=1 anchor)
        })
      }
    }

    // ── Interior strand endpoints (gap boundaries within merged helices) ──────
    // Strand 5'/3' termini that fall strictly inside a helix (not at axis_start
    // or axis_end) get a selectable ring so users can trigger continuation from
    // within an existing gap.

    const helixById    = new Map(design.helices.map(h => [h.id, h]))
    const seenInterior = new Set()   // deduplicate: "helixId:bp"

    // Per-helix bp coverage used to detect nicks vs. genuine gap boundaries.
    // A terminus at bp N is a nick (skip it) when both N-1 and N+1 are covered
    // by some domain on the same helix.  At least one uncovered neighbor means
    // there is a real gap, so the ring should be shown.
    const _covMap = new Map()  // helixId → Set<bp>
    for (const strand of design.strands) {
      for (const d of strand.domains) {
        let s = _covMap.get(d.helix_id)
        if (!s) { s = new Set(); _covMap.set(d.helix_id, s) }
        const lo = Math.min(d.start_bp, d.end_bp)
        const hi = Math.max(d.start_bp, d.end_bp)
        for (let b = lo; b <= hi; b++) s.add(b)
      }
    }

    for (const strand of design.strands) {
      const checks = [
        { helixId: strand.domains[0]?.helix_id,    bp: strand.domains[0]?.start_bp    },
        { helixId: strand.domains.at(-1)?.helix_id, bp: strand.domains.at(-1)?.end_bp },
      ]
      for (const { helixId, bp } of checks) {
        if (helixId == null || bp == null) continue
        const h = helixById.get(helixId)
        if (!h) continue
        const key = `${helixId}:${bp}`
        if (seenInterior.has(key)) continue

        const axDef  = helixAxes?.[helixId]
        const start3 = axDef
          ? new THREE.Vector3(...axDef.start)
          : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z)
        const end3   = axDef
          ? new THREE.Vector3(...axDef.end)
          : new THREE.Vector3(h.axis_end.x, h.axis_end.y, h.axis_end.z)
        // Use bp-fraction for the interior check — chord-length-based t breaks for
        // bent helices where chord < arc, causing bps near the tip to have t > 1
        // and be incorrectly skipped.
        const localBp  = bp - h.bp_start
        // Use physLen (physical bp count) as denominator, not h.length_bp.
        // For cadnano sub-helices h.length_bp = full array length (e.g. 832) while
        // the helix only spans physLen bps, so strand termini at the physical end
        // would get tArc ≪ 1 with the wrong denominator and be treated as interior.
        const physLenI = physLenMap.get(helixId) ?? h.length_bp
        const tArc     = physLenI > 1 ? localBp / (physLenI - 1) : 0
        // t≤0 or t≥1 means bp is at (or beyond) a physical axis endpoint — the
        // exterior loop above already places a ring there.
        if (tArc <= 0 || tArc >= 1) continue
        seenInterior.add(key)

        // Nick suppression: skip if both adjacent bps are covered — that means
        // two strand fragments butt directly against each other with no gap.
        const _cov = _covMap.get(helixId)
        if (_cov?.has(bp - 1) && _cov?.has(bp + 1)) continue

        // For curved helices, walk along the samples curve rather than lerping on
        // the chord between deformed endpoints — chord interpolation places rings
        // at incorrect intermediate positions that don't follow the helix contour.
        let pos, axisDir
        if (axDef?.samples?.length >= 2) {
          const n   = axDef.samples.length - 1
          const sf  = tArc * n
          const si  = Math.min(Math.floor(sf), n - 1)
          const sfr = sf - si
          const sA  = new THREE.Vector3(...axDef.samples[si])
          const sB  = new THREE.Vector3(...axDef.samples[si + 1])
          pos     = sA.clone().lerp(sB, sfr)
          axisDir = sB.clone().sub(sA).normalize()
        } else {
          pos     = start3.clone().lerp(end3, tArc)
          axisDir = end3.clone().sub(start3).normalize()
        }
        const plane    = _planeFromHelixId(helixId)
        const quat     = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 0, 1), axisDir,
        )
        const offsetNm = _offsetFromEndpoint({ x: pos.x, y: pos.y, z: pos.z }, plane)

        const ringMat = new THREE.MeshBasicMaterial({
          color: RING_COLOR, transparent: true, opacity: 0,
          side: THREE.DoubleSide, depthWrite: false,
        })
        const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
        ringMesh.position.copy(pos)
        ringMesh.quaternion.copy(quat)

        const hitMat = new THREE.MeshBasicMaterial({
          transparent: true, opacity: 0,
          side: THREE.DoubleSide, depthWrite: false,
        })
        const hitMesh = new THREE.Mesh(_hitGeo, hitMat)
        hitMesh.position.copy(pos)
        hitMesh.quaternion.copy(quat)

        // Offset toward the gap side (axisDir points in increasing-bp direction).
        const gapAt2HighBp  = !_cov?.has(bp + 1)
        const labelDir2Sign = gapAt2HighBp ? 1.0 : -1.0

        const showLabels2  = store.getState().showHelixLabels
        const helixNum2    = h.label ?? helices.indexOf(h)
        const labelSprite2 = _makeNumberSprite(helixNum2)
        labelSprite2.position.copy(pos).addScaledVector(axisDir, labelDir2Sign * 1.0)
        labelSprite2.material.depthTest = false
        labelSprite2.renderOrder = 5
        labelSprite2.material.opacity = showLabels2 ? LABEL_OPACITY : 0
        _group.add(labelSprite2)

        _group.add(ringMesh)
        _group.add(hitMesh)
        _ends.push({
          ringMesh, hitMesh, labelSprite: labelSprite2,
          plane, offsetNm, helixId,
          sourceBp:   bp - h.bp_start,
          isStart:    false,
          isInterior: true,
          interiorT:  tArc,
          helixLabel: helixNum2,
          bpStart:    h.bp_start ?? 0,
          physicsBp:  bp - h.bp_start,
          basePos:      pos.clone(),
          baseLabelPos: labelSprite2.position.clone(),
          baseQuat:     quat.clone(),
        })
      }
    }

    // ── Domain gap edges: overhang-helix side of disconnected strand segments ──
    // An overhang-only helix (no scaffold) can carry two separate overhang domains
    // with a physical gap between them.  Each domain endpoint that is interior to
    // the helix axis AND faces an uncovered bp (gap side) gets a ring+label.
    //
    // Loop 2 above only checks the 5′/3′ termini of each strand (start of first
    // domain, end of last domain).  That misses:
    //   • Crossover-entry gap edges (strand continues onto another helix — no
    //     terminus on the overhang helix at all).
    //   • Terminus-side gap edges where the terminal domain direction causes
    //     Loop 2's end_bp to land on an axis endpoint (tArc ≥ 1) and be skipped.
    // This pass catches both cases by walking ALL domain endpoints, not strand
    // termini.  Nick suppression (both neighbors covered → skip) prevents fires at
    // normal crossover sites where the helix is fully covered on both sides.

    for (const strand of design.strands) {
      for (const d of strand.domains) {
        const helixId = d.helix_id
        if (helixId == null) continue
        const h = helixById.get(helixId)
        if (!h) continue
        const _cov = _covMap.get(helixId)
        if (!_cov) continue

        const physLenG = physLenMap.get(helixId) ?? h.length_bp
        const bpStart  = h.bp_start ?? 0

        for (const bp of [Math.min(d.start_bp, d.end_bp), Math.max(d.start_bp, d.end_bp)]) {
          const key = `${helixId}:${bp}`
          if (seenInterior.has(key)) continue  // already emitted by Loop 2

          const localBp = bp - bpStart
          const tArc    = physLenG > 1 ? localBp / (physLenG - 1) : 0
          if (tArc <= 0 || tArc >= 1) continue  // axis endpoints handled by Loop 1

          // Only fire where the domain abuts a genuine gap
          if (_cov.has(bp - 1) && _cov.has(bp + 1)) continue

          seenInterior.add(key)

          const axDef  = helixAxes?.[helixId]
          const start3 = axDef
            ? new THREE.Vector3(...axDef.start)
            : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z)
          const end3   = axDef
            ? new THREE.Vector3(...axDef.end)
            : new THREE.Vector3(h.axis_end.x, h.axis_end.y, h.axis_end.z)

          let pos, axisDir
          if (axDef?.samples?.length >= 2) {
            const n   = axDef.samples.length - 1
            const sf  = tArc * n
            const si  = Math.min(Math.floor(sf), n - 1)
            const sfr = sf - si
            const sA  = new THREE.Vector3(...axDef.samples[si])
            const sB  = new THREE.Vector3(...axDef.samples[si + 1])
            pos     = sA.clone().lerp(sB, sfr)
            axisDir = sB.clone().sub(sA).normalize()
          } else {
            pos     = start3.clone().lerp(end3, tArc)
            axisDir = end3.clone().sub(start3).normalize()
          }
          const plane    = _planeFromHelixId(helixId)
          const quat     = new THREE.Quaternion().setFromUnitVectors(
            new THREE.Vector3(0, 0, 1), axisDir,
          )
          const offsetNm = _offsetFromEndpoint({ x: pos.x, y: pos.y, z: pos.z }, plane)

          const ringMatG = new THREE.MeshBasicMaterial({
            color: RING_COLOR, transparent: true, opacity: 0,
            side: THREE.DoubleSide, depthWrite: false,
          })
          const ringMesh = new THREE.Mesh(_ringGeo, ringMatG)
          ringMesh.position.copy(pos)
          ringMesh.quaternion.copy(quat)

          const hitMatG = new THREE.MeshBasicMaterial({
            transparent: true, opacity: 0,
            side: THREE.DoubleSide, depthWrite: false,
          })
          const hitMesh = new THREE.Mesh(_hitGeo, hitMatG)
          hitMesh.position.copy(pos)
          hitMesh.quaternion.copy(quat)

          // Offset the label toward the gap, not into the domain.
          // axisDir points in the direction of increasing bp; the gap may be
          // on either side of this domain endpoint.
          const gapAtHighBp   = !_cov.has(bp + 1)
          const labelDirSign  = gapAtHighBp ? 1.0 : -1.0

          const showLabelsG  = store.getState().showHelixLabels
          const helixNumG    = h.label ?? helices.indexOf(h)
          const labelSpriteG = _makeNumberSprite(helixNumG)
          labelSpriteG.position.copy(pos).addScaledVector(axisDir, labelDirSign * 1.0)
          labelSpriteG.material.depthTest = false
          labelSpriteG.renderOrder = 5
          labelSpriteG.material.opacity = showLabelsG ? LABEL_OPACITY : 0
          _group.add(labelSpriteG)

          _group.add(ringMesh)
          _group.add(hitMesh)
          _ends.push({
            ringMesh, hitMesh, labelSprite: labelSpriteG,
            plane, offsetNm, helixId,
            sourceBp:   localBp,
            isStart:    false,
            isInterior: true,
            interiorT:  tArc,
            helixLabel: helixNumG,
            bpStart,
            physicsBp:  localBp,
            basePos:      pos.clone(),
            baseLabelPos: labelSpriteG.position.clone(),
            baseQuat:     quat.clone(),
          })
        }
      }
    }

    // ── Overhang crossovers: main-helix side of regular↔overhang transitions ──
    // When a strand crosses between a regular helix and an overhang-only helix,
    // place a ring at the crossover bp on the main helix.  These are assembly
    // connection points distinct from ordinary interior strand termini.
    const seenXover = new Set()  // "helixId:bp" — separate from seenInterior

    for (const strand of design.strands) {
      const doms = strand.domains
      for (let i = 0; i < doms.length - 1; i++) {
        const d0 = doms[i], d1 = doms[i + 1]
        if (d0.helix_id === d1.helix_id) continue

        // Determine which domain is the main helix and which is the overhang side
        let mainHelixId = null, crossBp = null, ovhgHelixId = null
        const d0IsOH = d0.overhang_id != null
        const d1IsOH = d1.overhang_id != null
        if (!d0IsOH && d1IsOH) {
          // regular → overhang: crossover bp is d0.end_bp on d0.helix_id
          mainHelixId = d0.helix_id; crossBp = d0.end_bp;   ovhgHelixId = d1.helix_id
        } else if (d0IsOH && !d1IsOH) {
          // overhang → regular: crossover bp is d1.start_bp on d1.helix_id
          mainHelixId = d1.helix_id; crossBp = d1.start_bp; ovhgHelixId = d0.helix_id
        }
        if (mainHelixId == null || crossBp == null) continue

        const key = `${mainHelixId}:${crossBp}`
        if (seenXover.has(key) || seenInterior.has(key)) continue

        const h = helixById.get(mainHelixId)
        if (!h) continue

        const physLenX = physLenMap.get(mainHelixId) ?? h.length_bp
        const localBp  = crossBp - h.bp_start
        const tX       = physLenX > 1 ? localBp / (physLenX - 1) : 0
        if (tX < 0 || tX > 1) continue
        seenXover.add(key)

        const axDef  = helixAxes?.[mainHelixId]
        const start3 = axDef
          ? new THREE.Vector3(...axDef.start)
          : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z)
        const end3   = axDef
          ? new THREE.Vector3(...axDef.end)
          : new THREE.Vector3(h.axis_end.x, h.axis_end.y, h.axis_end.z)

        let pos, axisDir
        if (axDef?.samples?.length >= 2) {
          const n   = axDef.samples.length - 1
          const sf  = tX * n
          const si  = Math.min(Math.floor(sf), n - 1)
          const sfr = sf - si
          const sA  = new THREE.Vector3(...axDef.samples[si])
          const sB  = new THREE.Vector3(...axDef.samples[si + 1])
          pos     = sA.clone().lerp(sB, sfr)
          axisDir = sB.clone().sub(sA).normalize()
        } else {
          pos     = start3.clone().lerp(end3, tX)
          axisDir = end3.clone().sub(start3).normalize()
        }

        const plane    = _planeFromHelixId(mainHelixId)
        const quat     = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 0, 1), axisDir,
        )
        const offsetNm = _offsetFromEndpoint({ x: pos.x, y: pos.y, z: pos.z }, plane)

        const ringMat = new THREE.MeshBasicMaterial({
          color: RING_COLOR, transparent: true, opacity: 0,
          side: THREE.DoubleSide, depthWrite: false,
        })
        const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
        ringMesh.position.copy(pos)
        ringMesh.quaternion.copy(quat)

        const hitMat = new THREE.MeshBasicMaterial({
          transparent: true, opacity: 0,
          side: THREE.DoubleSide, depthWrite: false,
        })
        const hitMesh = new THREE.Mesh(_hitGeo, hitMat)
        hitMesh.position.copy(pos)
        hitMesh.quaternion.copy(quat)

        // Overhang crossover rings mark the main-helix attachment point for
        // continuation affordance only.  No number label here — the stub helix's
        // own Loop 1/2 rings already carry the label at the correct free end.
        _group.add(ringMesh)
        _group.add(hitMesh)
        _ends.push({
          ringMesh, hitMesh, labelSprite: null,
          plane, offsetNm, helixId: mainHelixId,
          sourceBp:   localBp,
          isStart:    false,
          isInterior: true,
          interiorT:  tX,
          helixLabel: null,
          bpStart:    h.bp_start ?? 0,
          physicsBp:  localBp,
          basePos:      pos.clone(),
          baseLabelPos: null,
          baseQuat:     quat.clone(),
        })
      }
    }
  }

  function _getHitIndex(e) {
    if (!_ends.length) return -1
    _setNDC(e)
    const hitMeshes = _ends.map(r => r.hitMesh)
    const hits      = _raycaster.intersectObjects(hitMeshes)
    if (!hits.length) return -1
    return hitMeshes.indexOf(hits[0].object)
  }

  function _setHovered(idx) {
    if (idx === _hoveredIdx) return
    // Restore previous
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
    // Re-apply hover emphasis if still hovering
    if (_hoveredIdx >= 0 && show && _ends[_hoveredIdx]?.labelSprite) {
      _ends[_hoveredIdx].labelSprite.material.opacity = LABEL_OPACITY_H
    }
  }

  // ── Store subscription ────────────────────────────────────────────────────

  store.subscribe((newState, prevState) => {
    if (
      newState.currentDesign    !== prevState.currentDesign ||
      newState.currentHelixAxes !== prevState.currentHelixAxes
    ) {
      // Skip rebuild when currentDesign changes due to a cluster-transform patch
      // (metadata-only: same topology, no geometry update).  The cluster gizmo
      // positions blunt ends live via applyClusterTransform; a rebuild here would
      // reset them to the stale pre-transform currentHelixAxes positions.
      if (newState.currentHelixAxes === prevState.currentHelixAxes) {
        const p = prevState.currentDesign, n = newState.currentDesign
        if (p && n &&
            p.helices.length         === n.helices.length       &&
            p.strands.length         === n.strands.length       &&
            p.deformations.length    === n.deformations.length  &&
            p.extensions.length      === n.extensions.length    &&
            p.overhangs.length       === n.overhangs.length     &&
            // Also check helix geometry hasn't changed — resize can grow/shrink helices,
            // which changes axis_end/axis_start even when counts are the same.
            p.helices.every((ph, i) => {
              const nh = n.helices[i]
              return nh && ph.length_bp === nh.length_bp && ph.bp_start === nh.bp_start
            })) return
      }
      _rebuild(newState.currentDesign, newState.currentHelixAxes)
      // After rebuild, re-apply view-specific positions so new label sprites land
      // in the correct coordinate space rather than 3D helix axis endpoints.
      // blunt_ends' subscriber fires AFTER the cadnano reapply subscriber, so
      // _rebuild() creates new sprites at 3D positions; re-apply cached cadnano
      // params immediately to correct them.
      if (store.getState().cadnanoActive && _lastCadnanoParams) {
        const { rowMap, spacing, midX } = _lastCadnanoParams
        _applyCadnanoPositions(rowMap, spacing, midX)
      }
      if (!store.getState().cadnanoActive) getUnfoldView?.()?.reapplyIfActive()
    } else if (
      newState.toolFilters       !== prevState.toolFilters ||
      newState.showHelixLabels   !== prevState.showHelixLabels
    ) {
      _updateLabelVisibility()
    }
  })

  // ── Event handlers ────────────────────────────────────────────────────────

  function _isBlocked() {
    return isDisabled?.() || !store.getState().toolFilters.bluntEnds
  }

  function _onPointerMove(e) {
    if (_isBlocked()) { _setHovered(-1); return }
    _setHovered(_getHitIndex(e))
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

  function _fireLeftMenu(idx) {
    const { plane, offsetNm, helixId, sourceBp } = _ends[idx]
    const design = store.getState().currentDesign
    const hasDeformations = !!(design?.deformations?.length) || _hasEffectiveTransform(helixId, design)
    onBluntEndClick?.({ plane, offsetNm, helixId, sourceBp, hasDeformations })
  }

  function _fireRightMenu(idx, x, y) {
    const { plane, offsetNm, helixId, sourceBp } = _ends[idx]
    const design = store.getState().currentDesign
    const hasDeformations = !!(design?.deformations?.length) || _hasEffectiveTransform(helixId, design)
    onBluntEndRightClick?.({ plane, offsetNm, helixId, sourceBp, hasDeformations, clientX: x, clientY: y })
  }

  function _onPointerDown(e) {
    if (_isBlocked()) return
    const idx = _hoveredIdx
    if (idx < 0) return

    if (e.button === 0) {
      // Intercept left-click: prevent OrbitControls from starting a drag
      e.stopImmediatePropagation()
      _pendingIdx = idx
      _pendingPos = { x: e.clientX, y: e.clientY }
    } else if (e.button === 2) {
      // Track right-click for context menu
      _pendingRightIdx = idx
      _pendingRightPos = { x: e.clientX, y: e.clientY }
    }
  }

  function _onPointerUp(e) {
    if (e.button !== 0) return
    if (_pendingIdx < 0) return
    const idx = _pendingIdx
    _pendingIdx = -1
    const moved = _pendingPos
      ? Math.hypot(e.clientX - _pendingPos.x, e.clientY - _pendingPos.y)
      : 999
    _pendingPos = null
    if (moved > 4) return
    e.stopImmediatePropagation()
    _fireLeftMenu(idx)
  }

  function _onContextMenu(e) {
    if (e.ctrlKey) return
    if (_isBlocked()) return
    if (_pendingRightIdx < 0) return
    const idx = _pendingRightIdx
    _pendingRightIdx = -1
    const moved = _pendingRightPos
      ? Math.hypot(e.clientX - _pendingRightPos.x, e.clientY - _pendingRightPos.y)
      : 999
    _pendingRightPos = null
    if (moved > 4) return
    e.preventDefault()
    e.stopImmediatePropagation()
    _fireRightMenu(idx, e.clientX, e.clientY)
  }

  // Hover uses normal bubble phase (needs to fire even when nothing intercepts)
  canvas.addEventListener('pointermove',   _onPointerMove)
  // Down/up must be capture phase so we can preventDefault orbit before it registers
  canvas.addEventListener('pointerdown',   _onPointerDown, { capture: true })
  canvas.addEventListener('pointerup',     _onPointerUp,   { capture: true })
  canvas.addEventListener('contextmenu',   _onContextMenu, { capture: true })

  // Named closure so it can be called both from the public API and from the
  // store subscriber (where the returned object methods are not yet in scope).
  function _applyCadnanoPositions(rowMap, spacing, midX) {
    _lastCadnanoParams = { rowMap, spacing, midX }
    for (const end of _ends) {
      if (end.isInterior) continue
      const row = rowMap.get(end.helixId)
      if (row == null) continue
      const y    = -row * spacing
      const z    = (end.bpStart + end.physicsBp) * BDNA_RISE_PER_BP
      const sign = end.isStart ? -1 : +1
      end.ringMesh.position.set(midX, y, z)
      end.hitMesh.position.set(midX, y, z)
      if (end.labelSprite) {
        end.labelSprite.position.set(midX, y, z + sign * 1.0)
      }
    }
  }

  return {
    clear() { _rebuild(null, null) },

    /**
     * Show or hide ALL blunt-end geometry (rings, hit disks, number-sprite labels).
     * Persists through _rebuild() because _group.visible is never reset on rebuild.
     * Called by assembly mode to suppress design-level overlays from the scene.
     */
    setVisible(bool) { _group.visible = bool },

    /**
     * Translate all rings, hit disks, and label sprites by their per-helix
     * unfold offset at lerp factor t.  Called every animation frame by unfold_view.js.
     *
     * @param {Map<string, THREE.Vector3>} helixOffsets  helix_id → offset vector
     * @param {number} t  lerp factor in [0, 1]
     */
    /**
     * Lerp rings and label sprites from straight to deformed axis endpoint positions.
     * @param {Map<string, {start:THREE.Vector3, end:THREE.Vector3}>} straightAxesMap
     * @param {number} t  lerp factor 0=straight, 1=deformed
     */
    applyDeformLerp(straightAxesMap, t) {
      for (const end of _ends) {
        const sa = straightAxesMap?.get(end.helixId)
        if (!sa) continue
        const sp = end.isInterior
          ? sa.start.clone().lerp(sa.end, end.interiorT)
          : (end.isStart ? sa.start : sa.end)
        const lerped = {
          x: sp.x + (end.basePos.x - sp.x) * t,
          y: sp.y + (end.basePos.y - sp.y) * t,
          z: sp.z + (end.basePos.z - sp.z) * t,
        }
        end.ringMesh.position.set(lerped.x, lerped.y, lerped.z)
        end.hitMesh.position.set(lerped.x, lerped.y, lerped.z)
        if (end.isInterior) continue   // no label or orientation slerp for interior ends
        // Label keeps same world-space offset from the ring
        const lOff = {
          x: end.baseLabelPos.x - end.basePos.x,
          y: end.baseLabelPos.y - end.basePos.y,
          z: end.baseLabelPos.z - end.basePos.z,
        }
        // Slerp ring/hit orientation: straight axis direction (t=0) → deformed (t=1).
        _bluntAxisDir.copy(sa.end).sub(sa.start).normalize()
        _bluntStraightQ.setFromUnitVectors(_Z_HAT, _bluntAxisDir)
        _bluntLerpedQ.copy(_bluntStraightQ).slerp(end.baseQuat, t)
        end.ringMesh.quaternion.copy(_bluntLerpedQ)
        end.hitMesh.quaternion.copy(_bluntLerpedQ)
        // Lerp the label offset direction between straight outward (t=0) and deformed (t=1).
        // Straight outward: isStart → negate axis (points away from helix), isEnd → axis as-is.
        const lOffLen = Math.sqrt(lOff.x * lOff.x + lOff.y * lOff.y + lOff.z * lOff.z)
        const sign    = end.isStart ? -1 : 1
        _bluntLabelOff.set(
          (sign * _bluntAxisDir.x + (lOff.x / lOffLen - sign * _bluntAxisDir.x) * t) * lOffLen,
          (sign * _bluntAxisDir.y + (lOff.y / lOffLen - sign * _bluntAxisDir.y) * t) * lOffLen,
          (sign * _bluntAxisDir.z + (lOff.z / lOffLen - sign * _bluntAxisDir.z) * t) * lOffLen,
        )
        end.labelSprite.position.set(
          lerped.x + _bluntLabelOff.x,
          lerped.y + _bluntLabelOff.y,
          lerped.z + _bluntLabelOff.z,
        )
      }
    },

    // Use global bp_index (bpStart + physicsBp) to match cadnano_view bead placement
    // which positions beads at bp_index * RISE.  sourceBp (0 or length_bp) is kept
    // for startToolAtBp which already adjusts for its local-index convention.
    applyCadnanoPositions(rowMap, spacing, midX) {
      _applyCadnanoPositions(rowMap, spacing, midX)
    },

    applyUnfoldOffsets(helixOffsets, t, straightAxesMap) {
      for (const end of _ends) {
        const off = helixOffsets.get(end.helixId)
        const ox  = off ? off.x * t : 0
        const oy  = off ? off.y * t : 0
        const oz  = off ? off.z * t : 0
        // Use straight axis endpoint as base when available.
        let bx, by, bz
        if (straightAxesMap) {
          const sa = straightAxesMap.get(end.helixId)
          const sp = sa
            ? (end.isInterior
                ? sa.start.clone().lerp(sa.end, end.interiorT)
                : (end.isStart ? sa.start : sa.end))
            : null
          bx = sp ? sp.x : end.basePos.x
          by = sp ? sp.y : end.basePos.y
          bz = sp ? sp.z : end.basePos.z
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

    /**
     * Move rings and labels to follow XPBD backbone positions.
     * Approximates the helix terminus position as the average of the FORWARD and
     * REVERSE backbone beads at the terminus bp_index.
     *
     * @param {Array<{helix_id,bp_index,direction,backbone_position}>} updates
     */
    applyPhysicsPositions(updates) {
      const posMap = new Map()
      for (const u of updates) {
        posMap.set(`${u.helix_id}:${u.bp_index}:${u.direction}`, u.backbone_position)
      }
      for (const end of _ends) {
        if (end.isInterior) continue   // no XPBD particle at interior gap boundary
        const globalBp = end.bpStart + end.physicsBp  // local → global bp_index
        const f = posMap.get(`${end.helixId}:${globalBp}:FORWARD`)
        const r = posMap.get(`${end.helixId}:${globalBp}:REVERSE`)
        let px, py, pz
        if (f && r) {
          px = (f[0] + r[0]) * 0.5; py = (f[1] + r[1]) * 0.5; pz = (f[2] + r[2]) * 0.5
        } else if (f || r) {
          const p = f ?? r; px = p[0]; py = p[1]; pz = p[2]
        } else {
          continue  // no physics particle at this terminus — leave unchanged
        }
        // Preserve the label's world-space offset from the ring.
        const lox = end.baseLabelPos.x - end.basePos.x
        const loy = end.baseLabelPos.y - end.basePos.y
        const loz = end.baseLabelPos.z - end.basePos.z
        end.ringMesh.position.set(px, py, pz)
        end.hitMesh.position.set(px, py, pz)
        end.labelSprite.position.set(px + lox, py + loy, pz + loz)
      }
    },

    /**
     * Snap all rings and labels back to their geometric positions (basePos from
     * last rebuild).  Called when physics is toggled off.
     */
    revertPhysics() {
      for (const end of _ends) {
        end.ringMesh.position.copy(end.basePos)
        end.hitMesh.position.copy(end.basePos)
        end.labelSprite?.position.copy(end.baseLabelPos)
        end.ringMesh.quaternion.copy(end.baseQuat)
        end.hitMesh.quaternion.copy(end.baseQuat)
      }
    },

    /**
     * Snapshot current ring/label positions for the given cluster helices.
     * Must be called once before applyClusterTransform begins (mirrors helix_renderer API).
     */
    captureClusterBase(helixIds, append = false) {
      const helixSet = new Set(helixIds)
      if (!append) _cbEnds.clear()
      for (const end of _ends) {
        if (!helixSet.has(end.helixId)) continue
        _cbEnds.set(end, {
          pos:      end.ringMesh.position.clone(),
          labelPos: end.labelSprite ? end.labelSprite.position.clone() : null,
          quat:     end.ringMesh.quaternion.clone(),
        })
      }
    },

    /**
     * Apply an incremental cluster transform to rings and labels.
     * Mirrors the helix_renderer signature so callers can drive both in parallel.
     */
    applyClusterTransform(helixIds, centerVec, dummyPosVec, incrRotQuat, bpRange = null) {
      const helixSet = new Set(helixIds)
      for (const end of _ends) {
        if (!helixSet.has(end.helixId)) continue
        if (bpRange !== null) {
          const globalBp = (end.bpStart ?? 0) + (end.physicsBp ?? 0)
          if (globalBp < bpRange[0] || globalBp > bpRange[1]) continue
        }
        const snap = _cbEnds.get(end)
        if (!snap) continue
        // Transform ring and hit position
        _bluntClusterV.copy(snap.pos).sub(centerVec).applyQuaternion(incrRotQuat)
        const nx = _bluntClusterV.x + dummyPosVec.x
        const ny = _bluntClusterV.y + dummyPosVec.y
        const nz = _bluntClusterV.z + dummyPosVec.z
        end.ringMesh.position.set(nx, ny, nz)
        end.hitMesh.position.set(nx, ny, nz)
        // Rotate ring/hit orientation
        _bluntClusterQ.multiplyQuaternions(incrRotQuat, snap.quat)
        end.ringMesh.quaternion.copy(_bluntClusterQ)
        end.hitMesh.quaternion.copy(_bluntClusterQ)
        // Transform label position
        if (snap.labelPos && end.labelSprite) {
          _bluntClusterV.copy(snap.labelPos).sub(centerVec).applyQuaternion(incrRotQuat)
          end.labelSprite.position.set(
            _bluntClusterV.x + dummyPosVec.x,
            _bluntClusterV.y + dummyPosVec.y,
            _bluntClusterV.z + dummyPosVec.z,
          )
        }
      }
    },

    /**
     * Returns a structured snapshot of every blunt-end entry for diagnostic use.
     * Each row has: helixId, helixLabel, isStart, isInterior, globalBp,
     *               ringPos3d ([x,y,z]), labelPos3d ([x,y,z] | null).
     */
    getEndTable() {
      return _ends.map(e => ({
        helixId:    e.helixId,
        helixLabel: e.helixLabel,
        isStart:    !!e.isStart,
        isInterior: !!e.isInterior,
        globalBp:   (e.bpStart ?? 0) + (e.physicsBp ?? 0),
        ringPos3d:  e.ringMesh.position.toArray(),
        labelPos3d: e.labelSprite?.position.toArray() ?? null,
      }))
    },

    /** Returns {mesh, helixId, isStart, label} for each end — used by debug overlay. */
    getHitMeshes() {
      return _ends.map(e => ({
        mesh:    e.hitMesh,
        helixId: e.helixId,
        isStart: e.isStart,
        label:   e.labelSprite?.userData?.text ?? null,
      }))
    },

    dispose() {
      canvas.removeEventListener('pointermove',   _onPointerMove)
      canvas.removeEventListener('pointerdown',   _onPointerDown, { capture: true })
      canvas.removeEventListener('pointerup',     _onPointerUp,   { capture: true })
      canvas.removeEventListener('contextmenu',   _onContextMenu, { capture: true })
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

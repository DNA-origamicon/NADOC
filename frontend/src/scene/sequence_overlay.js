/**
 * Sequence overlay — renders base-letter sprites at nucleotide backbone positions,
 * offset radially outward from the helix axis so they clear the backbone spheres.
 *
 * One InstancedMesh per letter type (A, T, G, C).  Nucleotides with no sequence
 * (N) and nucleotides with no strand_id are NOT rendered — they produce clutter
 * without conveying useful information.
 *
 * Orientation: labels face the YZ plane (plane normal = +X).
 *
 * Usage:
 *   const overlay = initSequenceOverlay(scene, store)
 *   overlay.setVisible(true/false)
 *   overlay.orientToCamera(camera)   // no-op until per-instance billboarding
 *   overlay.dispose()
 */

import * as THREE from 'three'

// ── Constants ─────────────────────────────────────────────────────────────────

const _SPRITE_SIZE   = 0.55   // nm — label quad width/height
const _RADIAL_OFFSET = 0.28   // nm — extra distance from backbone toward outside of helix

// Labels face the YZ plane (plane normal = +X).
// PlaneGeometry default normal = +Z; rotate 90° around Y → normal = +X.
const FACE_YZ_QUAT = new THREE.Quaternion().setFromAxisAngle(
  new THREE.Vector3(0, 1, 0),
  Math.PI / 2,
)

// Only render nucleotides with known sequence bases (not N / unassigned)
const LETTER_DEFS = [
  { letter: 'A', color: '#44dd88' },
  { letter: 'T', color: '#ff5555' },
  { letter: 'G', color: '#ffcc00' },
  { letter: 'C', color: '#55aaff' },
]

// ── Canvas texture builder ─────────────────────────────────────────────────────

function _makeLetterTexture(letter, color) {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width  = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, size, size)
  ctx.font         = `bold ${Math.round(size * 0.78)}px monospace`
  ctx.textAlign    = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle    = color
  ctx.fillText(letter, size / 2, size / 2)
  return new THREE.CanvasTexture(canvas)
}

const GEO_PLANE = new THREE.PlaneGeometry(_SPRITE_SIZE, _SPRITE_SIZE)

// ── Radial direction helper ───────────────────────────────────────────────────

/**
 * Compute the unit vector pointing radially outward from the helix axis through
 * the given backbone position.
 *
 * @param {THREE.Vector3} backbone  - backbone bead world position
 * @param {THREE.Vector3} axisStart - world position of helix axis start point
 * @param {THREE.Vector3} axisTangent - unit vector along helix axis
 * @returns {THREE.Vector3} unit radial vector (outward from axis)
 */
function _radialDir(backbone, axisStart, axisTangent) {
  // Project backbone onto the axis line, then subtract to get the perpendicular.
  const t   = backbone.clone().sub(axisStart).dot(axisTangent)
  const axisPoint = axisStart.clone().addScaledVector(axisTangent, t)
  const radial = backbone.clone().sub(axisPoint)
  const len = radial.length()
  if (len < 1e-9) {
    // Degenerate — backbone ON the axis (shouldn't happen); fall back to +X
    return new THREE.Vector3(1, 0, 0)
  }
  return radial.divideScalar(len)
}

// ── Overlay initialiser ───────────────────────────────────────────────────────

export function initSequenceOverlay(scene, storeRef) {
  let _letterMeshes = null
  let _visible      = false
  let _group        = null
  let _debugPanel   = null
  let _lastStats    = null
  let _instanceData = null   // per-instance unfold data

  // ── Debug panel ─────────────────────────────────────────────────────────────

  function _ensureDebugPanel() {
    if (_debugPanel) return
    _debugPanel = document.createElement('div')
    _debugPanel.id = 'seq-debug-panel'
    _debugPanel.style.cssText = [
      'position:fixed',
      'bottom:120px',
      'left:12px',
      'background:rgba(10,14,20,0.92)',
      'color:#c9d1d9',
      'font:11px "Courier New",monospace',
      'padding:8px 12px',
      'border-radius:4px',
      'border:1px solid #30363d',
      'z-index:50',
      'display:none',
      'white-space:pre',
      'pointer-events:none',
      'line-height:1.5',
    ].join(';')
    document.body.appendChild(_debugPanel)
  }

  function _updateDebugPanel(show) {
    _ensureDebugPanel()
    if (!show || !_lastStats) { _debugPanel.style.display = 'none'; return }
    const s = _lastStats
    const rows = [
      `── Sequence overlay debug ──`,
      `geometry nucleotides : ${s.totalNucs}`,
      `  with strand_id     : ${s.nucsWithStrand}`,
      `  without strand_id  : ${s.nucsWithoutStrand}  (not rendered)`,
      `unique strand IDs    : ${s.uniqueStrands}`,
      `scaffold strand ID   : ${s.scaffoldId ?? '(none)'}`,
      `scaffold nucs        : ${s.scaffoldNucs}`,
      `helix axes loaded    : ${s.helixAxesCount}`,
      `letter counts        : A=${s.counts.A} T=${s.counts.T} G=${s.counts.G} C=${s.counts.C}`,
      `instances created    : ${s.instancesCreated}`,
      `sample positions (first 3 scaffold nucs):`,
      ...s.samplePositions.map((p, i) =>
        `  [${i}] ${p.helix_id} bp${p.bp_index} ${p.direction}\n       bb=[${p.backbone_position.map(v => v.toFixed(3)).join(', ')}]`
      ),
    ]
    _debugPanel.textContent = rows.join('\n')
    _debugPanel.style.display = 'block'
  }

  // ── Dispose ─────────────────────────────────────────────────────────────────

  function _disposeGroup() {
    if (!_group) return
    scene.remove(_group)
    _group.traverse(obj => {
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) {
        if (obj.material.map) obj.material.map.dispose()
        obj.material.dispose()
      }
    })
    _group = null
    _letterMeshes = null
    _instanceData = null
  }

  function dispose() {
    _disposeGroup()
    if (_debugPanel) { _debugPanel.remove(); _debugPanel = null }
  }

  // ── rebuild ─────────────────────────────────────────────────────────────────

  function rebuild(geometry, design, helixAxes) {
    _disposeGroup()
    _lastStats = null

    if (!geometry || !design || geometry.length === 0) return

    // ── Strand sequence map ──────────────────────────────────────────────────
    const seqMap = new Map()   // strand_id → sequence string
    let scaffoldId = null
    for (const strand of (design.strands ?? [])) {
      if (strand.sequence) seqMap.set(strand.id, strand.sequence)
      if (strand.strand_type === 'scaffold') scaffoldId = strand.id
    }

    // ── Helix axis lookup for radial direction ───────────────────────────────
    // helixAxes: { helix_id: { start: [x,y,z], end: [x,y,z] } }
    const axisCache = new Map()   // helix_id → { start: THREE.Vector3, tangent: THREE.Vector3 }
    if (helixAxes) {
      for (const [hid, ax] of Object.entries(helixAxes)) {
        const start   = new THREE.Vector3(...ax.start)
        const end     = new THREE.Vector3(...ax.end)
        const tangent = end.clone().sub(start).normalize()
        axisCache.set(hid, { start, tangent })
      }
    }

    // ── Sort nucleotides by strand 5′→3′ for sequence index mapping ──────────
    const byStrand = new Map()
    for (const nuc of geometry) {
      if (!nuc.strand_id) continue
      if (!byStrand.has(nuc.strand_id)) byStrand.set(nuc.strand_id, [])
      byStrand.get(nuc.strand_id).push(nuc)
    }
    for (const nucs of byStrand.values()) {
      nucs.sort((a, b) => {
        const di = (a.domain_index ?? 0) - (b.domain_index ?? 0)
        if (di !== 0) return di
        return a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index
      })
    }

    // ── Assign letter to each nuc ────────────────────────────────────────────
    const nucLetter = new Map()   // nuc → 'A'|'T'|'G'|'C' (no N — those are skipped)
    for (const [strandId, nucs] of byStrand) {
      const seq = seqMap.get(strandId)
      if (!seq) continue   // no sequence → no labels for this strand
      for (let i = 0; i < nucs.length; i++) {
        const ch = seq[i]?.toUpperCase()
        if (ch && 'ATGC'.includes(ch)) nucLetter.set(nucs[i], ch)
      }
    }

    // ── Overhang sequences — read directly from design.overhangs ─────────────
    // This works even when assign_staple_sequences hasn't been called yet,
    // because OverhangSpec.sequence is set as soon as the user assigns one.
    // Nucs already assigned via strand.sequence are not overwritten.
    const overhangSeqMap = new Map()   // overhang_id → sequence string
    for (const ovhg of (design.overhangs ?? [])) {
      if (ovhg.sequence) overhangSeqMap.set(ovhg.id, ovhg.sequence)
    }
    if (overhangSeqMap.size > 0) {
      // Group geometry nucs by overhang_id
      const byOverhang = new Map()   // overhang_id → [nuc]
      for (const nuc of geometry) {
        if (!nuc.overhang_id) continue
        if (!byOverhang.has(nuc.overhang_id)) byOverhang.set(nuc.overhang_id, [])
        byOverhang.get(nuc.overhang_id).push(nuc)
      }
      // Sort each group in 5′→3′ traversal order and map to sequence chars
      for (const [ovhgId, nucs] of byOverhang) {
        const seq = overhangSeqMap.get(ovhgId)
        if (!seq) continue
        nucs.sort((a, b) =>
          a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index,
        )
        for (let i = 0; i < nucs.length; i++) {
          if (nucLetter.has(nucs[i])) continue   // strand.sequence already covered this
          const ch = seq[i]?.toUpperCase()
          if (ch && 'ATGC'.includes(ch)) nucLetter.set(nucs[i], ch)
        }
      }
    }

    // ── Count instances per letter ───────────────────────────────────────────
    const letterCounts = { A: 0, T: 0, G: 0, C: 0 }
    for (const letter of nucLetter.values()) {
      letterCounts[letter] = (letterCounts[letter] ?? 0) + 1
    }

    // ── Debug stats ──────────────────────────────────────────────────────────
    const scaffoldNucs = byStrand.get(scaffoldId)?.length ?? 0
    const samplePositions = (byStrand.get(scaffoldId) ?? [])
      .slice(0, 3)
      .map(n => ({
        helix_id:         n.helix_id,
        bp_index:         n.bp_index,
        direction:        n.direction,
        backbone_position: n.backbone_position,
      }))

    // ── Create InstancedMeshes ───────────────────────────────────────────────
    _group = new THREE.Group()
    scene.add(_group)
    _group.visible = _visible

    _letterMeshes = []
    let instancesCreated = 0
    for (const def of LETTER_DEFS) {
      const count = letterCounts[def.letter] ?? 0
      if (count === 0) { _letterMeshes.push(null); continue }
      const mat  = new THREE.MeshBasicMaterial({
        map: _makeLetterTexture(def.letter, def.color), transparent: true,
        depthWrite: false, side: THREE.DoubleSide,
      })
      const mesh = new THREE.InstancedMesh(GEO_PLANE, mat, count)
      mesh.name  = `seqLabel_${def.letter}`
      _group.add(mesh)
      _letterMeshes.push({ mesh, letter: def.letter, instanceIdx: 0 })
      instancesCreated += count
    }

    // ── Fill instance matrices ───────────────────────────────────────────────
    const _tMatrix  = new THREE.Matrix4()
    const _tPos     = new THREE.Vector3()
    const _tScale   = new THREE.Vector3(1, 1, 1)
    const _backbone = new THREE.Vector3()

    _instanceData = []

    for (const [nuc, letter] of nucLetter) {
      const entry = _letterMeshes.find(e => e?.letter === letter)
      if (!entry || entry.instanceIdx >= entry.mesh.count) continue

      _backbone.set(...nuc.backbone_position)

      // Offset radially outward from helix axis
      let radialVec = null
      const axDef = axisCache.get(nuc.helix_id)
      if (axDef) {
        radialVec = _radialDir(_backbone, axDef.start, axDef.tangent)
        _tPos.copy(_backbone).addScaledVector(radialVec, _RADIAL_OFFSET)
      } else {
        // No axis data — fall back to backbone position
        _tPos.copy(_backbone)
      }

      _tMatrix.compose(_tPos, FACE_YZ_QUAT, _tScale)
      entry.mesh.setMatrixAt(entry.instanceIdx, _tMatrix)

      _instanceData.push({
        letter,
        idx:       entry.instanceIdx,
        helix_id:  nuc.helix_id,
        bp_index:  nuc.bp_index,
        direction: nuc.direction,
        radial:    radialVec ? radialVec.clone() : null,
      })

      entry.instanceIdx++
    }

    for (const entry of _letterMeshes) {
      if (entry) entry.mesh.instanceMatrix.needsUpdate = true
    }

    // ── Store stats ──────────────────────────────────────────────────────────
    _lastStats = {
      totalNucs:         geometry.length,
      nucsWithStrand:    geometry.filter(n => !!n.strand_id).length,
      nucsWithoutStrand: geometry.filter(n => !n.strand_id).length,
      uniqueStrands:     byStrand.size,
      scaffoldId,
      scaffoldNucs,
      helixAxesCount:    axisCache.size,
      counts:            { ...letterCounts },
      instancesCreated,
      samplePositions,
    }

    const state = storeRef.getState()
    _updateDebugPanel(state.showSequences && state.debugOverlayActive)
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /** No-op until per-instance billboarding is implemented. */
  // eslint-disable-next-line no-unused-vars
  function orientToCamera(_camera) {}

  function setVisible(visible) {
    _visible = visible
    if (_group) _group.visible = visible
  }

  /**
   * Apply 2D unfold offsets so labels follow backbone positions during the
   * unfold animation.  Called by unfold_view.js each animation frame.
   *
   * @param {Map<string, THREE.Vector3>} helixOffsets  helix_id → translation
   * @param {number}                     t             lerp factor [0, 1]
   * @param {Map<string, THREE.Vector3>} straightPosMap  "hid:bp:dir" → straight backbone
   */
  function applyUnfoldOffsets(helixOffsets, t, straightPosMap) {
    if (!_letterMeshes || !_instanceData || !straightPosMap) return

    // Build a letter → {mesh, instanceMatrix} lookup.
    const meshMap = new Map()
    for (const entry of _letterMeshes) {
      if (entry) meshMap.set(entry.letter, entry.mesh)
    }

    const tMatrix = new THREE.Matrix4()
    const tPos    = new THREE.Vector3()
    const tScale  = new THREE.Vector3(1, 1, 1)

    for (const inst of _instanceData) {
      const straightBB = straightPosMap.get(
        `${inst.helix_id}:${inst.bp_index}:${inst.direction}`,
      )
      if (!straightBB) continue

      tPos.copy(straightBB)

      const offset = helixOffsets.get(inst.helix_id)
      if (offset) tPos.addScaledVector(offset, t)

      if (inst.radial) tPos.addScaledVector(inst.radial, _RADIAL_OFFSET)

      tMatrix.compose(tPos, FACE_YZ_QUAT, tScale)

      const mesh = meshMap.get(inst.letter)
      if (mesh) mesh.setMatrixAt(inst.idx, tMatrix)
    }

    for (const mesh of meshMap.values()) {
      mesh.instanceMatrix.needsUpdate = true
    }
  }

  // ── Store subscription ──────────────────────────────────────────────────────

  storeRef.subscribe((newState, prevState) => {
    const geomChanged  = newState.currentGeometry  !== prevState.currentGeometry
    const axesChanged  = newState.currentHelixAxes !== prevState.currentHelixAxes
    const designChanged= newState.currentDesign    !== prevState.currentDesign
    if (geomChanged || axesChanged || designChanged) {
      rebuild(newState.currentGeometry, newState.currentDesign, newState.currentHelixAxes)
    }

    if (newState.showSequences !== prevState.showSequences) {
      setVisible(newState.showSequences)
    }

    const showDebug = newState.showSequences && newState.debugOverlayActive
    const wasDebug  = prevState.showSequences && prevState.debugOverlayActive
    if (showDebug !== wasDebug) {
      _ensureDebugPanel()
      _updateDebugPanel(showDebug)
    }
  })

  return { setVisible, orientToCamera, applyUnfoldOffsets, dispose }
}

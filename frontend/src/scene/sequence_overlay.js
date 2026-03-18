/**
 * Sequence overlay — renders base-letter sprites at nucleotide backbone positions.
 *
 * Uses one InstancedMesh per letter type (A, T, G, C, N/unassigned) so the
 * overlay renders in 5 draw calls regardless of design size.  Each letter is
 * drawn on a small canvas and uploaded as a shared CanvasTexture per letter.
 *
 * Colours:
 *   A — green  (#44dd88)
 *   T — red    (#ff5555)
 *   G — yellow (#ffcc00)
 *   C — blue   (#55aaff)
 *   N — grey   (#888888)  (unassigned or no sequence)
 *
 * Orientation: labels face the YZ plane (plane normal = +X).
 * To billboard toward the camera, replace FACE_YZ_QUAT with per-instance logic.
 *
 * Usage:
 *   const overlay = initSequenceOverlay(scene, store)
 *   overlay.setVisible(true/false)
 *   overlay.orientToCamera(camera)   // currently a no-op; called from tick loop
 *   overlay.dispose()
 */

import * as THREE from 'three'

// ── Letter palette ─────────────────────────────────────────────────────────────

const LETTER_DEFS = [
  { letter: 'A', color: '#44dd88' },
  { letter: 'T', color: '#ff5555' },
  { letter: 'G', color: '#ffcc00' },
  { letter: 'C', color: '#55aaff' },
  { letter: 'N', color: '#888888' },
]

// ── Sprite size ────────────────────────────────────────────────────────────────

const _SPRITE_SIZE = 0.55   // nm — label quad width/height

// ── Fixed orientation: plane faces +X (plane is in the YZ plane) ──────────────
// PlaneGeometry default normal = +Z. Rotate 90° around Y to get normal = +X.

const FACE_YZ_QUAT = new THREE.Quaternion().setFromAxisAngle(
  new THREE.Vector3(0, 1, 0),
  Math.PI / 2,
)

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

// ── Geometry (shared across all letter materials) ─────────────────────────────

const GEO_PLANE = new THREE.PlaneGeometry(_SPRITE_SIZE, _SPRITE_SIZE)

// ── Overlay initialiser ───────────────────────────────────────────────────────

export function initSequenceOverlay(scene, storeRef) {
  let _letterMeshes = null
  let _visible      = false
  let _group        = null
  let _debugPanel   = null
  let _lastStats    = null   // populated after each rebuild

  // ── Debug panel (DOM) ───────────────────────────────────────────────────────

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
    if (!show || !_lastStats) {
      _debugPanel.style.display = 'none'
      return
    }
    const s = _lastStats
    const rows = [
      `── Sequence overlay debug ──`,
      `geometry nucleotides : ${s.totalNucs}`,
      `  with strand_id     : ${s.nucsWithStrand}`,
      `  without strand_id  : ${s.nucsWithoutStrand}`,
      `unique strand IDs    : ${s.uniqueStrands}`,
      `scaffold strand ID   : ${s.scaffoldId ?? '(none)'}`,
      `scaffold nucs        : ${s.scaffoldNucs}`,
      `letter counts        : A=${s.counts.A} T=${s.counts.T} G=${s.counts.G} C=${s.counts.C} N=${s.counts.N}`,
      `instances created    : ${s.instancesCreated}`,
      `sample positions (first 3 scaffold nucs):`,
      ...s.samplePositions.map((p, i) =>
        `  [${i}] ${p.helix_id} bp${p.bp_index} ${p.direction} → [${p.backbone_position.map(v => v.toFixed(3)).join(', ')}]`
      ),
    ]
    _debugPanel.textContent = rows.join('\n')
    _debugPanel.style.display = 'block'
  }

  // ── Material / mesh builders ────────────────────────────────────────────────

  function _buildMaterial(letterDef) {
    const tex = _makeLetterTexture(letterDef.letter, letterDef.color)
    return new THREE.MeshBasicMaterial({
      map:         tex,
      transparent: true,
      depthWrite:  false,
      side:        THREE.DoubleSide,
    })
  }

  function dispose() {
    if (_group) {
      scene.remove(_group)
      _group.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose()
        if (obj.material) {
          if (obj.material.map) obj.material.map.dispose()
          obj.material.dispose()
        }
      })
      _group = null
    }
    _letterMeshes = null
    if (_debugPanel) { _debugPanel.remove(); _debugPanel = null }
  }

  // ── rebuild ─────────────────────────────────────────────────────────────────

  function rebuild(geometry, design) {
    // Dispose old meshes but keep debug panel
    if (_group) {
      scene.remove(_group)
      _group.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose()
        if (obj.material) {
          if (obj.material.map) obj.material.map.dispose()
          obj.material.dispose()
        }
      })
      _group = null
    }
    _letterMeshes = null
    _lastStats    = null

    if (!geometry || !design || geometry.length === 0) return

    // ── Build strand → sequence map ─────────────────────────────────────────
    const seqMap = new Map()   // strand_id → sequence string
    let scaffoldId = null
    for (const strand of (design.strands ?? [])) {
      if (strand.sequence) seqMap.set(strand.id, strand.sequence)
      if (strand.strand_type === 'scaffold') scaffoldId = strand.id
    }

    // ── Group geometry by strand, sort 5′→3′ ────────────────────────────────
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
    const nucLetter = new Map()
    for (const [strandId, nucs] of byStrand) {
      const seq = seqMap.get(strandId)
      for (let i = 0; i < nucs.length; i++) {
        const raw = seq ? (seq[i] ?? 'N') : 'N'
        nucLetter.set(nucs[i], 'ATGCN'.includes(raw) ? raw : 'N')
      }
    }

    // ── Count instances per letter ───────────────────────────────────────────
    const letterCounts = { A: 0, T: 0, G: 0, C: 0, N: 0 }
    for (const letter of nucLetter.values()) {
      letterCounts[letter] = (letterCounts[letter] ?? 0) + 1
    }
    // Nucleotides with no strand_id → N
    const unassignedCount = geometry.filter(n => !n.strand_id).length
    letterCounts['N'] += unassignedCount

    // ── Build stats for debug panel ──────────────────────────────────────────
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
      const mat  = _buildMaterial(def)
      const mesh = new THREE.InstancedMesh(GEO_PLANE, mat, count)
      mesh.name  = `seqLabel_${def.letter}`
      _group.add(mesh)
      _letterMeshes.push({ mesh, letter: def.letter, instanceIdx: 0 })
      instancesCreated += count
    }

    // ── Fill instance matrices ───────────────────────────────────────────────
    const _tMatrix = new THREE.Matrix4()
    const _tPos    = new THREE.Vector3()
    const _tScale  = new THREE.Vector3(1, 1, 1)

    for (const nuc of geometry) {
      const letter = nuc.strand_id ? (nucLetter.get(nuc) ?? 'N') : 'N'
      const entry  = _letterMeshes.find(e => e?.letter === letter)
      if (!entry) continue
      if (entry.instanceIdx >= entry.mesh.count) continue  // guard overflow

      _tPos.set(...nuc.backbone_position)
      _tMatrix.compose(_tPos, FACE_YZ_QUAT, _tScale)
      entry.mesh.setMatrixAt(entry.instanceIdx, _tMatrix)
      entry.instanceIdx++
    }

    for (const entry of _letterMeshes) {
      if (entry) entry.mesh.instanceMatrix.needsUpdate = true
    }

    // ── Store stats ──────────────────────────────────────────────────────────
    _lastStats = {
      totalNucs:        geometry.length,
      nucsWithStrand:   geometry.filter(n => !!n.strand_id).length,
      nucsWithoutStrand: unassignedCount,
      uniqueStrands:    byStrand.size,
      scaffoldId,
      scaffoldNucs,
      counts:           { ...letterCounts },
      instancesCreated,
      samplePositions,
    }

    // Refresh debug panel if it was already showing
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

  // ── Store subscription ──────────────────────────────────────────────────────

  storeRef.subscribe((newState, prevState) => {
    const geomChanged   = newState.currentGeometry !== prevState.currentGeometry
    const designChanged = newState.currentDesign   !== prevState.currentDesign
    if (geomChanged || designChanged) {
      rebuild(newState.currentGeometry, newState.currentDesign)
    }

    if (newState.showSequences !== prevState.showSequences) {
      setVisible(newState.showSequences)
    }

    // Show/hide debug panel when either toggle changes
    const showDebug = newState.showSequences && newState.debugOverlayActive
    const wasDebug  = prevState.showSequences && prevState.debugOverlayActive
    if (showDebug !== wasDebug) {
      _ensureDebugPanel()
      _updateDebugPanel(showDebug)
    }
  })

  return { setVisible, orientToCamera, dispose }
}

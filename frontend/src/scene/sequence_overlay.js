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
 * Usage:
 *   const overlay = initSequenceOverlay(scene, store)
 *   overlay.rebuild(geometry, design)   // called after design/geometry changes
 *   overlay.setVisible(true/false)
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

// ── Canvas texture builder ─────────────────────────────────────────────────────

function _makeLetterTexture(letter, color) {
  const size = 64
  const canvas = document.createElement('canvas')
  canvas.width  = size
  canvas.height = size
  const ctx = canvas.getContext('2d')

  // Transparent background
  ctx.clearRect(0, 0, size, size)

  // Letter
  ctx.font        = `bold ${Math.round(size * 0.72)}px monospace`
  ctx.textAlign   = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle   = color
  ctx.fillText(letter, size / 2, size / 2)

  return new THREE.CanvasTexture(canvas)
}

// ── Sprite plane geometry (unit square, faces +Z) ─────────────────────────────
// We'll use a PlaneGeometry and a custom vertex shader that billboards it toward
// the camera — but for simplicity we use THREE.Sprite behaviour by parenting each
// instance to its own Sprite. However, with InstancedMesh we need manual billboarding.
//
// Simpler approach: use THREE.Sprite objects per letter type shared via
// InstancedMesh (PlaneGeometry + MeshBasicMaterial with map).
// We accept that sprites won't auto-billboard with InstancedMesh; instead we
// keep things simple: scale them small enough that camera orientation doesn't
// matter much, and add a per-frame orientToCamera call.

const _SPRITE_SIZE = 0.18   // nm — label quad width/height

const GEO_PLANE = new THREE.PlaneGeometry(_SPRITE_SIZE, _SPRITE_SIZE)

// ── Overlay initialiser ───────────────────────────────────────────────────────

export function initSequenceOverlay(scene, storeRef) {
  // Per-letter InstancedMesh storage: { mesh, count }
  let _letterMeshes = null
  let _visible = false
  let _group = null

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
  }

  /**
   * Rebuild the overlay from current geometry and design.
   * Called whenever geometry or design changes.
   */
  function rebuild(geometry, design) {
    dispose()
    if (!geometry || !design || geometry.length === 0) return

    // Build a map from (helix_id, bp_index, strand_id) → base letter
    // Sources: strand.sequence field if present, else 'N'
    const seqMap = new Map()   // strand_id → sequence string
    for (const strand of (design.strands ?? [])) {
      if (strand.sequence) seqMap.set(strand.id, strand.sequence)
    }

    // For each nucleotide, compute the 5′→3′ position within its strand
    // (domain_index and bp ordering within domain).
    // Actually: the geometry array already has backbone_position; we just need
    // to know which base letter to show.  We derive it from the domain ordering.

    // Build per-strand nucleotide order (same logic as helix_renderer byStrand sort)
    const byStrand = new Map()
    for (const nuc of geometry) {
      const key = nuc.strand_id
      if (!key) continue
      if (!byStrand.has(key)) byStrand.set(key, [])
      byStrand.get(key).push(nuc)
    }
    for (const [, nucs] of byStrand) {
      nucs.sort((a, b) => {
        const di = (a.domain_index ?? 0) - (b.domain_index ?? 0)
        if (di !== 0) return di
        return a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index
      })
    }

    // Assign letter to each nuc
    const nucLetter = new Map()   // nuc → letter char
    for (const [strandId, nucs] of byStrand) {
      const seq = seqMap.get(strandId)
      for (let i = 0; i < nucs.length; i++) {
        nucLetter.set(nucs[i], seq ? (seq[i] ?? 'N') : 'N')
      }
    }

    // Count per letter
    const letterCounts = {}
    for (const def of LETTER_DEFS) letterCounts[def.letter] = 0
    for (const [, letter] of nucLetter) letterCounts[letter] = (letterCounts[letter] ?? 0) + 1
    // Anything not A/T/G/C → N
    for (const [nuc] of nucLetter) {
      const l = nucLetter.get(nuc)
      if (!letterCounts.hasOwnProperty(l)) {
        nucLetter.set(nuc, 'N')
      }
    }

    // Re-count after normalisation
    for (const def of LETTER_DEFS) letterCounts[def.letter] = 0
    for (const [, letter] of nucLetter) {
      letterCounts[letter] = (letterCounts[letter] ?? 0) + 1
    }
    // Add unassigned nucs (no strand_id)
    const unassignedCount = geometry.filter(n => !n.strand_id).length
    letterCounts['N'] = (letterCounts['N'] ?? 0) + unassignedCount

    _group = new THREE.Group()
    scene.add(_group)
    _group.visible = _visible

    _letterMeshes = []
    const _tMatrix = new THREE.Matrix4()
    const _tPos    = new THREE.Vector3()
    const ID_QUAT  = new THREE.Quaternion()
    const _tScale  = new THREE.Vector3(1, 1, 1)

    for (const def of LETTER_DEFS) {
      const count = letterCounts[def.letter] ?? 0
      if (count === 0) {
        _letterMeshes.push(null)
        continue
      }
      const mat  = _buildMaterial(def)
      const mesh = new THREE.InstancedMesh(GEO_PLANE, mat, count)
      mesh.name = `seqLabel_${def.letter}`
      _group.add(mesh)
      _letterMeshes.push({ mesh, letter: def.letter, instanceIdx: 0 })
    }

    // Fill instance matrices
    for (const nuc of geometry) {
      const letter = nuc.strand_id ? (nucLetter.get(nuc) ?? 'N') : 'N'
      const entry  = _letterMeshes.find(e => e?.letter === letter)
      if (!entry) continue

      _tPos.set(...nuc.backbone_position)
      _tMatrix.compose(_tPos, ID_QUAT, _tScale)
      entry.mesh.setMatrixAt(entry.instanceIdx, _tMatrix)
      entry.instanceIdx++
    }

    for (const entry of _letterMeshes) {
      if (entry) entry.mesh.instanceMatrix.needsUpdate = true
    }
  }

  /**
   * No-op until per-instance billboarding is implemented.
   * Labels render with a fixed orientation (PlaneGeometry faces +Z).
   */
  // eslint-disable-next-line no-unused-vars
  function orientToCamera(_camera) {}

  function setVisible(visible) {
    _visible = visible
    if (_group) _group.visible = visible
  }

  // Re-subscribe: rebuild on geometry or design change
  storeRef.subscribe((newState, prevState) => {
    if (
      newState.currentGeometry !== prevState.currentGeometry ||
      newState.currentDesign   !== prevState.currentDesign
    ) {
      rebuild(newState.currentGeometry, newState.currentDesign)
    }
    if (newState.showSequences !== prevState.showSequences) {
      setVisible(newState.showSequences)
    }
  })

  return { rebuild, setVisible, orientToCamera, dispose }
}

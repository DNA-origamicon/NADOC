// Force-Crossover tool (3D forced ligation).
//
// The 3D counterpart of the cadnano editor's pencil-tool forced ligation. While
// active it forces the selection level to `end` (lighting the End filter button)
// and shows the standard yellow end-bead hover glow, but the selection manager is
// fully disabled (see `forceXoverActive` in main.js `isDisabled` + zeroed
// `selectableTypes`) so this tool — not the selection manager — owns the gesture:
//
//   1. Click a 5′ or 3′ strand end. It locks GREEN ("anchor").
//   2. Only the OPPOSITE-polarity ends on OTHER strands now hover-highlight
//      (3′ if you picked a 5′, and vice-versa). Hovering one previews the
//      crossover arc that would be created (yellow tube).
//   3. Click that previewed end → POST /design/forced-ligation. The two strands
//      become one (the 5′ strand's domains are appended onto the 3′ strand) and
//      the design re-syncs everywhere (3D, cadnano editor, sidebars) via the
//      shared `_syncFromDesignResponse` path. The tool resets to step 1 so chains
//      of crossovers can be made without re-toggling.
//   - Esc: in step 2 → back to step 1 (drop the anchor); in step 1 → exit tool.
//
// Lasso + multi-select are disabled for free because the selection manager is off.
// The forced ligation records a ForcedLigation (NOT a canonical Crossover) — any
// 3′↔5′ pair is allowed regardless of helix adjacency, matching cadnano.
//
// RULE (three-layer law): this is a TOPOLOGY edit, made only via the backend
// endpoint. No geometry/topology is reasoned about here — end polarity comes
// straight from the nucleotide's is_five_prime / is_three_prime flags.

import * as THREE from 'three'
import { arcControlPoint, bezierAt } from './crossover_connections.js'

const _SNAP_PX  = 80     // screen-space hover/click snap radius (matches selection_manager)
const _ARC_SEGS = 16     // preview-arc sample count

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** Strand-end polarity of a nucleotide: '3p' | '5p' | null (null if neither, or
 *  ambiguously both — a 1-nt strand whose single bead is both ends). */
export function endRole(nuc) {
  if (!nuc) return null
  const three = !!nuc.is_three_prime
  const five  = !!nuc.is_five_prime
  if (three && five) return null   // ambiguous single-bead strand — not usable
  if (three) return '3p'
  if (five)  return '5p'
  return null
}

/** True when `secondNuc` is a legal forced-ligation partner for `firstNuc`:
 *  one 3′ + one 5′ (opposite polarity), on DIFFERENT strands. */
export function isValidPair(firstNuc, secondNuc) {
  const r1 = endRole(firstNuc)
  const r2 = endRole(secondNuc)
  if (!r1 || !r2) return false
  if (r1 === r2) return false
  return firstNuc.strand_id !== secondNuc.strand_id
}

/** Map a (first, second) end pair to the backend request fields, independent of
 *  the order the user clicked them in: the 3′ end → three_prime_strand_id, the
 *  5′ end → five_prime_strand_id. Assumes the pair is already validated. */
export function ligationArgs(firstNuc, secondNuc) {
  const firstIsThree = endRole(firstNuc) === '3p'
  const three = firstIsThree ? firstNuc : secondNuc
  const five  = firstIsThree ? secondNuc : firstNuc
  return { three_prime_strand_id: three.strand_id, five_prime_strand_id: five.strand_id }
}

/** Sample points of the crossover preview arc between two end nucleotides.
 *  Uses the same quadratic-Bezier control point as the committed crossover arc
 *  so the preview matches what gets rendered. Returns THREE.Vector3[]. */
export function crossoverArcPoints(nucA, nucB, segs = _ARC_SEGS) {
  const A = new THREE.Vector3(...nucA.backbone_position)
  const B = new THREE.Vector3(...nucB.backbone_position)
  const C = arcControlPoint(A, B, nucA, nucB, new THREE.Vector3())
  const pts = []
  for (let i = 0; i <= segs; i++) pts.push(bezierAt(A, C, B, i / segs, new THREE.Vector3()))
  return pts
}

// ── Factory ──────────────────────────────────────────────────────────────────

export function initForceCrossoverTool({
  store, canvas, camera, designRenderer, selectionManager, api, getCamera,
}) {
  const _cam = () => (getCamera ? getCamera() : null) ?? camera

  let _active     = false
  let _firstEnd   = null   // { entry, nuc, strandId, role, world: THREE.Vector3 }
  let _committing = false
  let _prevLevel  = 'default'
  let _prevSelectableTypes = null
  let _prevModeText = ''
  let _consumedDown = false

  const _m4   = new THREE.Matrix4()
  const _tmp  = new THREE.Vector3()
  const _modeEl = () => document.getElementById('mode-indicator')

  function _instWorld(instMesh, id, out) {
    instMesh.getMatrixAt(id, _m4)
    return out.setFromMatrixPosition(_m4)
  }

  function _project(world) {
    const rect = canvas.getBoundingClientRect()
    const p = world.clone().project(_cam())
    return { x: (p.x * 0.5 + 0.5) * rect.width, y: (-p.y * 0.5 + 0.5) * rect.height, z: p.z }
  }

  // Nearest selectable end bead (canvas-relative sx,sy). In step 1 any end; in
  // step 2 only ends that form a valid pair with the anchor. Scaffold/staple
  // gates are ignored — both polarities of any strand are ligatable.
  function _nearestEnd(sx, sy) {
    let best = null, bestD = _SNAP_PX
    for (const e of designRenderer.getBackboneEntries()) {
      if (!e.instMesh.visible) continue
      if (!endRole(e.nuc)) continue
      if (_firstEnd && !isValidPair(_firstEnd.nuc, e.nuc)) continue
      const sp = _project(_instWorld(e.instMesh, e.id, _tmp))
      if (sp.z > 1) continue
      const d = Math.hypot(sp.x - sx, sp.y - sy)
      if (d < bestD) { bestD = d; best = e }
    }
    return best
  }

  function _setModeText() {
    const el = _modeEl()
    if (!el) return
    if (_firstEnd) {
      const want = _firstEnd.role === '3p' ? '5′' : '3′'
      el.textContent = `FORCE CROSSOVER — click a ${want} end on another strand · Esc: cancel pick`
    } else {
      el.textContent = 'FORCE CROSSOVER — click a 5′ or 3′ end · Esc: exit'
    }
  }

  function _clearFirstEnd() {
    _firstEnd = null
    designRenderer.clearGlow()
    designRenderer.clearPreviewGlow()
    designRenderer.clearPreviewArc?.()
  }

  function _setFirstEnd(entry) {
    const world = _instWorld(entry.instMesh, entry.id, new THREE.Vector3())
    _firstEnd = { entry, nuc: entry.nuc, strandId: entry.nuc.strand_id, role: endRole(entry.nuc), world }
    // Anchor = GREEN selection glow (selection-manager hover-clears only touch the
    // yellow preview layer, so the anchor stays put even while orbiting).
    designRenderer.setGlowEntries([{ pos: world.clone() }])
    designRenderer.clearPreviewGlow()
    designRenderer.clearPreviewArc?.()
    _setModeText()
  }

  // Hover (step 1: nearest end yellow; step 2: anchor green + nearest valid end
  // yellow + crossover arc preview).
  function _updateHover(clientX, clientY) {
    const rect = canvas.getBoundingClientRect()
    const sx = clientX - rect.left, sy = clientY - rect.top
    const hit = _nearestEnd(sx, sy)
    if (!_firstEnd) {
      if (hit) designRenderer.setPreviewGlow([{ pos: _instWorld(hit.instMesh, hit.id, new THREE.Vector3()) }])
      else     designRenderer.clearPreviewGlow()
      return
    }
    if (hit) {
      designRenderer.setPreviewGlow([{ pos: _instWorld(hit.instMesh, hit.id, new THREE.Vector3()) }])
      designRenderer.setPreviewArc(crossoverArcPoints(_firstEnd.nuc, hit.nuc))
    } else {
      designRenderer.clearPreviewGlow()
      designRenderer.clearPreviewArc?.()
    }
  }

  async function _commit(secondEntry) {
    if (_committing || !_firstEnd) return false
    if (!isValidPair(_firstEnd.nuc, secondEntry.nuc)) return false
    _committing = true
    const { three_prime_strand_id, five_prime_strand_id } = ligationArgs(_firstEnd.nuc, secondEntry.nuc)
    _clearFirstEnd()
    _setModeText()
    try {
      const ok = await api.forcedLigation(three_prime_strand_id, five_prime_strand_id)
      if (!ok) {
        const err = store.getState().lastError
        console.error('[force-xover] forced ligation failed:', err?.message)
      }
      return !!ok
    } finally {
      _committing = false
    }
  }

  // ── Pointer / key handlers (capture phase, added only while active) ──────────

  function _onMove(e) {
    if (!_active) return
    if (e.buttons !== 0) return   // mid-orbit/pan — keep the anchor, don't update preview
    _updateHover(e.clientX, e.clientY)
  }

  function _onDown(e) {
    if (!_active || e.button !== 0) return
    if (_committing) { e.stopImmediatePropagation(); return }
    const rect = canvas.getBoundingClientRect()
    const hit = _nearestEnd(e.clientX - rect.left, e.clientY - rect.top)
    if (!hit) return   // empty space → let OrbitControls handle the drag
    // We are acting on an end — take over the gesture from OrbitControls/selection.
    e.stopImmediatePropagation()
    _consumedDown = true
    if (!_firstEnd) _setFirstEnd(hit)
    else            _commit(hit)
  }

  function _onUp(e) {
    if (!_active) return
    if (_consumedDown && e.button === 0) { _consumedDown = false; e.stopImmediatePropagation() }
  }

  function _onKey(e) {
    if (!_active) return
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      if (_firstEnd) { _clearFirstEnd(); _setModeText() }   // step 2 → step 1
      else           deactivate()                            // step 1 → exit
    }
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  function activate() {
    if (_active) return
    if (store.getState().assemblyActive) return   // design-mode only
    _active = true
    _committing = false
    _consumedDown = false
    // Disable the selection manager entirely (lasso/multi-select/click) and force
    // the End level so the End button lights up.
    _prevSelectableTypes = { ...store.getState().selectableTypes }
    store.setState({
      forceXoverActive: true,
      selectedObject: null,
      selectableTypes: {
        scaffold: false, staples: false, strands: false, domains: false,
        ends: false, crossoverArcs: false, loops: false, skips: false, overhangs: false,
      },
    })
    designRenderer.clearGlow()
    _prevLevel = selectionManager.getSelectionLevel?.() ?? 'default'
    selectionManager.setSelectionLevel?.('end')
    _prevModeText = _modeEl()?.textContent ?? ''
    _setModeText()
    canvas.addEventListener('pointermove', _onMove, { capture: true })
    canvas.addEventListener('pointerdown', _onDown, { capture: true })
    canvas.addEventListener('pointerup',   _onUp,   { capture: true })
    window.addEventListener('keydown', _onKey, { capture: true })
  }

  function deactivate() {
    if (!_active) return
    _active = false
    _clearFirstEnd()
    canvas.removeEventListener('pointermove', _onMove, { capture: true })
    canvas.removeEventListener('pointerdown', _onDown, { capture: true })
    canvas.removeEventListener('pointerup',   _onUp,   { capture: true })
    window.removeEventListener('keydown', _onKey, { capture: true })
    selectionManager.setSelectionLevel?.(_prevLevel)
    store.setState({
      forceXoverActive: false,
      ...(_prevSelectableTypes ? { selectableTypes: _prevSelectableTypes } : {}),
    })
    _prevSelectableTypes = null
    const el = _modeEl()
    if (el) el.textContent = _prevModeText || 'NADOC · WORKSPACE'
  }

  function toggle() { _active ? deactivate() : activate() }

  // ── Button wiring (#view-tools fxover) + active-class reflection ─────────────
  const _btn = document.querySelector('#view-tools .sf-btn[data-key="fxover"]')
  _btn?.addEventListener('click', toggle)
  store.subscribe(() => { _btn?.classList.toggle('active', !!store.getState().forceXoverActive) })

  // Auto-exit if we leave design mode or the design changes out from under a pick.
  store.subscribe((n, p) => {
    if (_active && n.assemblyActive && !p.assemblyActive) deactivate()
    else if (_active && _firstEnd && n.currentDesign !== p.currentDesign && !_committing) {
      _clearFirstEnd(); _setModeText()
    }
  })

  return {
    activate, deactivate, toggle,
    isActive: () => _active,
    // Dev/test hook: drive the gesture without pixel math. Returns a promise for commits.
    testApi: {
      activate, deactivate, isActive: () => _active,
      getFirstEnd: () => (_firstEnd ? { strandId: _firstEnd.strandId, role: _firstEnd.role } : null),
      /** Distinct strand ids that currently have a rendered 5′/3′ end — the set a
       *  test can enumerate to find a ligatable pair to drive through pickEnd. */
      endStrandIds: () => [...new Set(designRenderer.getBackboneEntries().filter(e => endRole(e.nuc)).map(e => e.nuc.strand_id))],
      /** Pick the relevant end of `strandId`: step 1 → its first usable end as the
       *  anchor; step 2 → its opposite-polarity end → commit (returns the promise). */
      pickEnd(strandId) {
        const entries = designRenderer.getBackboneEntries()
        if (!_firstEnd) {
          const e = entries.find(x => x.nuc.strand_id === strandId && endRole(x.nuc))
          if (e) _setFirstEnd(e)
          return !!e
        }
        const e = entries.find(x => x.nuc.strand_id === strandId && isValidPair(_firstEnd.nuc, x.nuc))
        if (!e) return false
        return _commit(e)
      },
    },
  }
}

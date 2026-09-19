/**
 * Hairpin/self-dimer ⚠ markers in the 3D view — one clickable ⚠ over each
 * strand the checker flagged (hairpin_dimer_checker.js publishes the report).
 *
 * DOM buttons in a pointer-transparent layer over the canvas, not sprites, so a
 * click opens the structure window without touching the scene's pick/selection
 * pipeline (the orbit relay only forwards gestures that started on #canvas).
 *
 * Two-phase update, like unligated_crossover_markers.js:
 *   - rebuild on store changes (design / geometry / report / assembly mode):
 *     marker anchors = bead keys `helix:bp:dir` of the flagged domain;
 *   - refresh() every frame: average the LIVE bead positions via
 *     helixCtrl.lookupEntry (tracks unfold / cadnano view / expanded spacing /
 *     deform / cluster moves), project, place. Static geometry is the fallback.
 */
import * as THREE from 'three'
import { HAIRPIN_DIMER_COLORS, hairpinDimerMarkers } from '../ui/hairpin_dimer_report.js'

const MAX_KEYS = 24        // bead samples per marker
// Bright amber (same as the unligated-crossover ⚠) reads better over the dark scene.
const GLYPH_COLOR = { warning: '#f5a623', critical: HAIRPIN_DIMER_COLORS.critical }
const LIFT_PX = 10         // marker sits this far above its anchor point

function _anchorKeys(domains) {
  const keys = []
  for (const d of domains) {
    const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
    for (let bp = lo; bp <= hi; bp++) keys.push(`${d.helix_id}:${bp}:${d.direction}`)
  }
  if (keys.length <= MAX_KEYS) return keys
  const step = keys.length / MAX_KEYS
  return Array.from({ length: MAX_KEYS }, (_, i) => keys[Math.floor(i * step)])
}

/**
 * @param {object} o
 * @param {object} o.store         3D store (currentDesign, currentGeometry, hairpinDimerReport, assemblyActive)
 * @param {HTMLElement} o.host     positioned container of the canvas (#canvas-area)
 * @param {THREE.Camera} o.camera
 * @param {HTMLCanvasElement} o.canvas
 * @param {Function} o.getHelixCtrl
 * @param {Function} o.onOpen      (strandId, label) → open the structure window
 */
export function initHairpinDimerMarkers({ store, host, camera, canvas, getHelixCtrl, onOpen }) {
  const layer = document.createElement('div')
  layer.className = 'hd-3d-layer'
  layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:4'
  host.appendChild(layer)

  let _markers = []          // { strandId, keys, fallback, el, x, y, shown }
  let _geoRef = null
  let _geoMap = new Map()
  const _v = new THREE.Vector3()

  function _geoPositions(geometry) {
    if (geometry !== _geoRef) {
      _geoRef = geometry
      _geoMap = new Map()
      for (const n of geometry ?? []) {
        if (n.backbone_position) _geoMap.set(`${n.helix_id}:${n.bp_index}:${n.direction}`, n.backbone_position)
      }
    }
    return _geoMap
  }

  function _button(m) {
    const el = document.createElement('button')
    el.type = 'button'
    el.className = `hd-3d-marker hd-3d-marker--${m.level === 'critical' ? 'critical' : 'warning'}`
    el.textContent = '⚠'
    el.dataset.strandId = m.strandId
    el.title = `${m.tooltip}\n\nClick to show the structure.`
    el.setAttribute('aria-label', `Hairpin/dimer warning: ${m.label}`)
    el.style.cssText = 'position:absolute;left:0;top:0;pointer-events:auto;cursor:pointer;'
      + 'background:none;border:none;padding:0 2px;margin:0;line-height:1;'
      + 'font:700 20px sans-serif;text-shadow:0 0 3px #000,0 0 6px #000;'
      + 'visibility:hidden'
    el.style.color = GLYPH_COLOR[m.level] ?? GLYPH_COLOR.warning   // red above the critical Tm
    el.addEventListener('pointerdown', ev => ev.stopPropagation())
    el.addEventListener('click', ev => { ev.stopPropagation(); onOpen?.(m.strandId, m.label) })
    return el
  }

  function rebuild() {
    const s = store.getState()
    const list = s.assemblyActive ? [] : hairpinDimerMarkers(s.hairpinDimerReport, s.currentDesign)
    for (const m of _markers) m.el.remove()
    const geo = _geoPositions(s.currentGeometry)
    _markers = list.map(m => {
      const keys = _anchorKeys(m.domains)
      const pts = keys.map(k => geo.get(k)).filter(Boolean)
      const fallback = pts.length
        ? [0, 1, 2].map(a => pts.reduce((sum, p) => sum + p[a], 0) / pts.length)
        : null
      const el = _button(m)
      layer.appendChild(el)
      return { strandId: m.strandId, keys, fallback, el, x: null, y: null, shown: false }
    })
  }

  /** Per-frame: pin every marker to the live centroid of its anchor beads. */
  function refresh() {
    if (!_markers.length) return
    const ctrl = getHelixCtrl?.()
    const cr = canvas.getBoundingClientRect()
    const hr = host.getBoundingClientRect()
    for (const m of _markers) {
      let n = 0, x = 0, y = 0, z = 0
      if (ctrl?.lookupEntry) {
        for (const k of m.keys) {
          const p = ctrl.lookupEntry(k)?.pos
          if (p) { x += p.x; y += p.y; z += p.z; n++ }
        }
      }
      if (n) _v.set(x / n, y / n, z / n)
      else if (m.fallback) _v.fromArray(m.fallback)
      else { _hide(m); continue }
      _v.project(camera)
      if (_v.z < -1 || _v.z > 1) { _hide(m); continue }
      const sx = Math.round(cr.left - hr.left + (_v.x * 0.5 + 0.5) * cr.width)
      const sy = Math.round(cr.top - hr.top + (-_v.y * 0.5 + 0.5) * cr.height - LIFT_PX)
      if (sx !== m.x || sy !== m.y) {
        m.el.style.transform = `translate(${sx}px, ${sy}px) translate(-50%, -100%)`
        m.x = sx; m.y = sy
      }
      if (!m.shown) { m.el.style.visibility = 'visible'; m.shown = true }
    }
  }

  function _hide(m) {
    if (!m.shown) return
    m.el.style.visibility = 'hidden'
    m.shown = false
  }

  const unsubscribe = store.subscribe((n, p) => {
    if (n.currentDesign !== p.currentDesign || n.currentGeometry !== p.currentGeometry
      || n.hairpinDimerReport !== p.hairpinDimerReport || n.assemblyActive !== p.assemblyActive) rebuild()
  })
  rebuild()

  return {
    refresh,
    rebuild,
    count: () => _markers.length,
    destroy() {
      unsubscribe?.()
      layer.remove()
      _markers = []
    },
  }
}

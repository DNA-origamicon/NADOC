// Representation option sliders — the per-representation tuning rows in the
// right sidebar (bead radius, cylinder radius, hull-prism scan margin, hull
// curve detail) plus the show/hide logic that reveals only the rows relevant
// to the active representation.
//
// Extracted verbatim from main.js (`_reprOptionSliders` + the four slider
// `input` listeners) as the first lift of the representation-switcher campaign
// (frontier #2). The switcher core (`_setRepresentation`, the radio, the F-key
// loop) stays in main.js for now and drives this module via `updateForRepr`.

/**
 * Which option rows / panels are visible for a given representation.
 * Pure — drives the row `display` toggles in `updateForRepr`.
 * @param {string} repr
 * @returns {{beadRadius:boolean, slabThickness:boolean,
 *            cylRadius:boolean, hullMargin:boolean, hullCurve:boolean,
 *            atomisticSliders:boolean, surfacePanel:boolean}}
 */
export function reprSliderRowVisibility(repr) {
  return {
    beadRadius:       repr === 'full' || repr === 'beads',
    // Base-pair slabs are only built at full LOD (helix_renderer `_skipSlabs`).
    slabThickness:    repr === 'full',
    cylRadius:        repr === 'cylinders',
    hullMargin:       repr === 'hull-prism',
    hullCurve:        repr === 'hull-prism',
    atomisticSliders: repr === 'vdw' || repr === 'ballstick' || repr === 'stick',
    surfacePanel:     repr === 'surface',
  }
}

/**
 * Per-lattice default for the hull-prism cross-section scan margin (bp):
 * 8 for honeycomb, 7 otherwise (square).
 * @param {string|undefined} latticeType
 * @returns {number}
 */
export function hullMarginDefaultTick(latticeType) {
  return latticeType === 'HONEYCOMB' ? 8 : 7
}

/**
 * @param {object} deps
 * @param {object} deps.store                       app store (read currentDesign.lattice_type)
 * @param {object} deps.designRenderer              setBeadRadius / setCylinderRadius
 * @param {() => (object|null)} deps.getJointRenderer  hull-prism renderer (lazy; may be null)
 * @param {() => string} deps.getLodMode            current LOD mode ('full'|'beads'|'cylinders')
 * @param {(v:boolean)=>void} deps.setAtomisticSlidersVisible
 * @param {(v:boolean)=>void} deps.setSurfacePanelVisible
 * @returns {{updateForRepr: (repr:string)=>void}}
 */
export function initReprOptionSliders({
  store,
  designRenderer,
  getJointRenderer,
  getLodMode,
  setAtomisticSlidersVisible,
  setSurfacePanelVisible,
}) {
  let _currentBeadRadius = 0.10   // current bead radius (nm); matches sl-bead-radius default

  const _slBeadRadius = document.getElementById('sl-bead-radius')
  const _svBeadRadius = document.getElementById('sv-bead-radius')
  _slBeadRadius?.addEventListener('input', () => {
    const r = parseFloat(_slBeadRadius.value)
    _currentBeadRadius = r
    if (_svBeadRadius) _svBeadRadius.textContent = r.toFixed(2)
    const lod = getLodMode()
    if (lod === 'full' || lod === 'beads') designRenderer.setBeadRadius(r)
  })

  // Base-pair slab plate thickness (nm). Full repr only — the slabs don't exist
  // at bead/cylinder LOD. (A slab-opacity slider used to live here; removed
  // 2026-08-02 — it collided with the other opacity controls.)
  const _slSlabThickness = document.getElementById('sl-slab-thickness')
  const _svSlabThickness = document.getElementById('sv-slab-thickness')
  _slSlabThickness?.addEventListener('input', () => {
    const nm = parseFloat(_slSlabThickness.value)
    if (_svSlabThickness) _svSlabThickness.textContent = nm.toFixed(2)
    if (getLodMode() === 'full') designRenderer.setSlabThickness(nm)
  })

  const _slCylRadius = document.getElementById('sl-cyl-radius')
  const _svCylRadius = document.getElementById('sv-cyl-radius')
  _slCylRadius?.addEventListener('input', () => {
    const r = parseFloat(_slCylRadius.value)
    if (_svCylRadius) _svCylRadius.textContent = r.toFixed(2)
    if (getLodMode() === 'cylinders') designRenderer.setCylinderRadius(r)
  })

  // Hull-prism cross-section margin (bp) — granularity of the extrusion scan.
  const _slHullMargin = document.getElementById('sl-hull-margin')
  const _svHullMargin = document.getElementById('sv-hull-margin')
  _slHullMargin?.addEventListener('input', () => {
    const bp = parseInt(_slHullMargin.value, 10)
    if (_svHullMargin) _svHullMargin.textContent = String(bp)
    getJointRenderer()?.setHullScanTick(bp)
  })

  // Curved-hull facet detail (nm deviation tolerance): lower = smoother/more facets.
  const _slHullCurve = document.getElementById('sl-hull-curve')
  const _svHullCurve = document.getElementById('sv-hull-curve')
  _slHullCurve?.addEventListener('input', () => {
    const nm = parseFloat(_slHullCurve.value)
    if (_svHullCurve) _svHullCurve.textContent = nm.toFixed(2)
    getJointRenderer()?.setHullCurveDetail(nm)
  })

  function updateForRepr(repr) {
    const vis = reprSliderRowVisibility(repr)
    document.getElementById('repr-bead-radius-row')?.style.setProperty(
      'display', vis.beadRadius ? '' : 'none')
    document.getElementById('repr-slab-thickness-row')?.style.setProperty(
      'display', vis.slabThickness ? '' : 'none')
    document.getElementById('repr-cyl-radius-row')?.style.setProperty(
      'display', vis.cylRadius ? '' : 'none')
    document.getElementById('repr-hull-margin-row')?.style.setProperty(
      'display', vis.hullMargin ? '' : 'none')
    document.getElementById('repr-hull-curve-row')?.style.setProperty(
      'display', vis.hullCurve ? '' : 'none')
    if (repr === 'hull-prism') {
      // Sync the slider to the per-lattice default (7 square / 8 honeycomb).
      const lat = store.getState().currentDesign?.lattice_type
      const tick = hullMarginDefaultTick(lat)
      const sl = document.getElementById('sl-hull-margin')
      const sv = document.getElementById('sv-hull-margin')
      if (sl) sl.value = String(tick)
      if (sv) sv.textContent = String(tick)
    }
    setAtomisticSlidersVisible(vis.atomisticSliders)
    setSurfacePanelVisible(vis.surfacePanel)
  }

  return { updateForRepr }
}

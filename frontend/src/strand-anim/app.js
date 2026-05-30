/**
 * Strand-animation playground — PAGE HOST (the standalone `/strand-anim.html`
 * glue). Thin: wires the shared 3D scene, the reusable strand renderer, the
 * parameter panel, the φ ticker, and the readout overlay.
 *
 * The reusable, drop-in pieces live elsewhere and have no page dependencies:
 *   - model.js          → buildStrandGeometry(params, phi)  (pure)
 *   - strand_renderer.js → createStrandRenderer(scene)       (THREE only)
 *   - ticker.js          → createPhiTicker(...)              (RAF only)
 *   - params.js / melt.js / geometry_*.js                    (pure)
 * Only this file + panel.js + main.js + strand-anim.html are page-specific.
 * See project_strand_animations.md "Integration handoff" for dropping the
 * model + renderer into the main NADOC animation toolset.
 *
 * DISPLAY-ONLY: no Design, no topology, no backend.
 */

import { initScene } from '../scene/scene.js'
import { createParamState, DEFAULTS } from './params.js'
import { buildStrandGeometry } from './model.js'
import { createStrandRenderer } from './strand_renderer.js'
import { createPhiTicker } from './ticker.js'
import { buildPanel } from './panel.js'

const clamp01 = (v) => Math.max(0, Math.min(1, v))

/**
 * @param {HTMLCanvasElement} canvas
 * @param {HTMLElement} panelRoot
 * @returns {{ state:object, setPhi:(p:number)=>void, rebuildGeometry:()=>void, dispose:()=>void }}
 */
export function initStrandAnimApp(canvas, panelRoot) {
  const ctx = initScene(canvas)
  const state = createParamState()
  const readoutEl = document.getElementById('strand-readout')
  const renderer = createStrandRenderer(ctx.scene)

  let _panel = null

  function rebuildGeometry() {
    const params = state.snapshot()
    const { strands, meta } = buildStrandGeometry(params, params.phi)
    renderer.update(strands)
    if (readoutEl) readoutEl.textContent = `φ = ${clamp01(params.phi).toFixed(3)}   ${meta.readout || ''}`
  }

  function setPhi(phi) {
    state.set('phi', clamp01(phi))
    rebuildGeometry()
    _panel?.refresh()
  }

  const ticker = createPhiTicker({
    getState: () => state.snapshot(),
    setPhi,
    onState: () => _panel?.refresh(),
  })

  _panel = buildPanel(panelRoot, state, {
    onChange: rebuildGeometry,
    onPlayToggle: () => ticker.toggle(),
    isPlaying: () => ticker.isPlaying(),
  })

  // Camera framing: look at the duplex laid along +X in the XY plane.
  const cx = ((DEFAULTS.N - 1) * DEFAULTS.rise) / 2
  ctx.camera.position.set(cx, 0, 16)
  ctx.camera.up.set(0, 1, 0)
  ctx.controls.target.set(cx, 0, 0)
  ctx.controls.update()

  rebuildGeometry()

  function dispose() {
    ticker.stop()
    renderer.dispose()
  }

  return { state, setPhi, rebuildGeometry, dispose }
}

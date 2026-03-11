/**
 * NADOC frontend entry point — Phase 2 (workspace redesign).
 *
 * 1. Initialises the Three.js scene inside #viewport-container.
 * 2. Initialises the blank 3D workspace (plane picker + honeycomb lattice).
 * 3. On extrude: calls API → shows 3D helices via design renderer.
 * 4. Wires menu bar: File > New, View > Reset Camera / Toggle Origin Axes.
 * 5. Wires right-panel: Properties, Validation, Slab sliders, Reset Camera.
 * 6. Wires command palette (Ctrl+K) for advanced operations.
 * 7. Optionally enables ?debug=1 click readout.
 */

import * as THREE from 'three'
import { initScene }                 from './scene/scene.js'
import { initDesignRenderer }        from './scene/design_renderer.js'
import { initSelectionManager }      from './scene/selection_manager.js'
import { initCrossoverMarkers }      from './scene/crossover_markers.js'
import { initWorkspace }             from './scene/workspace.js'
import { initCommandPalette }        from './ui/command_palette.js'
import { initPropertiesPanel }       from './ui/properties_panel.js'
import { initValidationReportPanel } from './ui/validation_report_panel.js'
import { store }                     from './state/store.js'
import * as api                      from './api/client.js'

const DEBUG = new URLSearchParams(window.location.search).has('debug')

async function main() {
  const canvas = document.getElementById('canvas')
  const { scene, camera, renderer, controls } = initScene(canvas)

  // ── Persistent origin axes (toggleable via View > Toggle Origin Axes) ───────
  const originAxes = new THREE.AxesHelper(4)
  scene.add(originAxes)

  // ── Design renderer (reactive — shows helices when store has geometry) ───────
  const designRenderer = initDesignRenderer(scene, store)

  // ── Selection manager ───────────────────────────────────────────────────────
  initSelectionManager(canvas, camera, designRenderer)

  // ── Crossover markers ───────────────────────────────────────────────────────
  const crossoverMarkers = initCrossoverMarkers(scene, camera, canvas)

  // ── Workspace (blank 3D editor with plane picker) ───────────────────────────
  const workspace = initWorkspace(scene, camera, controls, {
    onExtrude: async ({ cells, lengthBp, plane }) => {
      const result = await api.createBundle({ cells, lengthBp, plane })
      if (!result) {
        const err = store.getState().lastError
        throw new Error(err?.message ?? 'Bundle creation failed')
      }
      // Hide workspace planes/lattice and show resulting helices
      workspace.hide()
    },
  })
  workspace.attach(canvas)

  // Start with blank workspace
  workspace.show()
  camera.position.set(6, 3, 18)
  controls.target.set(6, 3, 0)
  controls.update()

  // ── Menu bar ─────────────────────────────────────────────────────────────────
  document.getElementById('menu-file-new')?.addEventListener('click', async () => {
    await api.createDesign('Untitled')
    store.setState({ currentDesign: null, currentGeometry: null, validationReport: null })
    workspace.show()
    camera.position.set(6, 3, 18)
    controls.target.set(6, 3, 0)
    controls.update()
  })

  document.getElementById('menu-view-axes')?.addEventListener('click', () => {
    originAxes.visible = !originAxes.visible
  })

  document.getElementById('menu-view-reset')?.addEventListener('click', () => {
    const { currentGeometry } = store.getState()
    if (currentGeometry && currentGeometry.length > 0) {
      camera.position.set(6, 3, 7)
      controls.target.set(0, 0, 7)
    } else {
      workspace.reset()
    }
    controls.update()
  })

  // ── Reset camera button (right panel) ────────────────────────────────────────
  document.getElementById('reset-btn')?.addEventListener('click', () => {
    const { currentGeometry } = store.getState()
    if (currentGeometry && currentGeometry.length > 0) {
      camera.position.set(6, 3, 7)
      controls.target.set(0, 0, 7)
    } else {
      workspace.reset()
    }
    controls.update()
  })

  // ── Command palette ─────────────────────────────────────────────────────────
  initCommandPalette({
    onAddHelix: async (params) => {
      await api.addHelix(params)
    },

    onCrossoverMode: () => {
      const { currentDesign } = store.getState()
      const helices = currentDesign?.helices ?? []
      if (helices.length < 2) {
        alert('Need at least 2 helices to place a crossover.')
        return
      }
      crossoverMarkers.activate(helices[0].id, helices[1].id)
      document.getElementById('mode-indicator').textContent =
        'CROSSOVER PLACEMENT — click a gold marker · Esc to cancel'
    },

    onDeleteSelected: async () => {
      const { selectedObject } = store.getState()
      if (!selectedObject) return
      const nuc = selectedObject.data
      if (nuc?.strand_id) {
        const confirmed = confirm(`Delete strand "${nuc.strand_id}"?`)
        if (confirmed) await api.deleteStrand(nuc.strand_id)
      }
    },
  })

  // Exit crossover mode with Escape.
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && crossoverMarkers.isActive()) {
      crossoverMarkers.deactivate()
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
  })
  store.subscribe((newState, prevState) => {
    if (!newState.crossoverPlacement && prevState.crossoverPlacement) {
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
  })

  // ── UI panels ───────────────────────────────────────────────────────────────
  initPropertiesPanel()
  initValidationReportPanel()

  // ── Debug overlay (?debug=1) ─────────────────────────────────────────────────
  if (DEBUG) {
    const debugPanel = document.getElementById('debug-panel')
    debugPanel.classList.add('visible')
    debugPanel.innerHTML = '<div class="row">Click a backbone bead for details.</div>'

    store.subscribe((newState, prevState) => {
      if (newState.selectedObject !== prevState.selectedObject && newState.selectedObject) {
        const nuc = newState.selectedObject.data
        const fmt = arr => arr.map(v => Number(v).toFixed(4)).join(', ')
        debugPanel.innerHTML = `
          <div class="row">bp <span class="val">${nuc.bp_index}</span> · <span class="val">${nuc.direction}</span></div>
          <div class="row">strand <span class="val">${nuc.strand_id ?? '—'}</span>${nuc.is_scaffold ? ' <span class="val">[scaffold]</span>' : ''}</div>
          <div class="row">${nuc.is_five_prime ? "5′ end" : nuc.is_three_prime ? "3′ end" : "internal"}</div>
          <div class="row">backbone <span class="val">[${fmt(nuc.backbone_position)}]</span></div>
          <div class="row">base&nbsp;&nbsp;&nbsp;&nbsp; <span class="val">[${fmt(nuc.base_position)}]</span></div>
          <div class="row">bnormal  <span class="val">[${fmt(nuc.base_normal)}]</span></div>
        `
      }
    })
  }

  // ── Distance label update loop ────────────────────────────────────────────
  function updateDistLabel() {
    const info = designRenderer.getDistLabelInfo()
    let el = document.querySelector('.dist-label')
    if (!info) { if (el) el.remove(); return }
    if (!el) {
      el = document.createElement('div')
      el.className = 'dist-label'
      document.body.appendChild(el)
    }
    el.textContent = info.text
    const container = canvas.parentElement
    const offsetX   = container.getBoundingClientRect().left
    const v = new THREE.Vector3(...info.midpoint).project(camera)
    el.style.left = `${offsetX + (v.x * 0.5 + 0.5) * container.clientWidth  + 14}px`
    el.style.top  = `${(-v.y * 0.5 + 0.5) * container.clientHeight - 10}px`
  }

  ;(function tick() { updateDistLabel(); requestAnimationFrame(tick) })()
}

main().catch(err => {
  console.error('NADOC boot error:', err)
  const box = document.getElementById('prompt-box')
  if (box) box.innerHTML = `<p style="color:#ff6b6b">Boot error: ${err.message}</p>`
})

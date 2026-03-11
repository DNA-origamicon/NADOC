/**
 * NADOC frontend entry point — Phase 4 (staple crossovers).
 *
 * 1. Initialises the Three.js scene inside #viewport-container.
 * 2. Initialises the blank 3D workspace (plane picker + honeycomb lattice).
 * 3. On extrude: calls API → shows 3D helices via design renderer.
 * 4. Wires menu bar: File > New, View > Reset Camera / Toggle Origin Axes / Slice Plane.
 * 5. Wires right-panel: Properties, Validation, Slab sliders, Reset Camera.
 * 6. Wires command palette (Ctrl+K) for advanced operations.
 * 7. Optionally enables ?debug=1 click readout.
 * 8. Slice plane: toggled via View menu or 'S' key; slides along bundle axis,
 *    snaps to 0.334 nm grid, shows honeycomb lattice for new segment extrusion.
 * 9. Proximity crossover markers: always-on thin cylinders that fade in when
 *    cursor is nearby; clicking places a staple crossover (strand split+reconnect).
 */

import * as THREE from 'three'
import { initScene }                 from './scene/scene.js'
import { initDesignRenderer }        from './scene/design_renderer.js'
import { initSelectionManager }      from './scene/selection_manager.js'
import { initCrossoverMarkers }      from './scene/crossover_markers.js'
import { initWorkspace }             from './scene/workspace.js'
import { initSlicePlane }            from './scene/slice_plane.js'
import { initBluntEnds }             from './scene/blunt_ends.js'
import { initCommandPalette }        from './ui/command_palette.js'
import { initPropertiesPanel }       from './ui/properties_panel.js'
import { initValidationReportPanel } from './ui/validation_report_panel.js'
import { store }                     from './state/store.js'
import * as api                      from './api/client.js'

const DEBUG = new URLSearchParams(window.location.search).has('debug')

// Compute the maximum extent of the current design along the given plane normal.
// This is where the slice plane starts when first toggled on.
function _bundleMaxOffset(design, plane) {
  if (!design || !design.helices.length) return 0
  let max = 0
  for (const h of design.helices) {
    let v
    if      (plane === 'XY') v = Math.max(h.axis_start.z, h.axis_end.z)
    else if (plane === 'XZ') v = Math.max(h.axis_start.y, h.axis_end.y)
    else                     v = Math.max(h.axis_start.x, h.axis_end.x)
    if (v > max) max = v
  }
  return max
}

async function main() {
  const canvas = document.getElementById('canvas')
  const { scene, camera, renderer, controls } = initScene(canvas)

  // ── Persistent origin axes (toggleable via View > Toggle Origin Axes) ───────
  const originAxes = new THREE.AxesHelper(4)
  scene.add(originAxes)

  // ── Design renderer (reactive — shows helices when store has geometry) ───────
  const designRenderer = initDesignRenderer(scene, store)

  // ── Selection manager ───────────────────────────────────────────────────────
  initSelectionManager(canvas, camera, designRenderer, {
    onNick: async ({ helixId, bpIndex, direction }) => {
      const result = await api.addNick({ helixId, bpIndex, direction })
      if (!result) {
        const err = store.getState().lastError
        console.error('Nick failed:', err?.message)
      }
    },
  })

  // ── Crossover markers ───────────────────────────────────────────────────────
  const crossoverMarkers = initCrossoverMarkers(scene, camera, canvas)

  // ── Slice plane ─────────────────────────────────────────────────────────────
  const slicePlane = initSlicePlane(scene, camera, canvas, controls, {
    onExtrude: async ({ cells, lengthBp, plane, offsetNm, continuationMode }) => {
      const result = continuationMode
        ? await api.addBundleContinuation({ cells, lengthBp, plane, offsetNm })
        : await api.addBundleSegment({ cells, lengthBp, plane, offsetNm })
      if (!result) {
        const err = store.getState().lastError
        throw new Error(err?.message ?? 'Segment extrusion failed')
      }
      slicePlane.hide()
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    },
    getDesign: () => store.getState().currentDesign,
  })

  function _toggleSlicePlane() {
    if (slicePlane.isVisible()) {
      slicePlane.hide()
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      return
    }
    const { currentDesign, currentPlane } = store.getState()
    if (!currentDesign || !currentPlane) return
    const offset = _bundleMaxOffset(currentDesign, currentPlane)
    slicePlane.show(currentPlane, offset)
    document.getElementById('mode-indicator').textContent =
      'SLICE PLANE — drag handle to reposition · right-click cells → Extrude · Esc to close'
  }

  // ── Blunt end indicators ─────────────────────────────────────────────────────
  initBluntEnds(scene, camera, canvas, {
    onBluntEndClick: ({ plane, offsetNm }) => {
      store.setState({ currentPlane: plane })
      slicePlane.show(plane, offsetNm, true)  // continuation mode
      document.getElementById('mode-indicator').textContent =
        'CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
    },
    isDisabled: () => slicePlane.isVisible(),
  })

  // ── Workspace (blank 3D editor with plane picker) ───────────────────────────
  const workspace = initWorkspace(scene, camera, controls, {
    onExtrude: async ({ cells, lengthBp, plane }) => {
      const result = await api.createBundle({ cells, lengthBp, plane })
      if (!result) {
        const err = store.getState().lastError
        throw new Error(err?.message ?? 'Bundle creation failed')
      }
      // Record which plane was used so the slice plane knows its orientation.
      store.setState({ currentPlane: plane })
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
    slicePlane.hide()
    await api.createDesign('Untitled')
    store.setState({
      currentDesign: null, currentGeometry: null,
      validationReport: null, currentPlane: null,
    })
    workspace.show()
    camera.position.set(6, 3, 18)
    controls.target.set(6, 3, 0)
    controls.update()
  })

  document.getElementById('menu-file-export')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) {
      alert('No design to export.')
      return
    }
    await api.exportDesign()
  })

  document.getElementById('menu-edit-undo')?.addEventListener('click', async () => {
    const result = await api.undo()
    if (!result) {
      const err = store.getState().lastError
      if (err?.status === 404) alert('Nothing to undo.')
    } else {
      // If we undid back to an empty design, return to workspace
      const { currentDesign } = store.getState()
      if (!currentDesign?.helices?.length) {
        slicePlane.hide()
        workspace.show()
      }
    }
  })

  document.getElementById('menu-edit-redo')?.addEventListener('click', async () => {
    const result = await api.redo()
    if (!result) {
      const err = store.getState().lastError
      if (err?.status === 404) alert('Nothing to redo.')
    }
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

  document.getElementById('menu-view-slice')?.addEventListener('click', _toggleSlicePlane)

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

  // ── Keyboard shortcuts ────────────────────────────────────────────────────────
  document.addEventListener('keydown', async e => {
    const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'

    // Ctrl+Z — undo
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
      e.preventDefault()
      const result = await api.undo()
      if (!result) {
        const err = store.getState().lastError
        if (err?.status === 404) {
          document.getElementById('mode-indicator').textContent = 'Nothing to undo'
          setTimeout(() => {
            document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
          }, 1500)
        }
      } else {
        const { currentDesign } = store.getState()
        if (!currentDesign?.helices?.length) {
          slicePlane.hide()
          workspace.show()
        }
      }
      return
    }

    // Ctrl+Y or Ctrl+Shift+Z — redo
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
      e.preventDefault()
      const result = await api.redo()
      if (!result) {
        const err = store.getState().lastError
        if (err?.status === 404) {
          document.getElementById('mode-indicator').textContent = 'Nothing to redo'
          setTimeout(() => {
            document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
          }, 1500)
        }
      }
      return
    }

    // 'S' — toggle slice plane (when a design is loaded)
    if ((e.key === 's' || e.key === 'S') && !inInput) {
      _toggleSlicePlane()
      return
    }

    // Escape — exit crossover mode or close slice plane
    if (e.key === 'Escape') {
      if (crossoverMarkers.isActive()) {
        crossoverMarkers.deactivate()
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      } else if (slicePlane.isVisible()) {
        slicePlane.hide()
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      }
    }
  })

  // ── Command palette ─────────────────────────────────────────────────────────
  initCommandPalette({
    onAddHelix: async (params) => {
      await api.addHelix(params)
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

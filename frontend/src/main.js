/**
 * NADOC frontend entry point — Phase 5 (XPBD physics layer).
 *
 * 1. Initialises the Three.js scene inside #viewport-container.
 * 2. Initialises the blank 3D workspace (plane picker + honeycomb lattice).
 * 3. On extrude: calls API → shows 3D helices via design renderer.
 * 4. Wires menu bar: File > New, View > Reset Camera / Toggle Origin Axes /
 *    Slice Plane / Toggle Physics.
 * 5. Wires right-panel: Properties, Validation, Slab sliders, Reset Camera.
 * 6. Wires command palette (Ctrl+K) for advanced operations.
 * 7. Optionally enables ?debug=1 click readout.
 * 8. Slice plane: toggled via View menu or 'S' key; slides along bundle axis,
 *    snaps to 0.334 nm grid, shows honeycomb lattice for new segment extrusion.
 * 9. Proximity crossover markers: always-on thin cylinders that fade in when
 *    cursor is nearby; clicking places a staple crossover (strand split+reconnect).
 * 10. Physics mode [P key]: connects to /ws/physics WebSocket, streams XPBD-
 *     relaxed backbone positions as yellow spheres overlaid on white geometric
 *     positions.  Toggling off clears the overlay (V5.3: exact reset).
 */

import * as THREE from 'three'
import { initScene }                 from './scene/scene.js'
import { initDesignRenderer }        from './scene/design_renderer.js'
import { initSelectionManager }      from './scene/selection_manager.js'
import { initCrossoverMarkers }      from './scene/crossover_markers.js'
import { initWorkspace }             from './scene/workspace.js'
import { initSlicePlane }            from './scene/slice_plane.js'
import { initBluntEnds }             from './scene/blunt_ends.js'
import { initCommandPalette }  from './ui/command_palette.js'
import { initPropertiesPanel } from './ui/properties_panel.js'
import { createScriptRunner }  from './ui/script_runner.js'
import { store }               from './state/store.js'
import * as api                from './api/client.js'
import { initPhysicsClient }   from './physics/physics_client.js'
import { initDeformationEditor, startTool, startToolAtBp, isActive as isDeformActive,
         handlePointerMove as deformPointerMove,
         handlePointerDown as deformPointerDown,
         handleEscape as deformEscape,
         confirmDeformation, cancelDeformation, previewDeformation,
         getState as getDeformState, getToolType as getDeformToolType,
         STATES as DEFORM_STATES,
       } from './scene/deformation_editor.js'
import { initBendTwistPopup, openPopup as openDeformPopup,
         closePopup as closeDeformPopup,
       } from './ui/bend_twist_popup.js'

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

  // ── Deformation editor canvas listeners (capture phase — run before selectionMgr) ──

  // Track whether the deform tool consumed the most recent pointerdown.
  // We must only block the matching pointerup if we also blocked the pointerdown —
  // otherwise OrbitControls receives the pointerdown but never the pointerup,
  // leaving it stuck in a perpetual "dragging" state.
  let _deformConsumedDown = false

  canvas.addEventListener('pointermove', e => {
    if (!isDeformActive()) return
    deformPointerMove(e)
  }, { capture: true })

  canvas.addEventListener('pointerdown', e => {
    _deformConsumedDown = false
    if (!isDeformActive()) return
    const consumed = deformPointerDown(e)
    _deformConsumedDown = consumed
    if (consumed) e.stopImmediatePropagation()
    _watchDeformState()
  }, { capture: true })

  // Only block the pointerup when we also blocked the corresponding pointerdown.
  // If deformPointerDown returned false (click missed all axes → OrbitControls
  // received the pointerdown), we must let the pointerup through so OrbitControls
  // can exit its drag state cleanly.
  canvas.addEventListener('pointerup', e => {
    if (_deformConsumedDown && e.button === 0) {
      _deformConsumedDown = false
      e.stopImmediatePropagation()
    }
  }, { capture: true })

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

  // ── Loop strand popup ────────────────────────────────────────────────────────
  // When the user clicks a red circular-staple strand, show a warning popup with
  // an option to automatically nick at a valid position (≥7bp from domain boundaries).
  ;(function _initLoopPopup() {
    const overlay = document.createElement('div')
    overlay.id = 'loop-strand-popup'
    overlay.style.cssText = [
      'display:none', 'position:fixed', 'inset:0',
      'background:rgba(0,0,0,0.5)', 'z-index:1000',
      'align-items:center', 'justify-content:center',
    ].join(';')
    overlay.innerHTML = `
      <div style="background:#1e2a3a;border:1px solid #ff3333;border-radius:8px;padding:24px 28px;max-width:380px;color:#e8eef4;font-family:monospace;">
        <p style="margin:0 0 8px;font-size:13px;color:#ff6b6b;font-weight:bold;">⚠ Circular staple detected</p>
        <p style="margin:0 0 18px;font-size:12px;line-height:1.5;">
          This staple strand has no free 5′/3′ ends.
          Nick automatically at the midpoint of its longest domain,
          or dismiss to leave it unresolved.
        </p>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button id="loop-popup-leave" style="padding:6px 14px;background:#2d3f52;border:1px solid #445566;border-radius:4px;color:#e8eef4;cursor:pointer;font-family:monospace;font-size:12px;">Leave unresolved</button>
          <button id="loop-popup-nick" style="padding:6px 14px;background:#c0392b;border:none;border-radius:4px;color:#fff;cursor:pointer;font-family:monospace;font-size:12px;">Nick here</button>
        </div>
      </div>
    `
    document.body.appendChild(overlay)

    let _pendingNick = null  // { helixId, bpIndex, direction }

    function _close() {
      overlay.style.display = 'none'
      _pendingNick = null
    }

    document.getElementById('loop-popup-leave').addEventListener('click', _close)
    document.getElementById('loop-popup-nick').addEventListener('click', async () => {
      const nick = _pendingNick
      _close()
      if (!nick) return
      const result = await api.addNick(nick)
      if (!result) {
        const err = store.getState().lastError
        console.error('Loop nick failed:', err?.message)
      }
    })
    overlay.addEventListener('click', e => { if (e.target === overlay) _close() })

    store.subscribe((newState, prevState) => {
      if (newState.selectedObject === prevState.selectedObject) return
      const obj = newState.selectedObject
      if (!obj?.data?.strand_id) return
      const loopSet = new Set(newState.loopStrandIds ?? [])
      if (!loopSet.has(obj.data.strand_id)) return

      // Find the best nick position: midpoint of longest domain, ≥7bp from ends.
      const design = newState.currentDesign
      const strand = design?.strands?.find(s => s.id === obj.data.strand_id)
      if (!strand) return

      let bestNick = null
      let bestLen  = -1
      for (const domain of strand.domains) {
        const lo  = Math.min(domain.start_bp, domain.end_bp)
        const hi  = Math.max(domain.start_bp, domain.end_bp)
        const len = hi - lo + 1
        if (len < 15) continue   // need ≥7+1+7 bp to safely nick
        // Nick at midpoint of the domain.
        const midBp = lo + Math.floor(len / 2)
        if (len > bestLen) {
          bestLen  = len
          bestNick = { helixId: domain.helix_id, bpIndex: midBp, direction: domain.direction }
        }
      }
      if (!bestNick) {
        // Fallback: pick the longest domain regardless of minimum spacing.
        for (const domain of strand.domains) {
          const lo  = Math.min(domain.start_bp, domain.end_bp)
          const hi  = Math.max(domain.start_bp, domain.end_bp)
          const len = hi - lo + 1
          if (len > bestLen && len >= 3) {
            bestLen  = len
            bestNick = { helixId: domain.helix_id, bpIndex: lo + Math.floor(len / 2), direction: domain.direction }
          }
        }
      }

      _pendingNick = bestNick
      overlay.style.display = 'flex'
    })
  })()

  // ── Physics client (XPBD streaming, Phase 5) ─────────────────────────────
  const physicsClient = initPhysicsClient({
    onPositions: (updates) => {
      designRenderer.applyPhysicsPositions(updates)
    },
    onStatus: (msg) => {
      console.debug('[Physics]', msg)
    },
  })

  function _togglePhysics() {
    const { physicsMode, currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return

    if (!physicsMode) {
      // Enable: connect WebSocket, start streaming yellow overlay.
      store.setState({ physicsMode: true })
      physicsClient.start()
      document.getElementById('physics-controls')?.classList.add('visible')
      document.getElementById('mode-indicator').textContent =
        'PHYSICS MODE — XPBD thermal motion active  ·  [P] to toggle off'
    } else {
      // Disable: stop streaming, clear overlay.
      physicsClient.stop()
      designRenderer.applyPhysicsPositions(null)
      store.setState({ physicsMode: false })
      document.getElementById('physics-controls')?.classList.remove('visible')
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
  }

  // ── Physics sliders ──────────────────────────────────────────────────────────
  ;(function _initPhysicsSliders() {
    const sliders = [
      { sliderId: 'pl-noise', valId: 'pv-noise', param: 'noise_amplitude',   fmt: v => v.toFixed(3) },
      { sliderId: 'pl-bond',  valId: 'pv-bond',  param: 'bond_stiffness',    fmt: v => v.toFixed(2) },
      { sliderId: 'pl-bend',  valId: 'pv-bend',  param: 'bend_stiffness',    fmt: v => v.toFixed(2) },
      { sliderId: 'pl-bp',    valId: 'pv-bp',    param: 'bp_stiffness',      fmt: v => v.toFixed(2) },
      { sliderId: 'pl-stack', valId: 'pv-stack', param: 'stacking_stiffness', fmt: v => v.toFixed(2) },
      { sliderId: 'pl-elec',  valId: 'pv-elec',  param: 'elec_amplitude',    fmt: v => v.toFixed(3) },
      { sliderId: 'pl-debye', valId: 'pv-debye', param: 'debye_length',      fmt: v => v.toFixed(2) },
    ]
    for (const { sliderId, valId, param, fmt } of sliders) {
      const sl  = document.getElementById(sliderId)
      const val = document.getElementById(valId)
      if (!sl || !val) continue
      sl.addEventListener('input', () => {
        const v = parseFloat(sl.value)
        val.textContent = fmt(v)
        physicsClient.updateParams({ [param]: v })
      })
    }
  })()

  // ── Force toggle buttons ──────────────────────────────────────────────────────
  // Each toggle enables/disables a physics constraint by zeroing its stiffness
  // or restoring the slider value.  Slider remains editable when force is off.
  ;(function _initForceToggles() {
    const toggles = [
      { toggleId: 'ft-bond',  sliderId: 'pl-bond',  param: 'bond_stiffness' },
      { toggleId: 'ft-bend',  sliderId: 'pl-bend',  param: 'bend_stiffness' },
      { toggleId: 'ft-bp',    sliderId: 'pl-bp',    param: 'bp_stiffness' },
      { toggleId: 'ft-stack', sliderId: 'pl-stack', param: 'stacking_stiffness' },
      { toggleId: 'ft-elec',  sliderId: 'pl-elec',  param: 'elec_amplitude' },
    ]
    for (const { toggleId, sliderId, param } of toggles) {
      const btn = document.getElementById(toggleId)
      const sl  = document.getElementById(sliderId)
      if (!btn || !sl) continue

      btn.addEventListener('click', () => {
        const isOn = btn.classList.contains('on')
        if (isOn) {
          btn.classList.remove('on')
          physicsClient.updateParams({ [param]: 0 })
        } else {
          btn.classList.add('on')
          physicsClient.updateParams({ [param]: parseFloat(sl.value) })
        }
      })
    }
  })()

  // ── oxDNA controls ───────────────────────────────────────────────────────────
  ;(function _initOxdnaControls() {
    const stepsSlider = document.getElementById('pl-oxdna-steps')
    const stepsVal    = document.getElementById('pv-oxdna-steps')
    const statusEl    = document.getElementById('oxdna-status')
    const exportBtn   = document.getElementById('btn-oxdna-export')
    const runBtn      = document.getElementById('btn-oxdna-run')

    stepsSlider?.addEventListener('input', () => {
      stepsVal.textContent = stepsSlider.value
    })

    exportBtn?.addEventListener('click', async () => {
      statusEl.textContent = 'Preparing ZIP…'
      exportBtn.disabled = true
      const ok = await api.exportOxdna()
      statusEl.textContent = ok ? 'ZIP downloaded.' : 'Export failed — check console.'
      exportBtn.disabled = false
    })

    runBtn?.addEventListener('click', async () => {
      const steps = parseInt(stepsSlider?.value ?? '10000', 10)
      statusEl.textContent = `Running oxDNA (${steps} steps)…`
      runBtn.disabled = true
      const result = await api.runOxdna(steps)
      runBtn.disabled = false
      if (!result) {
        statusEl.textContent = 'Request failed — is design loaded?'
        return
      }
      if (!result.available) {
        statusEl.textContent = 'Not installed. Use Export ZIP instead.'
        return
      }
      statusEl.textContent = result.message
      if (result.positions?.length) {
        designRenderer.applyPhysicsPositions(result.positions)
      }
    })
  })()

  // ── Bend/Twist deformation editor ──────────────────────────────────────────
  initDeformationEditor(scene, camera, canvas, controls, designRenderer, () => {
    // onExit: restore mode indicator
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  })

  initBendTwistPopup({
    onPreview: (params) => previewDeformation(params),
    onConfirm: async (params) => {
      await confirmDeformation(params)
      _watchDeformState()
    },
    onCancel: () => {
      cancelDeformation()
      _watchDeformState()
    },
  })

  // Watch deformation editor state — open/close popup when state changes
  let _prevDeformState = DEFORM_STATES.IDLE
  function _watchDeformState() {
    const st = getDeformState()
    if (st === _prevDeformState) return
    _prevDeformState = st
    if (st === DEFORM_STATES.BOTH) {
      openDeformPopup(getDeformToolType() ?? 'twist')
    } else {
      closeDeformPopup()
    }
  }

  // ── Crossover markers ───────────────────────────────────────────────────────
  const crossoverMarkers = initCrossoverMarkers(scene, camera, canvas)

  // ── Slice plane ─────────────────────────────────────────────────────────────
  const slicePlane = initSlicePlane(scene, camera, canvas, controls, {
    onExtrude: async ({ cells, lengthBp, plane, offsetNm, continuationMode, deformedFrame }) => {
      let result
      if (deformedFrame) {
        result = await api.addBundleDeformedContinuation({ cells, lengthBp, plane, frame: deformedFrame })
      } else if (continuationMode) {
        result = await api.addBundleContinuation({ cells, lengthBp, plane, offsetNm })
      } else {
        result = await api.addBundleSegment({ cells, lengthBp, plane, offsetNm })
      }
      if (!result) {
        const err = store.getState().lastError
        throw new Error(err?.message ?? 'Segment extrusion failed')
      }
      slicePlane.hide()
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    },
    getDesign:    () => store.getState().currentDesign,
    getHelixAxes: () => store.getState().currentHelixAxes,
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

  // ── Blunt end sidebar panel ──────────────────────────────────────────────────
  const _bluntPanel        = document.getElementById('blunt-panel-actions')
  const _bluntPanelEmpty   = document.getElementById('blunt-panel-empty')
  const _bluntPanelInfo    = document.getElementById('blunt-panel-info')
  let   _bluntInfo         = null  // { plane, offsetNm, helixId, sourceBp, hasDeformations }

  function _showBluntPanel(info) {
    _bluntInfo = info
    if (_bluntPanelEmpty)  _bluntPanelEmpty.style.display  = 'none'
    if (_bluntPanelInfo)   _bluntPanelInfo.textContent = `helix ${info.helixId}  bp ${info.sourceBp}`
    if (_bluntPanel)       _bluntPanel.style.display = 'block'
  }
  function _hideBluntPanel() {
    _bluntInfo = null
    if (_bluntPanel)      _bluntPanel.style.display      = 'none'
    if (_bluntPanelEmpty) _bluntPanelEmpty.style.display = ''
  }

  // ── Blunt end right-click context menu ──────────────────────────────────────
  const _bluntCtx = document.getElementById('blunt-end-ctx-menu')
  let _bluntCtxInfo = null  // separate state for the floating ctx menu

  function _showBluntCtx(x, y, info) {
    _bluntCtxInfo = info
    if (_bluntCtx) {
      _bluntCtx.style.left = `${x}px`
      _bluntCtx.style.top  = `${y}px`
      _bluntCtx.style.display = 'block'
    }
  }
  function _hideBluntCtx() {
    if (_bluntCtx) _bluntCtx.style.display = 'none'
    _bluntCtxInfo = null
  }

  document.addEventListener('pointerdown', e => {
    if (_bluntCtx?.style.display !== 'none' && !_bluntCtx.contains(e.target)) _hideBluntCtx()
  })

  async function _bluntExtrude() {
    const info = _bluntInfo   // capture before _hideBluntPanel nulls it
    _hideBluntPanel()
    if (!info) return
    const { plane, offsetNm, helixId, sourceBp, hasDeformations } = info
    store.setState({ currentPlane: plane })
    if (hasDeformations) {
      const frame = await api.getDeformedFrame(sourceBp, helixId)
      if (frame) {
        slicePlane.showDeformed(frame, { plane, continuation: true })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
        return
      }
    }
    slicePlane.show(plane, offsetNm, true)
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
  }

  document.getElementById('blunt-extrude-btn')?.addEventListener('click', _bluntExtrude)
  document.getElementById('blunt-bend-btn')?.addEventListener('click', () => {
    const info = _bluntInfo
    _hideBluntPanel()
    if (!info) return
    startToolAtBp('bend', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'BEND — plane A set · click second plane to define segment · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn')?.addEventListener('click', () => {
    const info = _bluntInfo
    _hideBluntPanel()
    if (!info) return
    startToolAtBp('twist', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'TWIST — plane A set · click second plane to define segment · Esc to cancel'
  })

  // ── Context menu button wiring (right-click blunt end) ────────────────────
  document.getElementById('blunt-extrude-btn-ctx')?.addEventListener('click', async () => {
    const info = _bluntCtxInfo
    _hideBluntCtx()
    if (!info) return
    const { plane, offsetNm, helixId, sourceBp, hasDeformations } = info
    store.setState({ currentPlane: plane })
    if (hasDeformations) {
      const frame = await api.getDeformedFrame(sourceBp, helixId)
      if (frame) {
        slicePlane.showDeformed(frame, { plane, continuation: true })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
        return
      }
    }
    slicePlane.show(plane, offsetNm, true)
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
  })
  document.getElementById('blunt-bend-btn-ctx')?.addEventListener('click', () => {
    const info = _bluntCtxInfo
    _hideBluntCtx()
    if (!info) return
    startToolAtBp('bend', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'BEND — plane A set · click second plane to define segment · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn-ctx')?.addEventListener('click', () => {
    const info = _bluntCtxInfo
    _hideBluntCtx()
    if (!info) return
    startToolAtBp('twist', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'TWIST — plane A set · click second plane to define segment · Esc to cancel'
  })

  // ── Blunt end indicators ─────────────────────────────────────────────────────
  const bluntEnds = initBluntEnds(scene, camera, canvas, {
    onBluntEndClick: ({ plane, offsetNm, helixId, sourceBp, hasDeformations }) => {
      _showBluntPanel({ plane, offsetNm, helixId, sourceBp, hasDeformations })
    },
    onBluntEndRightClick: ({ plane, offsetNm, helixId, sourceBp, hasDeformations, clientX, clientY }) => {
      _showBluntCtx(clientX, clientY, { plane, offsetNm, helixId, sourceBp, hasDeformations })
    },
    isDisabled: () => slicePlane.isVisible() || isDeformActive(),
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
    bluntEnds.clear()
    crossoverMarkers.clear()
    // Stop physics on new design.
    if (store.getState().physicsMode) {
      physicsClient.stop()
      designRenderer.applyPhysicsPositions(null)
    }
    document.getElementById('physics-controls')?.classList.remove('visible')
    store.setState({
      currentDesign: null, currentGeometry: null, currentHelixAxes: null,
      validationReport: null, currentPlane: null, strandColors: {},
      physicsMode: false, physicsPositions: null,
    })
    workspace.show()
    camera.position.set(6, 3, 18)
    controls.target.set(6, 3, 0)
    controls.update()
    await api.createDesign('Untitled')
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
      // Topology changed — reset physics to pick up new strand connectivity.
      if (store.getState().physicsMode) physicsClient.reset()
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

  // ── Autostaple progress helpers ────────────────────────────────────────────
  const _apProgress = document.getElementById('autostaple-progress')
  const _apFill     = document.getElementById('autostaple-progress-fill')
  const _apLabel    = document.getElementById('autostaple-progress-label')

  function _showProgress(label) {
    _apLabel.textContent = label
    _apFill.style.width  = '0%'
    _apProgress.classList.add('visible')
  }
  function _updateProgress(step, total, label) {
    _apFill.style.width  = `${Math.round((step / total) * 100)}%`
    _apLabel.textContent = label ?? `${step} / ${total}`
  }
  function _hideProgress() {
    _apProgress.classList.remove('visible')
  }

  // Live-preview toggle state (persisted in localStorage)
  let _livePreview = localStorage.getItem('autostaple-live') === '1'
  const _liveBtn = document.getElementById('menu-edit-autostaple-live')
  if (_liveBtn) {
    if (_livePreview) _liveBtn.classList.add('active')
    _liveBtn.addEventListener('click', () => {
      _livePreview = !_livePreview
      localStorage.setItem('autostaple-live', _livePreview ? '1' : '0')
      _liveBtn.classList.toggle('active', _livePreview)
    })
  }

  document.getElementById('menu-edit-autostaple')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }

    if (_livePreview) {
      // ── Step-by-step mode: 2-stage with granular progress ───────────────
      // Stage 1: compute crossover plan + apply step-by-step
      const planResult = await api.getAutostapleplan()
      if (!planResult) {
        const err = store.getState().lastError
        alert('Autostaple failed: ' + (err?.message ?? 'unknown error'))
        return
      }
      const { plan } = planResult
      if (plan.length === 0) { alert('No crossovers to place.'); return }

      _showProgress(`Stage 1/2 — Placing crossover 0 / ${plan.length}`)
      for (let i = 0; i < plan.length; i++) {
        await api.applyAutostapleStep(plan[i])
        _updateProgress(i + 1, plan.length,
          `Stage 1/2 — Placing crossover ${i + 1} / ${plan.length}`)
      }

      // Stage 2: compute nick plan + apply nicks step-by-step
      const nickResult = await api.getAutostapleNicksPlan()
      if (!nickResult || nickResult.count === 0) {
        _hideProgress()
        return
      }
      const { nicks } = nickResult
      _updateProgress(0, nicks.length, `Stage 2/2 — Adding nick 0 / ${nicks.length}`)
      for (let i = 0; i < nicks.length; i++) {
        await api.addNick({
          helixId:  nicks[i].helix_id,
          bpIndex:  nicks[i].bp_index,
          direction: nicks[i].direction,
        })
        _updateProgress(i + 1, nicks.length,
          `Stage 2/2 — Adding nick ${i + 1} / ${nicks.length}`)
      }
      _hideProgress()
    } else {
      // ── Batch mode: 2-stage with labelled indeterminate bars ────────────
      // Stage 1: place crossovers (~60% of total time)
      _showProgress('Stage 1/2 — Placing crossovers…')
      _apFill.style.transition = 'none'
      _apFill.style.width = '0%'
      void _apFill.offsetWidth
      _apFill.style.transition = 'width 1.5s ease-out'
      _apFill.style.width = '55%'

      const result = await api.addAutostaple()

      // Snap to 100% then hide
      _apFill.style.transition = 'width 0.2s ease'
      _apFill.style.width = '100%'
      await new Promise(r => setTimeout(r, 250))
      _hideProgress()

      if (!result) {
        const err = store.getState().lastError
        alert('Autostaple failed: ' + (err?.message ?? 'unknown error'))
      }
    }
  })

  // ── Tools menu (Bend / Twist) ─────────────────────────────────────────────
  document.getElementById('menu-tools-twist')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    startTool('twist')
    document.getElementById('mode-indicator').textContent =
      'TWIST — click plane A (fixed), then plane B · Esc to exit'
  })

  document.getElementById('menu-tools-bend')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    startTool('bend')
    document.getElementById('mode-indicator').textContent =
      'BEND — click plane A (fixed), then plane B · Esc to exit'
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

  document.getElementById('menu-view-physics')?.addEventListener('click', _togglePhysics)

  // ── Selection filter toggles ──────────────────────────────────────────────────
  for (const key of ['scaffold', 'staples', 'bluntEnds', 'crossovers']) {
    const toggle = document.getElementById(`sel-toggle-${key}`)
    const row    = document.getElementById(`sel-row-${key}`)
    if (!toggle || !row) continue
    const _update = () => {
      const { selectableTypes, deformToolActive } = store.getState()
      const on = selectableTypes[key]
      // Dim and show as off when deformation tool is active (all selection blocked)
      toggle.classList.toggle('on', on && !deformToolActive)
      row.style.opacity       = deformToolActive ? '0.35' : '1'
      row.style.pointerEvents = deformToolActive ? 'none' : ''
      row.title = deformToolActive ? 'Selection disabled while deformation tool is active' : ''
    }
    row.addEventListener('click', () => {
      if (store.getState().deformToolActive) return
      const st = store.getState().selectableTypes
      store.setState({ selectableTypes: { ...st, [key]: !st[key] } })
      _update()
    })
    store.subscribe(() => _update())
  }

  // ── Nucleotide Slab collapse toggle ──────────────────────────────────────────
  ;(function () {
    const heading = document.getElementById('slab-heading')
    const body    = document.getElementById('slab-body')
    const arrow   = document.getElementById('slab-arrow')
    if (!heading || !body || !arrow) return
    heading.addEventListener('click', () => {
      const open = body.style.display !== 'none'
      body.style.display = open ? 'none' : 'block'
      arrow.textContent  = open ? '▶' : '▼'
    })
  })()

  // ── Orbit safety ──────────────────────────────────────────────────────────────
  // Re-enable controls whenever no buttons are held and we are not in bead-drag mode.
  document.addEventListener('pointerup', e => {
    if (e.button === 0 && e.buttons === 0 && !isDeformActive()) {
      controls.enabled = true
    }
  }, { capture: true })
  canvas.addEventListener('pointercancel', () => {
    if (!isDeformActive()) controls.enabled = true
  })

  // Orbit relay: when the left button is released OUTSIDE the canvas and the deform
  // tool is NOT active, forward a synthetic pointerup to the canvas so OrbitControls
  // can clean up its drag state. We skip this relay when deform is active because
  // our capture-phase handlers already manage pointer events correctly in that context,
  // and an extra synthetic event would only confuse things.
  document.addEventListener('pointerup', e => {
    if (e.button !== 0) return
    if (isDeformActive()) return          // deform tool manages its own state
    if (canvas.contains(e.target)) return // already on canvas — no relay needed
    canvas.dispatchEvent(new PointerEvent('pointerup', {
      pointerId:  e.pointerId,
      button:     0,
      buttons:    e.buttons,
      clientX:    e.clientX,
      clientY:    e.clientY,
      bubbles:    false,
      cancelable: false,
    }))
  })

  // ── Orbit debug overlay (?orbit_debug=1) ──────────────────────────────────────
  // Shows real-time state of everything that touches orbit controls.
  // Useful for diagnosing stuck-rotation bugs. Toggle with Alt+O.
  ;(function _initOrbitDebug() {
    const ORBIT_DEBUG = new URLSearchParams(window.location.search).has('orbit_debug')
    const panel = document.createElement('div')
    panel.id = 'orbit-debug'
    panel.style.cssText = [
      'display:none', 'position:fixed', 'bottom:14px', 'right:14px',
      'background:rgba(13,17,23,0.92)', 'border:1px solid #30363d',
      'border-radius:4px', 'padding:8px 12px', 'font-size:10px',
      'font-family:monospace', 'color:#8b949e', 'z-index:500',
      'pointer-events:none', 'min-width:220px', 'line-height:1.7',
    ].join(';')
    document.body.appendChild(panel)
    if (ORBIT_DEBUG) panel.style.display = 'block'

    let _lastEvt = '—'
    const _evtTypes = ['pointerdown', 'pointerup', 'pointermove', 'pointercancel']
    _evtTypes.forEach(type => {
      document.addEventListener(type, e => {
        if (e.button === undefined || e.button <= 0) {
          const src = canvas.contains(e.target) ? 'canvas' : e.target?.id || e.target?.tagName || '?'
          _lastEvt = `${type} btn=${e.button} btns=${e.buttons} src=${src}`
        }
      }, { capture: true })
    })

    let _visible = ORBIT_DEBUG
    document.addEventListener('keydown', e => {
      if (e.altKey && (e.key === 'o' || e.key === 'O')) {
        _visible = !_visible
        panel.style.display = _visible ? 'block' : 'none'
      }
    })

    // Refresh at 10 fps
    setInterval(() => {
      if (!_visible) return
      const deformState  = getDeformState()
      const deformActive = isDeformActive()
      const c = controls
      panel.innerHTML = [
        `<b style="color:#e6edf3">Orbit Debug</b>  <span style="color:#484f58">(Alt+O to hide)</span>`,
        `controls.enabled: <span style="color:${c.enabled ? '#3fb950' : '#f85149'}">${c.enabled}</span>`,
        `deformActive: <span style="color:${deformActive ? '#ffdd00' : '#484f58'}">${deformActive} (${deformState})</span>`,
        `_deformConsumedDown: <span style="color:${_deformConsumedDown ? '#ffdd00' : '#484f58'}">${_deformConsumedDown}</span>`,
        `crossovers: <span style="color:${deformActive ? '#f85149' : '#3fb950'}">${deformActive ? 'BLOCKED (deform active)' : 'enabled'}</span>`,
        `physicsMode: ${store.getState().physicsMode}`,
        `last ptr evt: <span style="color:#79c0ff">${_lastEvt}</span>`,
      ].join('<br>')
    }, 100)
  })()

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

    // 'P' — toggle physics mode
    if ((e.key === 'p' || e.key === 'P') && !inInput) {
      _togglePhysics()
      return
    }

    // Escape — exit deformation tool, crossover mode, or slice plane
    if (e.key === 'Escape') {
      if (isDeformActive()) {
        deformEscape()
        _watchDeformState()
        if (!isDeformActive()) {
          document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
        }
      } else if (crossoverMarkers.isActive()) {
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

  const { runScript } = createScriptRunner({
    slicePlane, bluntEnds, crossoverMarkers, workspace, camera, controls,
  })
  // ── Paste Script modal ───────────────────────────────────────────────────────
  const pasteOverlay  = document.getElementById('paste-script-overlay')
  const pasteInput    = document.getElementById('paste-script-input')
  const pasteError    = document.getElementById('paste-script-error')
  const pasteRunBtn   = document.getElementById('paste-script-run')
  const pasteCancelBtn = document.getElementById('paste-script-cancel')

  function _openPasteModal() {
    pasteError.textContent = ''
    pasteOverlay.style.display = 'flex'
    pasteInput.focus()
  }
  function _closePasteModal() {
    pasteOverlay.style.display = 'none'
  }

  document.getElementById('menu-file-paste-script')?.addEventListener('click', _openPasteModal)
  pasteCancelBtn?.addEventListener('click', _closePasteModal)
  pasteOverlay?.addEventListener('click', e => { if (e.target === pasteOverlay) _closePasteModal() })

  pasteRunBtn?.addEventListener('click', async () => {
    pasteError.textContent = ''
    let script
    try {
      script = JSON.parse(pasteInput.value)
    } catch (e) {
      pasteError.textContent = `JSON parse error: ${e.message}`
      return
    }
    if (!Array.isArray(script.steps)) {
      pasteError.textContent = 'Script must have a "steps" array.'
      return
    }
    _closePasteModal()
    try {
      await runScript(script)
    } catch (err) {
      console.error('Paste script error:', err)
      alert(`Script failed: ${err.message}`)
    }
  })

  pasteInput?.addEventListener('keydown', e => {
    if (e.key === 'Escape') _closePasteModal()
  })

  // ── Centroid orbit tracking ───────────────────────────────────────────────────
  // When geometry first appears, orbit about its centroid.
  // When a selection changes, orbit about the selected strand/nucleotide centroid.
  ;(function _initCentroidOrbit() {
    function _geomCentroid(geometry) {
      if (!geometry?.length) return null
      let x = 0, y = 0, z = 0
      for (const nuc of geometry) {
        const [nx, ny, nz] = nuc.backbone_position
        x += nx; y += ny; z += nz
      }
      const n = geometry.length
      return new THREE.Vector3(x / n, y / n, z / n)
    }

    function _strandCentroid(strandId, geometry) {
      const nucs = geometry?.filter(n => n.strand_id === strandId)
      return nucs?.length ? _geomCentroid(nucs) : null
    }

    store.subscribe((newState, prevState) => {
      // Snap orbit target to design centroid when geometry first appears.
      if (!prevState.currentGeometry && newState.currentGeometry?.length) {
        const c = _geomCentroid(newState.currentGeometry)
        if (c) { controls.target.copy(c); controls.update() }
        return
      }

      // Snap orbit target when selection changes.
      if (newState.selectedObject === prevState.selectedObject) return
      const obj = newState.selectedObject
      const geom = newState.currentGeometry
      if (!obj || !geom) return

      let target = null
      if (obj.type === 'nucleotide') {
        const [x, y, z] = obj.data.backbone_position
        target = new THREE.Vector3(x, y, z)
      } else {
        const sid = obj.data?.strand_id ?? obj.data?.fromNuc?.strand_id
        if (sid) target = _strandCentroid(sid, geom)
      }
      if (target) { controls.target.copy(target); controls.update() }
    })
  })()

  // ── Strand length histogram ──────────────────────────────────────────────────
  // Collapsible canvas histogram of staple lengths.  Outlier bars (< 18 or > 50 nt)
  // are red; clicking any bar selects and zooms to the first matching strand.
  ;(function _initStrandHistogram() {
    const heading  = document.getElementById('strand-hist-heading')
    const arrow    = document.getElementById('strand-hist-arrow')
    const body     = document.getElementById('strand-hist-body')
    const canvas   = document.getElementById('strand-hist-canvas')
    const tooltip  = document.getElementById('strand-hist-tooltip')
    const summary  = document.getElementById('strand-hist-summary')
    if (!heading || !canvas) return

    let _expanded = false
    let _barData  = []  // [{x, w, strandIds, length, color}] — hit areas

    heading.addEventListener('click', () => {
      _expanded = !_expanded
      body.style.display = _expanded ? 'block' : 'none'
      arrow.textContent = _expanded ? '▼' : '▶'
      if (_expanded) _redraw(store.getState().currentDesign)
    })

    function _strandLength(strand) {
      let t = 0
      for (const d of strand.domains) t += Math.abs(d.end_bp - d.start_bp) + 1
      return t
    }

    function _redraw(design) {
      const ctx = canvas.getContext('2d')
      const W   = canvas.width
      const H   = canvas.height
      ctx.clearRect(0, 0, W, H)
      _barData = []

      if (!design?.strands?.length) {
        summary.textContent = 'No design loaded.'
        return
      }

      // Collect staple lengths grouped by length value
      const staples = design.strands.filter(s => !s.is_scaffold)
      if (staples.length === 0) { summary.textContent = 'No staple strands.'; return }

      const byLength = new Map()
      for (const s of staples) {
        const len = _strandLength(s)
        if (!byLength.has(len)) byLength.set(len, [])
        byLength.get(len).push(s.id)
      }

      const lengths  = [...byLength.keys()].sort((a, b) => a - b)
      const minLen   = lengths[0]
      const maxLen   = lengths[lengths.length - 1]
      const maxCount = Math.max(...[...byLength.values()].map(v => v.length))

      // Count in-range
      const nOk   = staples.filter(s => { const l = _strandLength(s); return l >= 18 && l <= 50 }).length
      const nShort = staples.filter(s => _strandLength(s) < 18).length
      const nLong  = staples.filter(s => _strandLength(s) > 50).length
      const pct    = Math.round(100 * nOk / staples.length)
      summary.textContent = `${staples.length} staples · ${pct}% in 18–50 nt`
        + (nShort ? ` · ${nShort} short` : '')
        + (nLong  ? ` · ${nLong} long`   : '')

      const nBins  = lengths.length
      const pad    = 4
      const barW   = Math.max(2, Math.floor((W - 2 * pad) / nBins) - 1)
      const totalW = (barW + 1) * nBins
      const startX = pad + Math.floor((W - 2 * pad - totalW) / 2)

      // Draw canonical range background
      if (nBins > 1) {
        const xRange18 = startX + (18 >= minLen ? (18 - minLen) * (barW + 1) : 0)
        const xRange50 = startX + (50 <= maxLen ? (50 - minLen + 1) * (barW + 1) : W - 2 * pad)
        ctx.fillStyle = 'rgba(61,220,132,0.06)'
        ctx.fillRect(Math.max(pad, xRange18), 0, xRange50 - xRange18, H - 1)
      }

      // Draw bars
      for (let i = 0; i < nBins; i++) {
        const len    = lengths[i]
        const count  = byLength.get(len).length
        const x      = startX + i * (barW + 1)
        const barH   = Math.max(2, Math.round((count / maxCount) * (H - 14)))
        const y      = H - barH - 1
        const isOut  = len < 18 || len > 50

        ctx.fillStyle = isOut ? '#ff6b6b' : '#3ddc84'
        ctx.fillRect(x, y, barW, barH)

        _barData.push({ x, w: barW, y, h: barH, strandIds: byLength.get(len), length: len, isOut })
      }

      // X-axis ticks for 18 and 50
      ctx.fillStyle = '#484f58'
      ctx.font = '8px monospace'
      ctx.textAlign = 'center'
      for (const tick of [18, 50]) {
        if (tick >= minLen && tick <= maxLen) {
          const xi = startX + (tick - minLen) * (barW + 1) + barW / 2
          ctx.fillText(tick, xi, H)
        }
      }
    }

    // Click: select first strand of the clicked bar and zoom to it
    canvas.addEventListener('click', e => {
      const rect = canvas.getBoundingClientRect()
      const scaleX = canvas.width / rect.width
      const mx = (e.clientX - rect.left) * scaleX

      for (const bar of _barData) {
        if (mx >= bar.x && mx <= bar.x + bar.w) {
          const strandId = bar.strandIds[0]
          tooltip.textContent = `${bar.length} nt · ${bar.strandIds.length} strand(s) — click to select`

          // Select the strand
          store.setState({ selectedObject: { type: 'strand', id: strandId, data: { strand_id: strandId } } })

          // Zoom: move camera closer to the strand centroid
          const geom = store.getState().currentGeometry
          if (geom) {
            const nucs = geom.filter(n => n.strand_id === strandId)
            if (nucs.length) {
              let sx = 0, sy = 0, sz = 0
              for (const n of nucs) { sx += n.backbone_position[0]; sy += n.backbone_position[1]; sz += n.backbone_position[2] }
              const cx = sx / nucs.length, cy = sy / nucs.length, cz = sz / nucs.length
              const current = camera.position.clone()
              const tgt = new THREE.Vector3(cx, cy, cz)
              // Move camera to 8 nm from the centroid in its current direction
              const dir = current.clone().sub(tgt).normalize()
              camera.position.copy(tgt.clone().add(dir.multiplyScalar(8)))
              controls.target.copy(tgt)
              controls.update()
            }
          }
          return
        }
      }
      tooltip.textContent = ''
    })

    // Tooltip on hover
    canvas.addEventListener('mousemove', e => {
      const rect = canvas.getBoundingClientRect()
      const scaleX = canvas.width / rect.width
      const mx = (e.clientX - rect.left) * scaleX
      for (const bar of _barData) {
        if (mx >= bar.x && mx <= bar.x + bar.w) {
          tooltip.textContent = `${bar.length} nt · ${bar.strandIds.length} strand(s)${bar.isOut ? ' ⚠ out of range' : ''}`
          return
        }
      }
      tooltip.textContent = ''
    })
    canvas.addEventListener('mouseleave', () => { tooltip.textContent = '' })

    // Redraw when design changes and histogram is visible
    store.subscribe((newState, prevState) => {
      if (_expanded && newState.currentDesign !== prevState.currentDesign) {
        _redraw(newState.currentDesign)
      }
    })
  })()

  // ── AutoScaffold ──────────────────────────────────────────────────────────────
  document.getElementById('menu-edit-autoscaffold')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }

    _showProgress('AutoScaffold — routing scaffold path…')
    _apFill.style.transition = 'none'
    _apFill.style.width = '0%'
    void _apFill.offsetWidth
    _apFill.style.transition = 'width 2s ease-out'
    _apFill.style.width = '80%'

    const result = await api.autoScaffold()

    _apFill.style.transition = 'width 0.2s ease'
    _apFill.style.width = '100%'
    await new Promise(r => setTimeout(r, 250))
    _hideProgress()

    if (!result) {
      const err = store.getState().lastError
      alert('AutoScaffold failed: ' + (err?.message ?? 'unknown error'))
    }
  })

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

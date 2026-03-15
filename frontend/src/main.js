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
// TODO(refactor): crossover_markers.js — delete when confirmed unused
// import { initCrossoverMarkers }      from './scene/crossover_markers.js'
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
         handlePointerUp   as deformPointerUp,
         handleEscape as deformEscape,
         exitTool as deformExitTool,
         confirmDeformation, cancelDeformation, previewDeformation,
         getState as getDeformState, getToolType as getDeformToolType,
         STATES as DEFORM_STATES,
       } from './scene/deformation_editor.js'
import { initBendTwistPopup, openPopup as openDeformPopup,
         closePopup as closeDeformPopup,
       } from './ui/bend_twist_popup.js'
import { initUnfoldView }          from './scene/unfold_view.js'
import { initDeformView }          from './scene/deform_view.js'
import { initLoopSkipHighlight }   from './scene/loop_skip_highlight.js'
import { initCrossSectionMinimap } from './scene/cross_section_minimap.js'
import { initDebugOverlay }        from './scene/debug_overlay.js'

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
  const { scene, camera, controls } = initScene(canvas)

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
    if (isDeformActive()) deformPointerUp()   // always clean up bead drag before blocking
    if (_deformConsumedDown && e.button === 0) {
      _deformConsumedDown = false
      e.stopImmediatePropagation()
    }
  }, { capture: true })

  // ── Selection manager ───────────────────────────────────────────────────────
  const selectionManager = initSelectionManager(canvas, camera, designRenderer, {
    onNick: async ({ helixId, bpIndex, direction }) => {
      const result = await api.addNick({ helixId, bpIndex, direction })
      if (!result) {
        const err = store.getState().lastError
        console.error('Nick failed:', err?.message)
      }
    },
    // Lazy getter — unfoldView is defined later in this init sequence.
    getUnfoldView: () => unfoldView,
    controls,
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
      bluntEnds?.applyPhysicsPositions(updates)
      if (loopSkipHighlight?.isVisible()) loopSkipHighlight.applyPhysicsPositions(updates)
    },
    onStatus: (msg) => {
      console.debug('[Physics]', msg)
    },
  })

  function _updatePhysicsPlayBtn() {
    const btn = document.getElementById('btn-physics-play')
    if (!btn) return
    const { physicsMode } = store.getState()
    if (physicsMode) {
      btn.textContent = '⏹ Stop'
      btn.style.background = '#6e2020'
      btn.style.borderColor = '#c94a4a'
    } else {
      btn.textContent = '▶ Play'
      btn.style.background = '#1f6feb'
      btn.style.borderColor = '#388bfd'
    }
  }

  function _stopPhysicsIfActive() {
    if (!store.getState().physicsMode) return
    physicsClient.stop()
    designRenderer.applyPhysicsPositions(null)
    // Re-apply deform lerp at the current t so the scene returns to the correct
    // view state (straight when deform is off, deformed when on).  This also
    // repositions blunt ends and loop/skip highlights via _applyLerp's fan-out.
    deformView.reapplyLerp()
    store.setState({ physicsMode: false })
  }

  function _togglePhysics() {
    const { physicsMode, currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return

    if (!physicsMode) {
      store.setState({ physicsMode: true })
      physicsClient.start({ useStraight: !store.getState().deformVisuActive })
      document.getElementById('mode-indicator').textContent =
        'PHYSICS MODE — XPBD thermal motion active  ·  [P] to toggle off'
    } else {
      _stopPhysicsIfActive()
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
    _updatePhysicsPlayBtn()
  }

  // ── Physics panel collapse toggle ─────────────────────────────────────────
  ;(function _initPhysicsCollapse() {
    const heading = document.getElementById('physics-heading')
    const body    = document.getElementById('physics-body')
    const arrow   = document.getElementById('physics-arrow')
    if (!heading || !body) return
    // Start collapsed
    body.style.display = 'none'
    arrow.textContent = '▶'
    heading.addEventListener('click', () => {
      const collapsed = body.style.display === 'none'
      body.style.display = collapsed ? 'block' : 'none'
      arrow.textContent  = collapsed ? '▼' : '▶'
    })
  })()

  // ── Physics sliders ──────────────────────────────────────────────────────────
  ;(function _initPhysicsSliders() {
    const sliders = [
      { sliderId: 'pl-noise', valId: 'pv-noise', param: 'noise_amplitude',   fmt: v => v.toFixed(3) },
      { sliderId: 'pl-bp',    valId: 'pv-bp',    param: 'bp_stiffness',      fmt: v => v.toFixed(2) },
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
      { toggleId: 'ft-bp',   sliderId: 'pl-bp',   param: 'bp_stiffness' },
      { toggleId: 'ft-elec', sliderId: 'pl-elec', param: 'elec_amplitude' },
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

  // ── Play button ───────────────────────────────────────────────────────────────
  document.getElementById('btn-physics-play')?.addEventListener('click', _togglePhysics)

  // ── Speed controls (+/−) ─────────────────────────────────────────────────────
  // Speed steps: 1×=20 substeps, 2×=40, 4×=80, 8×=160, ½×=10, ¼×=5
  const _SPEED_STEPS = [1, 2, 4, 8, 10, 20, 40]  // multipliers relative to base 5
  const _BASE_SUBSTEPS = 5
  let _speedIdx = 4  // default: 10 × 5 = 50 substeps — matches DEFAULT_SUBSTEPS_PER_FRAME

  function _applySpeed() {
    const mult = _SPEED_STEPS[_speedIdx]
    const substeps = mult * _BASE_SUBSTEPS
    const el = document.getElementById('pv-speed')
    if (el) el.textContent = mult >= 1 ? `×${mult}` : `½`
    physicsClient.updateParams({ substeps_per_frame: substeps })
  }

  document.getElementById('btn-physics-faster')?.addEventListener('click', () => {
    _speedIdx = Math.min(_SPEED_STEPS.length - 1, _speedIdx + 1)
    _applySpeed()
  })
  document.getElementById('btn-physics-slower')?.addEventListener('click', () => {
    _speedIdx = Math.max(0, _speedIdx - 1)
    _applySpeed()
  })

  // ── Reset to defaults button ──────────────────────────────────────────────────
  document.getElementById('btn-physics-defaults')?.addEventListener('click', () => {
    const defaults = {
      'pl-noise': { val: '0',    valId: 'pv-noise', param: 'noise_amplitude',   fmt: v => v.toFixed(3) },
      'pl-bp':    { val: '0.8',  valId: 'pv-bp',    param: 'bp_stiffness',      fmt: v => v.toFixed(2) },
      'pl-elec':  { val: '0',    valId: 'pv-elec',  param: 'elec_amplitude',    fmt: v => v.toFixed(3) },
      'pl-debye': { val: '0.8',  valId: 'pv-debye', param: 'debye_length',      fmt: v => v.toFixed(2) },
    }
    const params = {}
    for (const [sliderId, { val, valId, param, fmt }] of Object.entries(defaults)) {
      const sl = document.getElementById(sliderId)
      const vl = document.getElementById(valId)
      if (sl) sl.value = val
      const v = parseFloat(val)
      if (vl) vl.textContent = fmt(v)
      params[param] = v
    }
    physicsClient.updateParams(params)
    // Reset speed to default (index 4 → ×10 multiplier → 50 substeps)
    _speedIdx = 4
    _applySpeed()
    // Restore force toggles to 'on'
    for (const id of ['ft-bp','ft-elec']) {
      document.getElementById(id)?.classList.add('on')
    }
  })

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
  // TODO(refactor): crossover_markers disabled — replaced by multiselect+X workflow
  // const crossoverMarkers = initCrossoverMarkers(scene, camera, canvas)
  const crossoverMarkers = { dispose() {}, clear() {}, isActive: () => false, applyDeformLerp() {}, getMarkers: () => [] }

  // ── Force Crossover ──────────────────────────────────────────────────────────
  // Ctrl+click two backbone beads to select them, then press X to connect them
  // with a half-crossover regardless of physical distance.
  // Uses POST /design/half-crossover (no distance constraint in that endpoint).

  const _FC_COLOR    = 0xff8c00   // vivid orange — distinct from selection white / marker cyan
  const _fcRaycaster = new THREE.Raycaster()
  const _fcNdc       = new THREE.Vector2()
  let _fcBeads       = []         // [{entry, nuc}, ...] up to 2 picks
  let _fcHintActive  = false      // true while force-crossover text is shown

  function _fcUpdateHint() {
    const el = document.getElementById('mode-indicator')
    if (!el) return
    const n = _fcBeads.length
    if (n === 0) {
      if (_fcHintActive) {
        el.textContent = 'NADOC · WORKSPACE'
        _fcHintActive = false
      }
    } else if (n === 1) {
      el.textContent = 'FORCE CROSSOVER — Ctrl+click 2nd bead  ·  Esc to cancel'
      _fcHintActive = true
    } else {
      el.textContent = 'FORCE CROSSOVER — [X] to connect  ·  Esc to cancel'
      _fcHintActive = true
    }
  }

  function _fcRestoreEntry(item) {
    designRenderer.setEntryColor(item.entry, item.entry.defaultColor)
    designRenderer.setBeadScale(item.entry, 1.0)
    if (item.entry.instMesh.instanceColor)  item.entry.instMesh.instanceColor.needsUpdate  = true
    if (item.entry.instMesh.instanceMatrix) item.entry.instMesh.instanceMatrix.needsUpdate = true
  }

  function _fcHighlight(entry) {
    designRenderer.setEntryColor(entry, _FC_COLOR)
    designRenderer.setBeadScale(entry, 1.6)
    if (entry.instMesh.instanceColor)  entry.instMesh.instanceColor.needsUpdate  = true
    if (entry.instMesh.instanceMatrix) entry.instMesh.instanceMatrix.needsUpdate = true
  }

  function _fcClear() {
    for (const item of _fcBeads) _fcRestoreEntry(item)
    _fcBeads = []
    _fcUpdateHint()
  }

  // Ctrl+pointerdown — record start position to detect drag vs. click.
  // Also disable OrbitControls immediately so it never starts a drag gesture
  // that would be left open when the pointerup is intercepted below.
  let _fcDownPos = null
  canvas.addEventListener('pointerdown', e => {
    if (e.ctrlKey && e.button === 0) {
      _fcDownPos = { x: e.clientX, y: e.clientY }
      controls.enabled = false
    } else {
      _fcDownPos = null
    }
  }, { capture: true })

  // Ctrl+pointerup — intercept before selection manager and crossover markers.
  canvas.addEventListener('pointerup', e => {
    if (e.ctrlKey && e.button === 0) controls.enabled = true
    if (!e.ctrlKey || e.button !== 0) return
    if (_fcDownPos && Math.hypot(e.clientX - _fcDownPos.x, e.clientY - _fcDownPos.y) > 4) return
    _fcDownPos = null

    const rect = canvas.getBoundingClientRect()
    if (e.clientX > rect.right - 300) return   // inside the right panel

    _fcNdc.set(
      ((e.clientX - rect.left) / rect.width)  *  2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
    _fcRaycaster.setFromCamera(_fcNdc, camera)

    const backboneEntries = designRenderer.getBackboneEntries()
    const meshes = [...new Set(backboneEntries.map(be => be.instMesh))]
    const hits   = _fcRaycaster.intersectObjects(meshes)
    const hit    = hits.length ? hits[0] : null
    const entry  = hit
      ? backboneEntries.find(be => be.instMesh === hit.object && be.id === hit.instanceId)
      : null

    if (!entry || entry.nuc.is_scaffold) {
      // Ctrl+click on empty space or scaffold — cancel selection
      if (_fcBeads.length > 0) { _fcClear(); e.stopImmediatePropagation() }
      return
    }

    e.stopImmediatePropagation()   // prevent normal selection and crossover marker click

    // Toggle: Ctrl+click the same bead again to deselect it
    const existingIdx = _fcBeads.findIndex(b => b.entry === entry)
    if (existingIdx >= 0) {
      _fcRestoreEntry(_fcBeads[existingIdx])
      _fcBeads.splice(existingIdx, 1)
      _fcUpdateHint()
      return
    }

    // Slide window: if already have 2, drop the oldest
    if (_fcBeads.length >= 2) {
      _fcRestoreEntry(_fcBeads[0])
      _fcBeads.shift()
    }

    _fcHighlight(entry)
    _fcBeads.push({ entry, nuc: entry.nuc })
    _fcUpdateHint()
  }, { capture: true })

  // Clear stale entry references whenever the scene rebuilds
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry !== prevState.currentGeometry && _fcBeads.length > 0) {
      _fcBeads = []   // entries are stale after a rebuild — don't try to restore colours
      _fcUpdateHint()
    }
  })

  // ── 2D Unfold view ──────────────────────────────────────────────────────────
  // bluntEnds is initialized below; use a getter so unfoldView can call it lazily.
  const unfoldView = initUnfoldView(scene, designRenderer, () => bluntEnds, () => loopSkipHighlight)

  // ── Deformed geometry view ──────────────────────────────────────────────────
  const deformView = initDeformView(designRenderer, () => bluntEnds, () => crossoverMarkers, () => unfoldView, () => loopSkipHighlight)

  // ── Debug hover overlay ─────────────────────────────────────────────────────
  const debugOverlay = initDebugOverlay(canvas, camera, designRenderer, {
    getBluntEnds:        () => bluntEnds,
    getCrossoverMarkers: () => crossoverMarkers,
    getUnfoldView:       () => unfoldView,
  })

  // ── Loop/Skip highlight overlay ─────────────────────────────────────────────
  const loopSkipHighlight = initLoopSkipHighlight(scene)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign  === prevState.currentDesign) return
    if (loopSkipHighlight.isVisible()) {
      loopSkipHighlight.rebuild(newState.currentDesign, newState.currentGeometry, newState.currentHelixAxes)
    }
  })
  initCrossSectionMinimap(document.getElementById('viewport-container'))

  function _isUnfoldActive() { return store.getState().unfoldActive }

  function _toggleUnfold() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return
    if (isDeformActive()) return
    // Cannot enter unfold while deformed view is on AND the design has actual
    // deformations — if there are none, straight = deformed so it's safe to proceed.
    const hasDeformations = !!(currentDesign?.deformations?.length)
    if (!unfoldView.isActive() && deformView.isActive() && hasDeformations) return
    // Stop physics before entering unfold — the two modes are incompatible.
    if (!unfoldView.isActive()) _stopPhysicsIfActive()
    unfoldView.toggle()
    const active = unfoldView.isActive()
    if (!active && !deformView.isActive()) {
      deformView.activate()
      _setMenuToggle('menu-view-deform', true)
    }
    document.getElementById('mode-indicator').textContent = active
      ? '2D UNFOLD — helices stacked by label order · [U] to return to 3D'
      : 'NADOC · WORKSPACE'
  }

  async function _toggleDeformView() {
    if (isDeformActive()) return
    const { currentDesign } = store.getState()
    // Cannot turn off when there are no deformations — deformed = straight, toggle is meaningless.
    if (!currentDesign?.deformations?.length) return
    if (deformView.isActive()) {
      // Turn OFF: animate to straight geometry so user can compare before/after.
      deformView.deactivate()
      _setMenuToggle('menu-view-deform', false)
      document.getElementById('mode-indicator').textContent =
        'STRAIGHT VIEW — geometry without deformations · click Deformed View to return'
    } else {
      // Turn ON: animate back to deformed geometry.
      _stopPhysicsIfActive()
      if (unfoldView.isActive()) unfoldView.deactivate()
      await deformView.activate()
      _setMenuToggle('menu-view-deform', true)
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
  }

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
      // Append new helix IDs to the unfold order (preserving existing order).
      const existing = store.getState().unfoldHelixOrder ?? []
      const newIds   = cells.map(([row, col]) => `h_${plane}_${row}_${col}`)
      const toAdd    = newIds.filter(id => !existing.includes(id))
      if (toAdd.length) store.setState({ unfoldHelixOrder: [...existing, ...toAdd] })
      slicePlane.hide()
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    },
    getDesign:    () => store.getState().currentDesign,
    getHelixAxes: () => store.getState().currentHelixAxes,
  })

  function _toggleSlicePlane() {
    if (_isUnfoldActive()) return   // slice plane disabled in unfold mode
    if (slicePlane.isVisible()) {
      slicePlane.hide()
      _setMenuToggle('menu-view-slice', false)
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      return
    }
    const { currentDesign, currentPlane } = store.getState()
    if (!currentDesign || !currentPlane) return
    const offset = _bundleMaxOffset(currentDesign, currentPlane)
    slicePlane.show(currentPlane, offset)
    _setMenuToggle('menu-view-slice', true)
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
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    _stopPhysicsIfActive()
    startToolAtBp('bend', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'BEND — drag planes to adjust segment · apply in popup · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn')?.addEventListener('click', () => {
    const info = _bluntInfo
    _hideBluntPanel()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    _stopPhysicsIfActive()
    startToolAtBp('twist', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'TWIST — drag planes to adjust segment · apply in popup · Esc to cancel'
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
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    _stopPhysicsIfActive()
    startToolAtBp('bend', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'BEND — drag planes to adjust segment · apply in popup · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn-ctx')?.addEventListener('click', () => {
    const info = _bluntCtxInfo
    _hideBluntCtx()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    _stopPhysicsIfActive()
    startToolAtBp('twist', info.sourceBp)
    document.getElementById('mode-indicator').textContent =
      'TWIST — drag planes to adjust segment · apply in popup · Esc to cancel'
  })

  // ── Blunt end indicators ─────────────────────────────────────────────────────
  const bluntEnds = initBluntEnds(scene, camera, canvas, {
    onBluntEndClick: ({ plane, offsetNm, helixId, sourceBp, hasDeformations }) => {
      _showBluntPanel({ plane, offsetNm, helixId, sourceBp, hasDeformations })
    },
    onBluntEndRightClick: ({ plane, offsetNm, helixId, sourceBp, hasDeformations, clientX, clientY }) => {
      _showBluntCtx(clientX, clientY, { plane, offsetNm, helixId, sourceBp, hasDeformations })
    },
    isDisabled:   () => slicePlane.isVisible() || isDeformActive() || _isUnfoldActive(),
    getUnfoldView: () => unfoldView,
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
      // Also store helix creation order (selection order) for 2D unfold.
      const helixIds = cells.map(([row, col]) => `h_${plane}_${row}_${col}`)
      store.setState({ currentPlane: plane, unfoldHelixOrder: helixIds })
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

  // ── File open / save ─────────────────────────────────────────────────────────
  // Tracks the File System Access API file handle so Ctrl+S can overwrite
  // the same file without re-opening a dialog.  Null when no file is open or
  // when the browser doesn't support the File System Access API.
  let _fileHandle = null

  /** Clear per-file state (physics, slice plane, store) and return to workspace. */
  function _resetForNewDesign() {
    deformExitTool()
    // Deformed view stays ON after reset (it is always on by default).
    // If currently in straight view, reactivate before clearing state.
    if (!deformView.isActive()) deformView.activate()
    slicePlane.hide()
    bluntEnds.clear()
    crossoverMarkers.clear()
    _stopPhysicsIfActive()
    _updatePhysicsPlayBtn()
    _setMenuToggle('menu-view-slice', false)
    _setMenuToggle('menu-view-loop-skip', false)
    _loopSkipLegend.style.display = 'none'
    store.setState({
      currentDesign: null, currentGeometry: null, currentHelixAxes: null,
      validationReport: null, currentPlane: null, strandColors: {},
      physicsMode: false, physicsPositions: null,
      unfoldHelixOrder: null, unfoldActive: false,
      straightGeometry: null, straightHelixAxes: null,
    })
  }

  /** Read raw .nadoc JSON content from the user's file system.
   *  Uses the File System Access API if available (Chrome/Edge) so the handle
   *  can be kept for in-place saves; falls back to a plain <input type="file">.
   *  Returns { content, handle } or null if the user cancelled. */
  async function _pickOpenFile() {
    if ('showOpenFilePicker' in window) {
      let handles
      try {
        handles = await window.showOpenFilePicker({
          types: [{ description: 'NADOC Design', accept: { 'application/json': ['.nadoc'] } }],
          multiple: false,
        })
      } catch (e) {
        if (e.name === 'AbortError') return null
        throw e
      }
      const handle = handles[0]
      const file = await handle.getFile()
      return { content: await file.text(), handle }
    }
    // Fallback: hidden file input
    return new Promise(resolve => {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = '.nadoc,application/json'
      input.onchange = async () => {
        const file = input.files[0]
        if (!file) { resolve(null); return }
        resolve({ content: await file.text(), handle: null })
      }
      input.oncancel = () => resolve(null)
      input.click()
    })
  }

  /** Fetch the active design's .nadoc JSON from the server. */
  async function _getDesignContent() {
    const r = await fetch('/api/design/export')
    if (!r.ok) return null
    return r.text()
  }

  /** Save design to an existing file handle (in-place overwrite). */
  async function _saveToHandle(handle) {
    const content = await _getDesignContent()
    if (!content) { alert('Failed to read design from server.'); return false }
    try {
      const writable = await handle.createWritable()
      await writable.write(content)
      await writable.close()
    } catch (e) {
      alert(`Save failed: ${e.message}`)
      return false
    }
    return true
  }

  /** Show a Save As dialog (File System Access API or browser download fallback). */
  async function _saveAs() {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design to save.'); return }
    const suggestedName = `${currentDesign.metadata?.name ?? 'design'}.nadoc`
    if ('showSaveFilePicker' in window) {
      let handle
      try {
        handle = await window.showSaveFilePicker({
          suggestedName,
          types: [{ description: 'NADOC Design', accept: { 'application/json': ['.nadoc'] } }],
        })
      } catch (e) {
        if (e.name === 'AbortError') return
        throw e
      }
      const ok = await _saveToHandle(handle)
      if (ok) _fileHandle = handle
    } else {
      // Fallback: trigger the existing export download
      await api.exportDesign()
    }
  }

  // ── Fit-to-view ───────────────────────────────────────────────────────────────
  function _fitToView() {
    const root = designRenderer.getHelixCtrl()?.root
    if (!root) return
    const box = new THREE.Box3().expandByObject(root)
    if (box.isEmpty()) return
    const center = box.getCenter(new THREE.Vector3())
    const size   = box.getSize(new THREE.Vector3())
    const radius = Math.max(size.x, size.y, size.z) * 0.5
    // Distance required to fit the bounding sphere, with 15% padding
    const dist = (radius / Math.sin((camera.fov * 0.5) * Math.PI / 180)) * 1.15
    // Keep current viewing direction
    const dir = camera.position.clone().sub(controls.target).normalize()
    controls.target.copy(center)
    camera.position.copy(center).addScaledVector(dir, dist)
    controls.update()
  }

  // ── Menu bar ─────────────────────────────────────────────────────────────────
  document.getElementById('menu-file-new')?.addEventListener('click', async () => {
    _resetForNewDesign()
    _fileHandle = null
    workspace.show()
    camera.position.set(6, 3, 18)
    controls.target.set(6, 3, 0)
    controls.update()
    await api.createDesign('Untitled')
  })

  document.getElementById('menu-file-open')?.addEventListener('click', async () => {
    const picked = await _pickOpenFile()
    if (!picked) return
    _resetForNewDesign()
    const result = await api.importDesign(picked.content)
    if (!result) {
      alert('Failed to open design: ' + (store.getState().lastError?.message ?? 'Unknown error'))
      workspace.show()
      return
    }
    _fileHandle = picked.handle  // may be null (fallback path)
    workspace.hide()
  })

  document.getElementById('menu-file-save')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design to save.'); return }
    if (_fileHandle) {
      await _saveToHandle(_fileHandle)
    } else {
      await _saveAs()
    }
  })

  document.getElementById('menu-file-save-as')?.addEventListener('click', _saveAs)

  document.getElementById('menu-edit-undo')?.addEventListener('click', async () => {
    if (isDeformActive()) return
    const result = await api.undo()
    if (!result) {
      const err = store.getState().lastError
      if (err?.status === 404) alert('Nothing to undo.')
    } else {
      // Topology changed — reset physics to pick up new strand connectivity.
      if (store.getState().physicsMode) physicsClient.reset()
      const { currentDesign } = store.getState()
      // If we undid back to an empty design, return to workspace.
      if (!currentDesign?.helices?.length) {
        slicePlane.hide()
        workspace.show()
      }
      // If undo removed the last deformation and deformed view is OFF, restore it.
      if (!currentDesign?.deformations?.length && !deformView.isActive()) {
        await deformView.activate()
        _setMenuToggle('menu-view-deform', true)
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      }
    }
  })

  document.getElementById('menu-edit-redo')?.addEventListener('click', async () => {
    if (isDeformActive()) return
    const result = await api.redo()
    if (!result) {
      const err = store.getState().lastError
      if (err?.status === 404) alert('Nothing to redo.')
    }
  })

  // ── Operation progress popup helpers ──────────────────────────────────────
  const _apProgress = document.getElementById('op-progress')
  const _apFill     = document.getElementById('op-progress-fill')
  const _apLabel    = document.getElementById('op-progress-label')
  const _apHeader   = document.getElementById('op-progress-header')

  let _toastTimeout = null
  function _showToast(msg, durationMs = 2200) {
    let toast = document.getElementById('_toast_msg')
    if (!toast) {
      toast = document.createElement('div')
      toast.id = '_toast_msg'
      toast.style.cssText = [
        'position:fixed', 'top:44px', 'right:308px',
        'background:rgba(30,40,50,0.92)', 'color:#cde', 'font-size:12px',
        'padding:6px 12px', 'border-radius:4px', 'pointer-events:none',
        'transition:opacity 0.4s', 'z-index:9999',
      ].join(';')
      document.body.appendChild(toast)
    }
    toast.textContent = msg
    toast.style.opacity = '1'
    clearTimeout(_toastTimeout)
    _toastTimeout = setTimeout(() => { toast.style.opacity = '0' }, durationMs)
  }

  function _showProgress(header, label) {
    if (_apHeader) _apHeader.textContent = header ?? 'Working…'
    _apLabel.textContent = label ?? ''
    _apFill.style.width  = '0%'
    _apProgress.classList.add('visible')
  }
  function _hideProgress() {
    _apProgress.classList.remove('visible')
  }

  // ── Tools: Auto Crossover ──────────────────────────────────────────────────
  document.getElementById('menu-tools-prebreak')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    _showProgress('Prebreak', 'Nicking staples at all crossover positions…')
    const result = await api.prebreak()
    _hideProgress()
    if (!result) {
      const err = store.getState().lastError
      alert('Prebreak failed: ' + (err?.message ?? 'unknown error'))
    }
  })

  document.getElementById('menu-tools-auto-crossover')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }

    _showProgress('Auto Crossover', 'Placing canonical DX crossovers…')
    _apFill.style.transition = 'none'
    _apFill.style.width = '0%'
    void _apFill.offsetWidth
    _apFill.style.transition = 'width 1.5s ease-out'
    _apFill.style.width = '80%'

    const result = await api.addAutoCrossover()

    _apFill.style.transition = 'width 0.2s ease'
    _apFill.style.width = '100%'
    await new Promise(r => setTimeout(r, 250))
    _hideProgress()

    if (!result) {
      const err = store.getState().lastError
      alert('Auto Crossover failed: ' + (err?.message ?? 'unknown error'))
    }
  })

  // ── Tools: Auto Break ────────────────────────────────────────────────────
  document.getElementById('menu-tools-auto-break')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    const result = await api.addAutoBreak()
    if (!result) {
      const err = store.getState().lastError
      alert('Auto Break failed: ' + (err?.message ?? 'unknown error'))
    }
  })

  // ── Tools menu (Bend / Twist) ─────────────────────────────────────────────
  document.getElementById('menu-tools-twist')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    if (!deformView.isActive() && currentDesign.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    _stopPhysicsIfActive()
    startTool('twist')
    document.getElementById('mode-indicator').textContent =
      'TWIST — click plane A (fixed), then plane B · Esc to exit'
  })

  document.getElementById('menu-tools-bend')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    if (!deformView.isActive() && currentDesign.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    _stopPhysicsIfActive()
    startTool('bend')
    document.getElementById('mode-indicator').textContent =
      'BEND — click plane A (fixed), then plane B · Esc to exit'
  })

  document.getElementById('menu-tools-update-staple-routing')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.deformations?.length) { alert('No deformation ops on the current design.'); return }
    // design.crossovers is always [] — check strand domain topology for actual cross-helix connections
    const hasCrossovers = currentDesign?.strands?.some(s =>
      s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
    )
    if (!hasCrossovers) { alert('Place crossovers first (Auto Crossover) before updating staple routing.'); return }
    _showProgress('Update Staple Routing', 'Applying loop/skip modifications…')
    const result = await api.applyAllDeformations()
    _hideProgress()
    if (!result) {
      const err = store.getState().lastError
      alert('Update Staple Routing failed: ' + (err?.message ?? 'unknown error'))
    } else {
      _showToast('Staple routing updated.')
    }
  })

  // Enable/disable "Update Staple Routing" based on whether crossovers exist.
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign === prevState.currentDesign) return
    const btn = document.getElementById('menu-tools-update-staple-routing')
    if (!btn) return
    const hasCrossovers = newState.currentDesign?.strands?.some(s =>
      s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
    ) ?? false
    btn.disabled = !hasCrossovers
  })

  document.getElementById('menu-view-axes')?.addEventListener('click', () => {
    originAxes.visible = !originAxes.visible
    _setMenuToggle('menu-view-axes', originAxes.visible)
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

  document.getElementById('menu-view-unfold')?.addEventListener('click', _toggleUnfold)

  document.getElementById('menu-view-deform')?.addEventListener('click', _toggleDeformView)

  // ── Loop/Skip legend ────────────────────────────────────────────────────────
  const _loopSkipLegend = document.createElement('div')
  _loopSkipLegend.style.cssText = `
    position: fixed;
    top: 44px;
    right: 308px;
    display: none;
    background: rgba(8,16,26,0.90);
    border: 1px solid #2a5a8a;
    border-radius: 5px;
    padding: 8px 12px;
    font-family: monospace;
    font-size: 12px;
    color: #c8daf0;
    line-height: 1.9;
    z-index: 9000;
    pointer-events: none;
  `
  _loopSkipLegend.innerHTML = `
    <div style="color:#5bc8ff;font-weight:bold;letter-spacing:.04em;margin-bottom:3px">LOOP / SKIP</div>
    <div><span style="display:inline-block;width:14px;height:14px;border-radius:50%;border:3px solid #ff8800;vertical-align:middle;margin-right:6px"></span>Loop &nbsp;(+1 bp)</div>
    <div><span style="color:#ff2222;font-size:15px;font-weight:bold;vertical-align:middle;margin-right:6px;line-height:1">✕</span>Skip &nbsp;(−1 bp)</div>
  `.trim()
  document.body.appendChild(_loopSkipLegend)

  document.getElementById('menu-view-loop-skip')?.addEventListener('click', () => {
    const nowVisible = !loopSkipHighlight.isVisible()
    loopSkipHighlight.setVisible(nowVisible)
    _setMenuToggle('menu-view-loop-skip', nowVisible)
    _loopSkipLegend.style.display = nowVisible ? 'block' : 'none'
    if (nowVisible) {
      const { currentDesign, currentGeometry, currentHelixAxes } = store.getState()
      loopSkipHighlight.rebuild(currentDesign, currentGeometry, currentHelixAxes)
    }
  })

  document.getElementById('menu-view-helix-labels')?.addEventListener('click', () => {
    store.setState({ showHelixLabels: !store.getState().showHelixLabels })
  })

  document.getElementById('menu-view-debug')?.addEventListener('click', () => {
    debugOverlay.toggle()
    _setMenuToggle('menu-view-debug', debugOverlay.isActive())
  })

  document.getElementById('unfold-spacing-input')?.addEventListener('change', e => {
    const val = parseFloat(e.target.value)
    if (!isNaN(val) && val > 0) unfoldView.setSpacing(val)
  })

  // ── View menu toggle pill state ───────────────────────────────────────────────

  function _setMenuToggle(id, on) {
    document.getElementById(id)?.classList.toggle('is-on', on)
  }

  // Sync store-backed toggles reactively.
  store.subscribe((newState, prevState) => {
    if (newState.physicsMode      !== prevState.physicsMode)      _setMenuToggle('menu-view-physics', newState.physicsMode)
    if (newState.unfoldActive     !== prevState.unfoldActive)     _setMenuToggle('menu-view-unfold',  newState.unfoldActive)
    if (newState.deformVisuActive !== prevState.deformVisuActive) _setMenuToggle('menu-view-deform',  newState.deformVisuActive)
    if (newState.showHelixLabels  !== prevState.showHelixLabels)  _setMenuToggle('menu-view-helix-labels', newState.showHelixLabels)
  })

  // Slice plane pill is updated imperatively in _toggleSlicePlane, Escape handler,
  // _resetForNewDesign, and any other place that calls slicePlane.hide/show directly.

  // ── Selection filter toggles ──────────────────────────────────────────────────
  // Stop physics when the deform tool opens — a running simulation would make
  // the deform preview ghost stale (ghost captures current physics positions,
  // but physics keeps advancing, causing the ghost and live mesh to diverge).
  store.subscribe((newState, prevState) => {
    if (newState.deformToolActive && !prevState.deformToolActive) {
      _stopPhysicsIfActive()
    }
  })

  // Save/restore selectableTypes when deform tool activates/deactivates so that
  // all selection code that reads selectableTypes sees the correct blocked state.
  let _savedSelectableTypes = null
  store.subscribe((newState, prevState) => {
    if (newState.deformToolActive === prevState.deformToolActive) return
    if (newState.deformToolActive) {
      // Deform just activated — save user's selection filter and disable all
      _savedSelectableTypes = { ...newState.selectableTypes }
      store.setState({
        selectableTypes: { scaffold: false, staples: false, bluntEnds: false, crossovers: false },
      })
    } else {
      // Deform just deactivated — restore saved selection filter
      if (_savedSelectableTypes) {
        store.setState({ selectableTypes: _savedSelectableTypes })
        _savedSelectableTypes = null
      }
    }
  })

  for (const key of ['scaffold', 'staples', 'bluntEnds', 'crossovers']) {
    const toggle = document.getElementById(`sel-toggle-${key}`)
    const row    = document.getElementById(`sel-row-${key}`)
    if (!toggle || !row) continue
    const _update = () => {
      const { selectableTypes, deformToolActive } = store.getState()
      toggle.classList.toggle('on', selectableTypes[key])
      row.style.opacity       = deformToolActive ? '0.35' : '1'
      row.style.pointerEvents = deformToolActive ? 'none' : ''
      row.title = deformToolActive ? 'Selection disabled while deformation tool is active' : ''
    }
    row.addEventListener('click', () => {
      if (store.getState().deformToolActive) return
      const st = store.getState().selectableTypes
      store.setState({ selectableTypes: { ...st, [key]: !st[key] } })
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

    // Ctrl+O — open design
    if ((e.ctrlKey || e.metaKey) && e.key === 'o') {
      e.preventDefault()
      document.getElementById('menu-file-open')?.click()
      return
    }

    // Ctrl+S — save design
    if ((e.ctrlKey || e.metaKey) && e.key === 's' && !e.shiftKey) {
      e.preventDefault()
      document.getElementById('menu-file-save')?.click()
      return
    }

    // Ctrl+Shift+S — save as
    if ((e.ctrlKey || e.metaKey) && e.key === 's' && e.shiftKey) {
      e.preventDefault()
      document.getElementById('menu-file-save-as')?.click()
      return
    }

    // Ctrl+Z — undo (blocked while deform tool is active)
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
      e.preventDefault()
      if (isDeformActive()) return
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
        // If undo removed the last deformation and deformed view is OFF, restore it.
        if (!currentDesign?.deformations?.length && !deformView.isActive()) {
          await deformView.activate()
          _setMenuToggle('menu-view-deform', true)
          document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
        }
      }
      return
    }

    // Ctrl+Y or Ctrl+Shift+Z — redo (blocked while deform tool is active)
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
      e.preventDefault()
      if (isDeformActive()) return
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

    // 'X' — place force crossover (when 2 beads are Ctrl+click selected)
    if ((e.key === 'x' || e.key === 'X') && !inInput && _fcBeads.length === 2) {
      e.preventDefault()
      const [beadA, beadB] = _fcBeads
      _fcBeads = []
      _fcHintActive = false
      const result = await api.addHalfCrossover({
        helixAId:   beadA.nuc.helix_id,
        bpA:        beadA.nuc.bp_index,
        directionA: beadA.nuc.direction,
        helixBId:   beadB.nuc.helix_id,
        bpB:        beadB.nuc.bp_index,
        directionB: beadB.nuc.direction,
      })
      if (!result) {
        const err = store.getState().lastError
        const el = document.getElementById('mode-indicator')
        if (el) {
          el.textContent = `Force crossover failed: ${err?.message ?? 'unknown error'}`
          setTimeout(() => { el.textContent = 'NADOC · WORKSPACE' }, 2500)
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

    // 'U' — toggle 2D unfold view
    if ((e.key === 'u' || e.key === 'U') && !inInput) {
      _toggleUnfold()
      return
    }

    // 'D' — toggle deformed view
    if ((e.key === 'd' || e.key === 'D') && !inInput) {
      _toggleDeformView()
      return
    }

    // '`' — toggle debug hover overlay
    if (e.key === '`' && !inInput) {
      debugOverlay.toggle()
      _setMenuToggle('menu-view-debug', debugOverlay.isActive())
      return
    }

    // 'F' — fit entire structure in view
    if ((e.key === 'f' || e.key === 'F') && !inInput) {
      _fitToView()
      return
    }

    // Escape — exit force crossover selection, deformation tool, or slice plane
    if (e.key === 'Escape') {
      if (_fcBeads.length > 0) {
        _fcClear()
        return
      }
      if (isDeformActive()) {
        deformEscape()
        _watchDeformState()
        if (!isDeformActive()) {
          document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
        }
      // TODO(refactor): remove when crossover_markers.js is deleted
      // } else if (crossoverMarkers.isActive()) {
      //   crossoverMarkers.deactivate()
      //   document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      } else if (slicePlane.isVisible()) {
        slicePlane.hide()
        _setMenuToggle('menu-view-slice', false)
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

  // Debug helper: window.SLICE.debug() in browser console
  window.SLICE = slicePlane
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

    store.subscribe((newState, prevState) => {
      // Snap orbit target to design centroid when geometry first appears.
      if (!prevState.currentGeometry && newState.currentGeometry?.length) {
        const c = _geomCentroid(newState.currentGeometry)
        if (c) { controls.target.copy(c); controls.update() }
      }
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

    // Click: select a strand of the clicked bar, cycling through all strands on repeated clicks
    let _lastClickedLength = null
    let _cycleIndex = 0
    canvas.addEventListener('click', e => {
      const rect = canvas.getBoundingClientRect()
      const scaleX = canvas.width / rect.width
      const mx = (e.clientX - rect.left) * scaleX

      for (const bar of _barData) {
        if (mx >= bar.x && mx <= bar.x + bar.w) {
          if (bar.length === _lastClickedLength) {
            _cycleIndex = (_cycleIndex + 1) % bar.strandIds.length
          } else {
            _lastClickedLength = bar.length
            _cycleIndex = 0
          }
          const strandId = bar.strandIds[_cycleIndex]
          const total = bar.strandIds.length
          tooltip.textContent = `${bar.length} nt · ${_cycleIndex + 1}/${total} strand(s)`

          selectionManager.selectStrand(strandId)
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

    // Redraw when design changes and histogram is visible; reset cycle state
    store.subscribe((newState, prevState) => {
      if (_expanded && newState.currentDesign !== prevState.currentDesign) {
        _lastClickedLength = null
        _cycleIndex = 0
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

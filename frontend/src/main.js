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
import { createGlowLayer }           from './scene/glow_layer.js'
import { initDesignRenderer }        from './scene/design_renderer.js'
import { initSelectionManager }      from './scene/selection_manager.js'
import { initCrossoverLocations }    from './scene/crossover_locations.js'
import { initWorkspace }             from './scene/workspace.js'
import { initSlicePlane }            from './scene/slice_plane.js'
import { initBluntEnds }             from './scene/blunt_ends.js'
import { initEndExtrudeArrows }      from './scene/end_extrude_arrows.js'
import { initCommandPalette }  from './ui/command_palette.js'
import { initPropertiesPanel } from './ui/properties_panel.js'
import { createScriptRunner }  from './ui/script_runner.js'
import { store, pushGroupUndo, popGroupUndo } from './state/store.js'
import * as api                from './api/client.js'
import { initPhysicsClient, initFastPhysicsClient } from './physics/physics_client.js'
import { initFemClient } from './physics/fem_client.js'
import { initFastPhysicsDisplay } from './physics/displayState.js'
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
import { initOverhangLocations }   from './scene/overhang_locations.js'
import { initOverhangNameOverlay } from './scene/overhang_name_overlay.js'
import { initCrossSectionMinimap } from './scene/cross_section_minimap.js'
import { initViewCube }            from './scene/view_cube.js'
import { initDebugOverlay }        from './scene/debug_overlay.js'
import { initSequenceOverlay }     from './scene/sequence_overlay.js'
import { initAtomisticRenderer }   from './scene/atomistic_renderer.js'
import { initSpreadsheet }         from './ui/spreadsheet.js'
import { initClusterPanel, helixIdsFromStrandIds } from './ui/cluster_panel.js'
import { initClusterGizmo }        from './scene/cluster_gizmo.js'
import { showToast }               from './ui/toast.js'
import { BDNA_RISE_PER_BP }        from './constants.js'

const DEBUG = new URLSearchParams(window.location.search).has('debug')

// Compute the maximum extent of the current design along the given plane normal.
// This is where the slice plane starts when first toggled on.
function _bundleAxisRange(design, plane) {
  if (!design || !design.helices.length) return { min: 0, max: 0 }
  let min = Infinity, max = -Infinity
  for (const h of design.helices) {
    let lo, hi
    if      (plane === 'XY') { lo = Math.min(h.axis_start.z, h.axis_end.z); hi = Math.max(h.axis_start.z, h.axis_end.z) }
    else if (plane === 'XZ') { lo = Math.min(h.axis_start.y, h.axis_end.y); hi = Math.max(h.axis_start.y, h.axis_end.y) }
    else                     { lo = Math.min(h.axis_start.x, h.axis_end.x); hi = Math.max(h.axis_start.x, h.axis_end.x) }
    if (lo < min) min = lo
    if (hi > max) max = hi
  }
  return { min, max }
}
function _bundleMaxOffset(design, plane) { return _bundleAxisRange(design, plane).max }
function _bundleMidOffset(design, plane) { const { min, max } = _bundleAxisRange(design, plane); return (min + max) / 2 }

async function main() {
  const canvas = document.getElementById('canvas')
  const { scene, camera, controls, switchOrbitMode } = initScene(canvas)

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

  // ── Routing checkmark state ────────────────────────────────────────────────
  // Tracks which routing steps have been successfully completed since the last
  // structural edit. Cleared on undo/redo, nick, loop/skip, or new-design reset.
  const _routingChecks = {
    scaffoldEnds: false,
    prebreak: false, autoCrossover: false, autoMerge: false,
  }
  const _routingIdMap = {
    scaffoldEnds:  'menu-routing-scaffold-ends',
    prebreak:      'menu-routing-prebreak',
    autoCrossover: 'menu-routing-auto-crossover',
    autoMerge:     'menu-routing-auto-merge',
  }
  function _setRoutingCheck(key, val) {
    _routingChecks[key] = val
    document.getElementById(_routingIdMap[key])?.classList.toggle('is-checked', val)
  }
  function _clearStapleChecks() {
    _setRoutingCheck('prebreak', false)
    _setRoutingCheck('autoCrossover', false)
    _setRoutingCheck('autoMerge', false)
  }
  function _clearScaffoldChecks() {
    _setRoutingCheck('scaffoldEnds', false)
  }

  // Placeholder filled by the overhang dialog IIFE below.
  let _showOverhangLengthDialog = () => {}

  // ── Selection manager ───────────────────────────────────────────────────────
  const selectionManager = initSelectionManager(canvas, camera, designRenderer, {
    onNick: async ({ helixId, bpIndex, direction }) => {
      _clearStapleChecks()
      const result = await api.addNick({ helixId, bpIndex, direction })
      if (!result) {
        const err = store.getState().lastError
        console.error('Nick failed:', err?.message)
      }
    },
    onLoopSkip: async ({ helixId, bpIndex, delta }) => {
      _clearStapleChecks()
      const result = await api.insertLoopSkip(helixId, bpIndex, delta)
      if (!result) {
        const err = store.getState().lastError
        console.error('Loop/skip insert failed:', err?.message)
      }
    },
    onOverhangArrow: (entry, clientX, clientY) => {
      _showOverhangLengthDialog(entry, clientX, clientY)
    },
    // Lazy getters — defined later in this init sequence.
    getUnfoldView:          () => unfoldView,
    getOverhangLocations:   () => overhangLocations,
    getLoopSkipHighlight:   () => loopSkipHighlight,
    controls,
  })

  // ── End extrusion arrows ──────────────────────────────────────────────────────
  // Thick arrows pointing outward along the helix axis at each selected 5'/3' end.
  initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, controls)

  // ── Measurement tool ─────────────────────────────────────────────────────────
  // Shows a 3D line + distance readout when exactly 2 ctrl-clicked beads are present
  // and the user presses 'M'.  Not valid in unfold view.

  let _measLine   = null   // THREE.Line currently in scene, or null
  let _measActive = false
  let _measBox    = null   // DOM element for distance readout

  function _measClear() {
    if (_measLine) { scene.remove(_measLine); _measLine.geometry.dispose(); _measLine.material.dispose(); _measLine = null }
    if (_measBox)  { _measBox.style.display = 'none' }
    _measActive = false
  }

  function _measShow(posA, posB) {
    _measClear()
    const dist = posA.distanceTo(posB)

    const geo = new THREE.BufferGeometry().setFromPoints([posA, posB])
    const mat = new THREE.LineBasicMaterial({ color: 0x00e5ff, linewidth: 2, depthTest: false, transparent: true, opacity: 0.9 })
    _measLine = new THREE.Line(geo, mat)
    _measLine.renderOrder = 999
    scene.add(_measLine)

    if (!_measBox) {
      _measBox = document.createElement('div')
      _measBox.style.cssText =
        'position:fixed;left:12px;bottom:12px;z-index:500;display:none;pointer-events:none;' +
        'background:rgba(10,18,30,0.88);border:1px solid #00e5ff;border-radius:6px;' +
        'color:#00e5ff;font-family:monospace;font-size:13px;padding:6px 14px;' +
        'box-shadow:0 2px 8px rgba(0,0,0,0.5);'
      document.body.appendChild(_measBox)
    }
    _measBox.textContent = `Distance: ${dist.toFixed(3)} nm`
    _measBox.style.display = 'block'
    _measActive = true
  }

  // Clear measurement whenever ctrl beads drop below 2 after being set
  selectionManager.onCtrlBeadsChange(beads => {
    if (_measActive && beads.length !== 2) _measClear()
  })

  // ── Overhang dialog ──────────────────────────────────────────────────────────

  ;(function _initOverhangDialog() {
    const inputStyle = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                       'color:#c9d1d9;padding:2px 6px;font-family:inherit;font-size:12px;'
    const tabStyle   = 'flex:1;padding:4px 0;background:none;border:none;border-bottom:2px solid transparent;' +
                       'color:#8b949e;font-family:inherit;font-size:11px;cursor:pointer;'
    const tabActiveStyle = tabStyle + 'color:#00e5ff;border-bottom-color:#00e5ff;'

    const overlay = document.createElement('div')
    overlay.id = 'overhang-length-dialog'
    Object.assign(overlay.style, {
      display:      'none',
      position:     'fixed',
      background:   '#161b22',
      border:       '1px solid #30363d',
      borderRadius: '6px',
      padding:      '12px 16px',
      color:        '#c9d1d9',
      fontFamily:   "'Courier New', monospace",
      fontSize:     '12px',
      zIndex:       '200',
      boxShadow:    '0 8px 24px rgba(0,0,0,0.5)',
      minWidth:     '260px',
    })
    overlay.innerHTML = `
      <div style="margin-bottom:10px;font-weight:bold;color:#00e5ff;">Add Overhang</div>

      <div style="margin-bottom:10px;">
        <div style="margin-bottom:4px;font-size:11px;color:#8b949e;">Name (optional):</div>
        <input id="ovhg-name-input" type="text" placeholder="e.g. toehold-1" autocomplete="off"
          style="width:100%;box-sizing:border-box;${inputStyle}">
      </div>

      <div style="display:flex;border-bottom:1px solid #30363d;margin-bottom:10px;">
        <button id="ovhg-tab-length" style="${tabActiveStyle}">By Length</button>
        <button id="ovhg-tab-seq"    style="${tabStyle}">By Sequence</button>
      </div>

      <div id="ovhg-panel-length">
        <label style="display:flex;align-items:center;gap:8px;">
          <span>Length (bp):</span>
          <input id="overhang-length-input" type="number" min="1" max="500" value="10"
            style="width:60px;${inputStyle}">
        </label>
      </div>

      <div id="ovhg-panel-seq" style="display:none">
        <div style="margin-bottom:4px;font-size:11px;color:#8b949e;">Paste sequence (5′→3′):</div>
        <input id="ovhg-seq-input" type="text" placeholder="ACGT…" autocomplete="off" spellcheck="false"
          style="width:100%;box-sizing:border-box;${inputStyle}letter-spacing:0.05em;">
        <div id="ovhg-seq-len" style="margin-top:3px;font-size:10px;color:#484f58;">0 bp</div>
      </div>

      <div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end;">
        <button id="overhang-cancel-btn"
          style="padding:3px 10px;background:#21262d;border:1px solid #30363d;border-radius:4px;
                 color:#c9d1d9;font-family:inherit;font-size:12px;cursor:pointer;">Cancel</button>
        <button id="overhang-ok-btn"
          style="padding:3px 10px;background:#1f6feb;border:none;border-radius:4px;
                 color:#fff;font-family:inherit;font-size:12px;cursor:pointer;">Extrude</button>
      </div>
    `
    document.body.appendChild(overlay)

    let _pendingEntry = null
    let _activeTab    = 'length'   // 'length' | 'seq'

    const tabLength  = overlay.querySelector('#ovhg-tab-length')
    const tabSeq     = overlay.querySelector('#ovhg-tab-seq')
    const panelLen   = overlay.querySelector('#ovhg-panel-length')
    const panelSeq   = overlay.querySelector('#ovhg-panel-seq')
    const seqInput   = overlay.querySelector('#ovhg-seq-input')
    const seqLenEl   = overlay.querySelector('#ovhg-seq-len')
    const okBtn      = overlay.querySelector('#overhang-ok-btn')
    const lenInput   = overlay.querySelector('#overhang-length-input')
    const nameInput  = overlay.querySelector('#ovhg-name-input')

    function _switchTab(tab) {
      _activeTab = tab
      const isLen = tab === 'length'
      tabLength.style.cssText  = isLen ? tabActiveStyle : tabStyle
      tabSeq.style.cssText     = isLen ? tabStyle : tabActiveStyle
      panelLen.style.display   = isLen ? '' : 'none'
      panelSeq.style.display   = isLen ? 'none' : ''
      okBtn.textContent        = isLen ? 'Extrude' : 'Extrude + Assign'
      setTimeout(() => (isLen ? lenInput : seqInput).focus(), 0)
    }

    tabLength.addEventListener('click', () => _switchTab('length'))
    tabSeq.addEventListener('click',    () => _switchTab('seq'))

    seqInput.addEventListener('input', () => {
      const n = seqInput.value.replace(/\s/g, '').length
      seqLenEl.textContent = `${n} bp`
      seqLenEl.style.color = n > 0 ? '#8b949e' : '#484f58'
    })

    function _hide() {
      overlay.style.display = 'none'
      _pendingEntry = null
      seqInput.value  = ''
      nameInput.value = ''
      seqLenEl.textContent = '0 bp'
      seqLenEl.style.color = '#484f58'
    }

    _showOverhangLengthDialog = function(entry, clientX, clientY) {
      _pendingEntry = entry
      overlay.style.left    = `${Math.min(clientX, window.innerWidth  - 290)}px`
      overlay.style.top     = `${Math.min(clientY, window.innerHeight - 200)}px`
      overlay.style.display = 'block'
      _switchTab('length')
      lenInput.value  = '10'
      nameInput.value = ''
      nameInput.focus()
    }

    async function _doExtrude() {
      const entry = _pendingEntry
      if (!entry) return

      let lengthBp, sequence
      if (_activeTab === 'length') {
        lengthBp = parseInt(lenInput.value, 10)
        if (!Number.isFinite(lengthBp) || lengthBp < 1) return
        sequence = null
      } else {
        sequence = seqInput.value.replace(/\s/g, '').toUpperCase()
        if (!sequence.length) return
        lengthBp = sequence.length
      }

      // Capture name BEFORE _hide() clears the input.
      const name = nameInput.value.trim() || null

      _hide()

      const result = await api.extrudeOverhang({
        helixId:     entry.helixId,
        bpIndex:     entry.bpIndex,
        direction:   entry.direction,
        isFivePrime: entry.isFivePrime,
        neighborRow: entry.neighborRow,
        neighborCol: entry.neighborCol,
        lengthBp,
      })
      if (!result) {
        console.error('Overhang extrude failed:', store.getState().lastError?.message)
        return
      }

      // Assign name and/or sequence to the new OverhangSpec immediately.
      if (sequence || name) {
        const endTag     = entry.isFivePrime ? '5p' : '3p'
        const overhangId = `ovhg_${entry.helixId}_${entry.bpIndex}_${endTag}`
        const patch = {}
        if (sequence) patch.sequence = sequence
        if (name)     patch.label    = name
        await api.patchOverhang(overhangId, patch)
      }
    }

    okBtn.addEventListener('click', _doExtrude)
    overlay.querySelector('#overhang-cancel-btn').addEventListener('click', _hide)

    lenInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') _doExtrude()
      if (e.key === 'Escape') _hide()
    })
    seqInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') _doExtrude()
      if (e.key === 'Escape') _hide()
    })

    // Click outside closes dialog
    document.addEventListener('pointerdown', e => {
      if (overlay.style.display !== 'none' && !overlay.contains(e.target)) _hide()
    }, true)
  })()

  // Track Ctrl key state — used to suppress popups during Ctrl+click interactions.
  let _ctrlHeld = false
  window.addEventListener('keydown', e => { if (e.key === 'Control') _ctrlHeld = true  })
  window.addEventListener('keyup',   e => { if (e.key === 'Control') _ctrlHeld = false })
  window.addEventListener('blur',    ()  => { _ctrlHeld = false })

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
      if (_ctrlHeld) return
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

  // ── Physics client (XPBD streaming, Phase 5 — detailed nucleotide mode) ──
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

  // ── Fast-mode helix-segment physics (Phase AA) ────────────────────────────
  const fastDisplay = initFastPhysicsDisplay(scene, designRenderer)

  const fastClient = initFastPhysicsClient({
    onUpdate: (frame, converged, particles, residuals) => {
      if (frame === 0 && particles.length > 0) {
        // First frame — build the overlay mesh from the initial particle list
        fastDisplay.start(particles)
        const statusEl = document.getElementById('fast-physics-status')
        if (statusEl) statusEl.style.display = 'block'
      }
      fastDisplay.onUpdate(frame, converged, particles, residuals)
      const statusEl = document.getElementById('fast-physics-status')
      if (statusEl) {
        statusEl.textContent = converged
          ? `Converged  ·  frame ${frame}`
          : `Running…  ·  frame ${frame}`
      }
      if (converged) {
        const modeEl = document.getElementById('mode-indicator')
        if (modeEl) modeEl.textContent = 'FAST PHYSICS — converged  ·  [P] to stop'
      }
    },
    onStatus: (msg) => console.debug('[FastPhysics]', msg),
  })

  // Physics on/off state + sub-mode (set by radio buttons in sidebar)
  let _physActive  = false
  let _physSubMode = 'fast'  // 'fast' | 'detailed'

  // Keep _physSubMode in sync with sidebar radio buttons
  ;(function _initPhysModeRadios() {
    const rFast     = document.getElementById('phys-mode-fast')
    const rDetailed = document.getElementById('phys-mode-detailed')
    const detailed  = document.getElementById('phys-detailed-controls')
    const fastSt    = document.getElementById('fast-physics-status')

    function _applyMode(mode) {
      _physSubMode = mode
      if (detailed) detailed.style.display = mode === 'detailed' ? 'block' : 'none'
      // fast-physics-status visibility is managed by onUpdate / _stopPhysicsIfActive
    }

    if (rFast) rFast.addEventListener('change', () => {
      if (_physActive) _stopPhysicsIfActive()
      _applyMode('fast')
    })
    if (rDetailed) rDetailed.addEventListener('change', () => {
      if (_physActive) _stopPhysicsIfActive()
      _applyMode('detailed')
    })

    // Apply initial state (fast is checked by default)
    _applyMode('fast')
  })()

  function _updatePhysicsPlayBtn() {
    const btn = document.getElementById('btn-physics-play')
    if (!btn) return
    if (!_physActive) {
      btn.textContent = '▶ Play'
      btn.style.background = '#1f6feb'
      btn.style.borderColor = '#388bfd'
    } else {
      btn.textContent = '⏹ Stop'
      btn.style.background = '#6e2020'
      btn.style.borderColor = '#c94a4a'
    }
  }

  function _stopPhysicsIfActive() {
    if (!_physActive) return
    if (_physSubMode === 'detailed') {
      physicsClient.stop()
      designRenderer.applyPhysicsPositions(null)
      deformView.reapplyLerp()
      store.setState({ physicsMode: false })
    } else {
      fastClient.stop()
      fastDisplay.stop()
      const statusEl = document.getElementById('fast-physics-status')
      if (statusEl) { statusEl.textContent = ''; statusEl.style.display = 'none' }
    }
    _physActive = false
  }

  function _togglePhysics() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return

    const modeEl = document.getElementById('mode-indicator')

    if (_physActive) {
      _stopPhysicsIfActive()
      if (modeEl) modeEl.textContent = 'NADOC · WORKSPACE'
    } else {
      _physActive = true
      if (_physSubMode === 'fast') {
        fastClient.start()
        if (modeEl) modeEl.textContent = 'FAST PHYSICS — running…  ·  [P] to stop'
      } else {
        store.setState({ physicsMode: true })
        physicsClient.start({ useStraight: !store.getState().deformVisuActive })
        if (modeEl) modeEl.textContent = 'PHYSICS MODE — XPBD thermal motion active  ·  [P] to stop'
      }
    }
    _updatePhysicsPlayBtn()
  }

  // ── Physics panel collapse toggle ─────────────────────────────────────────
  function _initCollapsiblePanel(headingId, bodyId, arrowId, startCollapsed = true) {
    const heading = document.getElementById(headingId)
    const body    = document.getElementById(bodyId)
    const arrow   = document.getElementById(arrowId)
    if (!heading || !body) return
    body.style.display = startCollapsed ? 'none' : 'block'
    if (arrow) arrow.textContent = startCollapsed ? '▶' : '▼'
    heading.addEventListener('click', () => {
      const collapsed = body.style.display === 'none'
      body.style.display = collapsed ? 'block' : 'none'
      if (arrow) arrow.textContent = collapsed ? '▼' : '▶'
    })
  }

  _initCollapsiblePanel('physics-heading', 'physics-body', 'physics-arrow')
  _initCollapsiblePanel('fem-heading',     'fem-body',     'fem-arrow')
  _initCollapsiblePanel('oxdna-heading',   'oxdna-body',   'oxdna-arrow')

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

  // ── Crossover Locations overlay ──────────────────────────────────────────────
  const crossoverLocations = initCrossoverLocations(scene, canvas, camera)
  // Stub used by legacy callers that expected crossoverMarkers shape.
  const crossoverMarkers = { dispose() {}, clear() { crossoverLocations.setVisible(false) }, isActive: () => false, applyDeformLerp() {}, getMarkers: () => [] }

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

  // Suppress browser context menu when Ctrl+right-click is used for crossover selection.
  canvas.addEventListener('contextmenu', e => { if (e.ctrlKey) e.preventDefault() }, { capture: true })

  // Ctrl+right-click — bead selection for manual crossover placement.
  // Disable OrbitControls on pointerdown so right-button orbit/pan never starts.
  let _fcDownPos = null
  canvas.addEventListener('pointerdown', e => {
    if (e.ctrlKey && e.button === 2) {
      _fcDownPos = { x: e.clientX, y: e.clientY }
      controls.enabled = false
    } else if (e.button === 2) {
      _fcDownPos = null
    }
  }, { capture: true })

  canvas.addEventListener('pointerup', e => {
    if (e.ctrlKey && e.button === 2) controls.enabled = true
    if (!e.ctrlKey || e.button !== 2) return
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

    if (!entry || entry.nuc.strand_type === 'scaffold') {
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
  const unfoldView = initUnfoldView(scene, designRenderer, () => bluntEnds, () => loopSkipHighlight, () => sequenceOverlay, () => overhangLocations, () => crossoverLocations)

  // ── Deformed geometry view ──────────────────────────────────────────────────
  const deformView = initDeformView(designRenderer, () => bluntEnds, () => crossoverMarkers, () => unfoldView, () => loopSkipHighlight, () => overhangLocations)

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

  // ── Overhang Locations overlay ───────────────────────────────────────────────
  const overhangLocations = initOverhangLocations(scene)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    if (overhangLocations.isVisible()) {
      overhangLocations.rebuild(newState.currentDesign, newState.currentGeometry)
    }
  })

  // ── Crossover Locations rebuild subscription ─────────────────────────────────
  store.subscribe((newState, prevState) => {
    const geomChanged = newState.currentGeometry !== prevState.currentGeometry
    if (geomChanged && crossoverLocations.isVisible()) {
      crossoverLocations.rebuild(newState.currentGeometry).then(() => unfoldView.reapplyIfActive())
    }
  })

  // ── Overhang Name overlay ────────────────────────────────────────────────────
  // Subscription is handled inside initOverhangNameOverlay via store.subscribe.
  const overhangNameOverlay = initOverhangNameOverlay(scene, store)

  // ── Atomistic renderer (Phase AA) ───────────────────────────────────────────
  const atomisticRenderer = initAtomisticRenderer(scene)

  // Fetch + load atom data whenever mode switches from off → non-off.
  let _atomDataCache  = null
  let _deltaDeg       = 0
  let _gammaDeg       = 0
  let _betaDeg        = 0
  let _frameRotDeg    = 39
  let _frameShiftN    = -0.07
  let _frameShiftY    = -0.59
  let _frameShiftZ    = 0.00

  let _crossoverMode = 'lerp'

  // Atomistic-only sliders (shown only while atomistic mode is active)
  const _atomisticSliderRowIds = [
    'sl-delta-row', 'sl-gamma-row', 'sl-beta-row',
    'sl-frame-rot-row', 'sl-frame-sn-row', 'sl-frame-sy-row', 'sl-frame-sz-row',
    'sl-crossover-mode-row',
  ]
  function _setAtomisticSlidersVisible(visible) {
    for (const id of _atomisticSliderRowIds) {
      const el = document.getElementById(id)
      if (el) el.style.display = visible ? '' : 'none'
    }
  }

  // Shared debounce for all atomistic parameter sliders
  let _atomDebounce = null
  function _scheduleAtomRefetch() {
    if (atomisticRenderer.getMode() === 'off') return
    clearTimeout(_atomDebounce)
    _atomDebounce = setTimeout(async () => {
      _atomDataCache = null
      await _applyAtomisticMode(atomisticRenderer.getMode())
    }, 200)
  }

  // Wire atomistic sliders: torsions (integer °) and frame params (float nm / °)
  const _sliderDefs = [
    { id: 'sl-delta',    val: 'sv-delta',    parse: parseInt,   set: v => { _deltaDeg    = v },          fmt: v => v },
    { id: 'sl-gamma',    val: 'sv-gamma',    parse: parseInt,   set: v => { _gammaDeg    = v },          fmt: v => v },
    { id: 'sl-beta',     val: 'sv-beta',     parse: parseInt,   set: v => { _betaDeg     = v },          fmt: v => v },
    { id: 'sl-frame-rot',val: 'sv-frame-rot',parse: parseInt,   set: v => { _frameRotDeg = v },          fmt: v => v },
    { id: 'sl-frame-sn', val: 'sv-frame-sn', parse: parseFloat, set: v => { _frameShiftN = v },          fmt: v => v.toFixed(2) },
    { id: 'sl-frame-sy', val: 'sv-frame-sy', parse: parseFloat, set: v => { _frameShiftY = v },          fmt: v => v.toFixed(2) },
    { id: 'sl-frame-sz', val: 'sv-frame-sz', parse: parseFloat, set: v => { _frameShiftZ = v },          fmt: v => v.toFixed(2) },
  ]
  for (const { id, val, parse, set, fmt } of _sliderDefs) {
    const input = document.getElementById(id)
    const label = document.getElementById(val)
    if (!input) continue
    input.addEventListener('input', () => {
      const v = parse(input.value, 10)
      set(v)
      if (label) label.textContent = fmt(v)
      _scheduleAtomRefetch()
    })
  }

  // ── Crossover backbone mode buttons ────────────────────────────────────────
  ;(function () {
    const _XOVER_MODES = ['none', 'lerp', 'natural']
    function _setXoverActive(mode) {
      for (const m of _XOVER_MODES) {
        document.getElementById(`xover-mode-${m}`)?.classList.toggle('active', m === mode)
      }
    }
    for (const m of _XOVER_MODES) {
      document.getElementById(`xover-mode-${m}`)?.addEventListener('click', () => {
        _crossoverMode = m
        _setXoverActive(m)
        _scheduleAtomRefetch()
      })
    }
  })()

  function _setCGVisible(visible) {
    const root = designRenderer.getHelixCtrl()?.root
    if (root) root.visible = visible
    unfoldView?.setArcsVisible(visible)
  }

  async function _applyAtomisticMode(mode) {
    atomisticRenderer.setMode(mode)
    // Hide CG model when any atomistic mode is active; restore when off
    _setCGVisible(mode === 'off')
    _setAtomisticSlidersVisible(mode !== 'off')
    if (mode !== 'off' && !_atomDataCache) {
      try {
        const url = `/api/design/atomistic?delta_deg=${_deltaDeg}&gamma_deg=${_gammaDeg}&beta_deg=${_betaDeg}&frame_rot_deg=${_frameRotDeg}&frame_shift_n=${_frameShiftN}&frame_shift_y=${_frameShiftY}&frame_shift_z=${_frameShiftZ}&crossover_mode=${_crossoverMode}`
        const resp = await fetch(url)
        if (!resp.ok) { console.error('Atomistic fetch failed:', resp.status); return }
        _atomDataCache = await resp.json()
        atomisticRenderer.update(_atomDataCache)
        // Re-apply current highlight after data load
        const { selectedObject, multiSelectedStrandIds } = store.getState()
        atomisticRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
      } catch (e) {
        console.error('Atomistic fetch error:', e)
      }
    }
  }

  // Invalidate atom cache on design change; re-hide CG root after any geometry rebuild.
  store.subscribe((newState, prevState) => {
    const designChanged   = newState.currentDesign   !== prevState.currentDesign
    const geometryChanged = newState.currentGeometry !== prevState.currentGeometry ||
                            newState.currentHelixAxes !== prevState.currentHelixAxes
    if (designChanged) _atomDataCache = null
    if ((designChanged || geometryChanged) && atomisticRenderer.getMode() !== 'off') {
      // The renderer just created a fresh root with visible=true — re-hide it.
      _setCGVisible(false)
      if (designChanged) _applyAtomisticMode(atomisticRenderer.getMode())
    }
  })

  // Keep highlight in sync with selection changes.
  store.subscribe((newState, prevState) => {
    if (newState.selectedObject         === prevState.selectedObject &&
        newState.multiSelectedStrandIds === prevState.multiSelectedStrandIds) return
    if (atomisticRenderer.getMode() === 'off') return
    atomisticRenderer.highlight(
      newState.selectedObject,
      newState.multiSelectedStrandIds ?? [],
    )
  })

  // ── Overhang sequences panel ─────────────────────────────────────────────────
  ;(function _initOverhangPanel() {
    const panel      = document.getElementById('overhang-panel')
    const list       = document.getElementById('overhang-list')
    const heading    = document.getElementById('overhang-panel-heading')
    const arrow      = document.getElementById('overhang-panel-arrow')
    const sizeSlider = document.getElementById('overhang-label-size')
    const sizeVal    = document.getElementById('overhang-label-size-val')
    if (!panel || !list) return

    if (sizeSlider) {
      sizeSlider.addEventListener('input', () => {
        const s = parseFloat(sizeSlider.value)
        if (sizeVal) sizeVal.textContent = s.toFixed(1)
        overhangNameOverlay.setScale(s)
      })
    }

    let _collapsed = false

    if (heading) {
      heading.addEventListener('click', () => {
        _collapsed = !_collapsed
        list.style.display  = _collapsed ? 'none' : ''
        arrow.textContent   = _collapsed ? '▶' : '▼'
      })
    }

    const iStyle = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                   'color:#c9d1d9;padding:2px 5px;font-family:monospace;font-size:11px;'

    function _rebuildPanel(design) {
      const overhangs = design?.overhangs ?? []
      panel.style.display = overhangs.length ? '' : 'none'
      if (!overhangs.length) return
      if (_collapsed) return   // keep content stale until expanded

      list.innerHTML = ''

      // Column header
      const hdr = document.createElement('div')
      hdr.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto;gap:4px;' +
                           'margin-bottom:4px;font-size:9px;color:#484f58;text-transform:uppercase;letter-spacing:.05em'
      hdr.innerHTML = '<span>Name</span><span>Sequence</span><span></span>'
      list.appendChild(hdr)

      for (const ovhg of overhangs) {
        const row = document.createElement('div')
        row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto;gap:4px;margin-bottom:6px;align-items:center'

        const nameInput = document.createElement('input')
        nameInput.type        = 'text'
        nameInput.placeholder = 'Name…'
        nameInput.value       = ovhg.label ?? ''
        nameInput.title       = ovhg.id
        nameInput.style.cssText = iStyle + 'width:100%;box-sizing:border-box'

        const seqInput = document.createElement('input')
        seqInput.type        = 'text'
        seqInput.placeholder = 'Sequence…'
        seqInput.value       = ovhg.sequence ?? ''
        seqInput.style.cssText = iStyle + 'width:100%;box-sizing:border-box;letter-spacing:.05em'

        const saveBtn = document.createElement('button')
        saveBtn.textContent   = 'Set'
        saveBtn.style.cssText = 'padding:2px 7px;background:#1f6feb;border:none;border-radius:4px;' +
                                'color:#fff;font-size:11px;cursor:pointer;white-space:nowrap'
        saveBtn.addEventListener('click', async () => {
          const patch = {
            sequence: seqInput.value.trim().toUpperCase() || null,
            label:    nameInput.value.trim() || null,
          }
          await api.patchOverhang(ovhg.id, patch)
        })

        row.appendChild(nameInput)
        row.appendChild(seqInput)
        row.appendChild(saveBtn)
        list.appendChild(row)
      }
    }

    store.subscribe((newState, prevState) => {
      if (newState.currentDesign === prevState.currentDesign) return
      _rebuildPanel(newState.currentDesign)
    })
  })()

  // ── Strand groups panel ──────────────────────────────────────────────────────
  ;(function _initGroupsPanel() {
    const panel   = document.getElementById('groups-panel')
    const list    = document.getElementById('groups-list')
    const heading = document.getElementById('groups-panel-heading')
    const arrow   = document.getElementById('groups-panel-arrow')
    const newBtn  = document.getElementById('groups-new-btn')
    if (!panel || !list) return

    let _collapsed = false

    heading.addEventListener('click', () => {
      _collapsed = !_collapsed
      list.style.display   = _collapsed ? 'none' : ''
      newBtn.style.display = _collapsed ? 'none' : ''
      arrow.textContent    = _collapsed ? '▶' : '▼'
    })

    const _iStyle  = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                     'color:#c9d1d9;padding:2px 5px;font-family:monospace;font-size:11px;'
    const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
    const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
    const _delStyle  = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'

    function _rebuildPanel(groups) {
      list.innerHTML = ''
      for (const group of groups) {
        const row = document.createElement('div')
        row.style.cssText = 'display:grid;grid-template-columns:1fr auto auto auto auto;gap:4px;margin-bottom:6px;align-items:center'

        // Name label
        const nameSpan = document.createElement('span')
        nameSpan.textContent = group.name
        nameSpan.style.cssText = 'font-size:11px;color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'

        // Edit / Save button — use only onclick so exactly one handler is active.
        const editBtn = document.createElement('button')
        editBtn.textContent = '✎'
        editBtn.title = 'Rename group'
        editBtn.style.cssText = _editStyle
        editBtn.addEventListener('pointerenter', () => {
          editBtn.style.background = editBtn.textContent === '✓' ? '#1f3d2a' : '#2d333b'
          editBtn.style.color      = editBtn.textContent === '✓' ? '#57d05a' : '#c9d1d9'
        })
        editBtn.addEventListener('pointerleave', () => {
          editBtn.style.cssText = editBtn.textContent === '✓' ? _saveStyle : _editStyle
        })

        function _enterGroupEdit() {
          const nameInput = document.createElement('input')
          nameInput.type = 'text'
          nameInput.value = group.name
          nameInput.style.cssText = _iStyle + 'width:100%;box-sizing:border-box'
          nameSpan.replaceWith(nameInput)
          nameInput.focus(); nameInput.select()
          editBtn.textContent = '✓'
          editBtn.title = 'Save name'
          editBtn.style.cssText = _saveStyle

          function _save() {
            const newName = nameInput.value.trim() || group.name
            nameInput.replaceWith(nameSpan)
            nameSpan.textContent = newName
            editBtn.textContent = '✎'
            editBtn.title = 'Rename group'
            editBtn.style.cssText = _editStyle
            editBtn.onclick = _enterGroupEdit
            pushGroupUndo()
            const gs = store.getState().strandGroups
            store.setState({ strandGroups: gs.map(g => g.id === group.id ? { ...g, name: newName } : g) })
          }
          nameInput.addEventListener('keydown', e => {
            if (e.key === 'Enter')  { e.preventDefault(); _save() }
            if (e.key === 'Escape') {
              nameInput.replaceWith(nameSpan)
              editBtn.textContent = '✎'
              editBtn.title = 'Rename group'
              editBtn.style.cssText = _editStyle
              editBtn.onclick = _enterGroupEdit
            }
          })
          editBtn.onclick = _save
        }
        editBtn.onclick = _enterGroupEdit

        // Color picker
        const colorInput = document.createElement('input')
        colorInput.type  = 'color'
        colorInput.value = group.color ?? '#74b9ff'
        colorInput.title = 'Group color'
        colorInput.style.cssText = 'width:28px;height:22px;border:none;background:none;cursor:pointer;padding:0'
        colorInput.addEventListener('change', () => {
          pushGroupUndo()
          const gs = store.getState().strandGroups
          store.setState({ strandGroups: gs.map(g => g.id === group.id ? { ...g, color: colorInput.value } : g) })
        })

        // Strand count badge
        const countEl = document.createElement('span')
        countEl.textContent = `${group.strandIds.length}`
        countEl.title       = `${group.strandIds.length} strand(s)`
        countEl.style.cssText = 'color:#8b949e;font-size:10px;min-width:1.5em;text-align:center'

        // Delete button
        const delBtn = document.createElement('button')
        delBtn.textContent = '×'
        delBtn.title = 'Remove group'
        delBtn.style.cssText = _delStyle
        delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
        delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
        delBtn.addEventListener('click', () => {
          pushGroupUndo()
          const gs = store.getState().strandGroups
          store.setState({ strandGroups: gs.filter(g => g.id !== group.id) })
        })

        row.appendChild(nameSpan)
        row.appendChild(editBtn)
        row.appendChild(colorInput)
        row.appendChild(countEl)
        row.appendChild(delBtn)
        list.appendChild(row)
      }
    }

    newBtn.addEventListener('click', () => {
      pushGroupUndo()
      const { strandGroups } = store.getState()
      const n = strandGroups.length + 1
      const colors = ['#74b9ff', '#6bcb77', '#ff6b6b', '#ffd93d', '#a29bfe', '#55efc4']
      const color = colors[(n - 1) % colors.length]
      store.setState({
        strandGroups: [...strandGroups, { id: `grp_${Date.now()}`, name: `Group ${n}`, color, strandIds: [] }],
      })
    })

    store.subscribe((newState, prevState) => {
      if (newState.strandGroups === prevState.strandGroups) return
      if (!_collapsed) _rebuildPanel(newState.strandGroups)
    })
  })()

  const sequenceOverlay = initSequenceOverlay(scene, store)

  const crossSectionMinimap = initCrossSectionMinimap(document.getElementById('viewport-container'))

  const viewCube = initViewCube(
    document.getElementById('viewport-container'),
    camera,
    controls,
    () => designRenderer.getHelixCtrl()?.root,
  )

  function _isUnfoldActive() { return store.getState().unfoldActive }

  function _toggleUnfold() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return
    if (isDeformActive()) return
    // Cannot enter unfold while deformed view is on AND the design has actual
    // deformations — if there are none, straight = deformed so it's safe to proceed.
    const hasDeformations = !!(currentDesign?.deformations?.length)
    if (!unfoldView.isActive() && deformView.isActive() && hasDeformations) {
      showToast('Press D to undeform before unfolding')
      return
    }
    // Stop physics before entering unfold — the two modes are incompatible.
    if (!unfoldView.isActive()) _stopPhysicsIfActive()
    unfoldView.toggle()
    const active = unfoldView.isActive()
    if (active) {
      // Aim the camera's orbit target at the design's Z midpoint so the
      // unfolded helices stay within the view frustum.  This prevents clipping
      // on imported designs with non-zero bp_start (e.g. axis_start.z ≈ 135 nm).
      // Helices are NOT translated in Z — only the camera target moves.
      const midZ = unfoldView.getMidZ()
      const dz = midZ - controls.target.z
      controls.target.z += dz
      camera.position.z += dz
      controls.update()
    }
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
    // Cannot turn off when there are no deformations or cluster transforms — deformed = straight.
    if (!currentDesign?.deformations?.length && !currentDesign?.cluster_transforms?.length) return
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
    onExtrude: async ({ cells, lengthBp, plane, offsetNm, continuationMode, deformedFrame, strandFilter = 'both' }) => {
      let result
      if (deformedFrame) {
        result = await api.addBundleDeformedContinuation({ cells, lengthBp, plane, frame: deformedFrame })
      } else if (continuationMode) {
        result = await api.addBundleContinuation({ cells, lengthBp, plane, offsetNm, strandFilter })
      } else {
        result = await api.addBundleSegment({ cells, lengthBp, plane, offsetNm, strandFilter })
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
    getDesign:      () => store.getState().currentDesign,
    getHelixAxes:   () => store.getState().currentHelixAxes,
    onOffsetChange: (offsetNm, plane) => {
      crossSectionMinimap.update(offsetNm, plane, designRenderer.getBackboneEntries())
      _updateSliceHighlights(offsetNm, plane)
    },
  })

  // ── Slice-plane backbone highlight ──────────────────────────────────────────
  // Colours all backbone beads at the slice plane's current bp position white,
  // restoring default colours when the plane moves or is hidden.

  let _sliceHighlightedEntries = []

  function _clearSliceHighlights() {
    for (const entry of _sliceHighlightedEntries) {
      designRenderer.setEntryColor(entry, entry.defaultColor)
    }
    _sliceHighlightedEntries = []
  }

  function _updateSliceHighlights(offsetNm, plane) {
    _clearSliceHighlights()
    const design  = store.getState().currentDesign
    if (!design) return
    const normalAxis = { XY: 'z', XZ: 'y', YZ: 'x' }[plane] ?? 'z'
    // Build a Set of "helixId::bpIndex" keys for quick matching.
    const targetKeys = new Set()
    for (const helix of design.helices) {
      const z0 = helix.axis_start[normalAxis]
      const bp = Math.round(helix.bp_start + (offsetNm - z0) / BDNA_RISE_PER_BP)
      if (bp < helix.bp_start || bp >= helix.bp_start + helix.length_bp) continue
      targetKeys.add(`${helix.id}::${bp}`)
    }
    if (!targetKeys.size) return
    for (const entry of designRenderer.getBackboneEntries()) {
      if (targetKeys.has(`${entry.nuc.helix_id}::${entry.nuc.bp_index}`)) {
        designRenderer.setEntryColor(entry, 0xffffff)
        _sliceHighlightedEntries.push(entry)
      }
    }
    for (const entry of designRenderer.getSlabEntries()) {
      if (targetKeys.has(`${entry.nuc.helix_id}::${entry.nuc.bp_index}`)) {
        designRenderer.setEntryColor(entry, 0xffffff)
        _sliceHighlightedEntries.push(entry)
      }
    }
  }

  function _toggleSlicePlane() {
    if (_isUnfoldActive()) return   // slice plane disabled in unfold mode
    if (slicePlane.isVisible()) {
      slicePlane.hide()
      crossSectionMinimap.clearSlice()
      crossSectionMinimap.hide()
      _clearSliceHighlights()
      _setMenuToggle('menu-view-slice', false)
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      return
    }
    const { currentDesign, currentPlane } = store.getState()
    if (!currentDesign || !currentPlane) return
    const offset = _bundleMidOffset(currentDesign, currentPlane)
    slicePlane.show(currentPlane, offset, false, true)   // read-only: no lattice, no extrude
    crossSectionMinimap.show()
    _setMenuToggle('menu-view-slice', true)
    document.getElementById('mode-indicator').textContent =
      'SLICE PLANE — drag handle to reposition · Esc to close'
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
    onExtrude: async ({ cells, lengthBp, plane, strandFilter = 'both', latticeType = 'HONEYCOMB' }) => {
      const result = await api.createBundle({ cells, lengthBp, plane, strandFilter, latticeType })
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

  // Start with nothing visible — user must go through File > New Part first.
  workspace.hide()
  camera.position.set(6, 3, 18)
  controls.target.set(6, 3, 0)
  controls.update()

  // ── Welcome screen ────────────────────────────────────────────────────────────
  const _welcomeScreen = document.getElementById('welcome-screen')

  function _showWelcome() {
    _welcomeScreen?.classList.remove('hidden')
  }
  function _hideWelcome() {
    _welcomeScreen?.classList.add('hidden')
  }

  // Buttons on the welcome screen delegate to the existing menu actions
  document.getElementById('welcome-new-btn')?.addEventListener('click', () => {
    _openNewDesignModal()
  })
  document.getElementById('welcome-open-btn')?.addEventListener('click', () => {
    document.getElementById('menu-file-open')?.click()
  })

  // ── File open / save ─────────────────────────────────────────────────────────
  // Tracks the File System Access API file handle so Ctrl+S can overwrite
  // the same file without re-opening a dialog.  Null when no file is open or
  // when the browser doesn't support the File System Access API.
  let _fileHandle = null

  /** Clear per-file state (physics, slice plane, store) and return to workspace. */
  function _resetForNewDesign() {
    _clearScaffoldChecks()
    _clearStapleChecks()
    deformExitTool()
    // Deformed view stays ON after reset (it is always on by default).
    // If currently in straight view, reactivate before clearing state.
    if (!deformView.isActive()) deformView.activate()
    slicePlane.hide()
    bluntEnds.clear()
    crossoverLocations.setVisible(false)
    _stopPhysicsIfActive()
    _updatePhysicsPlayBtn()
    _setMenuToggle('menu-view-slice', false)
    _setMenuToggle('menu-view-loop-skip', false)
    _loopSkipLegend.style.display = 'none'
    store.setState({
      currentDesign: null, currentGeometry: null, currentHelixAxes: null,
      validationReport: null, currentPlane: null, strandColors: {},
      physicsMode: false, physicsPositions: null,
      femMode: false, femPositions: null, femRmsf: null, femStatus: 'idle', femStats: null,
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
  function _centerOnStrand(strandId) {
    const { currentGeometry } = store.getState()
    if (!currentGeometry) return
    const nucs = currentGeometry.filter(n => n.strand_id === strandId)
    if (!nucs.length) return
    let sx = 0, sy = 0, sz = 0
    for (const n of nucs) { sx += n.backbone_position[0]; sy += n.backbone_position[1]; sz += n.backbone_position[2] }
    const cx = sx / nucs.length, cy = sy / nucs.length, cz = sz / nucs.length
    const dist = camera.position.distanceTo(controls.target)
    const dir = camera.position.clone().sub(controls.target).normalize()
    controls.target.set(cx, cy, cz)
    camera.position.set(cx + dir.x * dist, cy + dir.y * dist, cz + dir.z * dist)
    controls.update()
  }

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
  function _openNewDesignModal() {
    const modal = document.getElementById('new-design-modal')
    if (!modal) {
      _resetForNewDesign(); _fileHandle = null; workspace.show()
      api.createDesign('Untitled')
      return
    }
    // Show unsaved-changes warning when a design with helices is already loaded
    const hasDesign = !!(store.getState().currentDesign?.helices?.length)
    const warn = document.getElementById('new-design-unsaved-warn')
    if (warn) warn.style.display = hasDesign ? 'block' : 'none'
    // Reset name field
    const nameInput = document.getElementById('new-design-name')
    if (nameInput) nameInput.value = 'Untitled'
    modal.style.display = 'flex'
    // Focus the name field so the user can type immediately
    setTimeout(() => nameInput?.select(), 50)
  }

  document.getElementById('menu-file-new')?.addEventListener('click', _openNewDesignModal)

  document.getElementById('new-design-cancel')?.addEventListener('click', () => {
    document.getElementById('new-design-modal').style.display = 'none'
  })

  document.getElementById('new-design-modal')?.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.getElementById('new-design-modal').style.display = 'none'
    if (e.key === 'Enter')  document.getElementById('new-design-create')?.click()
  })

  document.getElementById('new-design-create')?.addEventListener('click', async () => {
    const modal   = document.getElementById('new-design-modal')
    const checked = modal.querySelector('input[name="new-lattice-type"]:checked')
    const lattice = checked?.value ?? 'HONEYCOMB'
    const name    = document.getElementById('new-design-name')?.value.trim() || 'Untitled'
    modal.style.display = 'none'
    _resetForNewDesign()
    _fileHandle = null
    _hideWelcome()
    workspace.show(lattice)
    camera.position.set(6, 3, 18)
    controls.target.set(6, 3, 0)
    controls.update()
    await api.createDesign(name, lattice)
  })

  document.getElementById('menu-file-open')?.addEventListener('click', async () => {
    const picked = await _pickOpenFile()
    if (!picked) return
    _resetForNewDesign()
    const result = await api.importDesign(picked.content)
    if (!result) {
      alert('Failed to open design: ' + (store.getState().lastError?.message ?? 'Unknown error'))
      _showWelcome()
      return
    }
    _hideWelcome()
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
    if (popGroupUndo()) return
    const result = await api.undo()
    if (!result) {
      const err = store.getState().lastError
      if (err?.status === 404) alert('Nothing to undo.')
    } else {
      _clearScaffoldChecks()
      _clearStapleChecks()
      // Topology changed — reset physics to pick up new strand connectivity.
      if (store.getState().physicsMode) physicsClient.reset()
      const { currentDesign } = store.getState()
      // If we undid back to an empty design, return to workspace.
      if (!currentDesign?.helices?.length) {
        slicePlane.hide()
        workspace.show()
        _showWelcome()
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
    } else {
      _clearScaffoldChecks()
      _clearStapleChecks()
    }
  })

  // ── caDNAno routing-change warning dialog ─────────────────────────────────
  /**
   * Show a warning that the operation will overwrite the imported caDNAno staple
   * routing.  Returns a Promise<boolean> — true if the user clicks Continue.
   */
  function _confirmCadnanoRoutingChange() {
    return new Promise(resolve => {
      const overlay = document.createElement('div')
      overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:10000',
        'background:rgba(0,0,0,0.55)',
        'display:flex', 'align-items:center', 'justify-content:center',
      ].join(';')

      const box = document.createElement('div')
      box.style.cssText = [
        'background:#1e2a35', 'border:1px solid #37474f',
        'border-radius:8px', 'padding:24px 28px', 'max-width:380px',
        'font-family:sans-serif', 'color:#cfd8dc',
        'box-shadow:0 8px 32px rgba(0,0,0,0.6)',
      ].join(';')

      const title = document.createElement('div')
      title.textContent = 'Overwrite caDNAno staple routing?'
      title.style.cssText = 'font-size:15px;font-weight:600;color:#eceff1;margin-bottom:10px'

      const msg = document.createElement('div')
      msg.textContent = 'This operation will change the staple routing imported from caDNAno. The existing staple breaks and crossovers may be replaced. Do you want to continue?'
      msg.style.cssText = 'font-size:13px;line-height:1.5;margin-bottom:20px'

      const btnRow = document.createElement('div')
      btnRow.style.cssText = 'display:flex;gap:10px;justify-content:flex-end'

      const btnCancel = document.createElement('button')
      btnCancel.textContent = 'Cancel'
      btnCancel.style.cssText = [
        'padding:7px 18px', 'border-radius:5px', 'border:1px solid #455a64',
        'background:#263238', 'color:#b0bec5', 'cursor:pointer', 'font-size:13px',
      ].join(';')

      const btnContinue = document.createElement('button')
      btnContinue.textContent = 'Continue'
      btnContinue.style.cssText = [
        'padding:7px 18px', 'border-radius:5px', 'border:none',
        'background:#0288d1', 'color:#fff', 'cursor:pointer', 'font-size:13px',
        'font-weight:600',
      ].join(';')

      const cleanup = () => document.body.removeChild(overlay)

      btnCancel.addEventListener('click', () => { cleanup(); resolve(false) })
      btnContinue.addEventListener('click', () => { cleanup(); resolve(true) })
      overlay.addEventListener('click', e => { if (e.target === overlay) { cleanup(); resolve(false) } })

      btnRow.append(btnCancel, btnContinue)
      box.append(title, msg, btnRow)
      overlay.appendChild(box)
      document.body.appendChild(overlay)
      btnContinue.focus()
    })
  }

  // ── Operation progress popup helpers ──────────────────────────────────────
  const _apProgress = document.getElementById('op-progress')
  const _apFill     = document.getElementById('op-progress-fill')
  const _apLabel    = document.getElementById('op-progress-label')
  const _apHeader   = document.getElementById('op-progress-header')


  function _showProgress(header, label) {
    if (_apHeader) _apHeader.textContent = header ?? 'Working…'
    _apLabel.textContent = label ?? ''
    _apFill.style.width  = '0%'
    _apProgress.classList.add('visible')
  }
  function _hideProgress() {
    _apProgress.classList.remove('visible')
  }

  // ── FEM Analysis panel ────────────────────────────────────────────────────
  ;(function _initFemPanel() {
    const _statusText  = document.getElementById('fem-status-text')
    const _progressWrap = document.getElementById('fem-progress-wrap')
    const _progressFill = document.getElementById('fem-progress-fill')
    const _stageLabel  = document.getElementById('fem-stage-label')
    const _resultsDiv  = document.getElementById('fem-results')
    const _statsDiv    = document.getElementById('fem-stats')
    const _chkShape    = document.getElementById('fem-show-shape')
    const _chkRmsf     = document.getElementById('fem-show-rmsf')
    const _rmsfLegend  = document.getElementById('fem-rmsf-legend')

    // Stage labels shown in the progress bar.
    const _STAGE_LABELS = {
      building_mesh: 'Building mesh…',
      assembling:    'Assembling stiffness matrix…',
      solving:       'Solving equilibrium…',
      rmsf:          'Computing RMSF (eigenmodes)…',
      packaging:     'Packaging results…',
      done:          'Done',
    }

    function _setStatus(text, color = '#8b949e') {
      if (_statusText) { _statusText.textContent = text; _statusText.style.color = color }
    }

    function _showProgress(pct, stage) {
      if (_progressWrap) _progressWrap.style.display = 'block'
      if (_progressFill) _progressFill.style.width   = pct + '%'
      if (_stageLabel)   _stageLabel.textContent      = _STAGE_LABELS[stage] ?? stage
    }

    function _hideProgressBar() {
      if (_progressWrap) _progressWrap.style.display = 'none'
    }

    function _showResults(stats) {
      if (_resultsDiv) _resultsDiv.style.display = 'block'
      if (_statsDiv) {
        _statsDiv.innerHTML =
          `nodes: ${stats.n_nodes} &nbsp;·&nbsp; ` +
          `elements: ${stats.n_elements} &nbsp;·&nbsp; ` +
          `crossovers: ${stats.n_crossovers}` +
          (stats.n_ssdna_springs > 0
            ? ` &nbsp;·&nbsp; ssDNA springs: ${stats.n_ssdna_springs}`
            : '')
      }
    }

    function _clearOverlay() {
      designRenderer.clearFemOverlay()
      if (_chkShape)   _chkShape.checked  = false
      if (_chkRmsf)    _chkRmsf.checked   = false
      if (_rmsfLegend) _rmsfLegend.style.display = 'none'
    }

    const femClient = initFemClient({
      onProgress(stage, pct) {
        store.setState({ femStatus: 'running' })
        _setStatus('Running…', '#58a6ff')
        _showProgress(pct, stage)
      },
      onResult(msg) {
        // Build position lookup keyed by "helix_id:bp_index:direction".
        const posMap = {}
        for (const p of msg.positions) {
          posMap[`${p.helix_id}:${p.bp_index}:${p.direction}`] = p.backbone_position
        }
        store.setState({
          femPositions: posMap,
          femRmsf:      msg.rmsf,
          femStatus:    'done',
          femStats:     msg.stats,
        })
        _hideProgressBar()
        _setStatus('Done', '#3fb950')
        _showResults(msg.stats)
      },
      onError(message) {
        store.setState({ femStatus: 'error', femPositions: null, femRmsf: null })
        _hideProgressBar()
        _setStatus('Error', '#f85149')
        alert('FEM failed: ' + message)
      },
    })

    document.getElementById('btn-fem-run')?.addEventListener('click', () => {
      if (!store.getState().currentDesign?.helices?.length) {
        alert('No design loaded.'); return
      }
      // Reset UI state.
      store.setState({ femStatus: 'running', femPositions: null, femRmsf: null, femStats: null })
      _clearOverlay()
      if (_resultsDiv) _resultsDiv.style.display = 'none'
      _setStatus('Running…', '#58a6ff')
      _showProgress(0, 'building_mesh')
      femClient.run()
    })

    _chkShape?.addEventListener('change', () => {
      const { femPositions } = store.getState()
      if (_chkShape.checked && femPositions) {
        // Convert posMap back to the array format applyFemPositions expects.
        const updates = Object.entries(femPositions).map(([key, pos]) => {
          const [helix_id, bp_index, direction] = key.split(':')
          return { helix_id, bp_index: Number(bp_index), direction, backbone_position: pos }
        })
        designRenderer.applyFemPositions(updates)
        store.setState({ femMode: true })
      } else {
        designRenderer.clearFemOverlay()
        // If RMSF is still on, re-apply colours after geometry revert.
        if (_chkRmsf?.checked) {
          const { femRmsf } = store.getState()
          if (femRmsf) designRenderer.applyFemRmsf(femRmsf)
        }
        store.setState({ femMode: false })
      }
    })

    _chkRmsf?.addEventListener('change', () => {
      if (_chkRmsf.checked) {
        const { femRmsf } = store.getState()
        if (femRmsf) designRenderer.applyFemRmsf(femRmsf)
        if (_rmsfLegend) _rmsfLegend.style.display = 'block'
      } else {
        _helixCtrl_clearColors()
        if (_rmsfLegend) _rmsfLegend.style.display = 'none'
      }
    })

    function _helixCtrl_clearColors() {
      designRenderer.getHelixCtrl()?.clearFemColors()
    }

    // Clear FEM overlay whenever the design changes (results are stale).
    store.subscribe((newState, prevState) => {
      if (newState.currentDesign !== prevState.currentDesign) {
        femClient.cancel()
        store.setState({ femMode: false, femPositions: null, femRmsf: null,
                         femStatus: 'idle', femStats: null })
        _clearOverlay()
        if (_resultsDiv)  _resultsDiv.style.display  = 'none'
        if (_progressWrap) _progressWrap.style.display = 'none'
        _setStatus('Idle', '#8b949e')
      }
    })
  })()

  // ── Routing: Scaffold ─────────────────────────────────────────────────────
  document.getElementById('menu-routing-scaffold-ends')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    const isSquare = currentDesign.helices?.length &&
      Math.abs(currentDesign.helices[0].twist_per_bp_rad - (3 * 2 * Math.PI / 32)) < 1e-4
    const raw = prompt('Autoscaffold — extension length (bp):', isSquare ? '8' : '7')
    if (raw === null) return
    const lengthBp = parseInt(raw, 10)
    if (isNaN(lengthBp) || lengthBp < 1) { alert('Enter a positive integer number of base pairs.'); return }
    _showProgress('Autoscaffold — extending near end…')
    const nearOk = await api.scaffoldExtrudeNear(lengthBp)
    if (!nearOk) {
      _hideProgress()
      alert('Autoscaffold failed (near extrude): ' + (store.getState().lastError?.message ?? 'unknown'))
      return
    }
    _showProgress('Autoscaffold — extending far end…')
    const farOk = await api.scaffoldExtrudeFar(lengthBp)
    if (!farOk) {
      _hideProgress()
      alert('Autoscaffold failed (far extrude): ' + (store.getState().lastError?.message ?? 'unknown'))
      return
    }
    // Re-run seam routing on the extended helices so that U-shape strand endpoints
    // land exactly at bp 0 and bp L-1 of the extended geometry — required for
    // scaffold_add_end_crossovers to correctly find and ligate those endpoints.
    _showProgress('Autoscaffold — routing seam…')
    const seamOk = await api.autoScaffold('seam_line', { scaffoldLoops: false })
    if (!seamOk) {
      _hideProgress()
      alert('Autoscaffold failed (seam route): ' + (store.getState().lastError?.message ?? 'unknown'))
      return
    }
    _showProgress('Autoscaffold — adding end crossovers…')
    const xoverOk = await api.scaffoldAddEndCrossovers()
    _hideProgress()
    if (!xoverOk) {
      alert('Autoscaffold failed (end crossovers): ' + (store.getState().lastError?.message ?? 'unknown'))
    } else {
      _setRoutingCheck('scaffoldEnds', true)
    }
  })

  // ── Routing: Staples — shared sub-operations ──────────────────────────────
  async function _runPrebreak() {
    if (!store.getState().currentDesign?.helices?.length) { alert('No design loaded.'); return false }
    _showProgress('Prebreak', 'Nicking staples at all crossover positions…')
    const result = await api.prebreak()
    _hideProgress()
    if (!result) {
      alert('Prebreak failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
      return false
    }
    _setRoutingCheck('prebreak', true)
    return true
  }

  async function _runAutoCrossover() {
    if (!store.getState().currentDesign?.helices?.length) { alert('No design loaded.'); return false }
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
      alert('Auto Crossover failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
      return false
    }
    _setRoutingCheck('autoCrossover', true)
    return true
  }

  document.getElementById('menu-routing-prebreak')?.addEventListener('click', _runPrebreak)

  document.getElementById('menu-routing-auto-crossover')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign?.helices?.length) { alert('No design loaded.'); return }
    if (store.getState().isCadnanoImport) {
      if (!await _confirmCadnanoRoutingChange()) return
      store.setState({ isCadnanoImport: false })
    }
    if (!_routingChecks.prebreak) { if (!await _runPrebreak()) return }
    await _runAutoCrossover()
  })

  document.getElementById('menu-routing-auto-merge')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign?.helices?.length) { alert('No design loaded.'); return }
    if (store.getState().isCadnanoImport) {
      if (!await _confirmCadnanoRoutingChange()) return
      store.setState({ isCadnanoImport: false })
    }
    if (!_routingChecks.prebreak)      { if (!await _runPrebreak())       return }
    if (!_routingChecks.autoCrossover) { if (!await _runAutoCrossover())  return }
    const result = await api.addAutoMerge()
    if (!result) {
      alert('Auto Merge failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
    } else {
      _setRoutingCheck('autoMerge', true)
    }
  })

  // ── Sequencing ────────────────────────────────────────────────────────────
  document.getElementById('menu-seq-assign-scaffold')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    _showProgress('Assigning M13MP18 scaffold sequence…')
    const ok = await api.assignScaffoldSequence()
    _hideProgress()
    if (!ok) alert('Assign scaffold sequence failed: ' + (store.getState().lastError?.message ?? 'unknown'))
  })

  document.getElementById('menu-seq-assign-staples')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    const scaffold = currentDesign.strands?.find(s => s.strand_type === 'scaffold')
    if (!scaffold?.sequence) {
      alert('Scaffold has no sequence. Run "Assign Scaffold Sequence" first.')
      return
    }
    _showProgress('Deriving complementary staple sequences…')
    const ok = await api.assignStapleSequences()
    _hideProgress()
    if (!ok) alert('Assign staple sequences failed: ' + (store.getState().lastError?.message ?? 'unknown'))
  })

  document.getElementById('menu-seq-update-routing')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.deformations?.length) { alert('No deformation ops on the current design.'); return }
    const hasCrossovers = currentDesign?.strands?.some(s =>
      s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
    )
    if (!hasCrossovers) { alert('Place crossovers first (Auto Crossover) before updating staple routing.'); return }
    _showProgress('Update Staple Routing', 'Applying loop/skip modifications…')
    const result = await api.applyAllDeformations()
    _hideProgress()
    if (!result) {
      alert('Update Staple Routing failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
    } else {
      showToast('Staple routing updated.')
    }
  })

  // Enable/disable "Update Staple Routing" based on whether crossovers exist.
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign === prevState.currentDesign) return
    const btn = document.getElementById('menu-seq-update-routing')
    if (!btn) return
    const hasCrossovers = newState.currentDesign?.strands?.some(s =>
      s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
    ) ?? false
    btn.disabled = !hasCrossovers
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

  document.getElementById('menu-view-axes')?.addEventListener('click', () => {
    originAxes.visible = !originAxes.visible
    _setMenuToggle('menu-view-axes', originAxes.visible)
  })

  // ── Orbit mode submenu (Turntable / Trackball) ──────────────────────────────
  let _orbitMode = 'trackball'
  function _setOrbitMode(mode) {
    _orbitMode = mode
    switchOrbitMode(mode)
    document.getElementById('menu-view-orbit-turntable')?.classList.toggle('is-checked', mode === 'turntable')
    document.getElementById('menu-view-orbit-trackball')?.classList.toggle('is-checked', mode === 'trackball')
  }
  document.getElementById('menu-view-orbit-turntable')?.addEventListener('click', () => _setOrbitMode('turntable'))
  document.getElementById('menu-view-orbit-trackball')?.addEventListener('click', () => _setOrbitMode('trackball'))
  _setOrbitMode('trackball')  // apply default at startup

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
    const active = debugOverlay.isActive()
    _setMenuToggle('menu-view-debug', active)
    store.setState({ debugOverlayActive: active })
  })

  document.getElementById('menu-view-sequences')?.addEventListener('click', () => {
    const { showSequences } = store.getState()
    store.setState({ showSequences: !showSequences })
    _setMenuToggle('menu-view-sequences', !showSequences)
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
    if (newState.physicsMode      !== prevState.physicsMode)      _setMenuToggle('menu-view-physics',      newState.physicsMode)
    if (newState.unfoldActive     !== prevState.unfoldActive)     _setMenuToggle('menu-view-unfold',       newState.unfoldActive)
    if (newState.deformVisuActive !== prevState.deformVisuActive) _setMenuToggle('menu-view-deform',       newState.deformVisuActive)
    if (newState.showHelixLabels  !== prevState.showHelixLabels)  _setMenuToggle('menu-view-helix-labels', newState.showHelixLabels)
    if (newState.showSequences    !== prevState.showSequences)    _setMenuToggle('menu-view-sequences',    newState.showSequences)
    if (newState.staplesHidden    !== prevState.staplesHidden)    _setMenuToggle('menu-view-hide-staples', newState.staplesHidden)
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

  // ── Tool Filter toggles (bluntEnds + crossoverLocations + overhangLocations) ──
  for (const key of ['bluntEnds', 'crossoverLocations', 'overhangLocations']) {
    const toggle = document.getElementById(`sel-toggle-${key}`)
    const row    = document.getElementById(`sel-row-${key}`)
    if (!toggle || !row) continue
    row.addEventListener('click', () => {
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, [key]: !tf[key] } })
    })
    store.subscribe(() => {
      toggle.classList.toggle('on', store.getState().toolFilters[key])
    })
  }

  // Sync toolFilters → tool visibility
  store.subscribe((newState, prevState) => {
    if (newState.toolFilters === prevState.toolFilters) return
    const tf = newState.toolFilters
    const prev = prevState.toolFilters ?? {}
    if (tf.crossoverLocations !== prev.crossoverLocations) {
      crossoverLocations.setVisible(tf.crossoverLocations)
      if (tf.crossoverLocations) {
        crossoverLocations.rebuild(store.getState().currentGeometry).then(() => unfoldView.reapplyIfActive())
      }
    }
    if (tf.overhangLocations !== prev.overhangLocations) {
      overhangLocations.setVisible(tf.overhangLocations)
      _setMenuToggle('menu-view-overhang-locations', tf.overhangLocations)
      if (tf.overhangLocations) {
        const { currentDesign, currentGeometry } = store.getState()
        overhangLocations.rebuild(currentDesign, currentGeometry)
      }
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
        selectableTypes: {
          scaffold: false, staples: false,
          strands: false, ends: false, crossoverArcs: false,
          loops: false, skips: false,
        },
      })
    } else {
      // Deform just deactivated — restore saved selection filter
      if (_savedSelectableTypes) {
        store.setState({ selectableTypes: _savedSelectableTypes })
        _savedSelectableTypes = null
      }
    }
  })

  // ── Selection Filter toggles ──────────────────────────────────────────────────
  const _allSelKeys = [
    'scaffold', 'staples',
    'strands', 'ends', 'crossoverArcs',
    'loops', 'skips',
  ]

  for (const key of _allSelKeys) {
    const toggle = document.getElementById(`sel-toggle-${key}`)
    const row    = document.getElementById(`sel-row-${key}`)
    if (!toggle || !row) continue

    const _update = () => {
      const { selectableTypes, deformToolActive, translateRotateActive } = store.getState()
      const locked = deformToolActive || translateRotateActive
      toggle.classList.toggle('on', selectableTypes[key])
      row.style.opacity       = locked ? '0.35' : '1'
      row.style.pointerEvents = locked ? 'none'  : ''
      row.title = locked ? 'Selection locked while a tool is active' : ''
    }
    row.addEventListener('click', () => {
      const { deformToolActive, translateRotateActive } = store.getState()
      if (deformToolActive || translateRotateActive) return
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
      if (popGroupUndo()) return
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
          _showWelcome()
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

    // 'S' — toggle spreadsheet panel
    if ((e.key === 's' || e.key === 'S') && !inInput) {
      spreadsheet.toggle()
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

    // Number hotkeys 1–6 — workflow shortcuts (routing → sequencing in order)
    // 1  Auto Scaffold Seam    (routing step 1)
    // 2  Prebreak              (routing step 2)
    // 3  Auto Crossover        (routing step 3)
    // 1  Autoscaffold          (routing step 1)
    // 2  Prebreak              (routing step 2)
    // 3  Auto Crossover        (routing step 3)
    // 4  Auto Merge            (routing step 4)
    // 5  Assign Scaffold Seq   (sequencing step 1)
    // 6  Assign Staple Seqs    (sequencing step 2)
    if (!inInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const _numHotkeyMap = {
        '1': 'menu-routing-scaffold-ends',
        '2': 'menu-routing-prebreak',
        '3': 'menu-routing-auto-crossover',
        '4': 'menu-routing-auto-merge',
        '5': 'menu-seq-assign-scaffold',
        '6': 'menu-seq-assign-staples',
      }
      const targetId = _numHotkeyMap[e.key]
      if (targetId) {
        e.preventDefault()
        const btn = document.getElementById(targetId)
        if (btn && !btn.disabled) btn.click()
        return
      }
    }

    // '`' — toggle debug hover overlay
    if (e.key === '`' && !inInput) {
      debugOverlay.toggle()
      const active = debugOverlay.isActive()
      _setMenuToggle('menu-view-debug', active)
      store.setState({ debugOverlayActive: active })
      return
    }

    // 'F' — fit entire structure in view
    if ((e.key === 'f' || e.key === 'F') && !inInput) {
      _fitToView()
      return
    }

    // 'M' — toggle distance measurement between 2 ctrl-clicked beads
    if ((e.key === 'm' || e.key === 'M') && !inInput) {
      e.preventDefault()
      if (store.getState().unfoldActive) {
        const el = document.getElementById('mode-indicator')
        if (el) {
          el.textContent = 'Measurement not available in unfold view'
          setTimeout(() => { el.textContent = 'NADOC · WORKSPACE' }, 2000)
        }
        return
      }
      if (_measActive) {
        _measClear()
        return
      }
      const cb = selectionManager.getCtrlBeads()
      if (cb.length === 2) {
        const posA = selectionManager.getCtrlBeadPos(0)
        const posB = selectionManager.getCtrlBeadPos(1)
        _measShow(posA, posB)
      }
      return
    }

    // 'B' — toggle blunt ends
    if ((e.key === 'b' || e.key === 'B') && !inInput) {
      e.preventDefault()
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, bluntEnds: !tf.bluntEnds } })
      return
    }

    // 'C' — toggle manual crossovers
    if ((e.key === 'c' || e.key === 'C') && !inInput) {
      e.preventDefault()
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, crossoverLocations: !tf.crossoverLocations } })
      return
    }

    // 'O' — toggle overhang locations
    if ((e.key === 'o' || e.key === 'O') && !inInput && !e.altKey && !(e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, overhangLocations: !tf.overhangLocations } })
      return
    }

    // Escape — exit force crossover selection, deformation tool, or slice plane
    if (e.key === 'Escape') {
      if (_measActive) { _measClear() }
      if (_fcBeads.length > 0) {
        _fcClear()
        return
      }
      if (_translateRotateActive) {
        _cancelTranslateRotateTool()
        return
      }
      if (isDeformActive()) {
        deformEscape()
        _watchDeformState()
        if (!isDeformActive()) {
          document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
        }
      } else if (slicePlane.isVisible()) {
        slicePlane.hide()
        crossSectionMinimap.clearSlice()
        crossSectionMinimap.hide()
        _clearSliceHighlights()
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
  const spreadsheet = initSpreadsheet(store, {
    designRenderer,
    selectionManager,
    goToStrand(strandId) {
      const geom = store.getState().currentGeometry
      if (!geom?.length) return
      const pts = geom.filter(n => n.strand_id === strandId)
      if (!pts.length) return
      let minX = Infinity, minY = Infinity, minZ = Infinity
      let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
      for (const n of pts) {
        const [x, y, z] = n.backbone_position
        if (x < minX) minX = x; if (x > maxX) maxX = x
        if (y < minY) minY = y; if (y > maxY) maxY = y
        if (z < minZ) minZ = z; if (z > maxZ) maxZ = z
      }
      const cx = (minX + maxX) * 0.5
      const cy = (minY + maxY) * 0.5
      const cz = (minZ + maxZ) * 0.5
      const radius = Math.max(maxX - minX, maxY - minY, maxZ - minZ) * 0.5
      const dist = Math.max((radius / Math.sin((camera.fov * 0.5) * Math.PI / 180)) * 1.3, 4)
      const dir = camera.position.clone().sub(controls.target).normalize()
      controls.target.set(cx, cy, cz)
      camera.position.set(cx + dir.x * dist, cy + dir.y * dist, cz + dir.z * dist)
      controls.update()
    },
  })

  // ── Translate/Rotate tool ─────────────────────────────────────────────────────
  // Euler↔quaternion helpers for transform fields (degrees, XYZ order)
  function _quatToEulerDeg(rotation) {
    const q = new THREE.Quaternion(rotation[0], rotation[1], rotation[2], rotation[3])
    const e = new THREE.Euler().setFromQuaternion(q, 'XYZ')
    const toDeg = r => r * (180 / Math.PI)
    return [toDeg(e.x), toDeg(e.y), toDeg(e.z)]
  }
  function _eulerDegToQuat(rx, ry, rz) {
    const toRad = d => d * (Math.PI / 180)
    const e = new THREE.Euler(toRad(rx), toRad(ry), toRad(rz), 'XYZ')
    const q = new THREE.Quaternion().setFromEuler(e)
    return [q.x, q.y, q.z, q.w]
  }

  const clusterGizmo    = initClusterGizmo(
    store, controls,
    (helixIds, centerVec, dummyPos, incrRotQuat) => {
      designRenderer.getHelixCtrl()?.applyClusterTransform(helixIds, centerVec, dummyPos, incrRotQuat)
    },
    (helixIds) => {
      designRenderer.getHelixCtrl()?.captureClusterBase(helixIds)
    },
    (translation, quaternion) => {
      const [rx, ry, rz] = _quatToEulerDeg([quaternion.x, quaternion.y, quaternion.z, quaternion.w])
      clusterPanel?.setTransformValues(translation[0], translation[1], translation[2], rx, ry, rz)
    },
  )
  // Cyan glow layer for active-cluster highlight (distinct from the green selection glow).
  const clusterGlowLayer = createGlowLayer(scene, 0x58a6ff)
  let _translateRotateActive = false

  // Checkmark confirm button (bottom-left, shown only when tool is active)
  const _confirmBtn = document.createElement('div')
  _confirmBtn.style.cssText = [
    'position:fixed;bottom:24px;left:24px;display:none',
    'width:56px;height:56px;border-radius:50%',
    'background:#1a6b2a;border:3px solid #2ea043',
    'cursor:pointer;align-items:center;justify-content:center',
    'font-size:30px;color:#fff;z-index:9000',
    'box-shadow:0 2px 16px rgba(46,160,67,0.5)',
    'transition:background 0.12s,transform 0.1s;user-select:none',
  ].join(';')
  _confirmBtn.textContent = '✓'
  _confirmBtn.title = 'Confirm transforms and exit tool'
  _confirmBtn.addEventListener('mouseenter', () => { _confirmBtn.style.background = '#2ea043'; _confirmBtn.style.transform = 'scale(1.08)' })
  _confirmBtn.addEventListener('mouseleave', () => { _confirmBtn.style.background = '#1a6b2a'; _confirmBtn.style.transform = 'scale(1)' })
  document.body.appendChild(_confirmBtn)

  async function _activateTranslateRotateTool() {
    const { currentDesign } = store.getState()
    const clusters = currentDesign?.cluster_transforms ?? []
    if (!clusters.length) {
      alert('No movable clusters exist. Create a cluster first by multi-selecting strands, then using the Movable Clusters panel.')
      return
    }
    _stopPhysicsIfActive()
    _translateRotateActive = true
    store.setState({ translateRotateActive: true })
    document.getElementById('mode-indicator').textContent = 'MOVE — Tab: translate/rotate · ✓: confirm · Esc: cancel'

    // Snapshot for single-undo on the session
    await api.snapshotDesign()

    // Attach gizmo to the currently highlighted cluster, or fall back to first.
    const { activeClusterId } = store.getState()
    const first = (activeClusterId && clusters.find(c => c.id === activeClusterId)) ?? clusters[0]
    // Only compute and set the pivot on very first activation (stored pivot is still [0,0,0]).
    // On re-activation the existing pivot + translation already place the dummy correctly;
    // re-computing from already-transformed geometry would set pivot = visual centroid and
    // double the stored translation → gizmo appears at 2× distance from origin.
    if (first.pivot.every(v => v === 0)) {
      const pivot = clusterGizmo.computePivot(first.id)
      await api.patchCluster(first.id, { pivot })
    }
    clusterGizmo.attach(first.id, scene, camera, canvas)

    _confirmBtn.style.display = 'flex'
  }

  async function _confirmTranslateRotateTool() {
    if (!_translateRotateActive) return
    _translateRotateActive = false
    store.setState({ translateRotateActive: false })
    clusterGizmo.detach()
    _confirmBtn.style.display = 'none'
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  }

  async function _cancelTranslateRotateTool() {
    if (!_translateRotateActive) return
    _translateRotateActive = false
    store.setState({ translateRotateActive: false })
    clusterGizmo.detach()
    _confirmBtn.style.display = 'none'
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    // Revert to pre-tool state via undo
    await api.undo()
  }

  _confirmBtn.addEventListener('click', _confirmTranslateRotateTool)

  document.getElementById('menu-tools-translate-rotate')?.addEventListener('click', () => {
    _activateTranslateRotateTool()
  })

  let clusterPanel = null
  clusterPanel = initClusterPanel(store, {
    onClusterClick: async (clusterId) => {
      if (!_translateRotateActive) {
        // Simple highlight toggle — no gizmo, no API calls.
        const current = store.getState().activeClusterId
        store.setState({ activeClusterId: current === clusterId ? null : clusterId })
        return
      }
      // Tool active: switch gizmo to the clicked cluster.
      if (clusterId === store.getState().activeClusterId) return
      const cluster = store.getState().currentDesign?.cluster_transforms?.find(c => c.id === clusterId)
      if (cluster?.pivot.every(v => v === 0)) {
        const pivot = clusterGizmo.computePivot(clusterId)
        await api.patchCluster(clusterId, { pivot })
      }
      clusterGizmo.attach(clusterId, scene, camera, canvas)
    },
    api,
    onTransformEdit: (tx, ty, tz, rx, ry, rz) => {
      if (!clusterGizmo.isActive()) return
      const rotation = _eulerDegToQuat(rx, ry, rz)
      clusterGizmo.setTransform([tx, ty, tz], rotation)
    },
  })

  // Populate transform fields with current cluster values when gizmo activates.
  store.subscribe((newState, prevState) => {
    if (newState.activeClusterId === prevState.activeClusterId) return
    if (!newState.activeClusterId || !newState.translateRotateActive) return
    const cluster = newState.currentDesign?.cluster_transforms?.find(c => c.id === newState.activeClusterId)
    if (!cluster) return
    const [rx, ry, rz] = _quatToEulerDeg(cluster.rotation)
    clusterPanel?.setTransformValues(cluster.translation[0], cluster.translation[1], cluster.translation[2], rx, ry, rz)
  })

  // Save/restore selectableTypes when translate/rotate tool activates/deactivates.
  let _savedClusterST = null
  store.subscribe((newState, prevState) => {
    if (newState.translateRotateActive === prevState.translateRotateActive) return
    if (newState.translateRotateActive) {
      _savedClusterST = { ...newState.selectableTypes }
      store.setState({
        selectableTypes: {
          scaffold: true, staples: true,
          strands: true, ends: false, crossoverArcs: false,
          loops: false, skips: false,
        },
      })
    } else {
      if (_savedClusterST) {
        store.setState({ selectableTypes: _savedClusterST })
        _savedClusterST = null
      }
    }
  })

  // When a strand is clicked while the tool is active, switch to that strand's cluster (if any).
  store.subscribe((newState, prevState) => {
    if (!_translateRotateActive) return
    if (newState.selectedObject === prevState.selectedObject) return
    const strandId = newState.selectedObject?.data?.strand_id
    if (!strandId) return
    const design = newState.currentDesign
    if (!design) return
    const helixIds = helixIdsFromStrandIds([strandId], design)
    const cluster = design.cluster_transforms?.find(c => c.helix_ids.some(h => helixIds.includes(h)))
    if (!cluster || cluster.id === newState.activeClusterId) return
    if (cluster.pivot.every(v => v === 0)) {
      const pivot = clusterGizmo.computePivot(cluster.id)
      api.patchCluster(cluster.id, { pivot }).then(() => {
        clusterGizmo.attach(cluster.id, scene, camera, canvas)
      })
    } else {
      clusterGizmo.attach(cluster.id, scene, camera, canvas)
    }
  })

  // Mutual exclusion: cancel translate/rotate when deform tool or physics starts.
  store.subscribe((newState, prevState) => {
    if (newState.deformToolActive && !prevState.deformToolActive && _translateRotateActive) {
      _cancelTranslateRotateTool()
    }
    if (newState.physicsMode && !prevState.physicsMode && _translateRotateActive) {
      _cancelTranslateRotateTool()
    }
  })

  // Cluster highlight — cyan glow on the active cluster's backbone beads.
  // Re-applies after every geometry rebuild so glow entries stay in sync.
  store.subscribe((newState, prevState) => {
    const activeId = newState.activeClusterId
    if (!activeId) {
      if (prevState.activeClusterId) clusterGlowLayer.clear()
      return
    }
    // Update when active cluster changes or geometry rebuilds (new bead entries).
    if (activeId === prevState.activeClusterId &&
        newState.currentGeometry === prevState.currentGeometry) return
    const cluster = newState.currentDesign?.cluster_transforms?.find(c => c.id === activeId)
    if (!cluster) { clusterGlowLayer.clear(); return }
    const helixSet = new Set(cluster.helix_ids)
    const entries  = designRenderer.getBackboneEntries().filter(e => helixSet.has(e.nuc.helix_id))
    clusterGlowLayer.setEntries(entries)
  })

  const { runScript } = createScriptRunner({
    slicePlane, bluntEnds, workspace, camera, controls,
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

    function _strandLength(strand, design) {
      const helixById = Object.fromEntries((design?.helices ?? []).map(h => [h.id, h]))
      let t = 0
      for (const d of strand.domains) {
        const span = Math.abs(d.end_bp - d.start_bp) + 1
        const helix = helixById[d.helix_id]
        const lo = Math.min(d.start_bp, d.end_bp)
        const hi = Math.max(d.start_bp, d.end_bp)
        const skipDelta = helix?.loop_skips
          ?.filter(ls => ls.bp_index >= lo && ls.bp_index <= hi)
          ?.reduce((s, ls) => s + ls.delta, 0) ?? 0
        t += span + skipDelta
      }
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
      const staples = design.strands.filter(s => s.strand_type === 'staple')
      if (staples.length === 0) { summary.textContent = 'No staple strands.'; return }

      const byLength = new Map()
      for (const s of staples) {
        const len = _strandLength(s, design)
        if (!byLength.has(len)) byLength.set(len, [])
        byLength.get(len).push(s.id)
      }

      const lengths  = [...byLength.keys()].sort((a, b) => a - b)
      const minLen   = lengths[0]
      const maxLen   = lengths[lengths.length - 1]
      const maxCount = Math.max(...[...byLength.values()].map(v => v.length))

      // Count in-range
      const nOk   = staples.filter(s => { const l = _strandLength(s, design); return l >= 18 && l <= 50 }).length
      const nShort = staples.filter(s => _strandLength(s, design) < 18).length
      const nLong  = staples.filter(s => _strandLength(s, design) > 50).length
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
          _centerOnStrand(strandId)
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


  // ── Import caDNAno ─────────────────────────────────────────────────────────────
  document.getElementById('menu-file-import-cadnano')?.addEventListener('click', () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const content = await file.text()
      _resetForNewDesign()
      const result = await api.importCadnanoDesign(content)
      if (!result) {
        alert('Failed to import caDNAno file: ' + (store.getState().lastError?.message ?? 'Unknown error'))
        _showWelcome()
        return
      }
      _hideWelcome()
      workspace.hide()
      if (result.import_warnings?.length) {
        showToast(result.import_warnings.join(' | '), 5000)
      }
    }
    input.click()
  })

  // ── Export Sequences (CSV) ─────────────────────────────────────────────────────
  document.getElementById('menu-file-export-seq-csv')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    const ok = await api.exportSequenceCsv()
    if (!ok) alert('Export failed: ' + (store.getState().lastError?.message ?? 'unknown'))
  })

  // ── Export caDNAno (.json) ─────────────────────────────────────────────────────
  document.getElementById('menu-file-export-cadnano')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    const ok = await api.exportCadnano()
    if (!ok) alert('Export failed: ' + (store.getState().lastError?.message ?? 'unknown'))
  })

  // ── Export PDB for NAMD ────────────────────────────────────────────────────────
  document.getElementById('menu-file-export-pdb')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    const a = document.createElement('a')
    a.href = '/api/design/export/pdb'
    a.download = ''
    a.click()
  })

  // ── Export PSF for NAMD ────────────────────────────────────────────────────────
  document.getElementById('menu-file-export-psf')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    const a = document.createElement('a')
    a.href = '/api/design/export/psf'
    a.download = ''
    a.click()
  })

  // ── Export NAMD complete package ──────────────────────────────────────────────
  document.getElementById('menu-file-export-namd-complete')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }

    // Trigger the download immediately — don't make the user wait for the prompt fetch.
    const a = document.createElement('a')
    a.href = '/api/design/export/namd-complete'
    a.download = ''
    a.click()

    // Fetch and display the AI assistant prompt in a popup.
    let promptText = null
    try {
      const r = await fetch('/api/design/export/namd-prompt')
      if (r.ok) promptText = await r.text()
    } catch (_) { /* non-fatal */ }
    if (!promptText) return

    // ── Modal ──────────────────────────────────────────────────────────────────
    const overlay = document.createElement('div')
    overlay.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:10001',
      'background:rgba(0,0,0,0.65)',
      'display:flex', 'align-items:center', 'justify-content:center',
      'padding:24px', 'box-sizing:border-box',
    ].join(';')

    const box = document.createElement('div')
    box.style.cssText = [
      'background:#1a2530', 'border:1px solid #37474f',
      'border-radius:10px', 'padding:0',
      'width:min(740px,100%)', 'max-height:85vh',
      'display:flex', 'flex-direction:column',
      'font-family:sans-serif', 'color:#cfd8dc',
      'box-shadow:0 12px 48px rgba(0,0,0,0.7)',
    ].join(';')

    const header = document.createElement('div')
    header.style.cssText = [
      'padding:18px 22px 14px', 'border-bottom:1px solid #263238',
      'display:flex', 'align-items:flex-start', 'gap:12px',
    ].join(';')

    const headerText = document.createElement('div')
    headerText.style.cssText = 'flex:1'

    const title = document.createElement('div')
    title.textContent = 'AI Assistant Prompt'
    title.style.cssText = 'font-size:15px;font-weight:700;color:#eceff1;margin-bottom:4px'

    const subtitle = document.createElement('div')
    subtitle.textContent = 'Paste into VS Code Copilot Chat, Claude, ChatGPT, or any LLM for step-by-step simulation guidance. Also included as AI_ASSISTANT_PROMPT.txt inside the ZIP.'
    subtitle.style.cssText = 'font-size:12px;color:#78909c;line-height:1.45'

    headerText.append(title, subtitle)

    const btnClose = document.createElement('button')
    btnClose.textContent = '✕'
    btnClose.style.cssText = [
      'background:none', 'border:none', 'color:#78909c',
      'font-size:18px', 'cursor:pointer', 'padding:0 2px',
      'line-height:1', 'flex-shrink:0', 'margin-top:1px',
    ].join(';')

    header.append(headerText, btnClose)

    const pre = document.createElement('textarea')
    pre.readOnly = true
    pre.value = promptText
    pre.style.cssText = [
      'flex:1', 'overflow:auto', 'margin:0',
      'padding:16px 20px', 'background:#111c24',
      'border:none', 'border-radius:0',
      'color:#b0bec5', 'font-family:"Cascadia Code","Fira Mono",monospace',
      'font-size:11.5px', 'line-height:1.6',
      'resize:none', 'outline:none',
      'white-space:pre', 'min-height:0',
    ].join(';')

    const footer = document.createElement('div')
    footer.style.cssText = [
      'padding:12px 22px', 'border-top:1px solid #263238',
      'display:flex', 'justify-content:flex-end', 'gap:10px',
    ].join(';')

    const btnCopy = document.createElement('button')
    btnCopy.textContent = 'Copy to Clipboard'
    btnCopy.style.cssText = [
      'padding:8px 20px', 'border-radius:5px', 'border:none',
      'background:#0288d1', 'color:#fff', 'cursor:pointer',
      'font-size:13px', 'font-weight:600',
    ].join(';')

    const btnDone = document.createElement('button')
    btnDone.textContent = 'Close'
    btnDone.style.cssText = [
      'padding:8px 18px', 'border-radius:5px',
      'border:1px solid #455a64',
      'background:#263238', 'color:#b0bec5',
      'cursor:pointer', 'font-size:13px',
    ].join(';')

    const cleanup = () => document.body.removeChild(overlay)

    btnCopy.addEventListener('click', async () => {
      await navigator.clipboard.writeText(promptText).catch(() => {
        pre.select()
        document.execCommand('copy')
      })
      btnCopy.textContent = 'Copied!'
      setTimeout(() => { btnCopy.textContent = 'Copy to Clipboard' }, 2000)
    })
    btnClose.addEventListener('click', cleanup)
    btnDone.addEventListener('click', cleanup)
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup() })

    footer.append(btnCopy, btnDone)
    box.append(header, pre, footer)
    overlay.appendChild(box)
    document.body.appendChild(overlay)
    pre.focus()
  })

  // ── Atomistic / Representation submenu — radio selection ─────────────────────
  const _ATOMISTIC_MODES = [
    { id: 'menu-view-atomistic-off',       mode: 'off'       },
    { id: 'menu-view-atomistic-vdw',       mode: 'vdw'       },
    { id: 'menu-view-atomistic-ballstick', mode: 'ballstick' },
  ]

  function _updateAtomisticRadio(activeMode) {
    for (const { id, mode } of _ATOMISTIC_MODES) {
      const el = document.getElementById(id)
      if (el) el.classList.toggle('is-checked', mode === activeMode)
    }
  }

  for (const { id, mode } of _ATOMISTIC_MODES) {
    document.getElementById(id)?.addEventListener('click', async () => {
      const { currentDesign } = store.getState()
      if (!currentDesign && mode !== 'off') { alert('No design loaded.'); return }
      await _applyAtomisticMode(mode)
      store.setState({ atomisticMode: mode })
      _updateAtomisticRadio(mode)
    })
  }

  // ── Hide Staples toggle ────────────────────────────────────────────────────────
  document.getElementById('menu-view-hide-staples')?.addEventListener('click', () => {
    const { staplesHidden } = store.getState()
    store.setState({ staplesHidden: !staplesHidden })
    _setMenuToggle('menu-view-hide-staples', !staplesHidden)
  })

  // ── Sync hide-staples toggle state on design changes ──────────────────────────
  store.subscribe((newState, prevState) => {
    if (newState.staplesHidden !== prevState.staplesHidden) {
      _setMenuToggle('menu-view-hide-staples', newState.staplesHidden)
    }
  })

  // ── Overhang Locations toggle ──────────────────────────────────────────────────
  document.getElementById('menu-view-overhang-locations')?.addEventListener('click', () => {
    const tf = store.getState().toolFilters
    store.setState({ toolFilters: { ...tf, overhangLocations: !tf.overhangLocations } })
  })

  document.getElementById('menu-view-overhang-names')?.addEventListener('click', () => {
    const { showOverhangNames } = store.getState()
    store.setState({ showOverhangNames: !showOverhangNames })
    _setMenuToggle('menu-view-overhang-names', !showOverhangNames)
  })

  // ── Help / Hotkeys modal ─────────────────────────────────────────────────────
  const helpModal = document.getElementById('help-modal')
  document.getElementById('menu-help-hotkeys')?.addEventListener('click', () => helpModal.classList.add('visible'))
  document.getElementById('help-modal-close')?.addEventListener('click', () => helpModal.classList.remove('visible'))
  helpModal?.addEventListener('click', e => { if (e.target === helpModal) helpModal.classList.remove('visible') })

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
          <div class="row">strand <span class="val">${nuc.strand_id ?? '—'}</span>${nuc.strand_type === 'scaffold' ? ' <span class="val">[scaffold]</span>' : ''}</div>
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

  ;(function tick() {
    updateDistLabel()
    sequenceOverlay.orientToCamera(camera)
    fastDisplay.tick()
    requestAnimationFrame(tick)
  })()

  // ── Test helpers (dev only — used by Playwright e2e tests) ───────────────
  if (import.meta.env.DEV) {
    window.__nadocTest = {
      /** Return cone entries (crossover connections) with screen {x, y} midpoints. */
      getConeScreenPositions() {
        const rect = canvas.getBoundingClientRect()
        const coneEntries = designRenderer.getConeEntries()
        const out = []
        for (const e of coneEntries) {
          if (!e.fromNuc || !e.toNuc) continue
          const fp = e.fromNuc.backbone_position
          const tp = e.toNuc.backbone_position
          const mid = new THREE.Vector3(
            (fp[0] + tp[0]) / 2, (fp[1] + tp[1]) / 2, (fp[2] + tp[2]) / 2,
          )
          const ndc = mid.clone().project(camera)
          out.push({
            x: rect.left + (ndc.x  *  0.5 + 0.5) * rect.width,
            y: rect.top  + (-ndc.y * 0.5 + 0.5) * rect.height,
            fromHelixId: e.fromNuc.helix_id,
            toHelixId:   e.toNuc.helix_id,
          })
        }
        return out
      },
    }
  }
}

main().catch(err => {
  console.error('NADOC boot error:', err)
  const box = document.getElementById('prompt-box')
  if (box) box.innerHTML = `<p style="color:#ff6b6b">Boot error: ${err.message}</p>`
})

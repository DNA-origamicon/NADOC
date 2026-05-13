/**
 * NADOC frontend entry point.
 *
 * 1. Initialises the Three.js scene inside #viewport-container.
 * 2. Initialises the blank 3D workspace (plane picker + honeycomb lattice).
 * 3. On extrude: calls API → shows 3D helices via design renderer.
 * 4. Wires menu bar: File > New, View > Reset Camera / Toggle Origin Axes /
 *    Slice Plane.
 * 5. Wires right-panel: Properties, Validation, Slab sliders, Reset Camera.
 * 6. Wires command palette (Ctrl+K) for advanced operations.
 * 7. Optionally enables ?debug=1 click readout.
 * 8. Slice plane: toggled via View menu or 'S' key; slides along bundle axis,
 *    snaps to 0.334 nm grid, shows honeycomb lattice for new segment extrusion.
 */

import * as THREE from 'three'
import { initScene }                 from './scene/scene.js'
import { createGlowLayer }           from './scene/glow_layer.js'
import { initDesignRenderer }        from './scene/design_renderer.js'
import { FLUORO_EMISSION_COLORS, buildNucLetterMap, buildStapleColorMap } from './scene/helix_renderer.js'
import { initSelectionManager }      from './scene/selection_manager.js'
import { initWorkspace }             from './scene/workspace.js'
import { initSlicePlane }            from './scene/slice_plane.js'
import { initDomainEnds }            from './scene/domain_ends.js'
import { initEndExtrudeArrows }      from './scene/end_extrude_arrows.js'
import { initCommandPalette }  from './ui/command_palette.js'
import { initPropertiesPanel } from './ui/properties_panel.js'
import { createScriptRunner }  from './ui/script_runner.js'
import { store, pushGroupUndo, popGroupUndo } from './state/store.js'
import * as api                from './api/client.js'
import { initMrdnaRelaxClient } from './physics/mrdna_relax_client.js'
import { initDeformationEditor, startTool, startToolAtBp, startToolForEdit as startDeformToolForEdit,
         isActive as isDeformActive,
         handlePointerMove as deformPointerMove,
         handlePointerDown as deformPointerDown,
         handlePointerUp   as deformPointerUp,
         handleEscape as deformEscape,
         exitTool as deformExitTool,
         confirmDeformation, cancelDeformation, previewDeformation,
         getState as getDeformState, getToolType as getDeformToolType,
         getPlanes as getDeformPlanes, repositionPlane as repositionDeformPlane,
         STATES as DEFORM_STATES,
       } from './scene/deformation_editor.js'
import { initBendTwistPopup, openPopup as openDeformPopup,
         closePopup as closeDeformPopup, setPlanePositions as setDeformPopupPlanes,
       } from './ui/bend_twist_popup.js'
import { initOverhangsManagerPopup,
         open as openOverhangsManager,
       } from './ui/overhangs_manager_popup.js'
import { initUnfoldView }          from './scene/unfold_view.js'
import { initCadnanoView }         from './scene/cadnano_view.js'
import { initDeformView }          from './scene/deform_view.js'
import { initLoopSkipHighlight }   from './scene/loop_skip_highlight.js'
import { initOverhangLocations }   from './scene/overhang_locations.js'
import { initOverhangLinkArcs }    from './scene/overhang_link_arcs.js'
import { initUnligatedCrossoverMarkers } from './scene/unligated_crossover_markers.js'
import { initLinkerAnchorDebug }   from './scene/linker_anchor_debug.js'
import { initOverhangNameOverlay } from './scene/overhang_name_overlay.js'
import { initCrossSectionMinimap } from './scene/cross_section_minimap.js'
import { initViewCube }            from './scene/view_cube.js'
import { initDebugOverlay }        from './scene/debug_overlay.js'
import { initSequenceOverlay }     from './scene/sequence_overlay.js'
import { initAtomisticRenderer }   from './scene/atomistic_renderer.js'
import { initSurfaceRenderer }     from './scene/surface_renderer.js'
import { initSpreadsheet }         from './ui/spreadsheet.js'
import { initAssemblyPanel }        from './ui/assembly_panel.js'
import { initAssemblyContextMenu }  from './ui/assembly_context_menu.js'
import { initLibraryPanel }         from './ui/library_panel.js'
import { openFileBrowser }          from './ui/file_browser.js'
import { initAssemblyRenderer }     from './scene/assembly_renderer.js'
import { initAssemblyJointRenderer } from './scene/assembly_joint_renderer.js'
import { getRigidBodyGroup, getKinematicChildren, isGroupAnchored, computeFixedDepths } from './scene/assembly_constraint_graph.js'
import { makeRefVec, ringPlaneHit, angleInRing }     from './scene/assembly_revolute_math.js'
import { initClusterPanel, helixIdsFromStrandIds } from './ui/cluster_panel.js'
import { initJointsPanel }                          from './ui/joints_panel.js'
import { initJointRenderer }                       from './scene/joint_renderer.js'
import { initCameraPanel }                        from './ui/camera_panel.js'
import { initAnimationPanel }                     from './ui/animation_panel.js'
import { initAssemblyConfigPanel }                from './ui/assembly_config_panel.js'
import { initFeatureLogPanel }                    from './ui/feature_log_panel.js'
import { initAnimationPlayer }                    from './scene/animation_player.js'
import { applyAnimationTextOverlay }              from './scene/animation_text_overlay.js'
import { exportVideo }                            from './scene/export_video.js'
import { initClusterGizmo, computeClusterPivotFromEntries, rebaseClusterTranslationForPivot } from './scene/cluster_gizmo.js'
import { initSubDomainGizmo } from './scene/sub_domain_gizmo.js'
import { initInstanceGizmo }       from './scene/instance_gizmo.js'
import { initOverhangGizmo } from './scene/overhang_gizmo.js'
import { showToast, showPersistentToast, dismissToast } from './ui/toast.js'
import { showOpProgress, hideOpProgress }                from './ui/op_progress.js'
import { BDNA_RISE_PER_BP }        from './constants.js'
import { initZoomScope }           from './scene/zoom_scope.js'
import { initExpandedSpacing }     from './scene/expanded_spacing.js'
import { registerShortcut, dispatchKeyEvent } from './input/shortcuts.js'
import { nadocBroadcast } from './shared/broadcast.js'
import { initMdOverlay }             from './scene/md_overlay.js'
import { initMdSegmentationOverlay, computeSegments as _computeMdSegments } from './scene/md_segmentation_overlay.js'
import { initPeriodicMdOverlay }    from './scene/periodic_md_overlay.js'
import { initPeriodicMdPanel }      from './ui/periodic_md_panel.js'
import { initMdPanel }    from './ui/md_panel.js'
import { inflateIcons, observeIcons } from './ui/primitives/icon.js'
import { getSectionCollapsed, setSectionCollapsed } from './ui/section_collapse_state.js'

// Inflate any [data-icon] markup in static HTML and watch for new ones in
// dynamically-added DOM (modals, context menus, panel rebuilds).
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    inflateIcons()
    observeIcons()
  })
} else {
  inflateIcons()
  observeIcons()
}

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
  const {
    scene, camera, renderer, controls,
    switchOrbitMode, captureCurrentCamera, animateCameraTo,
    setRenderCamera, restoreRenderCamera, getRenderCamera,
    getActiveControls,
    setResizeCallback, clearResizeCallback,
    pushControls, popControls,
    addFrameCallback, removeFrameCallback,
  } = initScene(canvas)

  // Bundle scene context for cadnano_view (and future modules that need camera/renderer switching).
  const sceneCtx = { scene, camera, renderer, controls, setRenderCamera, restoreRenderCamera, getRenderCamera, getActiveControls, setResizeCallback, clearResizeCallback, pushControls, popControls, captureCurrentCamera, animateCameraTo }

  // ── Persistent origin axes (toggleable via View > Toggle Origin Axes) ───────
  const originAxes = new THREE.AxesHelper(4)
  scene.add(originAxes)

  // ── Design renderer (reactive — shows helices when store has geometry) ───────
  const designRenderer = initDesignRenderer(scene, store)

  // ── Assembly renderer (shows PartInstance geometry when assembly mode active) ─
  const assemblyRenderer = initAssemblyRenderer(scene, store, api)

  // ── Cross-tab sync ──────────────────────────────────────────────────────────
  // Reuses the existing nadocBroadcast channel + the established
  // "part-design-updated" message type (already emitted from part-edit Save
  // and handled below by `_refreshAssemblyPartInstance` for assembly windows).
  // Below we also add a part-edit handler so a part-editor tab viewing the
  // same instance re-imports its design when the assembly window mutates it.
  function _broadcastInstanceChanged(instanceId) {
    if (!instanceId) return
    try { nadocBroadcast.emit('part-design-updated', { instanceId }) }
    catch (err) { console.warn('[sync] broadcast failed:', err?.message ?? err) }
  }

  // ── Zoom scope (Space = magnifier lens) ───────────────────────────────────
  const zoomScope = initZoomScope(canvas, scene, camera, designRenderer)

  // ── Deformation editor canvas listeners (capture phase — run before selectionMgr) ──

  // Track whether the deform tool consumed the most recent pointerdown.
  // We must only block the matching pointerup if we also blocked the pointerdown —
  // otherwise OrbitControls receives the pointerdown but never the pointerup,
  // leaving it stuck in a perpetual "dragging" state.
  let _deformConsumedDown = false

  // Canvas-local cursor position — shared across overlays that need a
  // hover-fade or hover-highlight. Updated on every pointermove (also when
  // the deform tool isn't active). null when the cursor leaves the canvas.
  let _canvasCursorX = null
  let _canvasCursorY = null
  canvas.addEventListener('pointermove', e => {
    const r = canvas.getBoundingClientRect()
    _canvasCursorX = e.clientX - r.left
    _canvasCursorY = e.clientY - r.top
  })
  canvas.addEventListener('pointerleave', () => {
    _canvasCursorX = null
    _canvasCursorY = null
  })

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
  }
  const _routingIdMap = {
    scaffoldEnds:  'menu-routing-scaffold-ends',
  }
  function _setRoutingCheck(key, val) {
    _routingChecks[key] = val
    document.getElementById(_routingIdMap[key])?.classList.toggle('is-checked', val)
  }
  function _clearStapleChecks() {
    // no staple-routing checks currently tracked
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
    onScaffoldRightClick: (clientX, clientY, coneEntry) => {
      _showScaffoldSplitCtx(clientX, clientY, coneEntry)
    },
    onCrossoverRightClick: async (xo, action) => {
      // Distinguish forced ligations (have three_prime_helix_id) from regular crossovers.
      const isForcedLigation = !!xo.three_prime_helix_id
      const patchExtraBases = isForcedLigation
        ? (id, seq) => api.patchForcedLigationExtraBases(id, seq)
        : (id, seq) => api.patchCrossoverExtraBases(id, seq)

      if (action === 'remove_extra_bases') {
        await patchExtraBases(xo.id, '')
        return
      }
      // action === 'extra_bases' — prompt for sequence
      const current = xo.extra_bases ?? ''
      const seq = prompt(
        current ? 'Edit extra bases sequence:' : 'Enter extra bases sequence (e.g. TT):',
        current,
      )
      if (seq === null) return  // cancelled
      await patchExtraBases(xo.id, seq)
    },
    onSetOverhangName: (overhangId) => {
      const design = store.getState().currentDesign
      const existing = design?.overhangs?.find(o => o.id === overhangId)?.label ?? ''
      const name = prompt('Overhang name:', existing)
      if (name === null) return  // cancelled
      api.patchOverhang(overhangId, { label: name.trim() || null })
    },
    onOverhangRightClick: (ovhgIds, clientX, clientY) => {
      _showOverhangOrientMenu(ovhgIds, clientX, clientY)
    },
    onOpenOverhangsManager: (ovhgIds) => {
      const { currentDesign } = store.getState()
      if (!currentDesign?.helices?.length) return
      openOverhangsManager(ovhgIds)
    },
    // Lazy getters — defined later in this init sequence.
    getUnfoldView:          () => unfoldView,
    getOverhangLocations:   () => overhangLocations,
    getOverhangLinkArcs:    () => overhangLinkArcs,
    getLoopSkipHighlight:   () => loopSkipHighlight,
    controls,
    getHoverEntry: () => zoomScope.getHoverEntry(),
    getCamera:     () => sceneCtx.getRenderCamera(),
    isDisabled:    () => slicePlane?.isContinuation(),
  })

  // ── End extrusion arrows ──────────────────────────────────────────────────────
  // Thick arrows pointing outward along the helix axis at each selected 5'/3' end.
  const endExtrudeArrows = initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, controls, {
    getCamera:   () => sceneCtx.getRenderCamera(),
    getControls: () => sceneCtx.getActiveControls(),
  })

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
        'color:#00e5ff;font-family:var(--font-ui);font-size:13px;padding:6px 14px;' +
        'box-shadow:0 2px 8px rgba(0,0,0,0.5);'
      document.body.appendChild(_measBox)
    }
    _measBox.textContent = `Distance: ${dist.toFixed(3)} nm`
    _measBox.style.display = 'block'
    _measActive = true
  }

  // Update hint text and clear measurement on ctrl-bead changes.
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
      fontFamily:   "var(--font-ui)",
      fontSize:     'var(--text-xs)',
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
        <div id="ovhg-seq-len" style="margin-top:3px;font-size:var(--text-xs);color:#484f58;">0 bp</div>
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

      const params = {
        helixId:     entry.helixId,
        bpIndex:     entry.bpIndex,
        direction:   entry.direction,
        isFivePrime: entry.isFivePrime,
        neighborRow: entry.neighborRow,
        neighborCol: entry.neighborCol,
        lengthBp,
      }

      if (entry.instanceId) {
        // Assembly-mode extrude: writes to that PartInstance's design file,
        // then re-renders the affected instance and broadcasts so part-editor
        // and cadnano-editor tabs viewing the same instance auto-refresh.
        let resp
        try {
          resp = await api.extrudeInstanceOverhang(entry.instanceId, params)
        } catch (err) {
          console.error('Overhang extrude (instance) failed:', err?.message ?? err)
          return
        }

        // Patch sequence/label on the same instance if the user supplied them.
        // Use the per-overhang assembly endpoint so the change lands in the
        // part's feature_log (and an assembly-level metadata entry) — the
        // wholesale patchInstanceDesign path bypasses the feature log.
        if ((sequence || name) && resp?.design) {
          const endTag     = entry.isFivePrime ? '5p' : '3p'
          const overhangId = `ovhg_${entry.helixId}_${entry.bpIndex}_${endTag}`
          const patch = {}
          if (sequence) patch.sequence = sequence
          if (name)     patch.label    = name
          try {
            await api.patchInstanceOverhang(entry.instanceId, overhangId, patch)
          } catch (err) {
            console.warn('Overhang label/sequence patch failed:', err?.message ?? err)
          }
        }

        // Re-fetch and re-render this instance in the assembly scene, then
        // refresh the overhang locations (active-instance arrows now reflect
        // the new topology).
        assemblyRenderer.invalidateInstance(entry.instanceId)
        await assemblyRenderer.rebuild(store.getState().currentAssembly)
        _rebuildOverhangLocations()

        // Tell other tabs viewing this instance to refresh.
        _broadcastInstanceChanged(entry.instanceId)
        return
      }

      const result = await api.extrudeOverhang(params)
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
      <div style="background:#1e2a3a;border:1px solid #ff3333;border-radius:8px;padding:24px 28px;max-width:380px;color:#e8eef4;font-family:var(--font-ui);">
        <p style="margin:0 0 8px;font-size:13px;color:#ff6b6b;font-weight:bold;">⚠ Circular staple detected</p>
        <p style="margin:0 0 18px;font-size:12px;line-height:1.5;">
          This staple strand has no free 5′/3′ ends.
          Nick automatically at the midpoint of its longest domain,
          or dismiss to leave it unresolved.
        </p>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button id="loop-popup-leave" style="padding:6px 14px;background:#2d3f52;border:1px solid #445566;border-radius:4px;color:#e8eef4;cursor:pointer;font-family:var(--font-ui);font-size:12px;">Leave unresolved</button>
          <button id="loop-popup-nick" style="padding:6px 14px;background:#c0392b;border:none;border-radius:4px;color:#fff;cursor:pointer;font-family:var(--font-ui);font-size:12px;">Nick here</button>
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

  // ── Collapsible-panel helper ──────────────────────────────────────────────
  // tabId / sectionId persist collapse state per-tab to localStorage so each
  // tab remembers its sub-section layout independently across reloads.
  function _initCollapsiblePanel(headingId, bodyId, arrowId, defaultCollapsed = true, tabId = null, sectionId = null) {
    const heading = document.getElementById(headingId)
    const body    = document.getElementById(bodyId)
    const arrow   = document.getElementById(arrowId)
    if (!heading || !body) return
    const startCollapsed = (tabId && sectionId)
      ? getSectionCollapsed(tabId, sectionId, defaultCollapsed)
      : defaultCollapsed
    body.style.display = startCollapsed ? 'none' : 'block'
    if (arrow) arrow.classList.toggle('is-collapsed', startCollapsed)
    heading.addEventListener('click', () => {
      const collapsed = body.style.display === 'none'
      body.style.display = collapsed ? 'block' : 'none'
      if (arrow) arrow.classList.toggle('is-collapsed', !(collapsed))
      if (tabId && sectionId) setSectionCollapsed(tabId, sectionId, !collapsed)
    })
  }

  _initCollapsiblePanel('oxdna-heading',   'oxdna-body',   'oxdna-arrow',   true, 'dynamics', 'oxdna-section')

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
        // Overlay relaxed positions via the shared FEM-style overlay path.
        designRenderer.applyFemPositions(result.positions)
      }
    })
  })()

  // ── Bend/Twist deformation editor ──────────────────────────────────────────

  // Context set while editing an existing feature; cleared on confirm or cancel.
  let _editContext = null  // { priorCursor, pendingParams }

  initDeformationEditor(scene, camera, canvas, controls, designRenderer,
    () => {
      // onExit: restore mode indicator; if editing, seek back to prior state
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      if (_editContext) {
        const ctx = _editContext
        _editContext = null
        _seekFeaturesWithDelta(ctx.priorCursor)
      }
    },
    () => {
      // onPlaneDragEnd: sync popup inputs with dragged plane positions
      const { a, b } = getDeformPlanes()
      setDeformPopupPlanes(a?.bp ?? 0, b?.bp ?? 0)
    },
  )

  initBendTwistPopup({
    onPreview: (params) => previewDeformation(params),
    onConfirm: async (params) => {
      const ctx = _editContext
      if (ctx?.featureIndex != null && ctx.editingFeatureType === 'deformation') {
        // Edit-in-place: update the existing DeformationOp + log entry rather
        // than appending a new feature_log entry.
        _editContext = null
        const planes = getDeformPlanes()
        const bpA = planes.a?.bp ?? 0
        const bpB = planes.b?.bp ?? 0
        const lo = Math.min(bpA, bpB)
        const hi = Math.max(bpA, bpB)
        const editBody = {
          type:       getDeformToolType() ?? 'twist',
          plane_a_bp: lo,
          plane_b_bp: hi,
          params,
          cluster_id: ctx.clusterId ?? null,
        }
        await api.editFeature(ctx.featureIndex, editBody)
        // The client-side _responseDeltaHandler (registered with
        // registerResponseDeltaHandler at init) takes care of applying the
        // cluster_only / positions_only diff to the renderer.
        deformExitTool()
        _watchDeformState()
        return
      }
      _editContext = null   // clear before confirm; addDeformation takes over
      await confirmDeformation(params)
      _watchDeformState()
    },
    onCancel: () => {
      if (_editContext) {
        // In edit mode: force full exit (skips A_PLACED intermediate)
        deformExitTool()   // → STATE.IDLE → onExit fires → seek back
      } else {
        cancelDeformation()
      }
      _watchDeformState()
    },
    onPlaneChanged: (which, bp) => repositionDeformPlane(which, bp),
  })

  // Watch deformation editor state — open/close popup when state changes
  let _prevDeformState = DEFORM_STATES.IDLE
  function _watchDeformState() {
    const st = getDeformState()
    if (st === _prevDeformState) return
    _prevDeformState = st
    if (st === DEFORM_STATES.BOTH) {
      const { a, b } = getDeformPlanes()
      const editParams = _editContext?.pendingParams ?? null
      openDeformPopup(getDeformToolType() ?? 'twist', a?.bp ?? 0, b?.bp ?? 0, editParams)
      if (_editContext) delete _editContext.pendingParams
    } else {
      closeDeformPopup()
    }
  }

  async function _onEditFeature(entry, featureIndex) {
    // ── Overhang orientation edit — open orientation panel for this overhang ─
    if (entry.feature_type === 'overhang_rotation') {
      const ovhgIds = entry.overhang_ids
      if (!ovhgIds?.length) return
      _ooOpen(ovhgIds)
      return
    }

    // ── Move/rotate (cluster_op) edit — highlight cluster and open tool ─────
    if (entry.feature_type === 'cluster_op') {
      const clusterId = entry.cluster_id
      if (!clusterId) return
      // Refuse if a later cluster_op exists for this cluster — editing an
      // earlier one would have ambiguous cumulative semantics. The backend
      // also enforces this on edit_feature.
      const log = store.getState().currentDesign?.feature_log ?? []
      const hasLater = log.slice(featureIndex + 1).some(e =>
        e.feature_type === 'cluster_op' && e.cluster_id === clusterId)
      if (hasLater) {
        showToast(`Edit blocked: a later move/rotate exists for this cluster. Edit the latest one.`, 5000)
        return
      }
      store.setState({ activeClusterId: clusterId })
      await _activateTranslateRotateTool()
      // Mark cluster_op edit in flight; _confirmTranslateRotateTool will
      // route the apply through api.editFeature instead of patchCluster, so
      // the existing log entry is updated rather than a new one appended.
      _editContext = {
        editingFeatureType: 'cluster_op',
        featureIndex,
        clusterId,
      }
      return
    }

    const op = entry.op_snapshot
    if (!op) return

    const design = store.getState().currentDesign
    const priorCursor = design?.feature_log_cursor ?? -1

    // Seek to state just before this feature (FN → seek FN-1; F1 → seek -2 = empty)
    const seekPos = featureIndex === 0 ? -2 : featureIndex - 1
    await _seekFeaturesWithDelta(seekPos)

    // Edit-in-place mode: confirm calls editFeature(index, …) instead of
    // appending a new deformation entry. featureIndex + clusterId are
    // captured at edit-start so the confirm handler can issue the right
    // request without re-discovering them from the live log (which has
    // been seeked back).
    _editContext = {
      priorCursor,
      pendingParams:    op.params,
      featureIndex,
      editingFeatureType: entry.feature_type,
      clusterId:        op.cluster_id ?? null,
    }

    // Open editor with pre-placed planes; _watchDeformState opens popup with params
    startDeformToolForEdit(op.type, op.plane_a_bp, op.plane_b_bp)

    document.getElementById('mode-indicator').textContent =
      `EDIT ${op.type.toUpperCase()} F${featureIndex + 1} — adjust planes/params · Apply to save · Esc to cancel`
  }

  // ── 2D Unfold view ──────────────────────────────────────────────────────────
  // bluntEnds is initialized below; use a getter so unfoldView can call it lazily.
  const unfoldView = initUnfoldView(scene, designRenderer, () => bluntEnds, () => loopSkipHighlight, () => sequenceOverlay, () => overhangLocations, null)

  // ── Cadnano mode ─────────────────────────────────────────────────────────
  const cadnanoView = initCadnanoView(sceneCtx, designRenderer, () => unfoldView, () => sequenceOverlay, null, () => slicePlane, () => bluntEnds, () => loopSkipHighlight)

  // ── Expanded helix spacing (Q) ───────────────────────────────────────────
  const expandedSpacing = initExpandedSpacing(
    designRenderer,
    () => bluntEnds,
    () => loopSkipHighlight,
    () => overhangLocations,
    () => sequenceOverlay,
    () => unfoldView,
    () => atomisticRenderer,
  )

  let jointRenderer = null

  // ── Deformed geometry view ──────────────────────────────────────────────────
  const deformView = initDeformView(designRenderer, () => bluntEnds, null, () => unfoldView, () => loopSkipHighlight, () => overhangLocations, () => jointRenderer)

  // ── Animation player ────────────────────────────────────────────────────────
  const animPlayer = initAnimationPlayer({
    camera,
    controls,
    getCameraPoses:         () => store.getState().currentDesign?.camera_poses        ?? [],
    getDesign:              () => store.getState().currentDesign,
    getClusterTransforms:   () => store.getState().currentDesign?.cluster_transforms   ?? [],
    getHelixCtrl:           () => designRenderer.getHelixCtrl(),
    getBluntEnds:           () => bluntEnds,
    getUnfoldView:          () => unfoldView,
    getDesignRenderer:      () => designRenderer,
    getOverhangLinkArcs:    () => overhangLinkArcs,
    // Pass through any opts (signal, suppressBusy) the player provides — the
    // bake loop wires its own AbortController and asks _request to skip the
    // generic "Working…" auto-popup so the panel's "Rendering Animation"
    // popup stays in front.
    onFetchGeometryBatch:   (positions, opts) => api.getGeometryBatch(positions, opts),
    onFetchAtomisticBatch:  (positions, opts) => api.getAtomisticBatch(positions, opts),
    getAtomisticRenderer:   () => atomisticRenderer,
    onFetchSurfaceBatch: (positions, opts) => {
      const { surfaceColorMode } = store.getState()
      return api.getSurfaceBatch(positions, surfaceColorMode, _surfaceProbeRadius, undefined, opts)
    },
    getSurfaceRenderer: () => surfaceRenderer,
    onTextOverlayUpdate: (state) => {
      applyAnimationTextOverlay(document.getElementById('canvas-area'), state)
    },
    onEvent: (evt) => {
      animPanel?.onPlayerEvent(evt)
      // When animation stops or finishes, restore all heavy representations to
      // the live (deformed) design state rather than holding the last lerped frame.
      if (evt.type === 'stopped' || evt.type === 'finished') {
        if (atomisticRenderer.getMode() !== 'off') {
          _atomDataCache = null
          _applyAtomisticMode(atomisticRenderer.getMode())
        }
        if (_surfaceMode !== 'off') {
          _surfaceDataCache = null
          _applySurfaceMode(_surfaceMode)
        }
      }
    },
  })

  // ── Debug hover overlay ─────────────────────────────────────────────────────
  const debugOverlay = initDebugOverlay(canvas, camera, designRenderer, {
    getBluntEnds:  () => bluntEnds,
    getUnfoldView: () => unfoldView,
  })

  // ── Loop/Skip highlight overlay ─────────────────────────────────────────────
  const loopSkipHighlight    = initLoopSkipHighlight(scene)
  const mdSegmentation       = initMdSegmentationOverlay(scene)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign  === prevState.currentDesign) return
    if (loopSkipHighlight.isVisible()) {
      loopSkipHighlight.rebuild(newState.currentDesign, newState.currentGeometry, newState.currentHelixAxes)
    }
  })

  // ── Crossover Locations overlay (stub — 3D sprite module not yet rebuilt) ───
  const crossoverLocations = {
    setVisible: () => {},
    rebuild: () => Promise.resolve(),
    isVisible: () => false,
    dispose: () => {},
  }

  // ── Overhang Locations overlay ───────────────────────────────────────────────
  const overhangLocations = initOverhangLocations(scene)

  /** Centralized rebuild — handles both design mode and assembly mode (active
   *  instance only). In assembly mode the arrow group is parented to the
   *  PartInstance's THREE.Group so it inherits the instance world transform. */
  function _rebuildOverhangLocations() {
    if (!overhangLocations.isVisible()) return
    const s = store.getState()
    if (s.assemblyActive) {
      const instId = s.activeInstanceId
      if (!instId) { overhangLocations.clear(); return }
      const rd = assemblyRenderer.getInstanceRenderData(instId)
      if (!rd?.design || !rd?.nucleotides || !rd?.group) { overhangLocations.clear(); return }
      overhangLocations.rebuild(rd.design, rd.nucleotides, { parentGroup: rd.group, instanceId: instId })
    } else {
      overhangLocations.rebuild(s.currentDesign, s.currentGeometry)
    }
  }

  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    if (newState.assemblyActive) return   // assembly mode rebuild is driven by other subscribers below
    _rebuildOverhangLocations()
  })
  // Assembly-mode triggers: active instance change, currentAssembly change,
  // and transitions in/out of assembly mode (so arrows clear when leaving).
  store.subscribe((newState, prevState) => {
    const modeChanged = newState.assemblyActive !== prevState.assemblyActive
    if (!modeChanged && !newState.assemblyActive) return
    if (!modeChanged &&
        newState.activeInstanceId === prevState.activeInstanceId &&
        newState.currentAssembly  === prevState.currentAssembly) return
    _rebuildOverhangLocations()
  })

  // ── Overhang Link Arcs (white tubes for design.overhang_connections) ────────
  const overhangLinkArcs = initOverhangLinkArcs(scene)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    overhangLinkArcs.rebuild(newState.currentDesign, newState.currentGeometry)
  })
  // Initial rebuild — when the persisted design was applied to the store
  // before this subscription was registered, the listener never fires.
  {
    const s = store.getState()
    if (s.currentDesign && s.currentGeometry) {
      overhangLinkArcs.rebuild(s.currentDesign, s.currentGeometry)
    }
  }

  // ── Linker anchor debug overlay (toggle via Help → Show Linker Anchor Debug) ─
  const linkerAnchorDebug = initLinkerAnchorDebug(
    scene,
    () => store.getState().currentDesign,
    () => store.getState().currentGeometry,
    () => designRenderer.getHelixCtrl(),
  )
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    if (linkerAnchorDebug.isVisible()) linkerAnchorDebug.rebuild()
  })

  // ── Unligated crossover markers (⚠ at midpoint of would-circularize crossovers) ─
  const unligatedCrossoverMarkers = initUnligatedCrossoverMarkers(scene)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry      === prevState.currentGeometry &&
        newState.currentDesign        === prevState.currentDesign &&
        newState.unligatedCrossoverIds === prevState.unligatedCrossoverIds) return
    unligatedCrossoverMarkers.rebuild(
      newState.currentDesign,
      newState.currentGeometry,
      newState.unligatedCrossoverIds,
    )
  })
  {
    const s = store.getState()
    if (s.currentDesign && s.currentGeometry) {
      unligatedCrossoverMarkers.rebuild(s.currentDesign, s.currentGeometry, s.unligatedCrossoverIds)
    }
  }

  // ── Overhang lookup table infrastructure ─────────────────────────────────────
  //
  // Four maps built in dependency order on every geometry/design change.
  // Two maps have a secondary construction path used for cross-validation.
  //
  //  Map 1  _ovhgSpecMap      id → OverhangSpec
  //  Map 2  _ovhgDomainMap    id → { strand, domIdx, domain }
  //  Map 3  _ovhgJunctionMap  id → { junctionBp, junctionDir }
  //  Map 4  _ovhgRootMap      id → { entry: BackboneEntry, pos: THREE.Vector3 }
  //
  // Cross-validation maps (built alongside; compared in the debug report):
  //  _xval_domainGeo    Map 2 built from nuc.domain_index instead of d.overhang_id scan
  //  _xval_junctionXover  Map 3 built from design.crossovers (cross-validation; ambiguous for shared helix pairs)
  //
  // FINDINGS recorded during construction:
  //  • d.overhang_id === spec.id is the safe domain match; d.helix_id is ambiguous when
  //    a strand visits the same helix twice (latent bug in original _findOvhgRootEntry)
  //  • nuc.domain_index comes from the backend and is always correct — geometry path
  //    uses it instead of findIndex so it is immune to the double-helix-visit problem
  //  • design.crossovers contains crossovers for inline overhangs (from the original
  //    cadnano import); autodetect_overhangs adds no crossovers but they already exist
  //  • xo.half_*.strand and nuc.direction are both 'FORWARD'/'REVERSE' strings — match
  //  • nuc.bp_index and HalfCrossover.index are both global bp indices — match
  //  • helixCtrl.lookupEntry("helix_id:bp_index:direction") is O(1) — preferred over
  //    backboneEntries.find() linear scan

  let _ovhgSpecMap         = new Map()
  let _ovhgDomainMap       = new Map()
  let _ovhgJunctionMap     = new Map()
  let _ovhgRootMap         = new Map()
  let _xval_domainGeo      = new Map()  // geometry-based domain map (cross-validation)
  let _xval_junctionXover  = new Map()  // crossover-based junction map (cross-validation)
  let _ohRootsGlowActive   = false
  let _domainEndsGlowActive = false
  let _domainEndEntries     = []

  // Map 1 — trivial; any missing entry here means design.overhangs is incomplete
  function _buildSpecMap(design) {
    return new Map((design?.overhangs ?? []).map(o => [o.id, o]))
  }

  // Map 2 (design path) — uses d.overhang_id === spec.id for exact match.
  // NOTE: d.helix_id match was the original approach and is WRONG when a strand
  // visits the same helix on two separate domains (findIndex returns first match).
  function _buildDomainMapFromDesign(design, specMap) {
    const map = new Map()
    for (const spec of specMap.values()) {
      const strand = design.strands?.find(s => s.id === spec.strand_id)
      if (!strand) continue
      const domIdx = strand.domains.findIndex(d => d.overhang_id === spec.id)
      if (domIdx < 0) continue
      map.set(spec.id, { strand, domIdx, domain: strand.domains[domIdx] })
    }
    return map
  }

  // Map 2 (geometry path, cross-validation) — uses nuc.domain_index, which is the
  // authoritative index emitted by the backend. Independent of d.overhang_id scan.
  function _buildDomainMapFromGeom(design, backboneEntries) {
    const map = new Map()
    for (const entry of backboneEntries) {
      const id = entry.nuc.overhang_id
      if (!id || map.has(id)) continue
      const strand = design?.strands?.find(s => s.id === entry.nuc.strand_id)
      if (!strand) continue
      const domIdx = entry.nuc.domain_index
      const domain = strand.domains[domIdx]
      if (domain) map.set(id, { strand, domIdx, domain })
    }
    return map
  }

  // Map 3 (crossover path) — reads design.crossovers for the exact (bp_index, direction)
  // of the junction bead. design.crossovers contains all inter-helix strand transitions
  // including those for inline overhangs created before overhang detection ran.
  function _buildJunctionMapFromXovers(design, specMap, domainMap) {
    const map = new Map()
    for (const [id, spec] of specMap) {
      const domEntry = domainMap.get(id)
      if (!domEntry) continue
      const { strand, domIdx } = domEntry
      const parentDomIdx = domIdx === 0 ? 1 : domIdx - 1
      if (parentDomIdx < 0 || parentDomIdx >= strand.domains.length) continue
      const parentDom = strand.domains[parentDomIdx]
      const xover = design.crossovers?.find(x =>
        (x.half_a?.helix_id === spec.helix_id && x.half_b?.helix_id === parentDom.helix_id) ||
        (x.half_b?.helix_id === spec.helix_id && x.half_a?.helix_id === parentDom.helix_id)
      )
      if (!xover) continue
      const side = xover.half_a?.helix_id === spec.helix_id ? xover.half_a : xover.half_b
      map.set(id, { junctionBp: side.index, junctionDir: side.strand })
    }
    return map
  }

  // Map 3 (domain-endpoint path, PRIMARY) — derives junction bp from domain start_bp/end_bp.
  // In NADOC start_bp is ALWAYS the 5′ end regardless of direction, so the junction is:
  //   overhang at 3' end of strand (domIdx > 0) → junction = 5' end of domain = start_bp
  //   overhang at 5' end of strand (domIdx = 0) → junction = 3' end of domain = end_bp
  // No direction check needed — the start_bp/end_bp convention handles it for HC and SQ.
  function _buildJunctionMapFromDomains(domainMap) {
    const map = new Map()
    for (const [id, { domIdx, domain }] of domainMap) {
      const isFirst = domIdx === 0
      const junctionBp = isFirst ? domain.end_bp : domain.start_bp
      map.set(id, { junctionBp, junctionDir: domain.direction })
    }
    return map
  }

  // Map 4 — uses helixCtrl.lookupEntry for O(1) lookup. The key format matches
  // the one used internally by helix_renderer: "helix_id:bp_index:direction".
  function _buildRootMap(specMap, junctionMap, helixCtrl) {
    const map = new Map()
    for (const [id, { junctionBp, junctionDir }] of junctionMap) {
      const spec = specMap.get(id)
      if (!spec) continue
      const entry = helixCtrl?.lookupEntry(`${spec.helix_id}:${junctionBp}:${junctionDir}`)
      if (entry) map.set(id, { entry, pos: entry.pos })
    }
    return map
  }

  // Master build — called on every geometry/design change.
  // junctionMap uses domain endpoints as primary source; _xval_junctionXover is compared
  // in the debug report to check agreement. Crossover path is ambiguous when multiple
  // strands share the same parent↔overhang helix pair — it returns the first crossover.
  function _buildOvhgMaps(design, backboneEntries) {
    const helixCtrl = designRenderer.getHelixCtrl()
    _ovhgSpecMap        = _buildSpecMap(design)
    _ovhgDomainMap      = _buildDomainMapFromDesign(design, _ovhgSpecMap)
    _ovhgJunctionMap    = _buildJunctionMapFromDomains(_ovhgDomainMap)
    _ovhgRootMap        = _buildRootMap(_ovhgSpecMap, _ovhgJunctionMap, helixCtrl)
    _xval_domainGeo     = _buildDomainMapFromGeom(design, backboneEntries)
    _xval_junctionXover = _buildJunctionMapFromXovers(design, _ovhgSpecMap, _ovhgDomainMap)
    if (_ohRootsGlowActive) _applyOhRootsGlow()
  }

  function _applyOhRootsGlow() {
    designRenderer.setGlowEntries([..._ovhgRootMap.values()].map(v => v.entry))
  }

  function _buildDomainEndEntries(backboneEntries) {
    const helixCtrl = designRenderer.getHelixCtrl()
    _domainEndEntries = []
    for (const entry of backboneEntries) {
      const { helix_id, bp_index, direction } = entry.nuc
      const hasPlus  = !!helixCtrl?.lookupEntry(`${helix_id}:${bp_index + 1}:${direction}`)
      const hasMinus = !!helixCtrl?.lookupEntry(`${helix_id}:${bp_index - 1}:${direction}`)
      if (hasPlus !== hasMinus) _domainEndEntries.push(entry)
    }
  }

  function _applyDomainEndsGlow() {
    designRenderer.setGlowEntries(_domainEndEntries)
  }

  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    const _bbEntries = designRenderer.getBackboneEntries?.() ?? []
    _buildOvhgMaps(newState.currentDesign, _bbEntries)
    _buildDomainEndEntries(_bbEntries)
    if (_domainEndsGlowActive) _applyDomainEndsGlow()
  })

  // ── Cadnano-active watchdog ──────────────────────────────────────────────────
  // Logs whenever cadnanoActive unexpectedly transitions while debugging.
  store.subscribe((newState, prevState) => {
    if (!window._cnDebug) return
    if (newState.cadnanoActive !== prevState.cadnanoActive) {
      console.warn(`[CN f${window._cnFrame}] cadnanoActive changed: ${prevState.cadnanoActive} → ${newState.cadnanoActive}`,
        new Error().stack.split('\n').slice(2, 6).join('\n'))
    }
  })

  // ── Overhang Name overlay ────────────────────────────────────────────────────
  // Subscription is handled inside initOverhangNameOverlay via store.subscribe.
  const overhangNameOverlay = initOverhangNameOverlay(scene, store)

  // ── Atomistic renderer (Phase AA) ───────────────────────────────────────────
  const atomisticRenderer = initAtomisticRenderer(scene)

  // ── MD overlay + panel ───────────────────────────────────────────────────────
  const mdOverlay         = initMdOverlay(scene)
  initMdPanel(store, { designRenderer, mdOverlay, atomisticRenderer })

  const periodicMdOverlay = initPeriodicMdOverlay(scene)
  initPeriodicMdPanel(store, {
    periodicMdOverlay,
    setCGVisible: _setCGVisible,
    getDesign:   () => store.getState().currentDesign,
  })

  // Log sub-panel collapse toggle
  document.getElementById('pmd-log-heading')?.addEventListener('click', () => {
    const logBody  = document.getElementById('pmd-log-body')
    const logArrow = document.getElementById('pmd-log-arrow')
    const open = logBody?.style.display !== 'none'
    if (logBody)  logBody.style.display = open ? 'none' : 'block'
    logArrow?.classList.toggle('is-collapsed', open)
  })

  // ── Surface renderer (VdW / SES) ─────────────────────────────────────────────
  const surfaceRenderer = initSurfaceRenderer(scene)
  let _surfaceDataCache   = null   // cached API response; null = needs re-fetch
  let _surfaceProbeRadius = 0.28   // current probe radius for SES (nm)
  let _surfaceMode        = 'off'  // mirrors store.surfaceMode
  let _currentBeadRadius  = 0.10   // current bead radius (nm); matches sl-bead-radius default

  function _setSurfacePanelVisible(visible) {
    const el = document.getElementById('surface-options-panel')
    if (el) el.style.display = visible ? '' : 'none'
  }

  async function _applySurfaceMode(mode) {
    _surfaceMode = mode
    if (mode === 'off') {
      surfaceRenderer.dispose()
      _surfaceDataCache = null
      // Only restore CG if atomistic overlay is also off
      if (atomisticRenderer.getMode() === 'off') _setCGVisible(true)
      _setSurfacePanelVisible(false)
      return
    }
    // Hide CG model and any active atomistic overlay
    _setCGVisible(false)
    if (atomisticRenderer.getMode() !== 'off') {
      atomisticRenderer.setMode('off')
      store.setState({ atomisticMode: 'off' })
    }
    _setSurfacePanelVisible(true)
    if (!_surfaceDataCache) {
      showPersistentToast('Computing surface…')
      try {
        const { surfaceColorMode } = store.getState()
        const url = `/api/design/surface?color_mode=${surfaceColorMode}&probe_radius=${_surfaceProbeRadius}`
        const resp = await fetch(url)
        if (!resp.ok) {
          dismissToast()
          console.error('Surface fetch failed:', resp.status)
          return
        }
        _surfaceDataCache = await resp.json()
        console.debug(`Surface computed: ${_surfaceDataCache.stats?.n_verts} verts, ${_surfaceDataCache.stats?.n_faces} faces, ${_surfaceDataCache.stats?.compute_ms} ms`)
      } catch (e) {
        dismissToast()
        console.error('Surface fetch error:', e)
        return
      }
      dismissToast()
    }
    const { surfaceColorMode, surfaceOpacity } = store.getState()
    surfaceRenderer.update(_surfaceDataCache, surfaceColorMode)
    surfaceRenderer.applyStrandColors(_getAtomStrandColors())
    surfaceRenderer.setOpacity(surfaceOpacity)
  }

  // Invalidate surface cache on design/geometry change
  store.subscribe((newState, prevState) => {
    const designChanged   = newState.currentDesign   !== prevState.currentDesign
    const geometryChanged = newState.currentGeometry !== prevState.currentGeometry ||
                            newState.currentHelixAxes !== prevState.currentHelixAxes
    if (designChanged || geometryChanged) {
      _surfaceDataCache = null
      if (_surfaceMode !== 'off') _applySurfaceMode(_surfaceMode)
    }
  })

  // Live surface option updates
  store.subscribe((newState, prevState) => {
    if (newState.surfaceColorMode !== prevState.surfaceColorMode) {
      if (_surfaceMode !== 'off') {
        if (newState.surfaceColorMode === 'uniform' || _surfaceDataCache?.vertex_colors) {
          // Switch colour in-place — no re-fetch needed
          surfaceRenderer.setColorMode(newState.surfaceColorMode)
        } else {
          // Need vertex colours but cache lacks them — re-fetch with new color_mode
          _surfaceDataCache = null
          _applySurfaceMode(_surfaceMode)
        }
      }
    }
    if (newState.surfaceOpacity !== prevState.surfaceOpacity) {
      surfaceRenderer.setOpacity(newState.surfaceOpacity)
    }
  })

  // Surface opacity slider
  const _slSurfaceOpacity = document.getElementById('sl-surface-opacity')
  const _svSurfaceOpacity = document.getElementById('sv-surface-opacity')
  _slSurfaceOpacity?.addEventListener('input', () => {
    const val = parseFloat(_slSurfaceOpacity.value)
    if (_svSurfaceOpacity) _svSurfaceOpacity.textContent = val.toFixed(2)
    store.setState({ surfaceOpacity: val })
  })

  // Surface probe radius slider (SES only)
  const _slSurfaceProbe = document.getElementById('sl-surface-probe')
  const _svSurfaceProbe = document.getElementById('sv-surface-probe')
  _slSurfaceProbe?.addEventListener('input', () => {
    _surfaceProbeRadius = parseFloat(_slSurfaceProbe.value)
    if (_svSurfaceProbe) _svSurfaceProbe.textContent = _surfaceProbeRadius.toFixed(2)
    if (_surfaceMode !== 'off') {
      _surfaceDataCache = null
      _applySurfaceMode('on')
    }
  })

  // Surface colour-mode toggle buttons
  document.getElementById('surface-color-strand')?.addEventListener('click', () => {
    document.getElementById('surface-color-strand')?.classList.add('active')
    document.getElementById('surface-color-uniform')?.classList.remove('active')
    store.setState({ surfaceColorMode: 'strand' })
  })
  document.getElementById('surface-color-uniform')?.addEventListener('click', () => {
    document.getElementById('surface-color-uniform')?.classList.add('active')
    document.getElementById('surface-color-strand')?.classList.remove('active')
    store.setState({ surfaceColorMode: 'uniform' })
  })

  // Atom radius scale slider
  const _slAtomVdwScale = document.getElementById('sl-atom-vdw-scale')
  const _svAtomVdwScale = document.getElementById('sv-atom-vdw-scale')
  _slAtomVdwScale?.addEventListener('input', () => {
    const scale = parseFloat(_slAtomVdwScale.value)
    if (_svAtomVdwScale) _svAtomVdwScale.textContent = scale.toFixed(2)
    atomisticRenderer.setVdwScale(scale)
  })

  async function _refetchAtomistic() {
    if (atomisticRenderer.getMode() === 'off') return
    try {
      const resp = await fetch(_atomisticUrl())
      if (!resp.ok) { console.error('Atomistic refetch failed:', resp.status); return }
      _atomDataCache = await resp.json()
      atomisticRenderer.update(_atomDataCache)
      _refreshAtomColors()
      const { selectedObject, multiSelectedStrandIds } = store.getState()
      atomisticRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
    } catch (e) {
      console.error('Atomistic refetch error:', e)
    }
  }

  // Atom colouring toggle
  // Backend-canonical staple palette (matches helix_renderer.STAPLE_PALETTE).
  const _ATOM_STAPLE_PALETTE = [
    0xff6b6b, 0xffd93d, 0x6bcb77, 0xf9844a, 0xa29bfe, 0xff9ff3,
    0x00cec9, 0xe17055, 0x74b9ff, 0x55efc4, 0xfdcb6e, 0xd63031,
  ]
  function _getAtomStrandColors() {
    const { strandColors, strandGroups, currentDesign, currentGeometry, coloringMode } = store.getState()
    const effective = { ...strandColors }
    for (const g of strandGroups ?? []) {
      if (g.color) {
        const hex = parseInt(g.color.replace('#', ''), 16)
        for (const sid of g.strandIds) effective[sid] = hex
      }
    }
    // scaffold gets sky-blue
    for (const s of currentDesign?.strands ?? []) {
      if (s.strand_type === 'scaffold' && !(s.id in effective)) {
        effective[s.id] = 0x29b6f6
      }
    }
    // Fill in palette-assigned colours for every staple strand so atomistic
    // matches the bead view exactly (atoms whose strand is not in the map fall
    // back to CPK in the renderer, which would mismatch the beads).
    if (currentDesign && currentGeometry) {
      const palette = buildStapleColorMap(currentGeometry, currentDesign)
      for (const s of currentDesign.strands ?? []) {
        if (!(s.id in effective)) {
          const p = palette.get(s.id)
          if (p != null) effective[s.id] = p
        }
      }
    }
    // Loop / circular-strand red highlight (matches helix_renderer.nucColor).
    // Skip in cluster mode — cluster fill below should win on clustered strands.
    const { loopStrandIds } = store.getState()
    if (loopStrandIds?.length && coloringMode !== 'cluster') {
      for (const sid of loopStrandIds) effective[sid] = 0xff3333
    }
    // 'cluster' coloring: replace each strand's color with its cluster's
    // palette colour, keyed off the strand's first domain helix.
    // 'base' is left as strand colour (atomistic lacks per-atom base mapping).
    if (coloringMode === 'cluster' && currentDesign?.cluster_transforms?.length) {
      const helixCluster = new Map()
      const domainCluster = new Map()
      const strandMap = new Map((currentDesign.strands ?? []).map(s => [s.id, s]))
      currentDesign.cluster_transforms.forEach((c, i) => {
        if (c.domain_ids?.length) {
          const bridges = new Set()
          for (const dr of c.domain_ids) {
            domainCluster.set(`${dr.strand_id}:${dr.domain_index}`, i)
            const dom = strandMap.get(dr.strand_id)?.domains?.[dr.domain_index]
            if (dom) bridges.add(dom.helix_id)
          }
          for (const hid of (c.helix_ids ?? [])) if (!bridges.has(hid)) helixCluster.set(hid, i)
        } else {
          for (const hid of (c.helix_ids ?? [])) helixCluster.set(hid, i)
        }
      })
      for (const s of currentDesign.strands ?? []) {
        let ci = null
        for (let di = 0; di < (s.domains ?? []).length; di++) {
          const k = `${s.id}:${di}`
          if (domainCluster.has(k)) { ci = domainCluster.get(k); break }
          const hid = s.domains[di].helix_id
          if (helixCluster.has(hid)) { ci = helixCluster.get(hid); break }
        }
        if (ci != null) effective[s.id] = _ATOM_STAPLE_PALETTE[ci % _ATOM_STAPLE_PALETTE.length]
      }
    }
    return new Map(Object.entries(effective).map(([k, v]) => [k, typeof v === 'number' ? v : parseInt(v.replace('#',''), 16)]))
  }

  // Build per-atom base-letter colour map (key: "strand_id:bp_index:direction").
  const _BASE_HEX = { A: 0x44dd88, T: 0xff5555, G: 0xffcc00, C: 0x55aaff }
  function _getAtomBaseColors() {
    const { currentDesign, currentGeometry } = store.getState()
    const out = new Map()
    if (!currentDesign || !currentGeometry) return out
    const nucLetter = buildNucLetterMap(currentDesign, currentGeometry)
    for (const [nuc, ch] of nucLetter) {
      const k = `${nuc.strand_id}:${nuc.bp_index}:${nuc.direction}`
      out.set(k, _BASE_HEX[ch])
    }
    return out
  }

  // Dispatch atomistic colouring based on the global coloringMode.
  // Extra-base atoms always use the strand colour map (handled inside
  // atomistic_renderer); the strand map we send mirrors coloringMode
  // ('strand' uses palette/groups, 'cluster' uses cluster-mapped colours).
  function _refreshAtomColors() {
    const { coloringMode } = store.getState()
    const strandMap = _getAtomStrandColors()
    if (coloringMode === 'base') {
      atomisticRenderer.setColorMode('base', strandMap, _getAtomBaseColors())
    } else if (coloringMode === 'cpk') {
      atomisticRenderer.setColorMode('cpk', strandMap)
    } else {
      // 'strand' or 'cluster' → strand-color path; map already reflects mode.
      atomisticRenderer.setColorMode('strand', strandMap)
    }
  }

  // Side-panel atomistic colour buttons — quick CPK ↔ Strand toggle that drives
  // the global coloringMode (so both menu and panel stay in sync).
  document.getElementById('atom-color-cpk')?.addEventListener('click', () => {
    _setColoringMode('cpk')
  })
  document.getElementById('atom-color-strand')?.addEventListener('click', () => {
    _setColoringMode('strand')
  })

  // Keep atom + surface strand colours in sync when groups/colors change.
  // Always refresh regardless of CPK/strand mode so extra-base coloring stays current.
  store.subscribe((newState, prevState) => {
    if (newState.strandColors === prevState.strandColors
        && newState.strandGroups === prevState.strandGroups
        && newState.coloringMode === prevState.coloringMode
        && newState.loopStrandIds === prevState.loopStrandIds) return
    if (atomisticRenderer.getMode() !== 'off') _refreshAtomColors()
    if (_surfaceMode !== 'off') {
      surfaceRenderer.applyStrandColors(_getAtomStrandColors())
    }
  })

  // Fetch + load atom data whenever mode switches from off → non-off.
  let _atomDataCache  = null

  // Atomistic-only option rows (shown only while atomistic mode is active)
  const _atomisticSliderRowIds = [
    'repr-atom-radius-row',
    'repr-atom-color-row',
  ]
  function _setAtomisticSlidersVisible(visible) {
    for (const id of _atomisticSliderRowIds) {
      const el = document.getElementById(id)
      if (el) el.style.display = visible ? '' : 'none'
    }
  }

  function _setCGVisible(visible) {
    const root = designRenderer.getHelixCtrl()?.root
    if (root) root.visible = visible   // extra-base beads/slabs are children of root
    unfoldView?.setArcsVisible(visible)
    overhangLinkArcs?.setVisible?.(visible)
  }

  function _atomisticUrl() {
    return '/api/design/atomistic'
  }

  async function _applyAtomisticMode(mode) {
    atomisticRenderer.setMode(mode)
    // Hide CG model when any atomistic mode is active; restore when off
    _setCGVisible(mode === 'off')
    _setAtomisticSlidersVisible(mode !== 'off')
    if (mode !== 'off' && !_atomDataCache) {
      showPersistentToast('Loading atomistic model…')
      try {
        const resp = await fetch(_atomisticUrl())
        if (!resp.ok) {
          dismissToast()
          console.error('Atomistic fetch failed:', resp.status)
          return
        }
        _atomDataCache = await resp.json()
        atomisticRenderer.update(_atomDataCache)
        _refreshAtomColors()
        const { selectedObject, multiSelectedStrandIds } = store.getState()
        atomisticRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
      } catch (e) {
        console.error('Atomistic fetch error:', e)
      } finally {
        dismissToast()
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
        arrow.classList.toggle('is-collapsed', _collapsed)
        if (!_collapsed) _rebuildPanel(store.getState().currentDesign)
      })
    }

    const iStyle = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                   'color:#c9d1d9;padding:2px 5px;font-family:var(--font-ui);font-size:11px;'

    // strand_id → array of row elements (one overhang may share a strand)
    let _rowsByStrandId = {}

    function _rebuildPanel(design) {
      const overhangs = design?.overhangs ?? []
      _rowsByStrandId = {}
      if (_collapsed) return

      list.innerHTML = ''

      if (!overhangs.length) {
        const empty = document.createElement('div')
        empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
        empty.textContent   = 'No overhangs on this design.'
        list.appendChild(empty)
        return
      }

      // Column header
      const hdr = document.createElement('div')
      hdr.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto auto;gap:4px;' +
                           'margin-bottom:4px;font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em'
      hdr.innerHTML = '<span>Name</span><span>Sequence</span><span></span><span></span>'
      list.appendChild(hdr)

      for (const ovhg of overhangs) {
        const row = document.createElement('div')
        row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto auto;gap:4px;' +
                            'margin-bottom:4px;align-items:center;padding:2px 4px;' +
                            'border-radius:3px;border-left:2px solid transparent;transition:background 0.1s'
        row.dataset.strandId = ovhg.strand_id

        // Register for highlight tracking
        if (!_rowsByStrandId[ovhg.strand_id]) _rowsByStrandId[ovhg.strand_id] = []
        _rowsByStrandId[ovhg.strand_id].push(row)

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

        for (const inp of [nameInput, seqInput]) {
          inp.addEventListener('keydown', e => e.stopPropagation())
          inp.addEventListener('focus', () => selectionManager.selectStrand(ovhg.strand_id))
        }

        const genBtn = document.createElement('button')
        genBtn.textContent = 'Gen'
        genBtn.title       = 'Generate random sequence (Johnson et al.)'
        genBtn.style.cssText = 'padding:2px 7px;background:#162420;border:1px solid #3fb950;border-radius:4px;' +
                               'color:#3fb950;font-size:11px;cursor:pointer;white-space:nowrap'
        genBtn.addEventListener('click', async () => {
          genBtn.disabled = true
          showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
          await api.generateOverhangRandomSequence(ovhg.id)
          genBtn.disabled = false
        })

        function _syncGenBtn() {
          const v = seqInput.value.trim()
          genBtn.style.display = (!v || /^n+$/i.test(v)) ? '' : 'none'
        }
        _syncGenBtn()
        seqInput.addEventListener('input', _syncGenBtn)

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
        row.appendChild(genBtn)
        row.appendChild(saveBtn)
        list.appendChild(row)
      }

      // Apply highlight for whatever is currently selected
      _updateHighlight()
    }

    /** Collect all strand IDs currently selected (single, multi-strand, or domain). */
    function _selectedStrandIds() {
      const s = store.getState()
      const ids = new Set()
      if (s.selectedObject?.data?.strand_id) ids.add(s.selectedObject.data.strand_id)
      for (const id of s.multiSelectedStrandIds  ?? []) ids.add(id)
      for (const d of s.multiSelectedDomainIds   ?? []) ids.add(d.strandId)
      return ids
    }

    function _updateHighlight() {
      const selected = _selectedStrandIds()
      for (const [strandId, rows] of Object.entries(_rowsByStrandId)) {
        const active = selected.has(strandId)
        for (const row of rows) {
          row.style.background  = active ? '#1e3a5f' : ''
          row.style.borderLeft  = active ? '2px solid #58a6ff' : '2px solid transparent'
        }
      }
    }

    store.subscribe((newState, prevState) => {
      if (newState.currentDesign !== prevState.currentDesign) {
        _rebuildPanel(newState.currentDesign)
      } else if (
        newState.selectedObject         !== prevState.selectedObject         ||
        newState.multiSelectedStrandIds !== prevState.multiSelectedStrandIds ||
        newState.multiSelectedDomainIds !== prevState.multiSelectedDomainIds
      ) {
        _updateHighlight()
      }
    })
  })()

  // ── Strand groups panel ──────────────────────────────────────────────────────
  ;(function _initGroupsPanel() {
    const panel   = document.getElementById('groups-panel')
    const list    = document.getElementById('groups-list')
    const heading = document.getElementById('groups-panel-heading')
    const arrow   = document.getElementById('groups-panel-arrow')
    const newBtn  = document.getElementById('groups-new-btn')
    const colorsBtn = document.getElementById('groups-colors-btn')
    if (!panel || !list) return

    let _collapsed = false

    heading.addEventListener('click', () => {
      _collapsed = !_collapsed
      list.style.display   = _collapsed ? 'none' : ''
      newBtn.style.display = _collapsed ? 'none' : ''
      if (colorsBtn) colorsBtn.style.display = _collapsed ? 'none' : ''
      arrow.classList.toggle('is-collapsed', _collapsed)
    })

    const _iStyle  = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                     'color:#c9d1d9;padding:2px 5px;font-family:var(--font-ui);font-size:11px;'
    const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
    const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
    const _delStyle  = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'

    function _rebuildPanel(groups) {
      list.innerHTML = ''
      for (const group of groups) {
        const row = document.createElement('div')
        row.style.cssText = 'display:grid;grid-template-columns:1fr auto auto auto auto;gap:4px;margin-bottom:6px;align-items:center;cursor:pointer'
        row.title = 'Select strands in this group'
        row.addEventListener('click', e => {
          if (e.target.closest('button,input')) return
          const designStrandIds = new Set((store.getState().currentDesign?.strands ?? []).map(s => s.id))
          const ids = (group.strandIds ?? []).filter(id => designStrandIds.has(id))
          if (!ids.length) {
            showToast('This group has no strands to select')
            return
          }
          selectionManager.setMultiHighlight(ids)
        })

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
        countEl.style.cssText = 'color:#8b949e;font-size:var(--text-xs);min-width:1.5em;text-align:center'

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

    colorsBtn?.addEventListener('click', () => {
      const { currentDesign, currentGeometry, strandColors, strandGroups } = store.getState()
      const strands = currentDesign?.strands ?? []
      if (!strands.length) return

      const effective = { ...(strandColors ?? {}) }
      for (const group of strandGroups ?? []) {
        if (!group.color) continue
        const hex = parseInt(group.color.replace('#', ''), 16)
        for (const sid of group.strandIds ?? []) effective[sid] = hex
      }
      const palette = currentGeometry ? buildStapleColorMap(currentGeometry, currentDesign) : new Map()

      function _hexFromInt(value) {
        return `#${Number(value).toString(16).padStart(6, '0').slice(-6)}`
      }

      const byColor = new Map()
      for (const strand of strands) {
        if (strand.strand_type === 'scaffold') continue
        let color = effective[strand.id]
        if (color == null && strand.color) color = parseInt(strand.color.replace('#', ''), 16)
        if (color == null) color = palette.get(strand.id)
        if (color == null) continue
        const key = _hexFromInt(color).toLowerCase()
        if (!byColor.has(key)) byColor.set(key, [])
        byColor.get(key).push(strand.id)
      }

      const groups = [...byColor.entries()].map(([color, strandIds], i) => ({
        id: `grp_color_${Date.now()}_${i}`,
        name: `Group ${i + 1}`,
        color,
        strandIds,
      }))
      pushGroupUndo()
      store.setState({ strandGroups: groups })
      showToast(`Created ${groups.length} staple group${groups.length === 1 ? '' : 's'} from colors`)
    })

    newBtn.addEventListener('click', () => {
      pushGroupUndo()
      const { strandGroups, multiSelectedStrandIds } = store.getState()
      const n = strandGroups.length + 1
      const colors = ['#74b9ff', '#6bcb77', '#ff6b6b', '#ffd93d', '#a29bfe', '#55efc4']
      const color = colors[(n - 1) % colors.length]
      const initialIds = multiSelectedStrandIds?.length > 0 ? [...multiSelectedStrandIds] : []
      // Remove selected strands from any existing group before adding to the new one.
      const trimmed = initialIds.length > 0
        ? strandGroups.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !initialIds.includes(s)) }))
        : strandGroups
      store.setState({
        strandGroups: [...trimmed, { id: `grp_${Date.now()}`, name: `Group ${n}`, color, strandIds: initialIds }],
      })
    })

    store.subscribe((newState, prevState) => {
      if (newState.strandGroups === prevState.strandGroups) return
      if (!_collapsed) _rebuildPanel(newState.strandGroups)
    })
  })()

  const sequenceOverlay = initSequenceOverlay(scene, store)

  // ── Cadnano position reapply on geometry or design change ───────────────────
  // Registered here — after initSequenceOverlay — so that this fires AFTER the
  // sequence overlay's subscriber, which rebuilds letter sprites at raw 3D
  // positions whenever geometry/design change.  Firing last ensures cadnano
  // positions are applied on top of both the unfold-view offsets (applied by
  // unfold_view's subscriber, registered much earlier) and the sequence overlay
  // rebuild.  It fires on design change too because API responses sometimes
  // deliver currentDesign and currentGeometry in two separate store.setState
  // calls (design first, geometry fetched async).
  store.subscribe((newState, prevState) => {
    if (!cadnanoView.isActive()) return
    const geoChg = newState.currentGeometry !== prevState.currentGeometry
    const desChg = newState.currentDesign   !== prevState.currentDesign
    if (geoChg || desChg) {
      if (window._cnDebug)
        console.log(`[CN f${window._cnFrame}] cadnanoView reapply subscriber fired (geo:${geoChg} des:${desChg})`)
      cadnanoView.reapplyPositions()
    }
  })

  // ── Cadnano compensator for async deform_view straightGeometry fetch ────────
  // When a design has deformations/cluster_transforms, deform_view.js fires an
  // async getStraightGeometry() fetch on currentGeometry change.  Once the fetch
  // resolves it calls store.setState({ straightGeometry, straightHelixAxes }),
  // which would normally trigger deform_view's own subscriber to reapply 3D
  // positions — but that subscriber is now guarded against cadnanoActive.
  // This subscriber fires instead and restores the cadnano layout.
  store.subscribe((newState, prevState) => {
    if (!cadnanoView.isActive()) return
    if (newState.straightGeometry  !== prevState.straightGeometry ||
        newState.straightHelixAxes !== prevState.straightHelixAxes) {
      if (window._cnDebug)
        console.log(`[CN f${window._cnFrame}] cadnanoView reapply — straightGeometry updated`)
      cadnanoView.reapplyPositions()
    }
  })

  // ── Browser dev-tools debug helpers ─────────────────────────────────────────
  //
  //  window._nadocDebug.help()           — print this usage guide
  //  window._nadocDebug.posTrace(on)     — log every backbone-bead position update
  //                                        with a stack trace (cadnano-active only)
  //  window._nadocDebug.snapPos(label)   — snapshot all bead [x,y,z] positions now
  //  window._nadocDebug.diffPos(a, b)    — compare two snapshots; print moved beads
  //  window._nadocDebug.storeTrace(keys) — log every store.setState() that touches
  //                                        the listed keys (or all keys if omitted)
  //  window._nadocDebug.subTrace(on)     — log every store subscriber notification
  //                                        when cadnano is active
  //  window._cnDebug = true              — cadnano_view verbose logging (existing)
  //  window._cnCheck()                   — snapshot cadnano state (existing)
  //  window._cnMonitor()                 — watch bead-0.x for drift (existing)
  //
  window._nadocDebug = (() => {
    let _posTraceOn = false
    let _storeTraceUnsub = null
    const _savedDrFns = {}  // saves originals when posTrace is on

    /** Intercept designRenderer position-setting functions and log with stack. */
    function posTrace(on = true) {
      if (on === _posTraceOn) return
      _posTraceOn = on
      const fns = ['applyUnfoldOffsets', 'applyDeformLerp', 'applyCadnanoPositions']

      if (on) {
        for (const name of fns) {
          const original = designRenderer[name].bind(designRenderer)
          _savedDrFns[name] = original
          designRenderer[name] = function(...args) {
            if (store.getState().cadnanoActive)
              console.trace(`[posTrace f${window._cnFrame ?? '?'}] designRenderer.${name}()`)
            return original(...args)
          }
        }
        console.log('[nadocDebug.posTrace] ON — stack traces logged when cadnano active')
      } else {
        for (const name of fns) {
          if (_savedDrFns[name]) { designRenderer[name] = _savedDrFns[name]; delete _savedDrFns[name] }
        }
        console.log('[nadocDebug.posTrace] OFF')
      }
    }

    /** Return a Map<key, [x,y,z]> snapshot of all non-phantom backbone bead positions. */
    function snapPos(label = 'snap') {
      const m = new Map()
      for (const e of designRenderer.getBackboneEntries()) {
        if (e.nuc.helix_id?.startsWith('__')) continue
        m.set(`${e.nuc.helix_id}:${e.nuc.bp_index}:${e.nuc.direction}`, [e.pos.x, e.pos.y, e.pos.z])
      }
      console.log(`[nadocDebug.snapPos] "${label}" — ${m.size} beads, cadnanoActive=${store.getState().cadnanoActive}`)
      return { label, map: m }
    }

    /** Print beads that moved more than threshold nm between two snapshots. */
    function diffPos(a, b, threshold = 0.05) {
      const moved = []
      for (const [key, [ax, ay, az]] of a.map) {
        const p = b.map.get(key)
        if (!p) { moved.push([key, 'missing in B']); continue }
        const [bx, by, bz] = p
        const d = Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)
        if (d > threshold)
          moved.push([key, `Δ=${d.toFixed(3)} nm`, `(${ax.toFixed(2)},${ay.toFixed(2)},${az.toFixed(2)})→(${bx.toFixed(2)},${by.toFixed(2)},${bz.toFixed(2)})`])
      }
      console.group(`[nadocDebug.diffPos] "${a.label}"→"${b.label}": ${moved.length} beads moved`)
      moved.slice(0, 25).forEach(r => console.log(...r))
      if (moved.length > 25) console.log(`  …and ${moved.length - 25} more`)
      console.groupEnd()
      return moved
    }

    /**
     * Log store.setState() calls that touch the listed keys (pass [] for ALL).
     * Returns an unsubscribe function to stop tracing.
     */
    function storeTrace(keys = []) {
      if (_storeTraceUnsub) { _storeTraceUnsub(); _storeTraceUnsub = null }
      const orig = store.setState.bind(store)
      store.setState = function(partial) {
        const changed = Object.keys(partial)
        const relevant = keys.length ? changed.filter(k => keys.includes(k)) : changed
        if (relevant.length > 0)
          console.trace(`[storeTrace f${window._cnFrame ?? '?'}] setState: ${relevant.join(', ')}`)
        return orig(partial)
      }
      const stop = () => { store.setState = orig; _storeTraceUnsub = null; console.log('[nadocDebug.storeTrace] OFF') }
      _storeTraceUnsub = stop
      console.log(`[nadocDebug.storeTrace] ON — watching: ${keys.length ? keys.join(', ') : 'ALL keys'}`)
      return stop
    }

    /**
     * Wrap every store subscriber to log which one is firing (by insertion index)
     * and whether cadnano is active.  Heavy — only use when debugging subscriber order.
     */
    function subTrace(on = true) {
      window._cnSubTrace = on
      console.log(`[nadocDebug.subTrace] ${on ? 'ON' : 'OFF'} — set window._cnSubTrace=false to stop`)
      // Actual interception is done by patching store.subscribe retroactively; since
      // that's not feasible post-init, use this flag to gate logging inside the
      // cadnano reapply subscriber (which is the most critical one).
    }

    /** Inventory ds-linker state: backend (currentDesign) vs frontend (renderer)
     *  ‒ surfaces mismatches like "0 connections but bridge meshes still in scene".
     *  Returns the inventory object so you can grep into specifics in the console. */
    function linkers() {
      const state = store.getState()
      const design = state.currentDesign
      const geometry = state.currentGeometry ?? []
      if (!design) {
        console.warn('[linkers] no currentDesign')
        return null
      }
      const conns = design.overhang_connections ?? []
      const lnkHelices = (design.helices ?? []).filter(h => h.id?.startsWith('__lnk__'))
      const lnkStrands = (design.strands ?? []).filter(s => s.id?.startsWith('__lnk__'))
      const lnkNucs    = geometry.filter(n => (n.helix_id ?? '').startsWith('__lnk__'))
      const helixCtrl  = designRenderer.getHelixCtrl?.()
      const allEntries = helixCtrl?.getBackboneEntries?.() ?? []
      const lnkEntries = allEntries.filter(e => (e.nuc.helix_id ?? '').startsWith('__lnk__'))
      const arcChildren = overhangLinkArcs?.group?.children ?? []

      console.group(`[NADOC linker inventory] connections=${conns.length}`)
      if (conns.length) {
        console.group(`overhang_connections (${conns.length})`)
        for (const c of conns) console.log(
          `${c.id} "${c.name}" type=${c.linker_type} ` +
          `A=${c.overhang_a_id}/${c.overhang_a_attach} ` +
          `B=${c.overhang_b_id}/${c.overhang_b_attach} ` +
          `len=${c.length_value} ${c.length_unit}`)
        console.groupEnd()
      }
      console.log(`__lnk__ helices in design.helices: ${lnkHelices.length}`,
        lnkHelices.map(h => h.id))
      console.log(`__lnk__ strands in design.strands: ${lnkStrands.length}`,
        lnkStrands.map(s => s.id))
      console.log(`__lnk__ nucs in currentGeometry:   ${lnkNucs.length}`)
      console.log(`__lnk__ entries in renderer:       ${lnkEntries.length}`)
      console.log(`overhangLinkArcs group children:   ${arcChildren.length}`,
        arcChildren.map(c => c.name || `(${c.type})`))
      console.groupEnd()

      const issues = []
      if (conns.length === 0) {
        if (lnkHelices.length)  issues.push(`${lnkHelices.length} __lnk__ helices but 0 connections`)
        if (lnkStrands.length)  issues.push(`${lnkStrands.length} __lnk__ strands but 0 connections`)
        if (lnkNucs.length)     issues.push(`${lnkNucs.length} __lnk__ nucs in geometry but 0 connections`)
        if (lnkEntries.length)  issues.push(`${lnkEntries.length} __lnk__ entries in renderer but 0 connections`)
        if (arcChildren.length) issues.push(`${arcChildren.length} overhangLinkArcs children but 0 connections`)
      }
      const expectedHelixIds = new Set(conns.map(c => `__lnk__${c.id}`))
      for (const h of lnkHelices) {
        if (!expectedHelixIds.has(h.id)) issues.push(`orphan __lnk__ helix in design: ${h.id}`)
      }
      const renderedHelixIds = new Set(lnkEntries.map(e => e.nuc.helix_id))
      for (const hid of renderedHelixIds) {
        if (!expectedHelixIds.has(hid)) issues.push(`renderer has __lnk__ entries for orphan helix: ${hid}`)
      }
      if (issues.length) {
        console.warn('[linkers] mismatches detected:')
        for (const i of issues) console.warn('  • ' + i)
      } else {
        console.log('[linkers] ✓ no mismatches')
      }
      return { conns, lnkHelices, lnkStrands, lnkNucs, lnkEntries, arcChildren, issues }
    }

    /** Force a full design_renderer rebuild by replacing currentGeometry's
     *  array reference. Useful to confirm whether a stale visual is the
     *  positions_only/cluster_only path failing to clean up something the
     *  full rebuild does correctly. */
    function forceRebuild() {
      const state = store.getState()
      if (!state.currentGeometry) {
        console.warn('[forceRebuild] no currentGeometry to refresh')
        return
      }
      // New array reference triggers design_renderer's geoChanged path,
      // bypassing the visual-only-design-change early-return.
      store.setState({
        currentGeometry:  [...state.currentGeometry],
        currentHelixAxes: state.currentHelixAxes
          ? { ...state.currentHelixAxes }
          : state.currentHelixAxes,
      })
      console.log('[forceRebuild] dispatched — design_renderer should rebuild now')
    }

    /** Trigger a clean backend re-fetch of design + geometry, replacing all
     *  stores. The ground truth for "what should be rendered". If linker
     *  meshes vanish after this, the bug is in the seek/undo/redo update
     *  path leaving stale meshes; if they persist, the bug is in the backend
     *  state itself. */
    async function refetch() {
      console.log('[refetch] re-fetching design + geometry from backend…')
      await api.getDesign()
      await api.getGeometry()
      console.log('[refetch] done — compare with .linkers() output')
    }

    function help() {
      console.log(`
NADOC debug tools — window._nadocDebug
  .posTrace(true/false)   Intercept designRenderer position setters; log stack traces when cadnano is active.
                          Reveals exactly which fn last moved beads.  Use with .snapPos / .diffPos for before/after.
  .snapPos("label")       → {label, map}  Snapshot all backbone bead [x,y,z] positions.
  .diffPos(a, b)          Compare two snapshots; shows beads that moved > 0.05 nm.
  .storeTrace(["key"…])   Patch store.setState to log matching keys with stack traces.
                          Pass [] for all keys.  Returns unsubscribe fn.
  .subTrace(true)         Set window._cnSubTrace=true to gate extra logging in key subscribers.

  .linkers()              Print backend vs renderer ds-linker inventory; flags mismatches like
                          "0 connections but bridge meshes still in scene". Returns the inventory.
  .forceRebuild()         Bump currentGeometry's array ref so design_renderer rebuilds the scene.
                          Useful to test whether a stale visual is the seek/cluster path leaving
                          something behind that a full rebuild would clear.
  .refetch()              await getDesign() + getGeometry() — restores the canonical backend state.
                          Use as ground truth: if linker meshes vanish here but reappear after a
                          seek, the bug is in the seek path; if they persist here, the bug is on
                          the backend.

Also available (cadnano_view.js):
  window._cnDebug = true  Verbose per-frame cadnano logging.
  window._cnCheck()       Show cadnano state: active, midX, bead counts at midX vs off-midX.
  window._cnMonitor()     Watch bead-0.x every frame for drift.
  window._cnEntries()     Return all backbone entries for manual inspection.

Typical debugging workflow for "reverts to 3D" bug:
  1.  _nadocDebug.posTrace(true)              // start intercepting
  2.  Delete a crossover in cadnano mode
  3.  Check console — last logged stack trace before positions go wrong is the culprit
  4.  OR: snap1=_nadocDebug.snapPos('before'); delete crossover; snap2=_nadocDebug.snapPos('after')
         _nadocDebug.diffPos(snap1, snap2)    // see which beads moved and how far
`)
    }

    return {
      posTrace, snapPos, diffPos, storeTrace, subTrace, linkers, forceRebuild, refetch, help,
      // Test-only handles — expose the running module instances so Playwright
      // can drive selection / inspect arc meshes without simulating mouse
      // events on the 3D canvas.
      selectionManager, overhangLinkArcs, scene,
    }
  })()

  const crossSectionMinimap = initCrossSectionMinimap(document.getElementById('canvas-area'))

  const viewCube = initViewCube(
    document.getElementById('canvas-area'),
    camera,
    controls,
    () => designRenderer.getHelixCtrl()?.root,
  )

  function _isUnfoldActive() { return store.getState().unfoldActive }

  async function _toggleUnfold() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return
    if (isDeformActive()) return

    // U key while cadnano is active: exit cadnano but stay in unfold view,
    // rather than toggling unfold off (which would break cadnano's internal state).
    if (cadnanoView.isActive()) {
      await cadnanoView.deactivate({ keepUnfold: true })
      if (!slicePlane.isVisible()) {
        crossSectionMinimap.clearSlice()
        crossSectionMinimap.hide()
        _clearSliceHighlights()
      }
      document.getElementById('mode-indicator').textContent =
        '2D UNFOLD — helices stacked by label order · [U] to return to 3D'
      return
    }

    // Cannot enter unfold while deformations or non-identity cluster transforms are
    // visually active — helices are not at pure topology positions, so the layout
    // would be skewed.  A default cluster with identity rotation/translation is
    // excluded because it produces no visual offset.  If the deform view is already
    // suppressed (t=0, D-key), geometry is at straight positions and unfold is safe.
    if (!unfoldView.isActive()) {
      const hasDeformations       = !!(currentDesign?.deformations?.length)
      const hasEffectiveTransform = currentDesign?.cluster_transforms?.some(ct => {
        const [x, y, z, w] = ct.rotation
        const [tx, ty, tz] = ct.translation
        return Math.abs(x) > 1e-9 || Math.abs(y) > 1e-9 || Math.abs(z) > 1e-9 || Math.abs(w - 1) > 1e-9
            || Math.abs(tx) > 1e-9 || Math.abs(ty) > 1e-9 || Math.abs(tz) > 1e-9
      }) ?? false
      const { deformVisuActive } = store.getState()
      if ((hasDeformations || hasEffectiveTransform) && deformVisuActive) {
        showToast('Deformations are active — press D to suppress them, then unfold')
        return
      }
    }
    // Disable expanded spacing before entering unfold view.
    if (!unfoldView.isActive()) expandedSpacing.forceOff()
    unfoldView.toggle()
    const active = unfoldView.isActive()
    if (active) {
      // Aim the camera's orbit target at the design's Z midpoint so the
      // unfolded helices stay within the view frustum.  This prevents clipping
      // on imported designs with non-zero bp_start (e.g. axis_start.z ≈ 135 nm).
      // Helices are NOT translated in Z — only the orbit target moves, not the camera.
      const midZ = unfoldView.getMidZ()
      const dz = midZ - controls.target.z
      controls.target.z += dz
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

  async function _toggleCadnano() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return
    if (isDeformActive()) return
    // Same deformation guard as unfold view.
    if (!cadnanoView.isActive()) {
      const hasDeformations       = !!(currentDesign?.deformations?.length)
      const hasEffectiveTransform = currentDesign?.cluster_transforms?.some(ct => {
        const [x, y, z, w] = ct.rotation
        const [tx, ty, tz] = ct.translation
        return Math.abs(x) > 1e-9 || Math.abs(y) > 1e-9 || Math.abs(z) > 1e-9 || Math.abs(w - 1) > 1e-9
            || Math.abs(tx) > 1e-9 || Math.abs(ty) > 1e-9 || Math.abs(tz) > 1e-9
      }) ?? false
      const { deformVisuActive } = store.getState()
      if ((hasDeformations || hasEffectiveTransform) && deformVisuActive) {
        showToast('Deformations are active — press D to suppress them, then enter cadnano mode')
        return
      }
      expandedSpacing.forceOff()
    }
    await cadnanoView.toggle()
    const active = cadnanoView.isActive()
    if (!active && !slicePlane.isVisible()) {
      // Cadnano slice indicator was hidden — clear minimap and base highlights.
      crossSectionMinimap.clearSlice()
      crossSectionMinimap.hide()
      _clearSliceHighlights()
    }
    document.getElementById('mode-indicator').textContent = active
      ? 'CADNANO MODE — two-track 2D view · [K] to exit'
      : unfoldView.isActive()
        ? '2D UNFOLD — helices stacked by label order · [U] to return to 3D'
        : 'NADOC · WORKSPACE'
  }

  // _toggleAssembly removed — assembly mode is entered by opening/creating a .nass file,
  // not by a toggle. _enterAssemblyMode / _exitAssemblyMode are used instead.

  async function _toggleDeformView() {
    if (isDeformActive()) return
    // Geometry in cadnano / unfold mode is at straight positions already (both
    // views require deform to be off). Toggling deform from inside those views
    // is meaningless and racy — the lerp would fight whichever overlay owns
    // bead positions. Surface the rule with a toast and return.
    if (cadnanoView.isActive()) {
      showToast('Exit cadnano mode (K) before toggling deformed view')
      return
    }
    if (unfoldView.isActive()) {
      showToast('Exit unfold view (U) before toggling deformed view')
      return
    }
    const { currentDesign } = store.getState()
    // Cannot toggle when geometry is already straight (no deformations and no non-identity
    // cluster transforms).  A default cluster with identity rotation/translation is excluded
    // because it produces no visual difference from the undeformed geometry.
    const hasDeformations = !!(currentDesign?.deformations?.length)
    const hasEffectiveTransform = currentDesign?.cluster_transforms?.some(ct => {
      const [x, y, z, w] = ct.rotation
      const [tx, ty, tz] = ct.translation
      return Math.abs(x) > 1e-9 || Math.abs(y) > 1e-9 || Math.abs(z) > 1e-9 || Math.abs(w - 1) > 1e-9
          || Math.abs(tx) > 1e-9 || Math.abs(ty) > 1e-9 || Math.abs(tz) > 1e-9
    }) ?? false
    if (!hasDeformations && !hasEffectiveTransform) return
    if (deformView.isActive()) {
      // Turn OFF: animate to straight geometry so user can compare before/after.
      deformView.deactivate()
      _setMenuToggle('menu-view-deform', false)
      document.getElementById('mode-indicator').textContent =
        'STRAIGHT VIEW — geometry without deformations · click Deformed View to return'
    } else {
      // Turn ON: animate back to deformed geometry.
      await deformView.activate()
      _setMenuToggle('menu-view-deform', true)
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
  }

  // ── Slice plane ─────────────────────────────────────────────────────────────
  const slicePlane = initSlicePlane(scene, camera, canvas, controls, {
    onExtrude: async ({ cells, lengthBp, plane, offsetNm, continuationMode, newBundle, latticeType = 'HONEYCOMB', deformedFrame, refHelixId, strandFilter = 'both', ligateAdjacent = true }) => {
      let result
      if (newBundle) {
        // Preserve the user's design name across bundle creation — _fileName is set
        // by the "New Design" modal or by opening a file; fall back to the current
        // design's metadata name, then to nothing (server default).
        const bundleName = _fileName ?? store.getState().currentDesign?.metadata?.name
        result = await api.createBundle({ cells, lengthBp, plane, strandFilter, latticeType, ligateAdjacent, ...(bundleName ? { name: bundleName } : {}) })
      } else if (deformedFrame) {
        result = await api.addBundleDeformedContinuation({ cells, lengthBp, plane, frame: deformedFrame, refHelixId })
      } else if (continuationMode) {
        result = await api.addBundleContinuation({ cells, lengthBp, plane, offsetNm, strandFilter, ligateAdjacent })
      } else {
        result = await api.addBundleSegment({ cells, lengthBp, plane, offsetNm, strandFilter, ligateAdjacent })
      }
      if (!result) {
        const err = store.getState().lastError
        throw new Error(err?.message ?? (newBundle ? 'Bundle creation failed' : 'Segment extrusion failed'))
      }
      if (newBundle) {
        // Record plane and helix creation order for the unfold view.
        const newHelices = store.getState().currentDesign?.helices?.slice(-cells.length) ?? []
        store.setState({ currentPlane: plane, unfoldHelixOrder: newHelices.map(h => h.id) })
        slicePlane.hide()
        workspace.deactivate()
        workspace.hide()
      } else {
        // Append new helix IDs to the unfold order (preserving existing order).
        const existing = store.getState().unfoldHelixOrder ?? []
        const newIds   = cells.map(([row, col]) => `h_${plane}_${row}_${col}`)
        const toAdd    = newIds.filter(id => !existing.includes(id))
        if (toAdd.length) store.setState({ unfoldHelixOrder: [...existing, ...toAdd] })
        slicePlane.hide()
      }
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    },
    getDesign:      () => store.getState().currentDesign,
    getHelixAxes:   () => store.getState().currentHelixAxes,
    onOffsetChange: (offsetNm, plane) => {
      // In cadnano mode the slice plane is in YZ orientation but offsetNm encodes
      // bp_index × RISE on the cadnano X-axis.  The minimap and highlight logic
      // both assume XY (Z-axis bundles), so we remap the plane to 'XY' here.
      // The BP formula  bp = round(bp_start + (offsetNm − axis_start.z) / RISE)
      // then gives the correct result because axis_start.z ≈ bp_start × RISE.
      const effectivePlane = store.getState().cadnanoActive ? 'XY' : plane
      crossSectionMinimap.update(offsetNm, effectivePlane, designRenderer.getBackboneEntries())
      _updateSliceHighlights(offsetNm, effectivePlane)
    },
  })

  // Link slicePlane to unfoldView so the plane dimensions lerp during unfold animation.
  unfoldView.setSlicePlane(slicePlane)

  // Auto-hide the slice plane when deformations are activated so the cross-section
  // always reflects the undeformed helix geometry.
  store.subscribe((newState, prevState) => {
    if (newState.deformVisuActive === prevState.deformVisuActive) return
    if (newState.deformVisuActive && newState.currentDesign?.deformations?.length) {
      if (slicePlane.isVisible()) {
        slicePlane.hide()
        crossSectionMinimap.clearSlice()
        crossSectionMinimap.hide()
        _clearSliceHighlights()
        _setMenuToggle('menu-view-slice', false)
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      }
    }
  })

  // When the user deletes their last helix (design loaded but now empty), surface
  // the workspace plane-picker so they can pick an origin plane and start a new
  // bundle — same UX as a brand-new part. Skipped in assembly mode (different flow).
  //
  // Comprehensive slice-plane teardown: matches the empty→non-empty branch
  // below so minimap, bp highlights, and the slice menu toggle all reset
  // cleanly when the design empties out from under an open slice plane.
  store.subscribe((newState, prevState) => {
    const newCount  = newState.currentDesign?.helices?.length  ?? 0
    const prevCount = prevState.currentDesign?.helices?.length ?? 0
    if (newCount !== 0 || prevCount === 0) return
    if (!newState.currentDesign || newState.assemblyActive) return
    if (slicePlane.isVisible()) {
      slicePlane.hide()
      crossSectionMinimap.clearSlice()
      crossSectionMinimap.hide()
      _clearSliceHighlights()
      _setMenuToggle('menu-view-slice', false)
    }
    workspace.show(newState.currentDesign.lattice_type ?? 'HONEYCOMB')
  })

  // Symmetric: when the design transitions from empty → non-empty via ANY path
  // (slider seek F0 → F1, undo back through an empty state, edit-feature replay,
  // file load while the workspace is up), dismiss the starting tool. The
  // existing in-tool cleanup at the createBundle callsite still runs first for
  // its branch (it also updates currentPlane/unfoldHelixOrder bookkeeping); this
  // subscription is idempotent and catches every other path.
  //
  // Mirrors the comprehensive teardown used elsewhere when the slice plane is
  // dismissed: hide minimap, clear bp highlights, untoggle the slice menu,
  // reset the mode indicator.
  store.subscribe((newState, prevState) => {
    const newCount  = newState.currentDesign?.helices?.length  ?? 0
    const prevCount = prevState.currentDesign?.helices?.length ?? 0
    if (newCount === 0 || prevCount !== 0) return
    if (!newState.currentDesign || newState.assemblyActive) return
    const sliceWasVisible = slicePlane.isVisible()
    if (sliceWasVisible) slicePlane.hide()
    if (workspace.isVisible?.() ?? true) {
      workspace.deactivate()
      workspace.hide()
    }
    if (sliceWasVisible) {
      crossSectionMinimap.clearSlice()
      crossSectionMinimap.hide()
      _clearSliceHighlights()
      _setMenuToggle('menu-view-slice', false)
    }
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
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
    if (slicePlane.isVisible()) {
      slicePlane.hide()
      crossSectionMinimap.clearSlice()
      crossSectionMinimap.hide()
      _clearSliceHighlights()
      _setMenuToggle('menu-view-slice', false)
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      return
    }
    const { currentDesign, currentPlane, deformVisuActive } = store.getState()
    if (!currentDesign || !currentPlane) return
    if (deformVisuActive && currentDesign.deformations?.length) {
      showToast('Slice plane is only available on the undeformed model — press D to suppress deformations first')
      return
    }
    const offset = _bundleMidOffset(currentDesign, currentPlane)
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
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
  let   _domainEndInfo     = null  // { helixId, bp, diskBp, openSide, plane, offsetNm, hasDeformations }

  function _showBluntPanel(info) {
    _domainEndInfo = info
    if (_bluntPanelEmpty)  _bluntPanelEmpty.style.display  = 'none'
    if (_bluntPanelInfo)   _bluntPanelInfo.textContent = `helix ${info.helixId}  bp ${info.bp}`
    if (_bluntPanel)       _bluntPanel.style.display = 'block'
  }
  function _hideBluntPanel() {
    _domainEndInfo = null
    if (_bluntPanel)      _bluntPanel.style.display      = 'none'
    if (_bluntPanelEmpty) _bluntPanelEmpty.style.display = ''
  }

  // ── Scaffold strand right-click context menu ────────────────────────────────
  const _scafSplitCtx  = document.getElementById('scaffold-split-ctx-menu')
  let _scafSplitTarget = null  // { strandId, helixId, bpPosition }

  function _showScaffoldSplitCtx(x, y, coneEntry) {
    const { helix_id, bp_index } = coneEntry.fromNuc
    _scafSplitTarget = { strandId: coneEntry.strandId, helixId: helix_id, bpPosition: bp_index }
    if (_scafSplitCtx) {
      _scafSplitCtx.style.left    = `${x}px`
      _scafSplitCtx.style.top     = `${y}px`
      _scafSplitCtx.style.display = 'block'
    }
  }
  function _hideScaffoldSplitCtx() {
    if (_scafSplitCtx) _scafSplitCtx.style.display = 'none'
    _scafSplitTarget = null
  }
  document.addEventListener('pointerdown', e => {
    if (_scafSplitCtx?.style.display !== 'none' && !_scafSplitCtx.contains(e.target)) _hideScaffoldSplitCtx()
  })

  document.getElementById('scaffold-split-btn')?.addEventListener('click', async () => {
    const target = _scafSplitTarget
    _hideScaffoldSplitCtx()
    if (!target) return
    const ok = await api.scaffoldSplit(target.strandId, target.helixId, target.bpPosition)
    if (!ok) alert('Scaffold split failed: ' + (store.getState().lastError?.message ?? 'unknown'))
  })

  document.getElementById('scaffold-assign-seq-btn')?.addEventListener('click', () => {
    const target = _scafSplitTarget
    _hideScaffoldSplitCtx()
    if (!target) return
    const modal = document.getElementById('assign-scaffold-modal')
    if (modal) modal.dataset.targetStrandId = target.strandId
    _openScaffoldModal()
  })

  document.getElementById('scaffold-delete-btn')?.addEventListener('click', async () => {
    const target = _scafSplitTarget
    _hideScaffoldSplitCtx()
    if (!target) return
    await api.deleteStrand(target.strandId)
  })

  // ── Overhang orientation context menu ────────────────────────────────────────

  let _ovhgCtxMenu = null   // currently visible menu element

  function _dismissOvhgMenu() {
    _ovhgCtxMenu?.remove()
    _ovhgCtxMenu = null
  }

  function _showOverhangOrientMenu(ovhgIds, clientX, clientY) {
    _dismissOvhgMenu()

    const menu = document.createElement('div')
    menu.style.cssText = `
      position: fixed; left: ${clientX}px; top: ${clientY}px;
      background: #1e2a3a; border: 1px solid #3a4a5a; border-radius: 6px;
      padding: 4px 0; min-width: 160px; z-index: 9999;
      box-shadow: 0 4px 16px rgba(0,0,0,0.5); font-family: var(--font-ui); font-size: 12px;
    `

    function _mItem(label, action, danger = false) {
      const el = document.createElement('div')
      el.textContent = label
      el.style.cssText = `padding: 6px 14px; color: ${danger ? '#ff7070' : '#eef'}; cursor: pointer;`
      el.addEventListener('mouseenter', () => { el.style.background = danger ? '#2d1515' : '#2a3a4a' })
      el.addEventListener('mouseleave', () => { el.style.background = 'transparent' })
      el.addEventListener('click', e => { e.stopPropagation(); _dismissOvhgMenu(); action() })
      return el
    }

    function _mSep() {
      const hr = document.createElement('div')
      hr.style.cssText = 'border-top: 1px solid #3a4a5a; margin: 4px 0;'
      return hr
    }

    menu.appendChild(_mItem('Edit Orientation', () => _ooOpen(ovhgIds)))
    menu.appendChild(_mItem('Reset Orientation', async () => {
      await api.patchOverhangRotationsBatch(ovhgIds.map(id => ({ overhang_id: id, rotation: [0, 0, 0, 1] })))
      if (store.getState().assemblyActive) {
        const { activeInstanceId, currentAssembly } = store.getState()
        if (activeInstanceId) assemblyRenderer.invalidateInstance(activeInstanceId)
        await assemblyRenderer.rebuild(currentAssembly)
      }
    }))
    if (ovhgIds.length === 1) {
      menu.appendChild(_mSep())
      menu.appendChild(_mItem('Set Label…', () => {
        const existing = store.getState().currentDesign?.overhangs?.find(o => o.id === ovhgIds[0])?.label ?? ''
        const name = prompt('Overhang label:', existing)
        if (name === null) return
        api.patchOverhang(ovhgIds[0], { label: name.trim() || null })
      }))
    }
    // Always-available entry into the manager — passes whichever overhang(s)
    // were right-clicked through as the prepopulation.
    menu.appendChild(_mSep())
    menu.appendChild(_mItem('Open Overhangs Manager…', () => {
      if (!store.getState().currentDesign?.helices?.length) return
      openOverhangsManager(ovhgIds)
    }))
    menu.appendChild(_mSep())
    menu.appendChild(_mItem('Clear All Overhangs', () => api.clearOverhangs(), true))

    document.body.appendChild(menu)
    _ovhgCtxMenu = menu

    setTimeout(() => {
      const dismiss = e => {
        if (!menu.contains(e.target)) {
          _dismissOvhgMenu()
          document.removeEventListener('pointerdown', dismiss)
        }
      }
      document.addEventListener('pointerdown', dismiss)
    }, 0)
  }

  // ── Blunt end right-click context menu ──────────────────────────────────────
  const _bluntCtx = document.getElementById('blunt-end-ctx-menu')
  let _domainEndCtxInfo = null  // { helixId, bp, diskBp, openSide, plane, offsetNm, hasDeformations }

  function _showBluntCtx(x, y, info) {
    _domainEndCtxInfo = info
    if (_bluntCtx) {
      _bluntCtx.style.left = `${x}px`
      _bluntCtx.style.top  = `${y}px`
      _bluntCtx.style.display = 'block'
    }
  }
  function _hideBluntCtx() {
    if (_bluntCtx) _bluntCtx.style.display = 'none'
    _domainEndCtxInfo = null
  }

  document.addEventListener('pointerdown', e => {
    if (_bluntCtx?.style.display !== 'none' && !_bluntCtx.contains(e.target)) _hideBluntCtx()
  })

  async function _bluntExtrude() {
    const info = _domainEndInfo   // capture before _hideBluntPanel nulls it
    _hideBluntPanel()
    if (!info) return
    const { plane, helixId, diskBp, hasDeformations } = info
    store.setState({ currentPlane: plane })
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
    const { deformVisuActive } = store.getState()
    if (hasDeformations && deformVisuActive) {
      const frame = await api.getDeformedFrame(diskBp, helixId)
      if (frame) {
        slicePlane.showDeformed(frame, { plane, continuation: true, refHelixId: helixId })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
        return
      }
    }
    slicePlane.showAtEnd(helixId, diskBp, true)
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
  }

  document.getElementById('blunt-extrude-btn')?.addEventListener('click', _bluntExtrude)
  document.getElementById('blunt-bend-btn')?.addEventListener('click', () => {
    const info = _domainEndInfo
    _hideBluntPanel()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('bend', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'BEND — drag planes to adjust segment · apply in popup · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn')?.addEventListener('click', () => {
    const info = _domainEndInfo
    _hideBluntPanel()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('twist', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'TWIST — drag planes to adjust segment · apply in popup · Esc to cancel'
  })

  // ── Context menu button wiring (right-click blunt end) ────────────────────
  document.getElementById('blunt-extrude-btn-ctx')?.addEventListener('click', async () => {
    const info = _domainEndCtxInfo
    _hideBluntCtx()
    if (!info) return
    const { plane, helixId, diskBp, hasDeformations } = info
    store.setState({ currentPlane: plane })
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
    const { deformVisuActive } = store.getState()
    if (hasDeformations && deformVisuActive) {
      const frame = await api.getDeformedFrame(diskBp, helixId)
      if (frame) {
        slicePlane.showDeformed(frame, { plane, continuation: true, refHelixId: helixId })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
        return
      }
    }
    slicePlane.showAtEnd(helixId, diskBp, true)
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
  })
  document.getElementById('blunt-bend-btn-ctx')?.addEventListener('click', () => {
    const info = _domainEndCtxInfo
    _hideBluntCtx()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('bend', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'BEND — drag planes to adjust segment · apply in popup · Esc to cancel'
  })
  document.getElementById('blunt-twist-btn-ctx')?.addEventListener('click', () => {
    const info = _domainEndCtxInfo
    _hideBluntCtx()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    if (!_clusterDeformGuard()) return
    startToolAtBp('twist', info.helixId, info.bp, info.openSide)
    document.getElementById('mode-indicator').textContent =
      'TWIST — drag planes to adjust segment · apply in popup · Esc to cancel'
  })

  // ── Blunt end indicators ─────────────────────────────────────────────────────
  const bluntEnds = initDomainEnds(scene, camera, canvas, {
    onDomainEndClick: (info) => {
      _showBluntPanel(info)
    },
    onDomainEndRightClick: ({ clientX, clientY, ...info }) => {
      _showBluntCtx(clientX, clientY, info)
    },
    // Block blunt-end picking whenever a gizmo or modal tool is in front of
    // the user. Deform / cluster-gizmo / unfold all paint geometry that the
    // user is meant to click on; if a blunt-end ring is layered over that
    // geometry, its capture-phase pointerdown listener swallows the click
    // and the gizmo never gets it.
    isDisabled: () => {
      if (slicePlane.isVisible()) return true
      if (_isUnfoldActive()) return true
      if (isDeformActive()) return true
      const s = store.getState()
      if (s.deformToolActive) return true
      if (s.translateRotateActive) return true
      return false
    },
    getUnfoldView: () => unfoldView,
  })

  // ── Workspace (blank 3D editor with plane picker) ───────────────────────────
  const workspace = initWorkspace(scene, camera, controls, {
    onPlanePicked: (plane, latticeType) => {
      slicePlane.show(plane, 0, false, false, { latticeType, newBundle: true })
      document.getElementById('mode-indicator').textContent =
        'NEW BUNDLE — select cells · right-click → Extrude · Esc to cancel'
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

  // IDs of menu-item divs that should be disabled until a design is loaded.
  // File + Help stay enabled (file ops + help are reachable on the welcome
  // screen). Origami Editor is gated since it operates on the open design.
  const _GATED_MENU_IDS = ['menu-item-edit', 'menu-item-tools', 'menu-item-view', 'menu-item-open-editor']

  function _setMenusEnabled(enabled) {
    for (const id of _GATED_MENU_IDS) {
      document.getElementById(id)?.classList.toggle('disabled', !enabled)
    }
  }

  function _setLeftPanelEnabled(enabled) {
    const leftPanel = document.getElementById('left-panel')
    if (!leftPanel) return
    const tabBtns   = document.querySelectorAll('#left-tab-strip .left-tab-btn')
    const toggleBtn = document.getElementById('left-tab-toggle')
    if (enabled) {
      leftPanel.classList.remove('locked-hidden')
      for (const b of tabBtns) b.disabled = false
      if (toggleBtn) toggleBtn.disabled = false
      // Re-apply the controller's persisted state now that the lock is lifted
      // (otherwise the panel would stay visually hidden until the next click).
      window.__leftSidebar?.refresh?.()
    } else {
      // Collapse and lock the panel; disable all tab buttons + toggle arrow
      // via the `:disabled` selector (CSS handles the visual dimming).
      leftPanel.classList.add('hidden', 'locked-hidden')
      for (const b of tabBtns) b.disabled = true
      if (toggleBtn) toggleBtn.disabled = true
    }
  }

  // Right panel: while disabled, every panel-section's body is collapsed
  // (h2 still visible) and pointer-events are blocked via .locked-inactive.
  function _setRightPanelEnabled(enabled) {
    document.getElementById('right-panel')?.classList.toggle('locked-inactive', !enabled)
  }

  // Top filter/view/mode strip above the canvas. Welcome screen disables it
  // since none of the toggles do anything meaningful without a design.
  function _setFilterStripEnabled(enabled) {
    document.getElementById('filter-view-strip')?.classList.toggle('locked-disabled', !enabled)
  }

  function _showWelcome() {
    if (window.nadocDebug?.verbose)
      console.log('[restore] _showWelcome() called from:', new Error().stack?.split('\n')[2]?.trim())
    libraryPanel?.refresh()
    _welcomeScreen?.classList.remove('hidden')
    _setMenusEnabled(false)
    _setLeftPanelEnabled(false)
    _setRightPanelEnabled(false)
    _setFilterStripEnabled(false)
    api.clearPersistedDesign()
    const spreadsheetPanel = document.getElementById('spreadsheet-panel')
    if (spreadsheetPanel) spreadsheetPanel.style.display = 'none'
    const vcWrap = document.getElementById('vc-wrap')
    if (vcWrap) vcWrap.style.display = 'none'
  }

  function _hideWelcome() {
    _welcomeScreen?.classList.add('hidden')
    _setMenusEnabled(true)
    _setLeftPanelEnabled(true)
    _setRightPanelEnabled(true)
    _setFilterStripEnabled(true)
    const spreadsheetPanel = document.getElementById('spreadsheet-panel')
    if (spreadsheetPanel) spreadsheetPanel.style.display = ''
    const vcWrap = document.getElementById('vc-wrap')
    if (vcWrap) vcWrap.style.display = ''
  }

  // ── Recent files ─────────────────────────────────────────────────────────────
  function _renderRecentMenu() {
    const submenu = document.getElementById('recent-files-submenu')
    if (!submenu) return
    const recent = api.getRecentFiles()
    submenu.innerHTML = ''
    if (!recent.length) {
      const el = document.createElement('button')
      el.className = 'dropdown-item'
      el.textContent = 'No recent files'
      el.disabled = true
      el.style.color = '#484f58'
      el.style.cursor = 'default'
      submenu.appendChild(el)
      return
    }
    for (const entry of recent) {
      const el = document.createElement('button')
      el.className = 'dropdown-item'
      el.style.display = 'flex'
      el.style.justifyContent = 'space-between'
      el.style.gap = '12px'
      const nameSpan = document.createElement('span')
      nameSpan.textContent = entry.name
      const typeSpan = document.createElement('span')
      typeSpan.textContent = entry.type ?? 'nadoc'
      typeSpan.style.color = '#484f58'
      typeSpan.style.fontSize = '10px'
      typeSpan.style.alignSelf = 'center'
      el.appendChild(nameSpan)
      el.appendChild(typeSpan)
      el.addEventListener('click', async () => {
        _setFileName(entry.name)
        _resetForNewDesign()
        const type = entry.type ?? 'nadoc'
        let result
        if (type === 'cadnano') {
          result = await api.importCadnanoDesign(entry.content)
        } else if (type === 'scadnano') {
          result = await api.importScadnanoDesign(entry.content)
        } else {
          result = await api.importDesign(entry.content)
        }
        if (!result) {
          alert('Failed to reload recent file: ' + (store.getState().lastError?.message ?? 'Unknown error'))
          _setFileName(null)
          _showWelcome()
          return
        }
        _hideWelcome()
        _fileHandle = null
        workspace.hide()
        api.addRecentFile(entry.name, entry.content, type)
        _renderRecentMenu()
        // Register in workspace so auto-save has a target
        const design = store.getState().currentDesign
        const wsName = (design?.metadata?.name ?? entry.name.replace(/\.[^.]+$/, '')).replace(/[^a-zA-Z0-9-_ ]/g, '_')
        const wsResult = await api.uploadLibraryFile(JSON.stringify(design), `${wsName}.nadoc`)
        if (wsResult?.path) { _setWorkspacePath(wsResult.path); libraryPanel?.refresh() }
      })
      submenu.appendChild(el)
    }
  }
  _renderRecentMenu()

  // ── Close Session ─────────────────────────────────────────────────────────────
  async function _closeSession() {
    // Tell every other NADOC tab (cadnano editors AND any other 3D windows)
    // to self-close. window.close() succeeds for tabs that were opened via
    // window.open() — tabs the user opened by typing a URL or duplicating
    // the tab will stay open per browser security rules. The originating
    // tab (this one) is excluded automatically by nadocBroadcast's source
    // filter, so it stays open and falls through to the welcome screen.
    try { nadocBroadcast.emit('session-closed') } catch { /* best-effort */ }

    const { currentDesign, assemblyActive } = store.getState()

    if (assemblyActive) {
      // Auto-save to workspace before clearing
      const hasInstances = (store.getState().currentAssembly?.instances?.length ?? 0) > 0
      if (hasInstances) {
        try { await (_assemblyWorkspacePath ? api.saveAssemblyAs(_assemblyWorkspacePath) : api.saveAssemblyToWorkspace()) } catch { /* best-effort */ }
      }
      _exitAssemblyMode()
      store.setState({ currentAssembly: null, activeInstanceId: null })
      // Reset design scene, camera, tools and any design state that may have been
      // loaded before the assembly session began.
      _resetForNewDesign()
      _fileHandle = null
      _setFileName(null)
      await api.closeSession()   // cleans up any backend design state; no-op if none loaded
      _showWelcome()
      document.title = 'NADOC 3D'
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      return
    }

    // Part-edit tab: clear context and URL param before the standard design close.
    if (_partEditContext) {
      _partEditContext = null
      api.setPersistedMode(null)
      history.replaceState({}, '', '/')
    }

    if (!currentDesign) {
      _showWelcome()
      document.title = 'NADOC 3D'
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      return
    }
    _resetForNewDesign()
    _fileHandle = null
    _setFileName(null)
    await api.closeSession()
    _showWelcome()
    document.title = 'NADOC 3D'
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  }

  document.getElementById('menu-file-close-session')?.addEventListener('click', _closeSession)

  // Gate menus and sidebar until a design is loaded (welcome screen is already
  // visible from HTML).  The restore block below may immediately un-gate them.
  _setMenusEnabled(false)
  _setLeftPanelEnabled(false)
  _setRightPanelEnabled(false)
  _setFilterStripEnabled(false)

  // ── File / assembly / part-edit state ─────────────────────────────────────────
  // Declared here (before the session-restore await blocks) to avoid TDZ errors
  // in the assembly restore and part-edit init blocks that run during startup.
  let _fileHandle         = null
  let _fileName           = null  // display name from filesystem (no extension)
  let _assemblyFileHandle = null
  let _assemblyName       = null
  let _partEditContext    = null  // { instanceId, name } when editing a part
  const _FNAME_KEY = 'nadoc:design-filename'
  function _setFileName(name) {
    _fileName = name
    if (name) localStorage.setItem(_FNAME_KEY, name)
    else      localStorage.removeItem(_FNAME_KEY)
  }

  // Workspace paths — set when a file is opened from or saved to the workspace.
  // Auto-save subscribers use these to know which file to overwrite.
  const _WS_PATH_KEY  = 'nadoc:workspace-path'
  const _ASM_PATH_KEY = 'nadoc:assembly-workspace-path'
  let _workspacePath         = localStorage.getItem(_WS_PATH_KEY)  || null
  let _assemblyWorkspacePath = localStorage.getItem(_ASM_PATH_KEY) || null
  function _setWorkspacePath(path) {
    _workspacePath = path
    if (path) localStorage.setItem(_WS_PATH_KEY, path)
    else      localStorage.removeItem(_WS_PATH_KEY)
  }
  function _setAssemblyWorkspacePath(path) {
    _assemblyWorkspacePath = path
    if (path) localStorage.setItem(_ASM_PATH_KEY, path)
    else      localStorage.removeItem(_ASM_PATH_KEY)
  }

  // ── Session persistence — always show welcome screen on page load ────────────
  // Auto-restore was removed: every reload/refresh starts from the welcome screen.
  // Clear all persisted session state so stale data never leaks into a new session.
  api.clearPersistedDesign()
  api.clearPersistedAssembly()
  api.setPersistedMode(null)
  localStorage.removeItem(_WS_PATH_KEY)
  localStorage.removeItem(_ASM_PATH_KEY)
  localStorage.removeItem(_FNAME_KEY)
  _workspacePath         = null
  _assemblyWorkspacePath = null
  _fileName              = null
  let _needsWelcomeOnBoot = true

  // ── File-load overlay DOM refs + event wiring (used by part-edit init below) ─
  const _flProgress   = document.getElementById('file-load-progress')
  const _flFillEl     = document.getElementById('flp-fill')
  const _flStatusEl   = document.getElementById('flp-status')
  const _flHeaderEl   = document.getElementById('flp-header')
  const _flLogEl      = document.getElementById('flp-log')
  const _flLogWrapEl  = document.getElementById('flp-log-wrap')
  const _flToggleBtn  = document.getElementById('flp-details-toggle')
  const _flActionsEl  = document.getElementById('flp-actions')
  const _flMenuBtn    = document.getElementById('flp-main-menu-btn')

  let _flLogOpen = false

  _flToggleBtn?.addEventListener('click', () => {
    _flLogOpen = !_flLogOpen
    _flLogWrapEl.style.display  = _flLogOpen ? 'block' : 'none'
    _flToggleBtn.textContent    = (_flLogOpen ? '▾' : '▸') + ' Details'
  })

  _flMenuBtn?.addEventListener('click', () => {
    _hideFileLoad()
    _showWelcome()
  })

  // ── Part-edit init — ?part-instance=<id> opens this tab as a part editor ────
  {
    const _partInstanceParam = new URLSearchParams(window.location.search).get('part-instance')
    if (_partInstanceParam) {
      _showFileLoad('Opening Part')
      let partDesign = null

      // Normal path: assembly is live on server
      try {
        _flSetProgress(0, 'Fetching part from assembly…')
        _flAppendLog(`Instance: ${_partInstanceParam}`)
        const resp = await fetch(`/api/assembly/instances/${_partInstanceParam}/design`)
        if (resp.ok) {
          const body = await resp.json()
          partDesign = body.design
          _flAppendLog('Part design received from server')
        } else {
          _flAppendLog(`Server returned ${resp.status} — trying local cache…`, 'warn')
        }
      } catch (e) {
        _flAppendLog(`Network error: ${e?.message ?? String(e)} — trying local cache…`, 'warn')
      }

      // Server-restart fallback: restore assembly from localStorage, then retry
      if (!partDesign) {
        const cached = api.getPersistedAssembly()
        if (cached) {
          try {
            _flAppendLog('Restoring assembly from local cache…')
            const restoreResult = await api.importAssembly(JSON.stringify(cached))
            if (restoreResult) {
              const resp2 = await fetch(`/api/assembly/instances/${_partInstanceParam}/design`)
              if (resp2.ok) {
                const body2 = await resp2.json()
                partDesign = body2.design
                _flAppendLog('Part design received after cache restore')
              }
            }
          } catch { _flAppendLog('Cache restore failed.', 'error') }
        }
      }

      if (partDesign) {
        _flSetProgress(50, 'Importing design…')
        _flAppendLog('Parsing and validating design…')
        await api.importDesign(JSON.stringify(partDesign))
        const partName = partDesign?.metadata?.name ?? 'Part'
        _partEditContext = { instanceId: _partInstanceParam, name: partName }
        // Populate currentAssembly in store so beforeunload can persist it
        await api.getAssembly()
        api.setPersistedMode('part-edit:' + _partInstanceParam)
        _setFileName(partName)
        _needsWelcomeOnBoot = false
        _hideWelcome()
        workspace.hide()
        document.title = `NADOC 3D — ${partName} [part edit]`
        document.getElementById('mode-indicator').textContent = `PART EDIT — ${partName}`
        _flAppendLog(`Part "${partName}" loaded successfully.`, 'success')
        _fitToView()
        await _flShowSuccess(`"${partName}" loaded`)
      } else {
        _flAppendLog('Could not load part: assembly session expired and no local cache available.', 'error')
        _flShowError('Could not load part.')
      }
    }
  }

  // Save state to localStorage on page close as a safety net.
  window.addEventListener('beforeunload', () => {
    api.persistDesign()
    api.persistAssembly()   // no-op if no assembly is loaded
  })

  // ── File open / save ─────────────────────────────────────────────────────────
  // Tracks the File System Access API file handle so Ctrl+S can overwrite
  // the same file without re-opening a dialog.  Null when no file is open or
  // when the browser doesn't support the File System Access API.
  // (_fileHandle, _fileName, _assemblyFileHandle, _assemblyName, _partEditContext,
  //  _FNAME_KEY, and _setFileName are declared above the session-restore block.)
  let _lastDetailLevel  = 0      // LOD level last applied to designRenderer (0=full, 1=beads, 2=cylinders)
  let _lodMode          = 'full' // 'full' | 'beads' | 'cylinders'

  /** Clear per-file state (slice plane, store) and return to workspace. */
  function _resetForNewDesign() {
    _lastDetailLevel = -1     // force LOD re-evaluation on first tick after new design
    _clearScaffoldChecks()
    _clearStapleChecks()
    // Hard-exit cadnano mode if active or mid-transition — synchronously restores
    // ortho camera/controls and axis arrows before the design state is cleared.
    cadnanoView.forceExit()
    deformExitTool()
    jointRenderer?.exitDefineMode()
    if (_translateRotateActive) {
      _translateRotateActive = false
      clusterGizmo?.detach()
      _removeToolPickListeners?.()
    }
    // Deformed view stays ON after reset (it is always on by default).
    // If currently in straight view, reactivate before clearing state.
    if (!deformView.isActive()) deformView.activate()
    slicePlane.hide()
    crossSectionMinimap.clearSlice()
    crossSectionMinimap.hide()
    _clearSliceHighlights()
    bluntEnds.clear()
    _hideBluntPanel()
    _setMenuToggle('menu-view-slice', false)
    _setMenuToggle('menu-view-loop-skip', false)
    _loopSkipLegend.style.display = 'none'
    mdSegmentation.hide()
    _setMenuToggle('menu-view-md-segmentation', false)
    _mdSegLegend.style.display = 'none'
    if (periodicMdOverlay.isApplied()) _setCGVisible(true)
    periodicMdOverlay.clear()
    // Reset representation to Full — deactivates atomistic/surface renderers,
    // resets the representation radio, and hides mode-specific option rows.
    _setRepresentation('full')
    // Reset camera to the same position as initial page load
    camera.position.set(6, 3, 18)
    controls.target.set(6, 3, 0)
    camera.up.set(0, 1, 0)
    controls.update()
    store.setState({
      currentDesign: null, currentGeometry: null, currentHelixAxes: null,
      validationReport: null, currentPlane: null, strandColors: {},
      unfoldHelixOrder: null, unfoldActive: false, cadnanoActive: false,
      straightGeometry: null, straightHelixAxes: null,
      selectedObject: null,
      multiSelectedStrandIds: [],
      multiSelectedDomainIds: [],
      isolatedStrandId: null,
      strandGroups: [],
      strandGroupsHistory: [],
      loopStrandIds: [],
      isCadnanoImport: false,
      lastError: null,
      activeClusterId: null,
      translateRotateActive: false,
    })
    _setWorkspacePath(null)
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
      return { content: await file.text(), handle, name: handle.name.replace(/\.nadoc$/i, '') }
    }
    // Fallback: hidden file input
    return new Promise(resolve => {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = '.nadoc,application/json'
      input.onchange = async () => {
        const file = input.files[0]
        if (!file) { resolve(null); return }
        resolve({ content: await file.text(), handle: null, name: file.name.replace(/\.nadoc$/i, '') })
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

  /** Save this tab's design back to the assembly instance, then notify the assembly tab. */
  async function _savePartToAssembly({ silent = false } = {}) {
    if (!_partEditContext) return null
    const content = await _getDesignContent()
    if (!content) {
      if (!silent) alert('Failed to read design.')
      return null
    }
    const result = await api.patchInstanceDesign(_partEditContext.instanceId, content)
    if (result) {
      _syncLog('info', 'BC-TX', `part-design-updated id=${_partEditContext.instanceId}`)
      _setSyncStatus('green', silent ? 'auto-saved to assembly' : 'saved to assembly')
      nadocBroadcast.emit('part-design-updated', { instanceId: _partEditContext.instanceId })
      if (!silent) {
        const modeEl = document.getElementById('mode-indicator')
        modeEl.textContent = `PART EDIT — ${_partEditContext.name} ✓ saved`
        setTimeout(() => { modeEl.textContent = `PART EDIT — ${_partEditContext.name}` }, 2000)
      }
    } else {
      _setSyncStatus('red', 'save error')
      _syncLog('err', 'BC-TX', `patchInstanceDesign failed for id=${_partEditContext.instanceId}`)
      if (!silent) alert('Save to assembly failed — assembly session may have expired.')
    }
    return result
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

  /** Save As — server-side only.  Updates session identity to the chosen path. */
  async function _saveAs() {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design to save.'); return }
    const stem = _workspacePath
      ? _workspacePath.replace(/\.nadoc$/i, '').split('/').pop()
      : (currentDesign.metadata?.name ?? 'design')
    const result = await openFileBrowser({
      title: 'Save Part As',
      mode: 'save',
      fileType: 'part',
      suggestedName: stem,
      suggestedExt: '.nadoc',
      api,
    })
    if (!result) return
    _setSyncStatus('yellow', 'saving…')
    const r = await api.saveDesignAs(result.path, result.overwrite ?? false)
    if (r) {
      _fileHandle = null
      _setWorkspacePath(result.path)
      _setFileName(result.name)
      _setSyncStatus('green', 'saved')
      libraryPanel?.refresh()
    } else {
      _setSyncStatus('red', 'save error')
    }
  }

  // ── Assembly file save helpers ────────────────────────────────────────────────

  async function _saveAssemblyToHandle(handle) {
    const content = await api.getAssemblyContent()
    if (!content) { alert('Failed to read assembly from server.'); return false }
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

  async function _saveAssemblyAs() {
    const { currentAssembly } = store.getState()
    const stem = _assemblyWorkspacePath
      ? _assemblyWorkspacePath.replace(/\.nass$/i, '').split('/').pop()
      : (_assemblyName ?? currentAssembly?.metadata?.name ?? 'assembly')
    const result = await openFileBrowser({
      title: 'Save Assembly As',
      mode: 'save',
      fileType: 'assembly',
      suggestedName: stem,
      suggestedExt: '.nass',
      api,
    })
    if (!result) return
    const r = await api.saveAssemblyAs(result.path, result.overwrite ?? false)
    if (r) {
      _assemblyFileHandle = null
      _assemblyName = result.name
      _setAssemblyWorkspacePath(result.path)
      _updateAssemblyTitle()
      libraryPanel?.refresh()
    }
  }

  function _updateAssemblyTitle() {
    const name = _assemblyName ?? store.getState().currentAssembly?.metadata?.name ?? 'Untitled'
    document.title = `NADOC 3D — ${name}`
  }

  // IDs of right-panel sections that are design-only (hidden in assembly mode)
  const _DESIGN_PANEL_IDS = [
    'sel-row-bluntEnds', 'sel-row-crossoverLocations',
    'selection-filter-section', 'properties-section',
    'blunt-panel', 'deform-panel', 'strand-hist-section',
    'groups-panel', 'overhang-panel',
    'oxdna-section', 'md-panel',
    'repr-options-section', 'reset-btn',
  ]
  let _savedDesignPanelDisplay = {}

  function _enterAssemblyMode() {
    if (window.nadocDebug?.verbose)
      console.log('[restore] _enterAssemblyMode() — assemblyActive →', true)
    _setDesignGeometryVisible(false)
    store.setState({ assemblyActive: true })
    api.setPersistedMode('assembly')
    _updateAssemblyTitle()
    document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
    _hideWelcome()

    // Save current display state of design-only right panel sections, then hide them
    _savedDesignPanelDisplay = {}
    for (const id of _DESIGN_PANEL_IDS) {
      const el = document.getElementById(id)
      if (el) {
        _savedDesignPanelDisplay[id] = el.style.display
        el.style.display = 'none'
      }
    }

    // Reveal the assembly panel in place (it lives permanently in the Scene
    // tab — no DOM relocation needed).
    const asmEl = document.getElementById('assembly-panel')
    if (asmEl) asmEl.style.display = ''
  }

  function _exitAssemblyMode() {
    _setDesignGeometryVisible(true)
    _assemblyFileHandle = null
    _assemblyName       = null
    _setAssemblyWorkspacePath(null)
    api.setPersistedMode(null)
    api.clearPersistedAssembly()
    store.setState({ assemblyActive: false })
    document.title = `NADOC 3D — ${_fileName ?? store.getState().currentDesign?.metadata?.name ?? 'Untitled'}`
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'

    // Restore design-only right panel sections
    for (const id of _DESIGN_PANEL_IDS) {
      const el = document.getElementById(id)
      if (el && _savedDesignPanelDisplay[id] !== undefined)
        el.style.display = _savedDesignPanelDisplay[id]
    }

    // Hide the assembly panel; it stays in the Scene tab and reappears next
    // time an assembly file is opened.
    const asmEl = document.getElementById('assembly-panel')
    if (asmEl) asmEl.style.display = 'none'
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
    const { assemblyActive } = store.getState()
    const box = assemblyActive
      ? assemblyRenderer.getBoundingBox()
      : (() => {
          const root = designRenderer.getHelixCtrl()?.root
          return root ? new THREE.Box3().expandByObject(root) : new THREE.Box3()
        })()
    if (box.isEmpty()) return
    const center = box.getCenter(new THREE.Vector3())
    const size   = box.getSize(new THREE.Vector3())
    const radius = Math.max(size.x, size.y, size.z) * 0.5
    const dist = (radius / Math.sin((camera.fov * 0.5) * Math.PI / 180)) * 1.15
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
    // Clear name field and hide any previous error
    const nameInput = document.getElementById('new-design-name')
    const nameError = document.getElementById('new-design-name-error')
    if (nameInput) { nameInput.value = ''; nameInput.style.borderColor = '' }
    if (nameError) nameError.style.display = 'none'
    modal.style.display = 'flex'
    setTimeout(() => nameInput?.focus(), 50)
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
    const modal     = document.getElementById('new-design-modal')
    const nameInput = document.getElementById('new-design-name')
    const nameError = document.getElementById('new-design-name-error')
    const name      = nameInput?.value.trim() ?? ''
    if (!name) {
      if (nameInput) nameInput.style.borderColor = '#f85149'
      if (nameError) nameError.style.display = 'block'
      nameInput?.focus()
      return
    }
    const checked = modal.querySelector('input[name="new-lattice-type"]:checked')
    const lattice = checked?.value ?? 'HONEYCOMB'
    modal.style.display = 'none'
    _resetForNewDesign()
    _fileHandle = null
    _setFileName(name)
    _hideWelcome()
    workspace.show(lattice)
    await api.createDesign(name, lattice)
    // Save to workspace immediately so auto-save has a target path
    const safeStem = name.replace(/[^a-zA-Z0-9-_ ]/g, '_').trim() || 'untitled'
    const wsResult = await api.uploadLibraryFile(
      JSON.stringify(store.getState().currentDesign), `${safeStem}.nadoc`,
    )
    if (wsResult?.path) {
      _setWorkspacePath(wsResult.path)
      libraryPanel?.refresh()
    }
  })

  document.getElementById('menu-file-open')?.addEventListener('click', async () => {
    const result = await openFileBrowser({ title: 'Open Part from Server', mode: 'open', fileType: 'part', api })
    if (result) await _openPartFromServer(result.path, result.name)
  })

  document.getElementById('menu-file-save')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design to save.'); return }
    if (_workspacePath) {
      const path = _workspacePath
      _syncLog('info', 'SAVE', `explicit save → ${path}`)
      _setSyncStatus('yellow', 'saving…')
      _selfSavedPaths.add(path)
      await api.saveDesignToWorkspace(path)
      _setSyncStatus('green', 'saved')
      setTimeout(() => _selfSavedPaths.delete(path), 5000)
      if (_fileHandle) await _saveToHandle(_fileHandle)
    } else if (_fileHandle) {
      await _saveToHandle(_fileHandle)
    } else {
      await _saveAs()
    }
  })

  document.getElementById('menu-file-save-as')?.addEventListener('click', _saveAs)

  document.getElementById('menu-file-new-assembly')?.addEventListener('click', async () => {
    const name = window.prompt('Assembly name:', 'Untitled')
    if (name === null) return   // user cancelled
    const trimmed = name.trim() || 'Untitled'
    const result = await api.createAssembly(trimmed)
    if (result) {
      _assemblyName = result.assembly?.metadata?.name ?? trimmed
      _assemblyFileHandle = null
      const saveResult = await api.saveAssemblyToWorkspace(trimmed)
      if (saveResult?.path) _setAssemblyWorkspacePath(saveResult.path)
      libraryPanel?.refresh()
      _enterAssemblyMode()
    }
  })

  document.getElementById('menu-file-open-assembly')?.addEventListener('click', async () => {
    const result = await openFileBrowser({ title: 'Open Assembly from Server', mode: 'open', fileType: 'assembly', api })
    if (result) await _openAssemblyFromServer(result.path)
  })

  document.getElementById('menu-file-save-assembly')?.addEventListener('click', async () => {
    const { currentAssembly } = store.getState()
    if (!currentAssembly) { alert('No assembly to save.'); return }
    if (_assemblyWorkspacePath) {
      const r = await api.saveAssemblyAs(_assemblyWorkspacePath)
      if (r?.path) _setAssemblyWorkspacePath(r.path)
      if (_assemblyFileHandle) await _saveAssemblyToHandle(_assemblyFileHandle)
    } else if (_assemblyFileHandle) {
      await _saveAssemblyToHandle(_assemblyFileHandle)
    } else {
      await _saveAssemblyAs()
    }
  })

  document.getElementById('menu-file-save-assembly-as')?.addEventListener('click', async () => {
    const { currentAssembly } = store.getState()
    if (!currentAssembly) { alert('No assembly to save.'); return }
    await _saveAssemblyAs()
  })

  document.getElementById('menu-file-upload')?.addEventListener('click', () => {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.nadoc,.nass,application/json'; input.multiple = true
    input.onchange = async (e) => {
      const files = Array.from(e.target.files ?? [])
      if (!files.length) return
      for (const file of files) {
        const content = await file.text()
        const ext     = file.name.endsWith('.nass') ? '.nass' : '.nadoc'
        const stem    = file.name.replace(/\.(nadoc|nass)$/i, '')
        const dest    = await openFileBrowser({
          title: `Upload "${file.name}" to…`,
          mode: 'save',
          fileType: ext === '.nass' ? 'assembly' : 'part',
          suggestedName: stem,
          suggestedExt: ext,
          api,
        })
        if (!dest) continue
        await api.uploadLibraryFile(content, file.name, { destPath: dest.path, overwrite: dest.overwrite ?? false })
        libraryPanel?.refresh()
      }
    }
    input.click()
  })

  document.getElementById('menu-file-download')?.addEventListener('click', async () => {
    const result = await openFileBrowser({ title: 'Download from Server', mode: 'open', fileType: 'all', api })
    if (!result) return
    const data = await api.getLibraryFileContent(result.path)
    if (!data?.content) { alert('Could not retrieve file from server.'); return }
    const blob = new Blob([data.content], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = result.path.split('/').pop(); a.click()
    URL.revokeObjectURL(url)
  })

  document.getElementById('menu-assembly-add-part')?.addEventListener('click', () => {
    assemblyPanel.openPicker()
  })

  document.getElementById('menu-assembly-define-joint')?.addEventListener('click', () => {
    _defineAssemblyConnector()
  })

  document.getElementById('menu-assembly-define-mate')?.addEventListener('click', () => {
    _defineAssemblyMate()
  })

  document.getElementById('menu-edit-undo')?.addEventListener('click', async () => {
    if (isDeformActive()) return
    if (popGroupUndo()) return
    const result = await api.undo()
    if (!result) {
      const err = store.getState().lastError
      if (err?.status === 404) alert('Nothing to undo.')
    } else {
      // Cluster-only undos take a fast path that mirrors the Apply
      // optimization (Plan B). Backend signals it via diff_kind +
      // cluster_diffs; the renderer applies a delta in-place rather
      // than rebuilding the whole scene.
      if (result.diff_kind === 'cluster_only') {
        await _applyClusterUndoRedoDeltas(result.cluster_diffs)
      } else if (result.diff_kind === 'positions_only') {
        _applyPositionsOnlyDiff(result)
      }
      _clearScaffoldChecks()
      _clearStapleChecks()
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
      if (result.diff_kind === 'cluster_only') {
        await _applyClusterUndoRedoDeltas(result.cluster_diffs)
      } else if (result.diff_kind === 'positions_only') {
        _applyPositionsOnlyDiff(result)
      }
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

  // ── Routing feature-override warning ─────────────────────────────────────
  /**
   * If the current design has strand extensions, show a confirmation dialog
   * warning that the routing operation may remove them.
   * Returns Promise<boolean> — true if the user clicks Yes/proceeds.
   * Returns true immediately (no dialog) when no extensions are present.
   */
  function _confirmFeatureOverride() {
    const design = store.getState().currentDesign
    const extCount = design?.extensions?.length ?? 0
    if (extCount === 0) return Promise.resolve(true)

    const featureList = `${extCount} strand extension${extCount === 1 ? '' : 's'}`

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
        'border-radius:8px', 'padding:24px 28px', 'max-width:400px',
        'font-family:sans-serif', 'color:#cfd8dc',
        'box-shadow:0 8px 32px rgba(0,0,0,0.6)',
      ].join(';')

      const title = document.createElement('div')
      title.textContent = 'Existing annotations may be affected'
      title.style.cssText = 'font-size:15px;font-weight:600;color:#eceff1;margin-bottom:10px'

      const msg = document.createElement('div')
      msg.textContent = `This design has ${featureList}. Running this routing operation will replace all staple strands and their associated data. Do you want to proceed?`
      msg.style.cssText = 'font-size:13px;line-height:1.5;margin-bottom:20px'

      const btnRow = document.createElement('div')
      btnRow.style.cssText = 'display:flex;gap:10px;justify-content:flex-end'

      const btnNo = document.createElement('button')
      btnNo.textContent = 'No'
      btnNo.style.cssText = [
        'padding:7px 18px', 'border-radius:5px', 'border:1px solid #455a64',
        'background:#263238', 'color:#b0bec5', 'cursor:pointer', 'font-size:13px',
      ].join(';')

      const btnYes = document.createElement('button')
      btnYes.textContent = 'Yes, proceed'
      btnYes.style.cssText = [
        'padding:7px 18px', 'border-radius:5px', 'border:none',
        'background:#c0392b', 'color:#fff', 'cursor:pointer', 'font-size:13px',
        'font-weight:600',
      ].join(';')

      const cleanup = () => document.body.removeChild(overlay)
      btnNo.addEventListener('click',  () => { cleanup(); resolve(false) })
      btnYes.addEventListener('click', () => { cleanup(); resolve(true)  })
      overlay.addEventListener('click', e => { if (e.target === overlay) { cleanup(); resolve(false) } })

      btnRow.append(btnNo, btnYes)
      box.append(title, msg, btnRow)
      overlay.appendChild(box)
      document.body.appendChild(overlay)
      btnNo.focus()
    })
  }

  // ── Operation progress popup helpers ──────────────────────────────────────
  // Thin wrappers around the shared module so client.js and tool flows share
  // one ref-counted progress widget — concurrent showers don't fight, and a
  // long API call (auto-shown by _request) layered on top of a tool-driven
  // progress (showProgress here) hides correctly when both finish.
  const _showProgress = showOpProgress
  const _hideProgress = hideOpProgress

  // ── File-load overlay helpers ──────────────────────────────────────────────
  function _showFileLoad(header) {
    _flLogOpen = false
    if (_flLogEl)     _flLogEl.innerHTML             = ''
    if (_flLogWrapEl) _flLogWrapEl.style.display     = 'none'
    if (_flToggleBtn) _flToggleBtn.textContent       = '▸ Details'
    if (_flActionsEl) _flActionsEl.style.display     = 'none'
    if (_flHeaderEl)  _flHeaderEl.textContent        = header
    if (_flFillEl)    { _flFillEl.style.background   = '#3ddc84'; _flFillEl.style.width = '0%' }
    if (_flStatusEl)  { _flStatusEl.textContent      = ''; _flStatusEl.style.color = '#c9d1d9' }
    _flProgress?.classList.add('visible')
  }

  function _hideFileLoad() {
    _flProgress?.classList.remove('visible')
  }

  function _flSetProgress(pct, msg) {
    if (_flFillEl)   _flFillEl.style.width    = pct + '%'
    if (_flStatusEl) _flStatusEl.textContent  = msg ?? ''
  }

  function _flAppendLog(msg, type = 'info') {
    if (!_flLogEl) return
    const colors = { info: '#8b949e', warn: '#d29922', error: '#f85149', success: '#3fb950' }
    const line = document.createElement('div')
    line.style.color  = colors[type] ?? colors.info
    line.textContent  = msg
    _flLogEl.appendChild(line)
    _flLogEl.scrollTop = _flLogEl.scrollHeight
  }

  function _flExpandDetails() {
    _flLogOpen = true
    if (_flLogWrapEl) _flLogWrapEl.style.display = 'block'
    if (_flToggleBtn) _flToggleBtn.textContent   = '▾ Details'
  }

  async function _flShowSuccess(msg) {
    if (_flFillEl)   { _flFillEl.style.width = '100%'; _flFillEl.style.background = '#3fb950' }
    if (_flStatusEl) { _flStatusEl.textContent = msg; _flStatusEl.style.color = '#3fb950' }
    await new Promise(r => setTimeout(r, 1500))
    _hideFileLoad()
  }

  function _flShowError(msg) {
    if (_flFillEl)   { _flFillEl.style.width = '100%'; _flFillEl.style.background = '#f85149' }
    if (_flStatusEl) { _flStatusEl.textContent = msg; _flStatusEl.style.color = '#f85149' }
    _flExpandDetails()
    if (_flActionsEl) _flActionsEl.style.display = 'flex'
  }

  // ── CG Relax (mrdna) ──────────────────────────────────────────────────────
  ;(() => {
    const _heading     = document.getElementById('cgrelax-heading')
    const _body        = document.getElementById('cgrelax-body')
    const _arrow       = document.getElementById('cgrelax-arrow')
    const _btnRun      = document.getElementById('btn-cgrelax-run')
    const _statusText  = document.getElementById('cgrelax-status-text')
    const _progressWrap= document.getElementById('cgrelax-progress-wrap')
    const _progressFill= document.getElementById('cgrelax-progress-fill')
    const _stageLabel  = document.getElementById('cgrelax-stage-label')
    const _resultsDiv  = document.getElementById('cgrelax-results')
    const _chkShape    = document.getElementById('cgrelax-show-shape')
    const _statsDiv    = document.getElementById('cgrelax-stats')

    _heading?.addEventListener('click', () => {
      const open = _body.style.display !== 'none'
      _body.style.display = open ? 'none' : 'block'
      _arrow.textContent  = open ? '▶' : '▼'
    })

    function _setStatus(text, color) {
      if (_statusText) { _statusText.textContent = text; _statusText.style.color = color }
    }
    function _showProgress(pct, stage) {
      if (_progressWrap) _progressWrap.style.display = 'block'
      if (_progressFill) _progressFill.style.width = `${Math.max(0, Math.min(100, pct))}%`
      if (_stageLabel)   _stageLabel.textContent = stage.replace(/_/g, ' ')
    }
    function _hideProgress() {
      if (_progressWrap) _progressWrap.style.display = 'none'
    }

    const cgRelaxClient = initMrdnaRelaxClient({
      onProgress(stage, pct) {
        _setStatus('Running…', '#388bfd')
        _showProgress(pct, stage)
      },
      onResult(msg) {
        store.setState({ cgRelaxPositions: msg.positions, cgRelaxStats: msg.stats })
        _hideProgress()
        _setStatus('Done', '#3fb950')
        if (_resultsDiv) _resultsDiv.style.display = 'block'
        if (_statsDiv) {
          const s = msg.stats
          _statsDiv.innerHTML =
            `Nucleotides: ${s.n_nucleotides}<br>` +
            `Sim time: ${s.sim_seconds}s`
        }
        if (_chkShape?.checked) _applyShape(msg.positions)
      },
      onError(message) {
        store.setState({ cgRelaxPositions: null })
        _hideProgress()
        _setStatus('Error', '#f85149')
        alert('CG Relax failed: ' + message)
      },
    })

    function _applyShape(positions) {
      if (!positions) { designRenderer.clearFemOverlay(); return }
      designRenderer.applyFemPositions(positions)
    }

    _btnRun?.addEventListener('click', () => {
      if (!store.getState().currentDesign?.helices?.length) {
        alert('No design loaded.'); return
      }
      store.setState({ cgRelaxPositions: null })
      if (_chkShape) _chkShape.checked = false
      if (_resultsDiv) _resultsDiv.style.display = 'none'
      _setStatus('Running…', '#388bfd')
      _showProgress(0, 'building_model')
      designRenderer.clearFemOverlay()
      cgRelaxClient.run()
    })

    _chkShape?.addEventListener('change', () => {
      const { cgRelaxPositions } = store.getState()
      if (_chkShape.checked && cgRelaxPositions) {
        _applyShape(cgRelaxPositions)
      } else {
        designRenderer.clearFemOverlay()
      }
    })

    store.subscribe((newState, prevState) => {
      if (newState.currentDesign === prevState.currentDesign) return
      cgRelaxClient.cancel()
      store.setState({ cgRelaxPositions: null, cgRelaxStats: null })
      if (_chkShape) _chkShape.checked = false
      if (_resultsDiv) _resultsDiv.style.display = 'none'
      if (_progressWrap) _progressWrap.style.display = 'none'
      _setStatus('Idle', '#8b949e')
    })
  })()

  // ── Routing: Autoscaffold (seamed / seamless picker) ──────────────────────
  ;(() => {
    const modal   = document.getElementById('autoscaffold-modal')
    const btnRun  = document.getElementById('as-run')
    const btnCancel = document.getElementById('as-cancel')

    async function _runAutoscaffold() {
      const { currentDesign } = store.getState()
      if (!currentDesign) { alert('No design loaded.'); return }
      const mode = modal.querySelector('input[name="as-mode"]:checked')?.value || 'seamed'
      modal.classList.remove('visible')
      if (mode === 'seamless') {
        _showProgress('Seamless Scaffold', 'Routing seamless scaffold strand…')
        const ok = await api.autoScaffoldSeamless()
        _hideProgress()
        if (!ok) {
          alert('Seamless scaffold failed: ' + (store.getState().lastError?.message ?? 'unknown'))
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      } else if (mode === 'advanced-seamed') {
        _showProgress('Advanced Seam Routing', 'Routing scaffold with experimental seam planner…')
        const ok = await api.autoScaffoldAdvancedSeamed()
        _hideProgress()
        if (!ok) {
          alert('Advanced seam routing failed: ' + (store.getState().lastError?.message ?? 'unknown'))
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      } else if (mode === 'advanced-seamless') {
        _showProgress('Advanced Seamless Routing', 'Routing scaffold with experimental seamless planner…')
        const ok = await api.autoScaffoldAdvancedSeamless()
        _hideProgress()
        if (!ok) {
          alert('Advanced seamless routing failed: ' + (store.getState().lastError?.message ?? 'unknown'))
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      } else {
        _showProgress('Autoscaffold (Seamed)', 'Routing scaffold strand with seam crossovers…')
        const ok = await api.autoScaffoldSeamed()
        _hideProgress()
        if (!ok) {
          alert('Seamed autoscaffold failed: ' + (store.getState().lastError?.message ?? 'unknown'))
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      }
    }

    document.getElementById('menu-routing-scaffold-ends')?.addEventListener('click', () => {
      if (!store.getState().currentDesign) { alert('No design loaded.'); return }
      modal.classList.add('visible')
    })
    btnRun?.addEventListener('click', _runAutoscaffold)
    btnCancel?.addEventListener('click', () => modal.classList.remove('visible'))
    modal?.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('visible') })
  })()

  document.getElementById('menu-routing-auto-crossover')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign?.helices?.length) { alert('No design loaded.'); return }
    const result = await api.addAutoCrossover()
    if (!result) {
      alert('Auto Crossover failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
    } else {
      showToast('Auto crossovers placed.')
    }
  })

  ;(() => {
    const modal = document.getElementById('autobreak-modal')
    const runBtn = document.getElementById('ab-run-3d')
    const cancelBtn = document.getElementById('ab-cancel-3d')

    document.getElementById('menu-routing-autobreak')?.addEventListener('click', () => {
      if (!store.getState().currentDesign?.helices?.length) { alert('No design loaded.'); return }
      if (modal) modal.style.display = 'flex'
    })

    let _animTimer = null
    function _startIndeterminate() {
      const fill = document.getElementById('op-progress-fill')
      if (!fill) return
      let pct = 0
      _animTimer = setInterval(() => {
        pct = (pct + 7) % 90
        fill.style.width = pct + '%'
      }, 400)
    }
    function _stopIndeterminate() {
      if (_animTimer) { clearInterval(_animTimer); _animTimer = null }
      const fill = document.getElementById('op-progress-fill')
      if (fill) fill.style.width = '100%'
    }

    async function _runAutoBreak3d() {
      if (modal) modal.style.display = 'none'
      const algo = document.querySelector('#autobreak-modal input[name="ab-algo"]:checked')?.value || 'basic'
      // Show operation progress overlay. For advanced algorithm show indeterminate animation.
      _showProgress('Autobreak', algo === 'advanced' ? 'Running advanced optimizer…' : 'Running nick planner…')
      if (algo === 'advanced') _startIndeterminate()
      const result = await api.addAutoBreak({ algorithm: algo })
      if (algo === 'advanced') _stopIndeterminate()
      _hideProgress()
      if (!result) {
        alert('Autobreak failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
      } else {
        showToast('Autobreak complete.')
      }
    }

    runBtn?.addEventListener('click', _runAutoBreak3d)
    cancelBtn?.addEventListener('click', () => { if (modal) modal.style.display = 'none' })
    modal?.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none' })
  })()

  // ── Sequencing ────────────────────────────────────────────────────────────

  // Scaffold lengths for each option (must match SCAFFOLD_LIBRARY in sequences.py)
  const _SCAFFOLD_LENGTHS = { M13mp18: 7249, p7560: 7560, p8064: 8064 }

  function _openScaffoldModal() {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }

    // Build (helixId + ':' + bpIndex) → delta map from helix loop_skips
    const lsMap = new Map()
    for (const helix of currentDesign.helices ?? []) {
      for (const ls of helix.loop_skips ?? []) {
        lsMap.set(`${helix.id}:${ls.bp_index}`, ls.delta)
      }
    }

    // Count scaffold nucleotides, honouring skips (delta=-1 → 0 nt) and
    // loops (delta=+1 → 2 nt), matching the backend _strand_nt_with_skips logic.
    const scaffold = currentDesign.strands?.find(s => s.strand_type === 'scaffold')
    let totalNt = 0
    if (scaffold) {
      for (const d of scaffold.domains) {
        const isForward = d.direction === 'FORWARD'
        const step = isForward ? 1 : -1
        for (let bp = d.start_bp; isForward ? bp <= d.end_bp : bp >= d.end_bp; bp += step) {
          const delta = lsMap.get(`${d.helix_id}:${bp}`) ?? 0
          if (delta <= -1) continue
          totalNt += delta + 1
        }
      }
    }

    const modal        = document.getElementById('assign-scaffold-modal')
    const lengthEl     = document.getElementById('asc-length-line')
    const warnEl       = document.getElementById('asc-warning')
    const customSeqEl  = document.getElementById('asc-custom-seq')
    const charCountEl  = document.getElementById('asc-custom-char-count')
    const customErrEl  = document.getElementById('asc-custom-error')

    // Clear custom textarea and reset error state on (re)open
    if (customSeqEl) { customSeqEl.value = ''; }
    if (charCountEl) charCountEl.textContent = '0 nt'
    if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }

    lengthEl.textContent = `Scaffold length: ${totalNt} nt`
    modal.style.display = 'flex'

    function _updateWarning() {
      const customRaw = customSeqEl?.value?.replace(/\s/g, '').toUpperCase() ?? ''
      if (customRaw) {
        // Custom sequence path — warn if shorter than scaffold
        if (customRaw.length < totalNt) {
          warnEl.textContent = `⚠ Custom sequence (${customRaw.length} nt) is shorter than scaffold (${totalNt} nt). `
            + `${totalNt - customRaw.length} bases will be assigned 'N'.`
          warnEl.style.display = 'block'
        } else {
          warnEl.style.display = 'none'
        }
        return
      }
      const sel = modal.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
      const seqLen = _SCAFFOLD_LENGTHS[sel] ?? 0
      if (totalNt > seqLen) {
        warnEl.textContent = `⚠ Scaffold (${totalNt} nt) exceeds ${sel} (${seqLen} nt). `
          + `${totalNt - seqLen} bases will be assigned 'N'.`
        warnEl.style.display = 'block'
      } else {
        warnEl.style.display = 'none'
      }
    }
    _updateWarning()
    modal.querySelectorAll('input[name="asc-scaffold"]').forEach(r => r.addEventListener('change', _updateWarning))

    // Custom sequence validation + char count
    if (customSeqEl) {
      customSeqEl.addEventListener('input', () => {
        const raw = customSeqEl.value.replace(/\s/g, '').toUpperCase()
        if (charCountEl) charCountEl.textContent = `${raw.length} nt`
        const bad = [...new Set(raw.replace(/[ATGCN]/g, ''))]
        if (bad.length > 0) {
          if (customErrEl) { customErrEl.textContent = `Invalid: ${bad.join(', ')}`; customErrEl.style.display = 'inline' }
        } else {
          if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }
        }
        _updateWarning()
      })
    }
  }

  document.getElementById('menu-seq-assign-scaffold')?.addEventListener('click', _openScaffoldModal)

  document.getElementById('asc-cancel')?.addEventListener('click', () => {
    document.getElementById('assign-scaffold-modal').style.display = 'none'
  })

  document.getElementById('assign-scaffold-modal')?.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.getElementById('assign-scaffold-modal').style.display = 'none'
    if (e.key === 'Enter')  document.getElementById('asc-apply')?.click()
  })

  document.getElementById('asc-apply')?.addEventListener('click', async () => {
    const modal        = document.getElementById('assign-scaffold-modal')
    const scaffoldName = modal.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
    const customRaw    = (document.getElementById('asc-custom-seq')?.value ?? '').replace(/\s/g, '').toUpperCase()
    const customErrEl  = document.getElementById('asc-custom-error')
    const targetStrandId = modal.dataset.targetStrandId || null

    // Block if custom sequence has invalid characters
    if (customRaw && customErrEl?.textContent) return

    modal.style.display = 'none'
    delete modal.dataset.targetStrandId  // clear targeting after use

    const label = customRaw ? `custom (${customRaw.length} nt)` : scaffoldName
    _showProgress('Assign Scaffold Sequence', `Assigning ${label} sequence…`)
    const json = await api.assignScaffoldSequence(scaffoldName, {
      customSequence: customRaw || null,
      strandId: targetStrandId,
    })
    _hideProgress()
    if (!json) {
      alert('Assign scaffold sequence failed: ' + (store.getState().lastError?.message ?? 'unknown'))
      return
    }
    await api.syncScaffoldSequenceResponse(json)
    if (_undefinedHighlightOn) _refreshUndefinedHighlight()
    const padMsg = json.padded_nt > 0 ? ` (${json.padded_nt} nt padded with N)` : ''
    showToast(`${label} sequence assigned.${padMsg}`)
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

  document.getElementById('menu-seq-generate-overhangs')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }
    const ovhgCount = currentDesign.overhangs?.length ?? 0
    if (ovhgCount === 0) { alert('No overhangs found.'); return }
    showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
    _showProgress(`Generating sequences for ${ovhgCount} overhang${ovhgCount !== 1 ? 's' : ''}…`)
    const result = await api.generateAllOverhangSequences()
    _hideProgress()
    if (!result?.ok) {
      alert('Generate overhangs failed: ' + (store.getState().lastError?.message ?? 'unknown'))
    } else {
      showToast(`Sequences generated for ${result.count} overhang${result.count !== 1 ? 's' : ''}.`)
    }
  })

  document.getElementById('menu-seq-update-routing')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    const isSQ = currentDesign?.lattice_type === 'SQUARE'
    if (!currentDesign?.deformations?.length && !isSQ) { alert('No deformation ops on the current design.'); return }
    const hasCrossovers = currentDesign?.strands?.some(s =>
      s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
    )
    if (!hasCrossovers) { alert('Place crossovers first (Auto Crossover) before adding loops/skips.'); return }
    _showProgress('Add Loops/Skips', 'Applying loop/skip modifications…')
    const result = await api.applyAllDeformations()
    _hideProgress()
    if (!result) {
      alert('Add Loops/Skips failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
    } else {
      showToast('Loops/skips added.')
    }
  })

  document.getElementById('menu-seq-clear-all-loop-skips')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign) { alert('No design loaded.'); return }
    if (!confirm('Remove all loop/skip marks from the design?')) return
    const result = await api.clearAllLoopSkips()
    if (!result) alert('Clear failed: ' + (store.getState().lastError?.message ?? 'unknown error'))
    else showToast('All loop/skips cleared.')
  })

  // Enable/disable "Add Loops/Skips" based on whether crossovers exist.
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

  /** Returns false and shows a toast if the user must pick a cluster first. */
  function _clusterDeformGuard() {
    const { currentDesign, activeClusterId } = store.getState()
    const clusterCount = currentDesign?.cluster_transforms?.length ?? 0
    if (clusterCount > 1 && !activeClusterId) {
      showToast('Select a cluster in the Cluster panel before bending or twisting.')
      return false
    }
    return true
  }

  document.getElementById('menu-tools-twist')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    if (!deformView.isActive() && currentDesign.deformations?.length) {
      alert('Switch back to deformed view (View → Deformed View) before adding further deformations.')
      return
    }
    if (!_clusterDeformGuard()) return
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
    if (!_clusterDeformGuard()) return
    startTool('bend')
    document.getElementById('mode-indicator').textContent =
      'BEND — click plane A (fixed), then plane B · Esc to exit'
  })

  initOverhangsManagerPopup({ store })
  document.getElementById('menu-tools-overhangs-manager')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { alert('No design loaded.'); return }
    openOverhangsManager()   // popup pulls preselect from store on its own
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

  // ── Coloring submenu (Strand / Base / Cluster / CPK) ────────────────────────
  function _setColoringMode(mode) {
    store.setState({ coloringMode: mode })
    document.getElementById('menu-view-coloring-strand') ?.classList.toggle('is-checked', mode === 'strand')
    document.getElementById('menu-view-coloring-base')   ?.classList.toggle('is-checked', mode === 'base')
    document.getElementById('menu-view-coloring-cluster')?.classList.toggle('is-checked', mode === 'cluster')
    document.getElementById('menu-view-coloring-cpk')    ?.classList.toggle('is-checked', mode === 'cpk')
    // Side-panel atom-color buttons mirror the (atomistic-relevant) modes.
    const cpkBtn    = document.getElementById('atom-color-cpk')
    const strandBtn = document.getElementById('atom-color-strand')
    cpkBtn   ?.classList.toggle('active', mode === 'cpk')
    strandBtn?.classList.toggle('active', mode === 'strand')
  }
  document.getElementById('menu-view-coloring-strand') ?.addEventListener('click', () => _setColoringMode('strand'))
  document.getElementById('menu-view-coloring-base')   ?.addEventListener('click', () => _setColoringMode('base'))
  document.getElementById('menu-view-coloring-cluster')?.addEventListener('click', () => _setColoringMode('cluster'))
  document.getElementById('menu-view-coloring-cpk')    ?.addEventListener('click', () => _setColoringMode('cpk'))

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

  const _backgroundContainer = document.getElementById('viewport-container') || document.body
  const _backgroundModal = document.getElementById('background-modal')
  const _bgColorInput = document.getElementById('bg-color-input')
  const _bgColorHexInput = document.getElementById('bg-color-hex')
  const _bgImageInput = document.getElementById('bg-image-input')
  const _bgImageFit = document.getElementById('bg-image-fit')
  const _bgImageName = document.getElementById('bg-image-name')
  const _bgPreview = document.getElementById('bg-preview')

  const _backgroundState = {
    mode: 'color',
    color: '#0d1117',
    imageUrl: '',
    imageName: '',
    imageFit: 'cover',
  }

  function _formatAqueousBackground() {
    return `radial-gradient(circle at 18% 18%, rgba(255,255,255,0.18), transparent 5%),
      radial-gradient(circle at 78% 22%, rgba(255,255,255,0.14), transparent 4%),
      radial-gradient(circle at 35% 72%, rgba(255,255,255,0.16), transparent 5%),
      radial-gradient(circle at 65% 80%, rgba(255,255,255,0.12), transparent 6%),
      linear-gradient(180deg, rgba(21,96,143,0.94), rgba(2,40,66,0.96))`
  }

  function _updateBackgroundPreviewText() {
    if (_backgroundState.mode === 'image' && _backgroundState.imageUrl) {
      _bgPreview.textContent = `Image background: ${_backgroundState.imageName || 'selected image'}`
    } else if (_backgroundState.mode === 'aqueous') {
      _bgPreview.textContent = 'Aqueous theme applied. The environment feels cooler and underwater.'
    } else {
      _bgPreview.textContent = `Solid color background: ${_backgroundState.color}`
    }
  }

  function _applyBackgroundStyle() {
    _backgroundContainer.style.backgroundRepeat = 'no-repeat'
    _backgroundContainer.style.backgroundPosition = 'center center'
    _backgroundContainer.style.backgroundAttachment = 'fixed'

    if (_backgroundState.mode === 'image' && _backgroundState.imageUrl) {
      _backgroundContainer.style.backgroundImage = `url("${_backgroundState.imageUrl}")`
      _backgroundContainer.style.backgroundSize = _backgroundState.imageFit === 'stretch' ? '100% 100%' : _backgroundState.imageFit
      _backgroundContainer.style.backgroundColor = _backgroundState.color
    } else if (_backgroundState.mode === 'aqueous') {
      _backgroundContainer.style.backgroundImage = _formatAqueousBackground()
      _backgroundContainer.style.backgroundSize = 'cover'
      _backgroundContainer.style.backgroundColor = '#07324a'
    } else {
      _backgroundContainer.style.backgroundImage = 'none'
      _backgroundContainer.style.backgroundColor = _backgroundState.color
    }
    _updateBackgroundPreviewText()
  }

  function _syncBackgroundModal() {
    _bgColorInput && (_bgColorInput.value = _backgroundState.color)
    _bgColorHexInput && (_bgColorHexInput.value = _backgroundState.color)
    if (_bgImageInput) _bgImageInput.value = ''
    if (_bgImageName) _bgImageName.textContent = _backgroundState.imageName || 'No image selected'
    if (_bgImageFit) _bgImageFit.value = _backgroundState.imageFit
    _updateBackgroundPreviewText()
  }

  _bgColorInput?.addEventListener('input', (event) => {
    _backgroundState.mode = 'color'
    _backgroundState.color = event.target.value
    _bgColorHexInput && (_bgColorHexInput.value = _backgroundState.color)
    _applyBackgroundStyle()
  })

  _bgColorHexInput?.addEventListener('input', (event) => {
    const value = event.target.value.trim()
    if (/^#[0-9a-fA-F]{6}$/.test(value)) {
      _backgroundState.mode = 'color'
      _backgroundState.color = value
      _bgColorInput && (_bgColorInput.value = value)
      _applyBackgroundStyle()
    }
  })

  _bgImageInput?.addEventListener('change', (event) => {
    const file = event.target.files?.[0]
    if (!file) {
      _backgroundState.mode = 'color'
      _backgroundState.imageUrl = ''
      _backgroundState.imageName = ''
      _applyBackgroundStyle()
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      _backgroundState.mode = 'image'
      _backgroundState.imageUrl = reader.result
      _backgroundState.imageName = file.name
      _bgImageName && (_bgImageName.textContent = file.name)
      _applyBackgroundStyle()
    }
    reader.readAsDataURL(file)
  })

  _bgImageFit?.addEventListener('change', (event) => {
    _backgroundState.imageFit = event.target.value
    if (_backgroundState.mode === 'image') _applyBackgroundStyle()
  })

  document.getElementById('menu-view-background')?.addEventListener('click', () => {
    _syncBackgroundModal()
    if (_backgroundModal) _backgroundModal.style.display = 'flex'
  })

  document.getElementById('background-modal-close')?.addEventListener('click', () => {
    if (_backgroundModal) _backgroundModal.style.display = 'none'
  })

  document.getElementById('background-modal-reset')?.addEventListener('click', () => {
    _backgroundState.mode = 'color'
    _backgroundState.color = '#0d1117'
    _backgroundState.imageUrl = ''
    _backgroundState.imageName = ''
    _backgroundState.imageFit = 'cover'
    _syncBackgroundModal()
    _applyBackgroundStyle()
  })

  document.getElementById('background-modal-aqueous')?.addEventListener('click', () => {
    _backgroundState.mode = 'aqueous'
    _backgroundState.color = '#0d1117'
    _backgroundState.imageUrl = ''
    _backgroundState.imageName = ''
    _syncBackgroundModal()
    _applyBackgroundStyle()
  })

  document.getElementById('background-modal-apply')?.addEventListener('click', () => {
    if (_backgroundModal) _backgroundModal.style.display = 'none'
  })

  _backgroundContainer && _applyBackgroundStyle()

  document.getElementById('menu-view-slice')?.addEventListener('click', _toggleSlicePlane)

  document.getElementById('menu-view-unfold')?.addEventListener('click', _toggleUnfold)

  document.getElementById('menu-view-cadnano')?.addEventListener('click', _toggleCadnano)

  document.getElementById('btn-open-editor')?.addEventListener('click', () => {
    window.open('/cadnano-editor.html', 'nadoc-editor')
  })

  document.getElementById('menu-view-deform')?.addEventListener('click', _toggleDeformView)

  // ── Loop/Skip legend ────────────────────────────────────────────────────────
  // Anchored below the filter-view strip (menu-bar 29 px + strip ~24 px → ~58 px).
  // Earlier `top: 44px` placed it inside the strip's vertical band, hiding the
  // selectability/view toggles. `right: 308px` keeps it left of the 300 px
  // right-panel.
  const _loopSkipLegend = document.createElement('div')
  _loopSkipLegend.style.cssText = `
    position: fixed;
    top: 64px;
    right: 308px;
    display: none;
    background: rgba(8,16,26,0.90);
    border: 1px solid #2a5a8a;
    border-radius: 5px;
    padding: 8px 12px;
    font-family: var(--font-ui);
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

  // ── MD Segmentation legend + toggle ─────────────────────────────────────────
  const _mdSegLegend = document.createElement('div')
  _mdSegLegend.style.cssText = `
    position: fixed;
    top: 64px;
    right: 308px;
    display: none;
    background: rgba(8,16,26,0.92);
    border: 1px solid #2a5a8a;
    border-radius: 5px;
    padding: 10px 14px;
    font-family: var(--font-ui);
    font-size: 12px;
    color: #c8daf0;
    line-height: 2.0;
    z-index: 9000;
    pointer-events: none;
    min-width: 220px;
  `
  _mdSegLegend.innerHTML = `
    <div style="color:#5bc8ff;font-weight:bold;letter-spacing:.04em;margin-bottom:5px">MD SEGMENTATION</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#44cc66;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>Periodic &nbsp;— matches modal period</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#ffdd00;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>Minor deviation &nbsp;(1–2 xovers)</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#ff8800;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>Moderate deviation</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#ff4444;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>High deviation / End region</div>
    <div id="md-seg-legend-detail" style="margin-top:6px;font-size:10px;color:#8b949e;border-top:1px solid #21262d;padding-top:5px"></div>
  `.trim()
  document.body.appendChild(_mdSegLegend)

  document.getElementById('menu-view-md-segmentation')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    const nowVisible = mdSegmentation.toggle(currentDesign)
    _setMenuToggle('menu-view-md-segmentation', nowVisible)
    _mdSegLegend.style.display = nowVisible ? 'block' : 'none'
    if (nowVisible && currentDesign) {
      const { windows, modal } = _computeMdSegments(currentDesign)
      const nPeriodic = windows.filter(w => w.category === 'periodic').length
      const detail    = document.getElementById('md-seg-legend-detail')
      if (detail) detail.textContent = `${nPeriodic} / ${windows.length} windows periodic  ·  modal = ${modal} xovers`
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

  function _syncAssemblyMenuVisibility(active) {
    document.getElementById('menu-item-assembly').style.display  = active ? '' : 'none'
    document.getElementById('menu-item-tools').style.display     = active ? 'none' : ''
    for (const id of ['menu-view-slice', 'menu-view-unfold', 'menu-view-cadnano']) {
      document.getElementById(id).style.display = active ? 'none' : ''
    }
  }

  // Import caDNAno / scadnano are only shown on the welcome screen or in assembly mode.
  function _syncImportMenuVisibility() {
    const { currentDesign, assemblyActive } = store.getState()
    const show = !currentDesign || assemblyActive
    for (const id of ['menu-file-import-cadnano', 'menu-file-import-scadnano']) {
      const el = document.getElementById(id)
      if (el) el.style.display = show ? '' : 'none'
    }
  }

  // Gray out the "Deformed View" menu item while cadnano or unfold is active.
  // Both modes require deform to be off (straight geometry), so the toggle is
  // disallowed from inside them; _toggleDeformView() also shows a toast.
  function _syncDeformMenuEnabled() {
    const s = store.getState()
    const disabled = !!(s.cadnanoActive || s.unfoldActive)
    document.getElementById('menu-view-deform')?.classList.toggle('disabled', disabled)
  }

  // Sync store-backed toggles reactively.
  store.subscribe((newState, prevState) => {
    if (newState.unfoldActive     !== prevState.unfoldActive)     { _setMenuToggle('menu-view-unfold',       newState.unfoldActive);  _syncDeformMenuEnabled() }
    if (newState.cadnanoActive    !== prevState.cadnanoActive)    { _setMenuToggle('menu-view-cadnano',      newState.cadnanoActive); _syncDeformMenuEnabled() }
    if (newState.assemblyActive   !== prevState.assemblyActive)   { _syncAssemblyMenuVisibility(newState.assemblyActive); _syncImportMenuVisibility() }
    if (newState.currentDesign    !== prevState.currentDesign)    _syncImportMenuVisibility()
    if (newState.deformVisuActive !== prevState.deformVisuActive) _setMenuToggle('menu-view-deform',       newState.deformVisuActive)
    if (newState.showHelixLabels  !== prevState.showHelixLabels)  _setMenuToggle('menu-view-helix-labels', newState.showHelixLabels)
    if (newState.showSequences    !== prevState.showSequences)    _setMenuToggle('menu-view-sequences',    newState.showSequences)
    if (newState.staplesHidden    !== prevState.staplesHidden)    _setMenuToggle('menu-view-hide-staples', newState.staplesHidden)
    // When unfold auto-deactivates on cadnano exit, update the mode indicator
    // once the unfold animation finishes (cadnanoActive is already false by then).
    if (newState.unfoldActive !== prevState.unfoldActive && !newState.unfoldActive && !newState.cadnanoActive) {
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
  })

  _syncImportMenuVisibility()

  // ── Browser tab title ────────────────────────────────────────────────────────
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign === prevState.currentDesign) return
    const metaName = newState.currentDesign?.metadata?.name ?? 'Untitled'
    document.title = `NADOC 3D — ${_fileName ?? metaName}`
  })

  // Slice plane pill is updated imperatively in _toggleSlicePlane, Escape handler,
  // _resetForNewDesign, and any other place that calls slicePlane.hide/show directly.

  // ── Selection filter toggles ──────────────────────────────────────────────────
  // Hide the slice plane when the deform tool opens.
  // Slice plane: cross-section geometry is only valid on the undeformed model.
  store.subscribe((newState, prevState) => {
    if (newState.deformToolActive && !prevState.deformToolActive) {
      if (slicePlane.isVisible()) {
        slicePlane.hide()
        crossSectionMinimap.clearSlice()
        crossSectionMinimap.hide()
        _clearSliceHighlights()
        _setMenuToggle('menu-view-slice', false)
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      }
    }
  })

  // ── Tool Filter toggles — #view-tools .sf-btn[data-key] ─────────────────────
  {
    const _tfKeyMap = [
      ['bluntEnds',          'blunt'],
      ['crossoverLocations', 'xloc' ],
      ['overhangLocations',  'ovhg' ],
    ]
    for (const [storeKey, dataKey] of _tfKeyMap) {
      const btn = document.querySelector(`#view-tools .sf-btn[data-key="${dataKey}"]`)
      if (!btn) continue
      btn.addEventListener('click', () => {
        const tf = store.getState().toolFilters
        store.setState({ toolFilters: { ...tf, [storeKey]: !tf[storeKey] } })
      })
      store.subscribe(() => {
        btn.classList.toggle('active', !!store.getState().toolFilters[storeKey])
      })
    }
  }

  // Sync toolFilters → tool visibility
  store.subscribe((newState, prevState) => {
    if (newState.toolFilters === prevState.toolFilters) return
    const tf = newState.toolFilters
    const prev = prevState.toolFilters ?? {}
    if (tf.crossoverLocations !== prev.crossoverLocations) {
      crossoverLocations.setVisible(tf.crossoverLocations)
      if (tf.crossoverLocations) {
        crossoverLocations.rebuild(store.getState().currentGeometry).then(() => {
          if (cadnanoView.isActive()) cadnanoView.reapplyPositions()
          else unfoldView.reapplyIfActive()
        })
      }
    }
    if (tf.overhangLocations !== prev.overhangLocations) {
      overhangLocations.setVisible(tf.overhangLocations)
      if (tf.overhangLocations) _rebuildOverhangLocations()
    }
    if (tf.extensionLocations !== prev.extensionLocations) {
      designRenderer.setExtensionsVisible(tf.extensionLocations)
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
          strands: false, domains: false, ends: false, crossoverArcs: false,
          loops: false, skips: false, overhangs: false,
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

  // ── Selection Filter toggles — #select-filter .sf-btn[data-key] ──────────────
  {
    const _selKeyMap = [
      ['scaffold',      'scaf'   ],
      ['staples',       'stap'   ],
      ['strands',       'strand' ],
      ['domains',       'line'   ],
      ['ends',          'ends'   ],
      ['crossoverArcs', 'xover'  ],
      ['loops',         'loop'   ],
      ['skips',         'skip'   ],
      ['overhangs',     'ovhangs'],
    ]
    const _allSelKeys = _selKeyMap.map(([k]) => k)
    const _selectFilter = document.getElementById('select-filter')
    let _preLoopSkipSelectables = null

    for (const [storeKey, dataKey] of _selKeyMap) {
      const btn = document.querySelector(`#select-filter .sf-btn[data-key="${dataKey}"]`)
      if (!btn) continue

      btn.addEventListener('click', () => {
        const { deformToolActive, translateRotateActive } = store.getState()
        if (deformToolActive || translateRotateActive) return
        const st = store.getState().selectableTypes
        if (storeKey === 'loops' || storeKey === 'skips' || storeKey === 'overhangs') {
          if (!st[storeKey]) {
            if (!st.loops && !st.skips && !st.overhangs) _preLoopSkipSelectables = { ...st }
            const cleared = {}
            for (const k of _allSelKeys) cleared[k] = false
            store.setState({ selectableTypes: { ...cleared, [storeKey]: true } })
          } else {
            if (_preLoopSkipSelectables) {
              store.setState({ selectableTypes: { ..._preLoopSkipSelectables } })
              _preLoopSkipSelectables = null
            } else {
              store.setState({ selectableTypes: { ...st, [storeKey]: false } })
            }
          }
        } else {
          store.setState({ selectableTypes: { ...st, [storeKey]: !st[storeKey] } })
        }
      })

      store.subscribe(() => {
        btn.classList.toggle('active', !!store.getState().selectableTypes[storeKey])
      })
    }

    // Lock the selectable filter while a tool is active
    store.subscribe((newState, prevState) => {
      if (newState.deformToolActive === prevState.deformToolActive &&
          newState.translateRotateActive === prevState.translateRotateActive) return
      _selectFilter?.classList.toggle('filter-inactive',
        !!(newState.deformToolActive || newState.translateRotateActive))
    })
  }

  // ── View tool buttons — length heatmap, seq, undef, grid, overhang names ──────
  {
    // Length heatmap
    const _HEATMAP_MIN = 14, _HEATMAP_MAX = 60
    function _heatmapHex(ntCount) {
      const t = Math.max(0, Math.min(1, (ntCount - _HEATMAP_MIN) / (_HEATMAP_MAX - _HEATMAP_MIN)))
      const hue = Math.round(240 * (1 - t))
      // HSL → hex
      const s = 0.9, l = 0.5
      const k = n => (n + hue / 30) % 12
      const a = s * Math.min(l, 1 - l)
      const ch = n => Math.round((l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))) * 255)
      return (ch(0) << 16) | (ch(8) << 8) | ch(4)
    }
    function _strandNt(strand) {
      let t = 0
      for (const d of strand.domains ?? []) t += Math.abs((d.end_bp ?? 0) - (d.start_bp ?? 0)) + 1
      return t
    }

    let _lengthHeatmapOn = false
    const _lenLegend = document.getElementById('length-heatmap-legend')

    function _applyLengthHeatmap() {
      const design = store.getState().currentDesign
      if (!design) return
      const colorMap = new Map()
      for (const s of design.strands ?? []) {
        if (s.strand_type === 'scaffold') continue
        colorMap.set(s.id, _heatmapHex(_strandNt(s)))
      }
      // backbone + slab entries expose strand_id via nuc; cone entries expose it directly
      for (const e of designRenderer.getBackboneEntries?.() ?? []) {
        const c = colorMap.get(e.nuc?.strand_id)
        if (c !== undefined) designRenderer.setEntryColor(e, c)
      }
      for (const e of designRenderer.getSlabEntries?.() ?? []) {
        const c = colorMap.get(e.nuc?.strand_id)
        if (c !== undefined) designRenderer.setEntryColor(e, c)
      }
      for (const e of designRenderer.getConeEntries?.() ?? []) {
        const c = colorMap.get(e.strandId)
        if (c !== undefined) designRenderer.setEntryColor(e, c)
      }
      _lenLegend?.classList.add('visible')
    }
    function _clearLengthHeatmap() {
      for (const e of designRenderer.getBackboneEntries?.() ?? []) {
        designRenderer.setEntryColor(e, e.defaultColor)
      }
      for (const e of designRenderer.getSlabEntries?.() ?? []) {
        designRenderer.setEntryColor(e, e.defaultColor)
      }
      for (const e of designRenderer.getConeEntries?.() ?? []) {
        designRenderer.setEntryColor(e, e.defaultColor)
      }
      _lenLegend?.classList.remove('visible')
    }

    // Grid helper
    const _gridHelper = new THREE.GridHelper(500, 50, 0x21262d, 0x1a1f27)
    _gridHelper.visible = false
    scene.add(_gridHelper)

    function _syncVtButtons() {
      const { showSequences, showOverhangNames, unfoldActive, cadnanoActive, deformVisuActive } = store.getState()
      document.querySelector('.vt-btn[data-vt="lengthHeatmap"]')?.classList.toggle('active', _lengthHeatmapOn)
      document.querySelector('.vt-btn[data-vt="sequences"]')?.classList.toggle('active', showSequences)
      document.querySelector('.vt-btn[data-vt="undefinedBases"]')?.classList.toggle('active', _undefinedHighlightOn)
      document.querySelector('.vt-btn[data-vt="grid"]')?.classList.toggle('active', _gridHelper.visible)
      document.querySelector('.vt-btn[data-vt="overhangNames"]')?.classList.toggle('active', showOverhangNames)
      document.querySelector('.vt-btn[data-vt="expanded"]')?.classList.toggle('active', expandedSpacing.isActive())
      document.querySelector('.vt-btn[data-vt="deform"]')?.classList.toggle('active', deformVisuActive)
      document.querySelector('.vt-btn[data-vt="unfold"]')?.classList.toggle('active', unfoldActive)
      document.querySelector('.vt-btn[data-vt="cadnano2d"]')?.classList.toggle('active', cadnanoActive)
    }

    document.querySelector('.vt-btn[data-vt="lengthHeatmap"]')?.addEventListener('click', () => {
      _lengthHeatmapOn = !_lengthHeatmapOn
      if (_lengthHeatmapOn) _applyLengthHeatmap()
      else _clearLengthHeatmap()
      _syncVtButtons()
    })

    document.querySelector('.vt-btn[data-vt="sequences"]')?.addEventListener('click', () => {
      const { showSequences } = store.getState()
      store.setState({ showSequences: !showSequences })
      _setMenuToggle('menu-view-sequences', !showSequences)
    })

    document.querySelector('.vt-btn[data-vt="undefinedBases"]')?.addEventListener('click', () => {
      _undefinedHighlightOn = !_undefinedHighlightOn
      _setMenuToggle('menu-view-undefined-bases', _undefinedHighlightOn)
      if (_undefinedHighlightOn) _refreshUndefinedHighlight()
      else designRenderer.clearUndefinedHighlight()
      _syncVtButtons()
    })

    document.querySelector('.vt-btn[data-vt="grid"]')?.addEventListener('click', () => {
      _gridHelper.visible = !_gridHelper.visible
      _syncVtButtons()
    })

    document.querySelector('.vt-btn[data-vt="overhangNames"]')?.addEventListener('click', () => {
      const { showOverhangNames } = store.getState()
      store.setState({ showOverhangNames: !showOverhangNames })
      _setMenuToggle('menu-view-overhang-names', !showOverhangNames)
    })

    document.querySelector('.vt-btn[data-vt="expanded"]')?.addEventListener('click', () => {
      expandedSpacing.toggle()
      _syncVtButtons()
    })

    document.querySelector('.vt-btn[data-vt="deform"]')?.addEventListener('click', () => {
      _toggleDeformView()
    })

    document.querySelector('.vt-btn[data-vt="unfold"]')?.addEventListener('click', () => {
      _toggleUnfold()
    })

    document.querySelector('.vt-btn[data-vt="cadnano2d"]')?.addEventListener('click', () => {
      _toggleCadnano()
    })

    // Keep vt buttons in sync when store changes (menu or other code toggling them)
    store.subscribe((newState, prevState) => {
      if (newState.showSequences !== prevState.showSequences ||
          newState.showOverhangNames !== prevState.showOverhangNames ||
          newState.unfoldActive !== prevState.unfoldActive ||
          newState.cadnanoActive !== prevState.cadnanoActive ||
          newState.deformVisuActive !== prevState.deformVisuActive) {
        _syncVtButtons()
      }
    })

    // Re-apply length heatmap when design changes
    store.subscribe((newState, prevState) => {
      if (_lengthHeatmapOn && newState.currentDesign !== prevState.currentDesign) {
        _applyLengthHeatmap()
      }
    })
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
      arrow.classList.toggle('is-collapsed', open)
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
      'border-radius:4px', 'padding:8px 12px', 'font-size:var(--text-xs)',
      'font-family:var(--font-ui)', 'color:#8b949e', 'z-index:500',
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
  // Each shortcut is registered individually; dispatchKeyEvent replaces the
  // monolithic if-else listener.  See frontend/src/input/shortcuts.js.

  registerShortcut({
    key: 'o', ctrl: true, shift: false,
    description: 'Open design file',
    handler(e) {
      e.preventDefault()
      document.getElementById('menu-file-open')?.click()
    },
  })

  registerShortcut({
    key: 's', ctrl: true, shift: false,
    description: 'Save design or assembly',
    handler(e) {
      e.preventDefault()
      if (_partEditContext) {
        _savePartToAssembly()
      } else if (store.getState().assemblyActive) {
        const modeEl = document.getElementById('mode-indicator')
        ;(_assemblyWorkspacePath ? api.saveAssemblyAs(_assemblyWorkspacePath) : api.saveAssemblyToWorkspace()).then(r => {
          if (r) {
            if (r.path) _setAssemblyWorkspacePath(r.path)
            modeEl.textContent = 'ASSEMBLY MODE — saved ✓'
            setTimeout(() => { modeEl.textContent = 'ASSEMBLY MODE' }, 2000)
          }
        })
      } else {
        document.getElementById('menu-file-save')?.click()
      }
    },
  })

  registerShortcut({
    key: 's', ctrl: true, shift: true,
    description: 'Save design as…',
    handler(e) {
      e.preventDefault()
      document.getElementById('menu-file-save-as')?.click()
    },
  })

  registerShortcut({
    key: 'z', ctrl: true, shift: false,
    description: 'Undo',
    blockedWhen: () => isDeformActive(),
    async handler(e) {
      e.preventDefault()
      if (store.getState().assemblyActive) {
        const result = await api.undoAssembly()
        if (!result) {
          const err = store.getState().lastError
          if (err?.status === 404) {
            document.getElementById('mode-indicator').textContent = 'Nothing to undo'
            setTimeout(() => {
              document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
            }, 1500)
          }
        }
        return
      }
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
        if (result.diff_kind === 'cluster_only') {
          await _applyClusterUndoRedoDeltas(result.cluster_diffs)
        } else if (result.diff_kind === 'positions_only') {
          _applyPositionsOnlyDiff(result)
        }
        const { currentDesign } = store.getState()
        if (!currentDesign?.helices?.length) {
          slicePlane.hide()
          workspace.show()
          _showWelcome()
        }
        if (!currentDesign?.deformations?.length && !deformView.isActive()) {
          await deformView.activate()
          _setMenuToggle('menu-view-deform', true)
          document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
        }
      }
    },
  })

  // Ctrl+Y — redo
  registerShortcut({
    key: 'y', ctrl: true,
    description: 'Redo',
    blockedWhen: () => isDeformActive(),
    async handler(e) {
      e.preventDefault()
      if (store.getState().assemblyActive) {
        const result = await api.redoAssembly()
        if (!result) {
          const err = store.getState().lastError
          if (err?.status === 404) {
            document.getElementById('mode-indicator').textContent = 'Nothing to redo'
            setTimeout(() => {
              document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
            }, 1500)
          }
        }
        return
      }
      const result = await api.redo()
      if (!result) {
        const err = store.getState().lastError
        if (err?.status === 404) {
          document.getElementById('mode-indicator').textContent = 'Nothing to redo'
          setTimeout(() => {
            document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
          }, 1500)
        }
      } else if (result.diff_kind === 'cluster_only') {
        await _applyClusterUndoRedoDeltas(result.cluster_diffs)
      } else if (result.diff_kind === 'positions_only') {
        _applyPositionsOnlyDiff(result)
      }
    },
  })

  // Ctrl+Shift+Z — redo (alternate)
  registerShortcut({
    key: 'z', ctrl: true, shift: true,
    description: 'Redo (alternate)',
    blockedWhen: () => isDeformActive(),
    async handler(e) {
      e.preventDefault()
      if (store.getState().assemblyActive) {
        const result = await api.redoAssembly()
        if (!result) {
          const err = store.getState().lastError
          if (err?.status === 404) {
            document.getElementById('mode-indicator').textContent = 'Nothing to redo'
            setTimeout(() => {
              document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
            }, 1500)
          }
        }
        return
      }
      const result = await api.redo()
      if (!result) {
        const err = store.getState().lastError
        if (err?.status === 404) {
          document.getElementById('mode-indicator').textContent = 'Nothing to redo'
          setTimeout(() => {
            document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
          }, 1500)
        }
      } else if (result.diff_kind === 'cluster_only') {
        await _applyClusterUndoRedoDeltas(result.cluster_diffs)
      } else if (result.diff_kind === 'positions_only') {
        _applyPositionsOnlyDiff(result)
      }
    },
  })

  registerShortcut({
    key: 's', ctrl: false,
    description: 'Toggle spreadsheet',
    blockedInInput: true,
    handler() { spreadsheet.toggle() },
  })

  registerShortcut({
    key: 'u', ctrl: false,
    description: 'Toggle 2D unfold view',
    blockedInInput: true,
    handler() { _toggleUnfold() },
  })

  registerShortcut({
    key: 'k', ctrl: false,
    description: 'Toggle cadnano mode',
    blockedInInput: true,
    handler() { _toggleCadnano() },
  })

  // Tab — cycle selection mode: strands → domains → ends → strands
  // Skipped when the move/rotate gizmo is active (cluster_gizmo.js owns Tab there).
  registerShortcut({
    key: 'Tab', ctrl: false,
    description: 'Cycle selection mode',
    blockedInInput: true,
    blockedWhen: () => _translateRotateActive,
    handler(e) {
      e.preventDefault()
      const st = store.getState().selectableTypes
      let next
      if      ( st.strands && !st.domains && !st.ends && !st.crossoverArcs) next = 'domains'
      else if (!st.strands &&  st.domains && !st.ends && !st.crossoverArcs) next = 'ends'
      else if (!st.strands && !st.domains &&  st.ends && !st.crossoverArcs) next = 'crossoverArcs'
      else                                                                   next = 'strands'
      store.setState({
        selectableTypes: {
          ...st,
          strands:       next === 'strands',
          domains:       next === 'domains',
          ends:          next === 'ends',
          crossoverArcs: next === 'crossoverArcs',
        },
      })
      showToast({
        strands:       'Select: Strands',
        domains:       'Select: Domains',
        ends:          'Select: Ends',
        crossoverArcs: 'Select: Crossover Arcs',
      }[next])
    },
  })

  registerShortcut({
    key: 'q', ctrl: false,
    description: 'Toggle expanded helix spacing',
    blockedInInput: true,
    handler() {
      if (_isUnfoldActive() || slicePlane.isVisible()) {
        showToast('Expanded spacing not available while unfold or slice plane is active')
        return
      }
      const { currentDesign } = store.getState()
      if (!currentDesign?.helices?.length) return
      expandedSpacing.toggle()
    },
  })

  registerShortcut({
    key: 'd', ctrl: false, shift: false,
    description: 'Toggle deformed view',
    blockedInInput: true,
    handler() { _toggleDeformView() },
  })

  registerShortcut({
    key: 'd', ctrl: false, shift: true,
    description: 'Dump deformation debug data to console',
    blockedInInput: true,
    async handler() {
      const data = await api.getDeformDebug()
      if (!data) { showToast('Deform debug: no design loaded'); return }
      /* ── pretty-print to console ── */
      console.group('%c[DEFORM DEBUG]', 'color:#5bc8ff;font-weight:bold')
      console.log('ops (%d):', data.ops.length)
      for (const op of data.ops) {
        console.log('  op %s  %s  planes [%d → %d]  affected=%s  cluster=%s',
          op.id.slice(0, 8), op.type, op.plane_a_bp, op.plane_b_bp,
          op.affected_helix_ids.join(',') || '(all)',
          op.cluster_id?.slice(0, 8) ?? 'none',
        )
        console.log('    params:', op.params)
      }
      console.log('cluster_transforms (%d):', data.cluster_transforms.length)
      for (const ct of data.cluster_transforms) {
        console.log('  cluster %s "%s"  default=%s  helices=%s',
          ct.id.slice(0, 8), ct.name, ct.is_default, ct.helix_ids.join(','))
        console.log('    translation:', ct.translation, '  rotation:', ct.rotation, '  pivot:', ct.pivot)
      }
      console.log('helices (%d):', data.helices.length)
      for (const h of data.helices) {
        console.group('  helix %s  bp_start=%d  len=%d  cluster=%s',
          h.helix_id.slice(0, 8), h.bp_start, h.length_bp,
          h.cluster_id?.slice(0, 8) ?? 'none')
        console.log('axis_start:', h.axis_start, '→ axis_end:', h.axis_end)
        console.log('arm_helix_ids:', h.arm_helix_ids)
        console.log('arm_all_ids (before cluster filter):', h.arm_all_ids)
        console.log('centroid_0:', h.centroid_0)
        console.log('tangent_0:', h.tangent_0)
        console.log('cs_offset:', h.cs_offset)
        console.log('arm_min_bp_start:', h.arm_min_bp_start)
        console.log('frames:')
        console.table(h.frames.map(f => ({
          bp_local:  f.bp_local,
          bp_global: f.bp_global,
          spine_x: f.spine[0].toFixed(3),
          spine_y: f.spine[1].toFixed(3),
          spine_z: f.spine[2].toFixed(3),
          axis_def_x: f.axis_deformed[0].toFixed(3),
          axis_def_y: f.axis_deformed[1].toFixed(3),
          axis_def_z: f.axis_deformed[2].toFixed(3),
          tang_x: f.tangent[0].toFixed(3),
          tang_y: f.tangent[1].toFixed(3),
          tang_z: f.tangent[2].toFixed(3),
        })))
        console.groupEnd()
      }
      /* also dump raw JSON so user can copy it */
      console.log('raw JSON:', JSON.stringify(data, null, 2))
      console.groupEnd()
      showToast('Deform debug dumped to browser console (Shift+D)')
    },
  })

  registerShortcut({
    key: 'v', ctrl: false,
    description: 'Capture camera pose',
    blockedInInput: true,
    handler() {
      const { currentDesign } = store.getState()
      if (!currentDesign) return
      const n = (currentDesign.camera_poses?.length ?? 0) + 1
      const camState = captureCurrentCamera()
      api.createCameraPose(`Pose ${n}`, camState)
      showToast(`Camera pose saved: Pose ${n}`)
    },
  })

  // Number hotkeys 1–6 — workflow shortcuts (routing → sequencing in order)
  for (const [key, menuId, desc] of [
    ['1', 'menu-routing-scaffold-ends',  'Autoscaffold'],
    ['2', 'menu-routing-auto-crossover', 'Auto Crossover'],
    ['3', 'menu-routing-autobreak',      'Autobreak'],
    ['4', 'menu-seq-update-routing',     'Add Loops/Skips'],
    ['5', 'menu-seq-assign-scaffold',    'Scaffold sequence'],
    ['6', 'menu-seq-assign-staples',     'Staple sequence'],
  ]) {
    registerShortcut({
      key, ctrl: false, shift: false, alt: false,
      description: desc,
      blockedInInput: true,
      handler(e) {
        e.preventDefault()
        const btn = document.getElementById(menuId)
        if (btn && !btn.disabled) btn.click()
      },
    })
  }

  registerShortcut({
    key: '`', ctrl: false,
    description: 'Toggle debug hover overlay',
    blockedInInput: true,
    handler() {
      debugOverlay.toggle()
      const active = debugOverlay.isActive()
      _setMenuToggle('menu-view-debug', active)
      store.setState({ debugOverlayActive: active })
    },
  })

  registerShortcut({
    key: 'f', ctrl: false,
    description: 'Fit structure in view',
    blockedInInput: true,
    handler() { _fitToView() },
  })

  registerShortcut({
    key: 'm', ctrl: false,
    description: 'Toggle distance measurement',
    blockedInInput: true,
    handler(e) {
      e.preventDefault()
      if (store.getState().unfoldActive) {
        const el = document.getElementById('mode-indicator')
        if (el) {
          el.textContent = 'Measurement not available in unfold view'
          setTimeout(() => { el.textContent = 'NADOC · WORKSPACE' }, 2000)
        }
        return
      }
      if (_measActive) { _measClear(); return }
      const cb = selectionManager.getCtrlBeads()
      if (cb.length === 2) {
        const posA = selectionManager.getCtrlBeadPos(0)
        const posB = selectionManager.getCtrlBeadPos(1)
        _measShow(posA, posB)
      }
    },
  })

  registerShortcut({
    key: 'b', ctrl: false, shift: false,
    description: 'Toggle blunt ends',
    blockedInInput: true, noRepeat: true,
    handler(e) {
      e.preventDefault()
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, bluntEnds: !tf.bluntEnds } })
    },
  })

  registerShortcut({
    key: 'c', ctrl: false, shift: false,
    description: 'Toggle manual crossover markers',
    blockedInInput: true, noRepeat: true,
    handler(e) {
      e.preventDefault()
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, crossoverLocations: !tf.crossoverLocations } })
    },
  })

  registerShortcut({
    key: 'o', ctrl: false, alt: false, shift: false,
    description: 'Toggle overhang location markers',
    blockedInInput: true, noRepeat: true,
    handler(e) {
      e.preventDefault()
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, overhangLocations: !tf.overhangLocations } })
    },
  })

  registerShortcut({
    key: 'Delete',
    description: 'Delete selected strand, overhang, or unplace selected crossover',
    blockedInInput: true,
    async handler(e) {
      e.preventDefault()
      const { selectedObject, multiSelectedStrandIds, multiSelectedOverhangIds } = store.getState()

      if (multiSelectedOverhangIds?.length > 0) {
        const ids = [...multiSelectedOverhangIds]
        selectionManager.clearMultiOverhangSelection?.()
        _ooClose()
        await api.deleteOverhangs(ids)
        return
      }

      if (multiSelectedStrandIds?.length > 0) {
        const ids = [...multiSelectedStrandIds]
        if (ids.length === 1) await api.deleteStrand(ids[0])
        else await api.deleteStrandsBatch(ids)
        return
      }

      const { multiSelectedDomainIds } = store.getState()
      if (multiSelectedDomainIds?.length > 0) {
        const ids = [...new Set(multiSelectedDomainIds.map(d => d.strandId))]
        if (ids.length === 1) await api.deleteStrand(ids[0])
        else await api.deleteStrandsBatch(ids)
        return
      }

      const multiArcs = selectionManager.getMultiCrossoverArcs()
      if (multiArcs.length > 0) {
        selectionManager.clearMultiCrossoverArcs()
        const design = store.getState().currentDesign
        const flIds = new Set((design?.forced_ligations ?? []).map(fl => fl.id))

        // Separate forced-ligation arcs from regular crossover arcs
        const flArcIds = []
        const nicks = []
        for (const a of multiArcs) {
          if (!a.fromNuc) continue
          if (flIds.has(a.crossover_id)) {
            flArcIds.push(a.crossover_id)
          } else {
            nicks.push({
              helixId:   a.fromNuc.helix_id,
              bpIndex:   a.fromNuc.bp_index,
              direction: a.fromNuc.direction,
            })
          }
        }

        // Delete forced ligations (splits strands + removes FL records)
        if (flArcIds.length === 1) await api.deleteForcedLigation(flArcIds[0])
        else if (flArcIds.length > 1) await api.batchDeleteForcedLigations(flArcIds)

        // Nick regular crossovers
        if (nicks.length === 1) await api.addNick(nicks[0])
        else if (nicks.length > 1) await api.addNickBatch(nicks)
        return
      }

      if (!selectedObject) return

      if (selectedObject.type === 'strand' || selectedObject.type === 'bead' || selectedObject.type === 'nucleotide') {
        const strandId = selectedObject.data?.strand_id
        if (strandId) await api.deleteStrand(strandId)
      } else if (selectedObject.type === 'domain') {
        const strandId = selectedObject.data?.strand_id
        if (/^__lnk__.+__(a|b)$/.test(strandId ?? '')) await api.deleteStrand(strandId)
      } else if (selectedObject.type === 'cone') {
        const strandId = selectedObject.data?.strand_id
        if (/^__lnk__.+__(a|b)$/.test(strandId ?? '')) {
          await api.deleteStrand(strandId)
          return
        }
        const fromNuc = selectedObject.data?.fromNuc
        if (fromNuc) {
          await api.addNick({
            helixId:   fromNuc.helix_id,
            bpIndex:   fromNuc.bp_index,
            direction: fromNuc.direction,
          })
        }
      }
    },
  })

  // Escape — exit force crossover selection, deformation tool, or slice plane.
  // Not blockedInInput so Escape always works regardless of focus.
  registerShortcut({
    key: 'Escape',
    description: 'Cancel active tool / clear selection',
    handler() {
      if (_ooActiveIds.length > 0) {
        _ooClose()
        return
      }
      if (_measActive) { _measClear() }
      if (selectionManager.getCtrlBeads().length > 0) {
        selectionManager.clearCtrlBeads()
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
    },
  })

  document.addEventListener('keydown', dispatchKeyEvent)

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

  // ── Move/Rotate tool ─────────────────────────────────────────────────────────
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
  /** Swing-twist decomposition: extract the signed rotation angle (degrees) around joint.axis_direction. */
  function _extractJointAngleDeg(quaternion, joint) {
    const axisDir = new THREE.Vector3(...joint.axis_direction).normalize()
    const dot = quaternion.x * axisDir.x + quaternion.y * axisDir.y + quaternion.z * axisDir.z
    const len = Math.sqrt(dot * dot + quaternion.w * quaternion.w)
    if (len < 1e-8) return 0
    return 2 * Math.atan2(dot / len, quaternion.w / len) * (180 / Math.PI)
  }

  const clusterGizmo    = initClusterGizmo(
    store, controls,
    (helixIds, centerVec, dummyPos, incrRotQuat, domainIds) => {
      const helixCtrl = designRenderer.getHelixCtrl()
      helixCtrl?.applyClusterTransform(helixIds, centerVec, dummyPos, incrRotQuat, domainIds)
      // Blunt-end rings + labels: domainIds filters to only the strand-domain
      // ends owned by the moved subset (sub-cluster mode); without filtering
      // it covers every blunt end on the helix (full-cluster mode).
      bluntEnds?.applyClusterTransform(helixIds, centerVec, dummyPos, incrRotQuat, domainIds)
      // Joint indicators + overhang locations don't yet support sub-cluster
      // partitioning — skip them for split-domain clusters to avoid moving
      // elements that belong to the un-moved partition.
      if (!domainIds?.length) jointRenderer?.applyClusterTransform(helixIds, centerVec, dummyPos, incrRotQuat)
      if (!domainIds?.length) overhangLocations.applyClusterTransform(helixIds, centerVec, dummyPos, incrRotQuat)
      // Keep crossover arcs, xb beads, and extension beads in sync with the moved cluster.
      unfoldView.applyClusterArcUpdate(helixIds)
      unfoldView.applyClusterExtArcUpdate(helixIds)
      designRenderer.applyClusterCrossoverUpdate(helixIds)
      // Extra-base beads now live in crossoverConnections group — rebuilt on full scene rebuild.
      // DEBUG — log once per frame so you can see cone state during a drag
      helixCtrl?.logConeDebug('LIVE-FRAME')
    },
    (helixIds, domainIds) => {
      const helixCtrl = designRenderer.getHelixCtrl()
      helixCtrl?.captureClusterBase(helixIds, domainIds)
      bluntEnds?.captureClusterBase(helixIds, false, domainIds)
      if (!domainIds?.length) jointRenderer?.captureClusterBase(helixIds)
      if (!domainIds?.length) overhangLocations.captureClusterBase(helixIds)
      // DEBUG — snapshot the bead positions at drag-start before any transform
      helixCtrl?.logConeDebug('DRAG-START')
    },
    (translation, quaternion) => {
      _clusterDirty = true
      const [rx, ry, rz] = _quatToEulerDeg([quaternion.x, quaternion.y, quaternion.z, quaternion.w])
      _mrSetTransformValues(translation[0], translation[1], translation[2], rx, ry, rz)
      const activeJoint = clusterGizmo?.getActiveJoint()
      if (activeJoint) {
        _mrSetJointAngle(_extractJointAngleDeg(quaternion, activeJoint))
      }
    },
  )
  // Phase 4 — per-sub-domain rotation gizmo DISABLED 2026-05-11.
  // The gizmo's gold/cyan rings used to attach in the main 3D scene whenever
  // a sub-domain was selected via the Domain Designer. The user removed the
  // rotation tools from the DD; correspondingly, the gizmo is no longer
  // instantiated here. Saved `rotation_theta_deg` / `rotation_phi_deg`
  // values still flow through the geometry pipeline if present in a loaded
  // design, but there is no UI to author them. To re-enable, restore the
  // `initSubDomainGizmo(store, controls, {…})` call and the
  // `window.__nadocSubDomainGizmo` export.
  void initSubDomainGizmo  // keep import alive so the module isn't tree-shaken
                           // out by Vite while the disable is provisional.
  // DEBUG — expose cone snapshot to browser console: nadocConeSnap('label')
  window.nadocConeSnap     = (label = 'MANUAL') => designRenderer.getHelixCtrl()?.logConeDebug(label)
  // DEBUG — expose overhang arrow snapshot: nadocOverhangSnap('label')
  window.nadocOverhangSnap = (label = 'MANUAL') => overhangLocations.logOverhangDebug(label)
  // DEBUG — expose rendered domain-end helix label sprites as a table.
  window.nadocHelixLabelTable = function nadocHelixLabelTable(opts = {}) {
    const labels = opts.labels ? new Set(opts.labels.map(v => String(v))) : null
    const overhangsOnly = opts.overhangsOnly ?? false
    const rows = (bluntEnds?.getHelixLabelTable?.() ?? []).filter(row => {
      if (labels && !labels.has(String(row.helixLabel))) return false
      if (overhangsOnly && !row.overhangId) return false
      return true
    })
    console.table(rows.map(row => ({
      helix:    row.helixLabel,
      helixId:  row.helixId,
      domainBp: row.domainBp,
      ringBp:   row.ringBp,
      side:     row.openSide,
      dir:      row.direction,
      ovhg:     row.overhangId,
      strand:   row.strandType,
      visible:  row.visible,
      labelPos: row.labelPos3d?.map(v => +v.toFixed(3)).join(','),
    })))
    return rows
  }

  window.nadocHelixLabelDrift = function nadocHelixLabelDrift(opts = {}) {
    const rows = window.nadocHelixLabelTable(opts)
    const isCadnano = !!store.getState().cadnanoActive
    const drift = rows.map(row => {
      const [rx, ry, rz] = row.ringPos3d ?? [null, null, null]
      const [lx, ly, lz] = row.labelPos3d ?? [null, null, null]
      const dx = lx - rx
      const dy = ly - ry
      const dz = lz - rz
      const gapNm = Math.sqrt(dx*dx + dy*dy + dz*dz)
      const gapBpZ = dz / 0.334
      const ringBpFromZ = rz / 0.334
      const labelBpFromZ = lz / 0.334
      const ringBpError = isCadnano ? ringBpFromZ - row.ringBp : null
      const labelGapError = isCadnano ? Math.abs(gapBpZ) - 1 : null
      return {
        helix: row.helixLabel,
        helixId: row.helixId,
        domainBp: row.domainBp,
        ringBp: row.ringBp,
        side: row.openSide,
        ovhg: row.overhangId,
        ringBpFromZ: isCadnano ? +ringBpFromZ.toFixed(3) : null,
        labelBpFromZ: isCadnano ? +labelBpFromZ.toFixed(3) : null,
        ringBpError: isCadnano ? +ringBpError.toFixed(3) : null,
        labelGapBpZ: isCadnano ? +gapBpZ.toFixed(3) : null,
        labelGapError: isCadnano ? +labelGapError.toFixed(3) : null,
        sideOk: isCadnano ? Math.sign(gapBpZ) === Math.sign(row.openSide) : null,
        gapNm: +gapNm.toFixed(3),
        ringPos: row.ringPos3d?.map(v => +v.toFixed(3)).join(','),
        labelPos: row.labelPos3d?.map(v => +v.toFixed(3)).join(','),
      }
    }).sort((a, b) =>
      Number(a.helix) - Number(b.helix) ||
      a.ringBp - b.ringBp ||
      String(a.ovhg ?? '').localeCompare(String(b.ovhg ?? ''))
    )
    const mismatches = drift.filter(row => {
      if (!isCadnano) return false
      return Math.abs(row.ringBpError) > 0.01 ||
        Math.abs(row.labelGapError) > 0.01 ||
        row.sideOk === false
    })
    console.table(drift)
    if (mismatches.length) {
      console.warn(`nadocHelixLabelDrift: ${mismatches.length} mismatch(es)`)
      console.table(mismatches)
    } else {
      console.log(`nadocHelixLabelDrift: no caDNAno bp/gap mismatches in ${drift.length} label(s)`)
    }
    return { rows: drift, mismatches }
  }

  // ── Assembly helix label debug ────────────────────────────────────────────
  // Usage: nadocAssemblyLabelTable()           — all instances
  //        nadocAssemblyLabelTable({inst:'Ultimate…'}) — filter by instance name substring
  window.nadocAssemblyLabelTable = function nadocAssemblyLabelTable(opts = {}) {
    const rows = assemblyRenderer.getLabelTable()
    const filtered = opts.inst
      ? rows.filter(r => r.instName?.includes(opts.inst))
      : rows
    console.table(filtered.map(r => ({
      inst:     r.instName,
      helix:    r.helixLabel,
      tag:      r.tag,
      helixId:  r.helixId,
      localPos: r.localPos?.join(','),
      worldPos: r.worldPos?.join(','),
    })))
    return filtered
  }

  // ── Label / terminus audit ────────────────────────────────────────────────
  // nadocLabelAudit({ labels, overhangsOnly })
  //
  // Compare rendered domain-end rings / helix label sprites against domain
  // endpoints.  Useful after caDNAno import:
  //   nadocLabelAudit({ labels: [28,29,30,31,32,33,42,43,44,45], overhangsOnly: true })
  //
  // Returns { labelTable, terminusTable, comparison, phantomTermini }.
  window.nadocLabelAudit = function nadocLabelAudit(opts = {}) {
    const { currentDesign } = store.getState()
    if (!currentDesign) { console.warn('nadocLabelAudit: no design loaded'); return null }
    const labelFilter = opts.labels
      ? new Set(opts.labels.map(v => String(v)))
      : null
    const overhangsOnly = opts.overhangsOnly ?? false

    // ── Table 1: blunt-end labels ─────────────────────────────────────────
    const rawLabelTable = bluntEnds?.getHelixLabelTable?.() ?? bluntEnds?.getEndTable() ?? []
    const labelTable = rawLabelTable.filter(l => {
      if (labelFilter && !labelFilter.has(String(l.helixLabel))) return false
      if (overhangsOnly && !l.overhangId) return false
      return true
    })

    // ── Table 2: domain terminus beads ───────────────────────────────────
    const backboneEntries = designRenderer.getBackboneEntries()

    // Position lookup: "helixId:bp:dir" → backbone_position [x,y,z]
    const posLookup = new Map()
    for (const { nuc, pos } of backboneEntries) {
      posLookup.set(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`, pos?.toArray?.() ?? nuc.backbone_position)
    }

    // Coverage map: helixId → Set<bp>  (all bps covered by any domain)
    const covMap = new Map()
    for (const strand of currentDesign.strands ?? []) {
      for (const d of strand.domains) {
        let s = covMap.get(d.helix_id)
        if (!s) { s = new Set(); covMap.set(d.helix_id, s) }
        const lo = Math.min(d.start_bp, d.end_bp)
        const hi = Math.max(d.start_bp, d.end_bp)
        for (let b = lo; b <= hi; b++) s.add(b)
      }
    }

    const terminusTable = []
    for (const strand of currentDesign.strands ?? []) {
      const nDoms = strand.domains.length
      for (let di = 0; di < nDoms; di++) {
        const dom  = strand.domains[di]
        // start_bp = 5' end of domain, end_bp = 3' end (NADOC convention)
        const termBps = [
          { bp: dom.start_bp, is5p: true,  is3p: false },
          { bp: dom.end_bp,   is5p: false, is3p: true  },
        ]
        for (const { bp, is5p, is3p } of termBps) {
          const cov  = covMap.get(dom.helix_id)
          const fPos = posLookup.get(`${dom.helix_id}:${bp}:FORWARD`)
          const rPos = posLookup.get(`${dom.helix_id}:${bp}:REVERSE`)
          // Axis position = midpoint of FORWARD + REVERSE beads (matches ring placement logic)
          let axisPos3d = null
          if (fPos && rPos) {
            axisPos3d = [(fPos[0]+rPos[0])*0.5, (fPos[1]+rPos[1])*0.5, (fPos[2]+rPos[2])*0.5]
          } else if (fPos || rPos) {
            axisPos3d = fPos ?? rPos
          }
          terminusTable.push({
            helixId:         dom.helix_id,
            bp,
            direction:       dom.direction,
            strandId:        strand.id,
            domainIdx:       di,
            isStrand5p:      di === 0          && is5p,
            isStrand3p:      di === nDoms - 1  && is3p,
            overhangId:      dom.overhang_id ?? null,
            backbonePos3d:   (dom.direction === 'FORWARD' ? fPos : rPos) ?? null,
            axisPos3d,
            prevBpOccupied:  cov?.has(bp - 1) ?? false,
            nextBpOccupied:  cov?.has(bp + 1) ?? false,
          })
        }
      }
    }

    // ── Comparison: align on { helixId, bp } ──────────────────────────────
    // Group terminus entries by "helixId:bp" for fast lookup
    const termByKey = new Map()
    for (const t of terminusTable) {
      const key = `${t.helixId}:${t.bp}`
      if (!termByKey.has(key)) termByKey.set(key, [])
      termByKey.get(key).push(t)
    }

    const comparison = []
    for (const lbl of labelTable) {
      const domainBp = lbl.domainBp ?? lbl.bp
      const ringBp   = lbl.ringBp ?? lbl.diskBp
      const key  = `${lbl.helixId}:${domainBp}`
      const hits = termByKey.get(key) ?? []
      if (!hits.length) {
        comparison.push({
          helixId:    lbl.helixId,
          helixLabel: lbl.helixLabel,
          bp:         domainBp,
          diskBp:     ringBp,
          openSide:   lbl.openSide,
          overhangId: lbl.overhangId,
          ringPos3d:  lbl.ringPos3d,
          labelPos3d: lbl.labelPos3d,
          terminusMatch: null,
          ringToAxisDist:   null,
          labelToBeadDist:  null,
          note: 'NO_TERMINUS_AT_BP',
        })
        continue
      }
      for (const t of hits) {
        let ringToAxisDist  = null
        let labelToBeadDist = null
        if (t.axisPos3d && lbl.ringPos3d) {
          const dx = lbl.ringPos3d[0]-t.axisPos3d[0]
          const dy = lbl.ringPos3d[1]-t.axisPos3d[1]
          const dz = lbl.ringPos3d[2]-t.axisPos3d[2]
          ringToAxisDist = +Math.sqrt(dx*dx+dy*dy+dz*dz).toFixed(4)
        }
        if (t.backbonePos3d && lbl.labelPos3d) {
          const dx = lbl.labelPos3d[0]-t.backbonePos3d[0]
          const dy = lbl.labelPos3d[1]-t.backbonePos3d[1]
          const dz = lbl.labelPos3d[2]-t.backbonePos3d[2]
          labelToBeadDist = +Math.sqrt(dx*dx+dy*dy+dz*dz).toFixed(4)
        }
        comparison.push({
          helixId:    lbl.helixId,
          helixLabel: lbl.helixLabel,
          bp:         domainBp,
          diskBp:     ringBp,
          openSide:   lbl.openSide,
          overhangId: lbl.overhangId,
          ringPos3d:  lbl.ringPos3d,
          labelPos3d: lbl.labelPos3d,
          terminusMatch: t,
          ringToAxisDist,
          labelToBeadDist,
          prevBpOccupied: t.prevBpOccupied,
          nextBpOccupied: t.nextBpOccupied,
          note: (!t.prevBpOccupied || !t.nextBpOccupied) ? 'FREE_END' : 'NICK_OR_XOVER',
        })
      }
    }

    // Phantom termini: terminus beads at free ends with no matching blunt-end label
    const labeledKeys = new Set(labelTable.map(l => `${l.helixId}:${l.domainBp ?? l.bp}`))
    const phantomTermini = terminusTable.filter(t =>
      (!t.prevBpOccupied || !t.nextBpOccupied) &&
      (!overhangsOnly || t.overhangId) &&
      (!labelFilter || labelFilter.has(String(currentDesign.helices.find(h => h.id === t.helixId)?.label
        ?? currentDesign.helices.findIndex(h => h.id === t.helixId)))) &&
      !labeledKeys.has(`${t.helixId}:${t.bp}`)
    )

    console.group('nadocLabelAudit')
    console.log(`Labels: ${labelTable.length}   Terminus beads: ${terminusTable.length}`)
    console.table(comparison.map(r => ({
      helix:    r.helixLabel,
      helixId:  r.helixId,
      bp:       r.bp,
      diskBp:   r.diskBp,
      side:     r.openSide,
      ovhg:     r.overhangId,
      ringPos:  r.ringPos3d?.map(v => +v.toFixed(3)).join(','),
      labelPos: r.labelPos3d?.map(v => +v.toFixed(3)).join(','),
      'ring->axis': r.ringToAxisDist,
      'lbl->bead':  r.labelToBeadDist,
      freeEnd:  r.note === 'FREE_END',
      note:     r.note,
    })))
    if (phantomTermini.length) {
      console.warn(`${phantomTermini.length} free-end terminus bead(s) with no blunt-end label:`)
      console.table(phantomTermini.map(t => ({
        helixId: t.helixId, bp: t.bp, dir: t.direction,
        strand:  t.strandId, ovhg: t.overhangId,
        axisPos: t.axisPos3d?.map(v => +v.toFixed(3)).join(','),
        'bp-1': t.prevBpOccupied, 'bp+1': t.nextBpOccupied,
      })))
    }
    console.groupEnd()

    return { labelTable, terminusTable, comparison, phantomTermini }
  }

  // ── Overhang Orientation right-sidebar panel ─────────────────────────────────
  const _ooPanel     = document.getElementById('overhang-orient-panel')
  const _ooInfo      = document.getElementById('overhang-orient-info')
  const _ooApplyBtn  = document.getElementById('oo-apply-btn')
  const _ooResetBtn  = document.getElementById('oo-reset-btn')
  const _ooCancelBtn = document.getElementById('oo-cancel-btn')
  const _ooRxInp     = document.getElementById('oo-rx')
  const _ooRyInp     = document.getElementById('oo-ry')
  const _ooRzInp     = document.getElementById('oo-rz')
  let   _ooActiveIds          = []    // overhang_id strings currently being edited
  let   _ooRightClickedId     = null  // anchor ID — gizmo centres on this overhang's pivot
  let   _ooOriginalRotations  = {}    // {id: [qx,qy,qz,qw]} captured on open, used by Cancel
  let   _ooPivotPositions     = {}    // {id: THREE.Vector3} junction bead positions in world space
  let   _ooDirtyPreview       = false // true once any drag-preview frame has fired

  function _ooOpen(ovhgIds, rightClickedId = null) {
    _ooActiveIds         = ovhgIds
    _ooRightClickedId    = rightClickedId ?? ovhgIds[0]
    _ooOriginalRotations = {}
    _ooPivotPositions    = {}
    _ooDirtyPreview      = false

    const { currentDesign } = store.getState()
    for (const id of ovhgIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (o) _ooOriginalRotations[id] = [...o.rotation]
      const root = _ovhgRootMap.get(id)
      if (root) _ooPivotPositions[id] = root.pos
    }

    if (!_ooPanel) return
    _ooPanel.style.display = ''

    if (_ooInfo) {
      const n = ovhgIds.length
      if (n === 1) {
        const label = currentDesign?.overhangs?.find(o => o.id === ovhgIds[0])?.label
        _ooInfo.textContent = label ? `"${label}"` : ovhgIds[0]
      } else {
        _ooInfo.textContent = `${n} overhangs selected`
      }
    }

    _ooUpdateAngleFields(new THREE.Quaternion())

    const anchorPivot = _ooPivotPositions[_ooRightClickedId] ?? null
    overhangGizmo.attach(_ooRightClickedId, ovhgIds, currentDesign, anchorPivot)
  }

  function _ooClose() {
    _ooActiveIds        = []
    _ooRightClickedId   = null
    _ooOriginalRotations = {}
    if (_ooPanel) _ooPanel.style.display = 'none'
    overhangGizmo.detach()
    if (_ooDirtyPreview) {
      _ooDirtyPreview = false
      api.getGeometry()   // revert client-side preview — re-fetches current server geometry
    }
  }

  function _ooUpdateAngleFields(q) {
    const e = new THREE.Euler().setFromQuaternion(q, 'XYZ')
    const fmt = rad => parseFloat(THREE.MathUtils.radToDeg(rad).toFixed(1))
    if (_ooRxInp) _ooRxInp.value = fmt(e.x)
    if (_ooRyInp) _ooRyInp.value = fmt(e.y)
    if (_ooRzInp) _ooRzInp.value = fmt(e.z)
  }

  async function _ooApplyDelta(R_delta) {
    if (!_ooActiveIds.length) return
    const { currentDesign } = store.getState()
    const ops = []
    for (const id of _ooActiveIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (!o) continue
      const R_existing = new THREE.Quaternion(o.rotation[0], o.rotation[1], o.rotation[2], o.rotation[3])
      const R_new = R_delta.clone().multiply(R_existing)
      ops.push({ overhang_id: id, rotation: [R_new.x, R_new.y, R_new.z, R_new.w] })
    }
    if (ops.length) await api.patchOverhangRotationsBatch(ops)
    if (store.getState().assemblyActive) {
      const { activeInstanceId, currentAssembly } = store.getState()
      if (activeInstanceId) assemblyRenderer.invalidateInstance(activeInstanceId)
      await assemblyRenderer.rebuild(currentAssembly)
    }
    _ooDirtyPreview = false
    const { currentDesign: updated } = store.getState()
    overhangGizmo.attach(_ooRightClickedId, _ooActiveIds, updated)
    _ooUpdateAngleFields(new THREE.Quaternion())
  }

  async function _ooApply() {
    await _ooApplyDelta(overhangGizmo.getCurrentRDelta())
    _ooClose()
  }

  // Instant client-side preview of an incremental rotation q_inc (world-space quaternion).
  // Captures the current rendered base, applies q_inc about each overhang's root bead,
  // and accumulates into the gizmo so getCurrentRDelta() and Apply stay consistent.
  // No server round-trip — same path as onPreview during a gizmo drag.
  function _ooPreviewIncrement(q_inc) {
    if (!_ooActiveIds.length) return
    const { currentDesign } = store.getState()
    const helixCtrl = designRenderer.getHelixCtrl()
    const helixIds = [], allDomainIds = [], extrudeHelixIds = []
    for (const id of _ooActiveIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (!o) continue
      helixIds.push(o.helix_id)
      const domIds = _ovhgDomainIds(id, currentDesign)
      if (domIds) allDomainIds.push(...domIds)
      if (_isExtrudeOverhang(id, currentDesign)) {
        extrudeHelixIds.push(o.helix_id)
      }
    }
    helixCtrl?.captureClusterBase(helixIds, allDomainIds.length ? allDomainIds : null)
    bluntEnds?.captureClusterBase(new Set(_ooActiveIds))
    if (extrudeHelixIds.length) {
      helixCtrl?.captureClusterBase(extrudeHelixIds, null, true, { forceAxes: true })
      overhangLocations?.captureClusterBase(extrudeHelixIds)
    }
    _ooDirtyPreview = true
    for (const id of _ooActiveIds) {
      const o = currentDesign?.overhangs?.find(x => x.id === id)
      if (!o) continue
      const pivot = _ooPivotPositions[id]
        ?? new THREE.Vector3(o.pivot[0], o.pivot[1], o.pivot[2])
      const domIds = _ovhgDomainIds(id, currentDesign)
      const isExtrude = _isExtrudeOverhang(id, currentDesign)
      helixCtrl?.applyClusterTransform([o.helix_id], pivot, pivot, q_inc, domIds,
        isExtrude ? { forceAxes: true } : undefined)
      bluntEnds?.applyClusterTransform([id], pivot, pivot, q_inc)
      if (isExtrude) {
        overhangLocations?.applyClusterTransform([o.helix_id], pivot, pivot, q_inc)
      }
    }
    overhangGizmo.accumulateDelta(q_inc)
    _ooUpdateAngleFields(overhangGizmo.getCurrentRDelta())
  }

  // Preview the absolute Euler angles typed into the fields by computing the delta
  // from the current accumulated rotation to the target, then applying it incrementally.
  function _ooPreviewFromFields() {
    const rx = parseFloat(_ooRxInp?.value) || 0
    const ry = parseFloat(_ooRyInp?.value) || 0
    const rz = parseFloat(_ooRzInp?.value) || 0
    const Q_target = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(
        THREE.MathUtils.degToRad(rx),
        THREE.MathUtils.degToRad(ry),
        THREE.MathUtils.degToRad(rz),
        'XYZ'
      )
    )
    const Q_delta = Q_target.clone().multiply(overhangGizmo.getCurrentRDelta().invert())
    _ooPreviewIncrement(Q_delta)
  }

  if (_ooApplyBtn)  _ooApplyBtn.addEventListener('click', _ooApply)
  if (_ooCancelBtn) _ooCancelBtn.addEventListener('click', _ooClose)

  if (_ooResetBtn) _ooResetBtn.addEventListener('click', async () => {
    if (!_ooActiveIds.length) return
    const ops = _ooActiveIds.map(id => ({ overhang_id: id, rotation: [0, 0, 0, 1] }))
    await api.patchOverhangRotationsBatch(ops)
    if (store.getState().assemblyActive) {
      const { activeInstanceId, currentAssembly } = store.getState()
      if (activeInstanceId) assemblyRenderer.invalidateInstance(activeInstanceId)
      await assemblyRenderer.rebuild(currentAssembly)
    }
    _ooDirtyPreview = false
    const { currentDesign } = store.getState()
    overhangGizmo.attach(_ooRightClickedId, _ooActiveIds, currentDesign)
    _ooUpdateAngleFields(new THREE.Quaternion())
  })

  // ── Overhang angle field wiring ──────────────────────────────────────────────

  const _ooAxisVecs = {
    rx: new THREE.Vector3(1, 0, 0),
    ry: new THREE.Vector3(0, 1, 0),
    rz: new THREE.Vector3(0, 0, 1),
  }

  function _ooStepAxis(axis, deg) {
    const q = new THREE.Quaternion().setFromAxisAngle(_ooAxisVecs[axis], THREE.MathUtils.degToRad(deg))
    _ooPreviewIncrement(q)
  }

  document.getElementById('oo-rx-dec')?.addEventListener('click', () => _ooStepAxis('rx', -45))
  document.getElementById('oo-rx-inc')?.addEventListener('click', () => _ooStepAxis('rx', +45))
  document.getElementById('oo-ry-dec')?.addEventListener('click', () => _ooStepAxis('ry', -45))
  document.getElementById('oo-ry-inc')?.addEventListener('click', () => _ooStepAxis('ry', +45))
  document.getElementById('oo-rz-dec')?.addEventListener('click', () => _ooStepAxis('rz', -45))
  document.getElementById('oo-rz-inc')?.addEventListener('click', () => _ooStepAxis('rz', +45))

  for (const inp of [_ooRxInp, _ooRyInp, _ooRzInp]) {
    inp?.addEventListener('keydown', e => { if (e.key === 'Enter') _ooPreviewFromFields() })
  }

  // ── Overhang gizmo (TransformControls, rotate-only) ─────────────────────────

  // Returns true if this overhang has its own independent helix (no scaffold on that helix).
  // This covers native extrude overhangs AND autodetected stub-helix inline overhangs from
  // imported designs (including helices that once had scaffold but the user deleted it).
  // Split-domain inline overhangs (helix shared with scaffold) return false — their axis
  // cannot be rotated independently.
  function _isExtrudeOverhang(ovhgId, design) {
    const o = design?.overhangs?.find(x => x.id === ovhgId)
    if (!o?.helix_id) return false
    return !design?.strands?.some(
      s => s.strand_type === 'scaffold' && s.domains?.some(d => d.helix_id === o.helix_id)
    )
  }

  // Returns domain ID objects for the overhang's strand — used to filter captureClusterBase
  // and applyClusterTransform so that unselected overhangs sharing the same child helix are
  // not affected by the live preview transform.
  function _ovhgDomainIds(ovhgId, design) {
    const o = design?.overhangs?.find(x => x.id === ovhgId)
    if (!o) return null
    const strand = design?.strands?.find(s => s.id === o.strand_id)
    if (!strand?.domains?.length) return null
    return strand.domains.map((_, i) => ({ strand_id: strand.id, domain_index: i }))
  }

  function _ovhgDomainBpRange(ovhgId, design) {
    const o = design?.overhangs?.find(x => x.id === ovhgId)
    if (!o) return null
    const strand = design?.strands?.find(s => s.id === o.strand_id)
    const d = strand?.domains?.find(d => d.overhang_id === ovhgId)
    if (!d) return null
    return [Math.min(d.start_bp, d.end_bp), Math.max(d.start_bp, d.end_bp)]
  }

  const overhangGizmo = initOverhangGizmo(scene, camera, canvas, controls)
  overhangGizmo.setCallbacks({
    onDragStart: (helixIds) => {
      const { currentDesign } = store.getState()
      const helixCtrl = designRenderer.getHelixCtrl()
      const allDomainIds = _ooActiveIds.flatMap(id => _ovhgDomainIds(id, currentDesign) ?? [])
      helixCtrl?.captureClusterBase(helixIds, allDomainIds.length ? allDomainIds : null)
      const extrudeHelixIds = _ooActiveIds
        .filter(id => _isExtrudeOverhang(id, currentDesign))
        .map(id => currentDesign?.overhangs?.find(x => x.id === id)?.helix_id)
        .filter(Boolean)
      bluntEnds?.captureClusterBase(new Set(_ooActiveIds))
      if (extrudeHelixIds.length) {
        helixCtrl?.captureClusterBase(extrudeHelixIds, null, true, { forceAxes: true })
        overhangLocations?.captureClusterBase(extrudeHelixIds)
      }
    },
    onPreview: (R_delta) => {
      _ooDirtyPreview = true
      const { currentDesign } = store.getState()
      const helixCtrl = designRenderer.getHelixCtrl()
      for (const id of _ooActiveIds) {
        const o = currentDesign?.overhangs?.find(x => x.id === id)
        if (!o) continue
        const pivot = _ooPivotPositions[id]
          ?? new THREE.Vector3(o.pivot[0], o.pivot[1], o.pivot[2])
        const domIds = _ovhgDomainIds(id, currentDesign)
        const isExtrude = _isExtrudeOverhang(id, currentDesign)
        helixCtrl?.applyClusterTransform([o.helix_id], pivot, pivot, R_delta, domIds,
          isExtrude ? { forceAxes: true } : undefined)
        bluntEnds?.applyClusterTransform([id], pivot, pivot, R_delta)
        if (isExtrude) {
          overhangLocations?.applyClusterTransform([o.helix_id], pivot, pivot, R_delta)
        }
      }
      _ooUpdateAngleFields(overhangGizmo.getCurrentRDelta())
    },
    onDragEnd: () => { /* no auto-commit — user presses Apply */ },
  })

  // Close the panel when overhangs are structurally added or removed (not on rotation patch).
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign !== prevState.currentDesign) {
      const oldIds = new Set((prevState.currentDesign?.overhangs ?? []).map(o => o.id))
      const newIds = new Set((newState.currentDesign?.overhangs ?? []).map(o => o.id))
      const setsChanged = oldIds.size !== newIds.size || [...oldIds].some(id => !newIds.has(id))
      if (setsChanged && _ooActiveIds.length) _ooClose()
    }
  })

  // ── Move/Rotate right-sidebar panel ──────────────────────────────────────────
  const _mrPanel         = document.getElementById('move-rotate-panel')
  const _mrClusterSel    = document.getElementById('mr-cluster-sel')
  const _mrTxInp         = document.getElementById('mr-tx')
  const _mrTyInp         = document.getElementById('mr-ty')
  const _mrTzInp         = document.getElementById('mr-tz')
  const _mrRxInp         = document.getElementById('mr-rx')
  const _mrRyInp         = document.getElementById('mr-ry')
  const _mrRzInp         = document.getElementById('mr-rz')
  const _mrJaInp         = document.getElementById('mr-ja')
  const _mrPivotSel      = document.getElementById('mr-pivot-sel')
  const _mrRotSection    = document.getElementById('mr-rotation-section')
  const _mrJaSection     = document.getElementById('mr-joint-angle-section')
  let   _mrPivotIsJoint  = false
  let   _mrAssemblyCtx   = null

  function _mrShowJointMode(on) {
    _mrPivotIsJoint = on
    if (_mrRotSection) _mrRotSection.style.display = on ? 'none' : ''
    if (_mrJaSection)  _mrJaSection.style.display  = on ? '' : 'none'
  }

  function _mrSetTransformValues(tx, ty, tz, rx, ry, rz) {
    if (_mrTxInp && document.activeElement !== _mrTxInp) _mrTxInp.value = tx.toFixed(3)
    if (_mrTyInp && document.activeElement !== _mrTyInp) _mrTyInp.value = ty.toFixed(3)
    if (_mrTzInp && document.activeElement !== _mrTzInp) _mrTzInp.value = tz.toFixed(3)
    if (_mrRxInp && document.activeElement !== _mrRxInp) _mrRxInp.value = rx.toFixed(3)
    if (_mrRyInp && document.activeElement !== _mrRyInp) _mrRyInp.value = ry.toFixed(3)
    if (_mrRzInp && document.activeElement !== _mrRzInp) _mrRzInp.value = rz.toFixed(3)
  }

  function _mrSetTransformValuesFromMatrix(matrix4) {
    if (!matrix4) return
    const pos = new THREE.Vector3()
    const quat = new THREE.Quaternion()
    const scale = new THREE.Vector3()
    matrix4.decompose(pos, quat, scale)
    const [rx, ry, rz] = _quatToEulerDeg([quat.x, quat.y, quat.z, quat.w])
    _mrSetTransformValues(pos.x, pos.y, pos.z, rx, ry, rz)
  }

  function _mrSetJointAngle(deg) {
    if (_mrJaInp && document.activeElement !== _mrJaInp) _mrJaInp.value = deg.toFixed(1)
  }

  function _mrSetPivotOptions(joints) {
    if (!_mrPivotSel) return
    while (_mrPivotSel.options.length > 1) _mrPivotSel.remove(1)
    for (const j of (joints ?? [])) {
      const opt = document.createElement('option')
      opt.value = j.id
      opt.textContent = `Joint: ${j.name}`
      _mrPivotSel.appendChild(opt)
    }
  }

  function _mrSetSelectedPivot(id) {
    if (_mrPivotSel) _mrPivotSel.value = id ?? 'centroid'
    _mrShowJointMode(id !== 'centroid' && id != null)
  }

  function _mrSetClusterOptions(clusters, selectedId) {
    if (!_mrClusterSel) return
    _mrClusterSel.innerHTML = ''
    for (const c of clusters) {
      const opt = document.createElement('option')
      opt.value = c.id
      opt.textContent = c.name
      _mrClusterSel.appendChild(opt)
    }
    _mrClusterSel.value = selectedId ?? clusters[clusters.length - 1]?.id ?? ''
  }

  function _mrSyncClusterDropdown(clusterId) {
    if (_mrClusterSel) _mrClusterSel.value = clusterId
  }

  function _mrCommitInputs() {
    if (store.getState().assemblyActive) {
      if (!_mrAssemblyCtx) return
      const tx = parseFloat(_mrTxInp?.value) || 0
      const ty = parseFloat(_mrTyInp?.value) || 0
      const tz = parseFloat(_mrTzInp?.value) || 0
      const rx = parseFloat(_mrRxInp?.value) || 0
      const ry = parseFloat(_mrRyInp?.value) || 0
      const rz = parseFloat(_mrRzInp?.value) || 0
      const q = _eulerDegToQuat(rx, ry, rz)
      const mat = new THREE.Matrix4().compose(
        new THREE.Vector3(tx, ty, tz),
        new THREE.Quaternion(q[0], q[1], q[2], q[3]),
        new THREE.Vector3(1, 1, 1),
      )
      _applyAssemblyPrimaryLive(_mrAssemblyCtx, mat)
      instanceGizmo.setMatrix(mat)
      _queueAssemblyPrimaryCommit(_mrAssemblyCtx, mat)
      return
    }
    if (_mrPivotIsJoint) {
      if (!clusterGizmo.isActive()) return
      const joint = clusterGizmo.getActiveJoint()
      if (!joint) return
      const deg = parseFloat(_mrJaInp?.value)
      if (!isNaN(deg)) clusterGizmo.setJointRotation(joint, deg)
      return
    }
    if (!clusterGizmo.isActive()) return
    const tx = parseFloat(_mrTxInp?.value) || 0
    const ty = parseFloat(_mrTyInp?.value) || 0
    const tz = parseFloat(_mrTzInp?.value) || 0
    const rx = parseFloat(_mrRxInp?.value) || 0
    const ry = parseFloat(_mrRyInp?.value) || 0
    const rz = parseFloat(_mrRzInp?.value) || 0
    clusterGizmo.setTransform([tx, ty, tz], _eulerDegToQuat(rx, ry, rz))
  }

  // Wire translation/rotation text inputs
  for (const inp of [_mrTxInp, _mrTyInp, _mrTzInp, _mrRxInp, _mrRyInp, _mrRzInp].filter(Boolean)) {
    inp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); inp.blur(); _mrCommitInputs() } })
    inp.addEventListener('change', _mrCommitInputs)
  }
  if (_mrJaInp) {
    _mrJaInp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); _mrJaInp.blur(); _mrCommitInputs() } })
    _mrJaInp.addEventListener('change', _mrCommitInputs)
  }

  // Pivot dropdown change
  _mrPivotSel?.addEventListener('change', () => {
    const val = _mrPivotSel.value
    if (val === 'centroid') {
      _mrShowJointMode(false)
      clusterGizmo.setConstraint('centroid', null)
    } else {
      const joint = store.getState().currentDesign?.cluster_joints?.find(j => j.id === val)
      if (joint) { _mrShowJointMode(true); clusterGizmo.setConstraint('joint', joint) }
    }
  })

  function _vecClose(a = [], b = [], eps = 1e-6) {
    return a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= eps)
  }

  async function _refreshClusterPivotForAttach(clusterId) {
    if (clusterGizmo.hasPendingTransform?.(clusterId)) return
    const { currentDesign } = store.getState()
    const backboneEntries = designRenderer.getBackboneEntries?.() ?? []
    if (!backboneEntries.length) return
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === clusterId)
    if (!cluster) return

    const pivot = computeClusterPivotFromEntries(cluster, currentDesign, backboneEntries)
    if (!pivot.every(Number.isFinite)) return

    const translation = rebaseClusterTranslationForPivot(cluster, pivot)
    if (_vecClose(cluster.pivot, pivot) && _vecClose(cluster.translation, translation)) return

    clusterGizmo.setPendingTransform(clusterId, {
      pivot,
      translation,
      rotation: cluster.rotation,
    })
  }

  // Cluster dropdown change — switch gizmo to chosen cluster
  _mrClusterSel?.addEventListener('change', async () => {
    const clusterId = _mrClusterSel.value
    if (!clusterId || !_translateRotateActive) return
    if (clusterId === store.getState().activeClusterId) return
    await _refreshClusterPivotForAttach(clusterId)
    clusterGizmo.attach(clusterId, scene, camera, canvas)
  })

  const instanceGizmo = initInstanceGizmo(store, controls)
  const assemblyJointRenderer = initAssemblyJointRenderer(scene, camera, canvas, store, api, controls)

  // Sync blunt-end connectors into the assembly joint renderer when:
  //   • assembly mode is active AND toolFilters.bluntEnds is ON → pass blunt ends
  //   • otherwise → clear them
  // Called after assemblyRenderer.rebuild() resolves (cache is populated) and when
  // the toolFilter toggle changes.
  function _syncAssemblyBluntEnds() {
    if (!store.getState().assemblyActive) {
      assemblyJointRenderer.setExtraConnectors([])
      return
    }
    const bluntEnds = store.getState().toolFilters?.bluntEnds
      ? assemblyRenderer.getInstanceBluntEnds()
      : []
    assemblyJointRenderer.setExtraConnectors(bluntEnds)
  }

  // Re-sync when the blunt-end tool-filter toggle changes while in assembly mode
  store.subscribe((newState, prevState) => {
    if (!newState.assemblyActive) return
    if (newState.toolFilters?.bluntEnds !== prevState.toolFilters?.bluntEnds) {
      _syncAssemblyBluntEnds()
    }
  })

  function _canvasNdc(e) {
    const r = canvas.getBoundingClientRect()
    return {
      x:  ((e.clientX - r.left) / r.width)  * 2 - 1,
      y: -((e.clientY - r.top)  / r.height) * 2 + 1,
    }
  }

  function _clusterBackboneEntries(cluster, design, backboneEntries = null) {
    backboneEntries ??= designRenderer.getBackboneEntries?.() ?? []
    if (!cluster?.helix_ids?.length || !backboneEntries.length) return []

    if (cluster.domain_ids?.length) {
      // Mixed cluster: domain bridge entries plus full exclusive helices. This
      // mirrors the active-cluster glow so picking matches the highlighted body.
      const domainKeySet = new Set(cluster.domain_ids.map(d => `${d.strand_id}:${d.domain_index}`))
      const strands = design?.strands ?? []
      const strandMap = new Map(strands.map(s => [s.id, s]))
      const bridgeHelixIds = new Set()
      for (const dr of cluster.domain_ids) {
        const dom = strandMap.get(dr.strand_id)?.domains?.[dr.domain_index]
        if (dom) bridgeHelixIds.add(dom.helix_id)
      }
      const exclusiveHelixSet = new Set(cluster.helix_ids.filter(hid => !bridgeHelixIds.has(hid)))
      return backboneEntries.filter(entry =>
        domainKeySet.has(`${entry.nuc.strand_id}:${entry.nuc.domain_index}`) ||
        exclusiveHelixSet.has(entry.nuc.helix_id))
    }

    const helixSet = new Set(cluster.helix_ids)
    return backboneEntries.filter(entry => helixSet.has(entry.nuc.helix_id))
  }

  const _clusterPickRaycaster = new THREE.Raycaster()
  const _clusterPickNdc = new THREE.Vector2()

  function _pickActiveClusterEntry(e) {
    const { activeClusterId, currentDesign } = store.getState()
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === activeClusterId)
    if (!cluster) return null

    const entries = _clusterBackboneEntries(cluster, currentDesign)
    if (!entries.length) return null

    const idsByMesh = new Map()
    for (const entry of entries) {
      if (!entry.instMesh) continue
      let ids = idsByMesh.get(entry.instMesh)
      if (!ids) {
        ids = new Set()
        idsByMesh.set(entry.instMesh, ids)
      }
      ids.add(entry.id)
    }
    const meshes = [...idsByMesh.keys()].filter(mesh => mesh?.visible !== false)
    if (!meshes.length) return null

    const ndc = _canvasNdc(e)
    _clusterPickNdc.set(ndc.x, ndc.y)
    _clusterPickRaycaster.setFromCamera(_clusterPickNdc, camera)

    const hits = _clusterPickRaycaster.intersectObjects(meshes, false)
    for (const hit of hits) {
      if (idsByMesh.get(hit.object)?.has(hit.instanceId)) {
        return entries.find(entry => entry.instMesh === hit.object && entry.id === hit.instanceId) ?? null
      }
    }
    return null
  }

  const assemblyContextMenu = initAssemblyContextMenu({
    api,
    onMoveRotate: _activateTranslateRotateTool,
    onDefineConnector: (id) => assemblyJointRenderer.enterConnectorDefineMode(id, () => {}),
  })

  function _defineAssemblyConnector(instanceId = store.getState().activeInstanceId) {
    if (!instanceId) return
    assemblyJointRenderer.enterConnectorDefineMode(instanceId, () => {})
  }

  function _defineAssemblyMate() {
    _syncAssemblyBluntEnds()
    assemblyJointRenderer.enterMateDefineMode(
      () => {},
      (id, mat) => assemblyRenderer.setLiveTransform(id, mat),
    )
  }

  // Cyan glow layer for active-cluster highlight (distinct from the green selection glow).
  const clusterGlowLayer = createGlowLayer(scene, 0x58a6ff)
  let _translateRotateActive = false
  let _clusterDirty         = false   // true once any local transform changes during the active tool session

  // ── Joint arrow pick handler (translate/rotate tool only) ───────────────────

  async function _onToolPickPointerDown(e) {
    if (e.button != null && e.button !== 0) return

    // Check for a drag start on a joint rotation ring (pointerdown, not click,
    // so setPointerCapture works correctly).
    const ringJointId = jointRenderer.pickJointRing(e)
    if (!ringJointId) {
      if (!clusterGizmo.isJointConstraintActive?.()) return
      const joint = clusterGizmo.getActiveJoint?.()
      if (!joint || !_pickActiveClusterEntry(e)) return
      e.stopImmediatePropagation()
      clusterGizmo.beginConstrainedRotation(joint, e)
      return
    }
    const design = store.getState().currentDesign
    const joint  = design?.cluster_joints?.find(j => j.id === ringJointId)
    if (!joint) return

    // Ensure the joint's cluster is the active one before starting the drag.
    const { activeClusterId, currentDesign: cd } = store.getState()
    if (joint.cluster_id !== activeClusterId) {
      const cluster = cd?.cluster_transforms?.find(c => c.id === joint.cluster_id)
      if (!cluster) {
        // Cluster not ready — just switch cluster; user can drag on next pointerdown.
        store.setState({ activeClusterId: joint.cluster_id })
        return
      }
      await _refreshClusterPivotForAttach(joint.cluster_id)
      clusterGizmo.attach(joint.cluster_id, scene, camera, canvas)
    }

    _mrSetSelectedPivot(ringJointId)
    clusterGizmo.beginConstrainedRotation(joint, e)
  }

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

  async function _activateTranslateRotateTool(targetClusterId = null) {
    const { assemblyActive, activeInstanceId, currentDesign } = store.getState()

    // ── Assembly mode: attach instance gizmo ────────────────────────────────
    if (assemblyActive) {
      if (!activeInstanceId) {
        alert('Select an instance first by clicking it in the viewport or its row in the Assembly panel.')
        return
      }
      const _instForGizmo = store.getState().currentAssembly?.instances?.find(i => i.id === activeInstanceId)
      if (_instForGizmo?.fixed) {
        alert('This part is marked as Fixed and cannot be moved. Uncheck Fixed in the right-click menu to enable movement.')
        return
      }
      const ctx = _createAssemblyTransformContext(activeInstanceId)
      if (!ctx) return
      _mrAssemblyCtx = ctx
      _translateRotateActive = true
      store.setState({ translateRotateActive: true })
      document.getElementById('mode-indicator').textContent = 'MOVE — Tab: move/rotate · ✓: confirm · Esc: exit'
      _attachGroupGizmo(activeInstanceId, ctx)
      _mrSetClusterOptions([{ id: activeInstanceId, name: _instForGizmo?.name ?? 'Selected part' }], activeInstanceId)
      if (_mrClusterSel) _mrClusterSel.disabled = true
      if (_mrPivotSel) _mrPivotSel.disabled = true
      _mrSetPivotOptions([])
      _mrSetSelectedPivot('centroid')
      _mrSetTransformValuesFromMatrix(ctx.primaryStart)
      if (_mrPanel) _mrPanel.style.display = ''
      _confirmBtn.style.display = 'flex'
      return
    }

    // ── Design mode: attach cluster gizmo ───────────────────────────────────
    const clusters = currentDesign?.cluster_transforms ?? []
    if (!clusters.length) {
      alert('No movable clusters exist. Create a cluster first by multi-selecting strands, then using the Movable Clusters panel.')
      return
    }
    _clusterDirty         = false
    _translateRotateActive = true
    store.setState({ translateRotateActive: true })
    document.getElementById('mode-indicator').textContent = 'MOVE/ROTATE — Esc: cancel'

    // Attach gizmo to the target cluster (from Rotate button), the active cluster, or the last cluster.
    const { activeClusterId } = store.getState()
    const first = (targetClusterId && clusters.find(c => c.id === targetClusterId))
      ?? (activeClusterId && clusters.find(c => c.id === activeClusterId))
      ?? clusters[clusters.length - 1]
    await _refreshClusterPivotForAttach(first.id)
    clusterGizmo.attach(first.id, scene, camera, canvas)

    canvas.addEventListener('pointerdown', _onToolPickPointerDown)

    // Populate and show the right-sidebar move/rotate panel
    _mrAssemblyCtx = null
    if (_mrClusterSel) _mrClusterSel.disabled = false
    if (_mrPivotSel) _mrPivotSel.disabled = false
    _mrSetClusterOptions(clusters, first.id)
    const initJoints = store.getState().currentDesign?.cluster_joints?.filter(j => j.cluster_id === first.id) ?? []
    _mrSetPivotOptions(initJoints)
    _mrSetSelectedPivot('centroid')
    const [irx, iry, irz] = _quatToEulerDeg(first.rotation)
    _mrSetTransformValues(first.translation[0], first.translation[1], first.translation[2], irx, iry, irz)
    if (_mrPanel) _mrPanel.style.display = ''
  }

  // Activate (or switch) the move/rotate tool targeting a specific joint's cluster and axis.
  async function _rotateJoint(joint) {
    const { currentDesign } = store.getState()
    const clusters = currentDesign?.cluster_transforms ?? []

    if (!_translateRotateActive) {
      await _activateTranslateRotateTool(joint.cluster_id)
    } else if (joint.cluster_id !== store.getState().activeClusterId) {
      // Tool already active but pointing at a different cluster — switch it.
      await _refreshClusterPivotForAttach(joint.cluster_id)
      clusterGizmo.attach(joint.cluster_id, scene, camera, canvas)
      _mrSetClusterOptions(clusters, joint.cluster_id)
      const joints = currentDesign?.cluster_joints?.filter(j => j.cluster_id === joint.cluster_id) ?? []
      _mrSetPivotOptions(joints)
    }

    // Point the gizmo at this joint — overrides whatever centroid default was just set.
    _mrSetSelectedPivot(joint.id)
    clusterGizmo.setConstraint('joint', joint)
  }

  function _removeToolPickListeners() {
    canvas.removeEventListener('pointerdown', _onToolPickPointerDown)
  }

  /**
   * Fast-path renderer update for an undo/redo whose only delta is cluster
   * transforms (signaled by `diff_kind: 'cluster_only'` in the response).
   * Mirrors the cluster-commit Plan B optimisation: avoids the backend full
   * geometry recompute and the design_renderer scene rebuild by composing
   * the existing applyClusterTransform pipeline (which the live-drag and
   * Apply path also use). For each changed cluster, snapshots the current
   * visual state, then applies a delta `(R_new * R_old⁻¹, oldOrigin → newOrigin)`
   * on top — landing each affected mesh at the post-undo/redo position.
   *
   * Backend's `_diff_is_cluster_only` requires pivot to be unchanged across
   * the diff, so the math reduces to a single applyClusterTransform call
   * per cluster (no straight-position resolve needed).
   */
  async function _applyClusterUndoRedoDeltas(clusterDiffs) {
    if (!Array.isArray(clusterDiffs) || !clusterDiffs.length) return
    const helixCtrl = designRenderer.getHelixCtrl()
    if (!helixCtrl) return
    const clusterIds = clusterDiffs.map(d => d.cluster_id).filter(Boolean)
    const allHelixIds = new Set()
    let anyAxisRebake = false
    for (const d of clusterDiffs) {
      const helixIds = d.helix_ids ?? []
      if (!helixIds.length) continue
      for (const hid of helixIds) allHelixIds.add(hid)
      const oldQ = new THREE.Quaternion(
        d.old_rotation[0], d.old_rotation[1], d.old_rotation[2], d.old_rotation[3])
      const newQ = new THREE.Quaternion(
        d.new_rotation[0], d.new_rotation[1], d.new_rotation[2], d.new_rotation[3])
      const deltaQ = newQ.clone().multiply(oldQ.clone().invert())
      const oldOrigin = new THREE.Vector3(
        d.old_pivot[0] + d.old_translation[0],
        d.old_pivot[1] + d.old_translation[1],
        d.old_pivot[2] + d.old_translation[2])
      const newOrigin = new THREE.Vector3(
        d.new_pivot[0] + d.new_translation[0],
        d.new_pivot[1] + d.new_translation[1],
        d.new_pivot[2] + d.new_translation[2])
      // Snapshot current visual state as the base for the delta transform.
      // NOTE: jointRenderer and overhangLocations are intentionally omitted
      // here — they auto-rebuild via dedicated subscribers when their
      // backing fields change in currentDesign, which fired synchronously
      // during the preceding _syncClusterOnlyDiff setState. Calling
      // applyClusterTransform on top would double-apply the delta on
      // already-positioned meshes, putting joints/overhangs at the wrong
      // location. Same applies to overhangLinkArcs (rebuilt below).
      helixCtrl.captureClusterBase(helixIds, null)
      bluntEnds?.captureClusterBase?.(helixIds)
      // Apply: world = R_delta * (current - oldOrigin) + newOrigin.
      helixCtrl.applyClusterTransform(helixIds, oldOrigin, newOrigin, deltaQ, null)
      bluntEnds?.applyClusterTransform?.(helixIds, oldOrigin, newOrigin, deltaQ)
      unfoldView?.applyClusterArcUpdate?.(helixIds)
      unfoldView?.applyClusterExtArcUpdate?.(helixIds)
      designRenderer.applyClusterCrossoverUpdate(helixIds)
      // Rebake currentHelixAxes for these helices so jointRenderer.rebuildHulls
      // (called below) reads post-delta axes when constructing the hull prism.
      // Sub-cluster (domain_ids) moves don't rigidly transform the helix —
      // skip the rebake there. cluster_diffs doesn't include domain_ids, so
      // look them up on the live design.
      const liveCt = store.getState().currentDesign?.cluster_transforms?.find(c => c.id === d.cluster_id)
      if (!liveCt?.domain_ids?.length) {
        _rebakeHelixAxesForClusterDelta(
          helixIds,
          { pivot: d.old_pivot, translation: d.old_translation, rotation: d.old_rotation },
          { pivot: d.new_pivot, translation: d.new_translation, rotation: d.new_rotation },
        )
        anyAxisRebake = true
      }
    }
    // Sync currentGeometry's nuc.backbone_position / base_normal in-place
    // so downstream consumers see the post-undo/redo positions.
    if (allHelixIds.size) {
      helixCtrl.commitClusterPositions([...allHelixIds])
      if (anyAxisRebake) jointRenderer.rebuildHulls(store.getState().currentDesign)
      // Re-emit ds-linker bridge nucs (Plan B doesn't refresh geometry on
      // undo/redo, so bridge midpoints would otherwise stay frozen at the
      // pre-undo anchor positions).
      try {
        const bridgeNucs = await api.refreshBridges(clusterIds)
        if (bridgeNucs.length) helixCtrl.applyBridgeNucsUpdate(bridgeNucs)
      } catch (e) {
        console.warn('[refreshBridges] failed:', e)
      }
      // Refresh overlays whose subscribers fired during the lean store
      // update (with currentGeometry's nuc.backbone_position still stale)
      // — same as the cluster-commit reconciliation in _confirmTranslateRotateTool.
      const s = store.getState()
      const cd = s.currentDesign
      const cg = s.currentGeometry
      const ca = s.currentHelixAxes
      if (cd && cg) {
        overhangLinkArcs?.rebuild?.(cd, cg)
        if (overhangLocations?.isVisible?.()) overhangLocations.rebuild(cd, cg)
        if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
        if (linkerAnchorDebug?.isVisible?.()) linkerAnchorDebug.rebuild()
        if (unligatedCrossoverMarkers) unligatedCrossoverMarkers.rebuild(cd, cg, s.unligatedCrossoverIds)
      }
    }
  }

  /** Apply a positions_only diff to the renderer: walk the per-helix
   * positions arrays into helix_renderer.applyPositionsUpdate, then refresh
   * overlays the same way the cluster-commit reconciliation does. The
   * store has already mutated currentGeometry / currentHelixAxes in place
   * (see _syncPositionsOnlyDiff in client.js), so design_renderer's
   * visual-only-design-change check returns early — no rebuild. */
  function _applyPositionsOnlyDiff(json) {
    const helixCtrl = designRenderer.getHelixCtrl()
    if (!helixCtrl) return
    helixCtrl.applyPositionsUpdate(json.positions_by_helix, json.helix_axes)
    // Cross-helix arcs (unfold_view's _arcGroup) and crossover extra-base
    // beads pull from helixCtrl.getNucLivePos() via applyClusterArcUpdate /
    // applyClusterCrossoverUpdate. Live drag refreshes these per frame; for
    // a seek we have to invoke them once with every potentially-affected
    // helix. Topology is unchanged so design.helices covers every real helix
    // (extension and __lnk__ ones inherit through the cluster-arc helpers).
    const s = store.getState()
    const cd = s.currentDesign
    const cg = s.currentGeometry
    const ca = s.currentHelixAxes
    const allHelixIds = (cd?.helices ?? []).map(h => h.id)
    if (allHelixIds.length) {
      unfoldView?.applyClusterArcUpdate?.(allHelixIds)
      unfoldView?.applyClusterExtArcUpdate?.(allHelixIds)
      designRenderer.applyClusterCrossoverUpdate(allHelixIds)
    }
    // Overlays that derive positions from currentDesign + currentGeometry
    // need a refresh now that backbone_position has shifted.
    if (cd && cg) {
      overhangLinkArcs?.rebuild?.(cd, cg)
      if (overhangLocations?.isVisible?.()) overhangLocations.rebuild(cd, cg)
      if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
      if (linkerAnchorDebug?.isVisible?.()) linkerAnchorDebug.rebuild()
      if (unligatedCrossoverMarkers) unligatedCrossoverMarkers.rebuild(cd, cg, s.unligatedCrossoverIds)
    }
  }

  /** Apply whichever delta path the response signals — registered with
   * api.registerResponseDeltaHandler so EVERY client.js endpoint that goes
   * through _syncClusterOnlyDiff / _syncPositionsOnlyDiff (undo, redo, seek,
   * delete-feature, edit-feature, relaxLinker, …) gets the in-place renderer
   * update for free, without per-endpoint main.js wrappers. */
  async function _applyResponseDelta(result) {
    if (result?.diff_kind === 'cluster_only') {
      await _applyClusterUndoRedoDeltas(result.cluster_diffs)
    } else if (result?.diff_kind === 'positions_only') {
      _applyPositionsOnlyDiff(result)
    }
    return result
  }
  api.registerResponseDeltaHandler(_applyResponseDelta)

  // The wrappers below remain for callers that need to await full completion
  // (e.g. the slider toast lifecycle waits for the full chain). Since the
  // delta is now applied inside the client.js _sync* helpers, these are
  // thin pass-throughs.
  async function _seekFeaturesWithDelta(position, subPosition = null) {
    return api.seekFeatures(position, subPosition)
  }

  async function _deleteFeatureWithDelta(index) {
    return api.deleteFeature(index)
  }

  /** Rebake `currentHelixAxes` for `helixIds` so its baked-in cluster transform
   *  matches `newCt` instead of `oldCt`. Plan B's commit/edit path keeps
   *  currentHelixAxes stale (skipGeometry: true), but downstream consumers that
   *  rebuild geometry from helix_axes (notably jointRenderer.rebuildHulls) need
   *  fresh axes to place the hull prism correctly. We apply the inverse of the
   *  old transform then the new one to each axis point, in place — keeping the
   *  outer object reference stable so subscribers that gate on identity don't
   *  fire spurious rebuilds. */
  function _rebakeHelixAxesForClusterDelta(helixIds, oldCt, newCt) {
    const { currentHelixAxes } = store.getState()
    if (!currentHelixAxes || !helixIds?.length || !oldCt || !newCt) return
    const pOld = new THREE.Vector3(...oldCt.pivot)
    const tOld = new THREE.Vector3(...oldCt.translation)
    const rOldInv = new THREE.Quaternion(...oldCt.rotation).invert()
    const pNew = new THREE.Vector3(...newCt.pivot)
    const tNew = new THREE.Vector3(...newCt.translation)
    const rNew = new THREE.Quaternion(...newCt.rotation)
    const _tmp = new THREE.Vector3()
    const xform = (p) => {
      _tmp.set(p[0], p[1], p[2]).sub(pOld).sub(tOld).applyQuaternion(rOldInv).add(pOld)
      _tmp.sub(pNew).applyQuaternion(rNew).add(pNew).add(tNew)
      return [_tmp.x, _tmp.y, _tmp.z]
    }
    const xformDir = (d) => {
      _tmp.set(d[0], d[1], d[2]).applyQuaternion(rOldInv).applyQuaternion(rNew)
      return [_tmp.x, _tmp.y, _tmp.z]
    }
    for (const hid of helixIds) {
      const ax = currentHelixAxes[hid]
      if (!ax) continue
      if (ax.start) ax.start = xform(ax.start)
      if (ax.end)   ax.end   = xform(ax.end)
      if (Array.isArray(ax.samples)) ax.samples = ax.samples.map(xform)
      if (Array.isArray(ax.segments)) {
        ax.segments = ax.segments.map(seg => ({
          ...seg,
          start: seg.start ? xform(seg.start) : seg.start,
          end:   seg.end   ? xform(seg.end)   : seg.end,
        }))
      }
      if (ax.ovhgAxes && typeof ax.ovhgAxes === 'object') {
        for (const ohId of Object.keys(ax.ovhgAxes)) {
          const oa = ax.ovhgAxes[ohId]
          if (!oa) continue
          if (oa.start) oa.start = xform(oa.start)
          if (oa.end)   oa.end   = xform(oa.end)
          if (Array.isArray(oa.samples)) oa.samples = oa.samples.map(xform)
          if (oa.direction) oa.direction = xformDir(oa.direction)
        }
      }
    }
  }

  async function _restoreTransformPreviewFromStore() {
    const { currentDesign, currentGeometry, currentHelixAxes } = store.getState()
    if (!currentGeometry) return

    // Force local renderers back to the committed store geometry. Dragging only
    // mutates scene objects and pending gizmo state, so no backend undo is needed.
    store.setState({
      currentGeometry: [...currentGeometry],
      currentHelixAxes: currentHelixAxes ? { ...currentHelixAxes } : currentHelixAxes,
      lastPartialChangedHelixIds: null,
    })
    jointRenderer.rebuild(currentDesign)
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
  }

  async function _confirmTranslateRotateTool() {
    if (!_translateRotateActive) return
    _translateRotateActive = false
    store.setState({ translateRotateActive: false })
    _confirmBtn.style.display = 'none'
    if (_mrPanel) _mrPanel.style.display = 'none'

    if (store.getState().assemblyActive) {
      instanceGizmo.detach()
      if (_hasAssemblyPending()) {
        _showProgress('Updating Assembly', 'Applying part transform…', { indeterminate: true })
        try {
          await _commitAssemblyPending()
        } finally {
          _hideProgress()
        }
      }
      _mrAssemblyCtx = null
      if (_mrPanel) _mrPanel.style.display = 'none'
      document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
      return
    }

    // Edit-in-place for cluster_op feature_log entries: instead of letting
    // commitPendingTransforms append a new ClusterOpLogEntry, route the
    // pending transform for the edited cluster through api.editFeature so
    // the existing entry's translation/rotation/pivot are updated in place.
    //
    // Important: the gizmo's live drag has ALREADY painted the new positions
    // into the renderer (Plan B's whole point). The editFeature response
    // identifies a cluster_only diff (old → new transform), but applying
    // that delta here would double-move the cluster — the visual is already
    // at "new". We mirror the standard cluster-commit post-processing
    // (commitClusterPositions, refreshBridges, overlay rebuilds) instead of
    // calling _applyResponseDelta.
    const editCtx = _editContext
    if (_clusterDirty && editCtx?.editingFeatureType === 'cluster_op') {
      _editContext = null
      _showProgress('Applying Change', 'Updating transformed geometry…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        const pending = clusterGizmo.getPendingTransform(editCtx.clusterId)
        if (pending) {
          // Snapshot pre-edit transform so we can rebake helix axes after
          // commit (matches the standard commit path).
          const preDesign = store.getState().currentDesign
          const preCt = preDesign?.cluster_transforms?.find(c => c.id === editCtx.clusterId)
          const oldCt = preCt ? {
            pivot:       [...preCt.pivot],
            translation: [...preCt.translation],
            rotation:    [...preCt.rotation],
            helix_ids:   [...(preCt.helix_ids ?? [])],
          } : null
          // The gizmo's live drag has already moved beads/joints/hulls to
          // the post-edit state. Ask the client.js layer NOT to apply the
          // cluster_only delta this response will carry — applying it on
          // top of the gizmo's already-applied transform would double-move
          // the cluster.
          api.skipNextResponseDelta()
          await api.editFeature(editCtx.featureIndex, pending)
          clusterGizmo.clearPendingTransform(editCtx.clusterId)

          const helixCtrl = designRenderer.getHelixCtrl()
          if (helixCtrl) {
            const design = store.getState().currentDesign
            const ct = design?.cluster_transforms?.find(c => c.id === editCtx.clusterId)
            const helixIds = ct?.helix_ids ?? []
            if (helixIds.length) {
              helixCtrl.commitClusterPositions(helixIds)
              // Sub-cluster (domain_ids) moves don't rigidly transform the
              // helix, so skip the axis rebake for those.
              if (oldCt && ct && !ct.domain_ids?.length) {
                _rebakeHelixAxesForClusterDelta(oldCt.helix_ids, oldCt, ct)
              }
              jointRenderer.rebuildHulls(store.getState().currentDesign)
              // Same Plan B bridge refresh as the standard commit path.
              try {
                const bridgeNucs = await api.refreshBridges([editCtx.clusterId])
                if (bridgeNucs.length) helixCtrl.applyBridgeNucsUpdate(bridgeNucs)
              } catch (e) {
                console.warn('[refreshBridges] failed:', e)
              }
              // Same overlay refresh as the standard commit path.
              const s = store.getState()
              const cd = s.currentDesign
              const cg = s.currentGeometry
              const ca = s.currentHelixAxes
              if (cd && cg) {
                overhangLinkArcs?.rebuild?.(cd, cg)
                if (overhangLocations?.isVisible?.()) overhangLocations.rebuild(cd, cg)
                if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
                if (linkerAnchorDebug?.isVisible?.()) linkerAnchorDebug.rebuild()
                if (unligatedCrossoverMarkers) unligatedCrossoverMarkers.rebuild(cd, cg, s.unligatedCrossoverIds)
              }
            }
          }
        }
      } finally {
        _hideProgress()
        _clusterDirty = false
        clusterGizmo.detach()
        _removeToolPickListeners()
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      }
      return
    }

    if (_clusterDirty) {
      _showProgress('Applying Change', 'Updating transformed geometry…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        // Snapshot pre-commit cluster_transforms so we can compute the
        // OLD→NEW delta after commit and rebake currentHelixAxes (which
        // Plan B's skipGeometry leaves stale). Without this, hull-prism
        // rebuilds (e.g. on next repr toggle or topology mutation) place
        // the hull at the pre-move position.
        const preDesign = store.getState().currentDesign
        const oldCtById = new Map()
        for (const ct of preDesign?.cluster_transforms ?? []) {
          oldCtById.set(ct.id, {
            pivot:       [...ct.pivot],
            translation: [...ct.translation],
            rotation:    [...ct.rotation],
            helix_ids:   [...(ct.helix_ids ?? [])],
          })
        }
        const { clusterIds } = await clusterGizmo.commitPendingTransforms({ log: true })
        // Plan B: patchCluster no longer refreshes backend geometry. Reconcile
        // currentGeometry with the rendered state for each committed cluster
        // so downstream consumers (oxDNA / atomistic / surface mesh /
        // save-and-reload / undo) see the post-cluster-transform positions.
        if (clusterIds.length) {
          const helixCtrl = designRenderer.getHelixCtrl()
          if (helixCtrl) {
            const design = store.getState().currentDesign
            const allHelixIds = new Set()
            for (const cid of clusterIds) {
              const ct = design?.cluster_transforms?.find(c => c.id === cid)
              if (ct?.helix_ids?.length) {
                for (const hid of ct.helix_ids) allHelixIds.add(hid)
              }
            }
            if (allHelixIds.size) {
              helixCtrl.commitClusterPositions([...allHelixIds])
              // Rebake currentHelixAxes for each moved cluster so any
              // subsequent rebuild from helix_axes (jointRenderer.rebuildHulls,
              // overhang locations, etc.) reads post-commit positions.
              // Skip sub-cluster moves: domain_ids means only PART of the
              // helix was transformed, so its axis isn't rigidly rotatable.
              for (const cid of clusterIds) {
                const oldCt = oldCtById.get(cid)
                const newCt = design?.cluster_transforms?.find(c => c.id === cid)
                if (newCt?.domain_ids?.length) continue
                if (oldCt && newCt) _rebakeHelixAxesForClusterDelta(oldCt.helix_ids, oldCt, newCt)
              }
              // Hull prism: live drag has already moved the outer group
              // rigidly, but rebuilding from the now-fresh axes gives a
              // hull whose orientation also reflects any cluster rotation.
              jointRenderer.rebuildHulls(store.getState().currentDesign)
              // Plan B has no backend geometry refresh, so ds-linker bridge
              // nucs (positions derived from live OH anchors via
              // _emit_bridge_nucs) go stale when one cluster moves. Ask the
              // backend to re-emit just the affected bridges and patch them
              // in-place. Fire-and-forget against rendering: it's a tiny
              // round-trip but we want it before the overlay rebuilds below.
              try {
                const bridgeNucs = await api.refreshBridges(clusterIds)
                if (bridgeNucs.length) helixCtrl.applyBridgeNucsUpdate(bridgeNucs)
              } catch (e) {
                console.warn('[refreshBridges] failed:', e)
              }
              // Refresh overlays whose subscribers fired during patchCluster's
              // setState (with currentGeometry's nuc.backbone_position still
              // stale) and rebuilt themselves at pre-cluster-transform
              // positions. commitClusterPositions has now synced
              // backbone_position in-place, so re-rebuild explicitly here.
              const s = store.getState()
              const cd = s.currentDesign
              const cg = s.currentGeometry
              const ca = s.currentHelixAxes
              if (cd && cg) {
                overhangLinkArcs?.rebuild?.(cd, cg)
                if (overhangLocations?.isVisible?.()) overhangLocations.rebuild(cd, cg)
                if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
                if (linkerAnchorDebug?.isVisible?.()) linkerAnchorDebug.rebuild()
                if (unligatedCrossoverMarkers) unligatedCrossoverMarkers.rebuild(cd, cg, s.unligatedCrossoverIds)
              }
            }
          }
        }
      } finally {
        _hideProgress()
      }
    }
    _clusterDirty = false
    clusterGizmo.detach()
    _removeToolPickListeners()
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  }

  async function _cancelTranslateRotateTool() {
    if (!_translateRotateActive) return
    const hadLocalPreview = _clusterDirty
    _translateRotateActive = false
    store.setState({ translateRotateActive: false })
    _confirmBtn.style.display = 'none'
    if (_mrPanel) _mrPanel.style.display = 'none'
    // Drop any cluster_op edit context so the next gizmo session takes the
    // standard "append a new cluster_op" path.
    if (_editContext?.editingFeatureType === 'cluster_op') _editContext = null

    if (store.getState().assemblyActive) {
      instanceGizmo.detach()
      _assemblyPendingTransforms.clear()
      _assemblyPendingPartJoints.clear()
      _mrAssemblyCtx = null
      if (_mrPanel) _mrPanel.style.display = 'none'
      const assembly = store.getState().currentAssembly
      if (assembly) {
        await assemblyRenderer.rebuild(assembly)
        assemblyRenderer.rebuildLinkers(assembly)
        assemblyJointRenderer.rebuild(assembly)
        _syncAssemblyBluntEnds()
      }
      document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
      return
    }

    _clusterDirty = false
    clusterGizmo.discardPendingTransforms?.()
    clusterGizmo.detach()
    _removeToolPickListeners()
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'

    if (hadLocalPreview) {
      _showProgress('Cancelling Transform', 'Restoring previous geometry…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        await _restoreTransformPreviewFromStore()
      } finally {
        _hideProgress()
      }
    }
  }

  _confirmBtn.addEventListener('click', _confirmTranslateRotateTool)
  document.getElementById('mr-apply-btn')?.addEventListener('click', _confirmTranslateRotateTool)
  document.getElementById('mr-cancel-btn')?.addEventListener('click', _cancelTranslateRotateTool)

  document.getElementById('menu-tools-translate-rotate')?.addEventListener('click', () => {
    _activateTranslateRotateTool()
  })

  registerShortcut({
    key: 't', ctrl: false,
    description: 'Activate move/rotate tool',
    blockedInInput: true,
    handler() {
      if (_translateRotateActive) {
        _confirmTranslateRotateTool()
      } else {
        _activateTranslateRotateTool()
      }
    },
  })

  // ── Joint renderer ────────────────────────────────────────────────────────────
  jointRenderer = initJointRenderer(scene, camera, canvas, store, api)

  // Joint indicators are clickable at any time: clicking one activates the
  // move/rotate tool (if not already active) prepopulated with that joint's
  // cluster + axis, or switches an already-active tool to that joint.
  let _jointSelectPointerDownAt = null
  canvas.addEventListener('pointerdown', e => {
    if (e.button === 0) _jointSelectPointerDownAt = { x: e.clientX, y: e.clientY }
  }, { capture: true })
  canvas.addEventListener('click', async e => {
    if (e.button != null && e.button !== 0) return
    if (!jointRenderer.isVisible()) return
    if (store.getState().assemblyActive) return
    if (_jointSelectPointerDownAt) {
      const dx = e.clientX - _jointSelectPointerDownAt.x
      const dy = e.clientY - _jointSelectPointerDownAt.y
      if (dx * dx + dy * dy > 36) return
    }
    const jointId = jointRenderer.pickJointAny(e)
    if (!jointId) return
    const joint = store.getState().currentDesign?.cluster_joints?.find(j => j.id === jointId)
    if (!joint) return
    e.stopImmediatePropagation()
    await _rotateJoint(joint)
  }, { capture: true })

  // Rebuild joint axis indicators whenever cluster_joints list changes.
  store.subscribe((n, p) => {
    if (n.currentDesign?.cluster_joints === p.currentDesign?.cluster_joints) return
    jointRenderer.rebuild(n.currentDesign)
    // Keep pivot dropdown in sync when joints are added/removed
    if (_translateRotateActive && n.activeClusterId) {
      const joints = n.currentDesign?.cluster_joints?.filter(j => j.cluster_id === n.activeClusterId) ?? []
      _mrSetPivotOptions(joints)
    }
  })

  // Hull prisms depend on currentHelixAxes (which already includes cluster
  // transforms when fresh) and on the set of clusters. Rebuild when either
  // changes — but NOT on every cluster_joints update, because Plan B's
  // skipGeometry path leaves currentHelixAxes stale after a cluster commit
  // and a destructive rebuild would undo the per-frame transform that
  // jointRenderer.applyClusterTransform applies during the gizmo drag.
  store.subscribe((n, p) => {
    const axesChanged = n.currentHelixAxes !== p.currentHelixAxes
    const prevCts = p.currentDesign?.cluster_transforms ?? []
    const newCts  = n.currentDesign?.cluster_transforms ?? []
    let clusterStructChanged = prevCts.length !== newCts.length
    if (!clusterStructChanged) {
      // ID-set change is a structural change too (cluster renamed/replaced).
      for (let i = 0; i < newCts.length; i++) {
        if (prevCts[i]?.id !== newCts[i]?.id) { clusterStructChanged = true; break }
      }
    }
    if (!axesChanged && !clusterStructChanged) return
    jointRenderer.rebuildHulls(n.currentDesign)
  })

  // ── Assembly panel ───────────────────────────────────────────────────────────
  // Part context panel references (initialized later in main.js — captured via closure)
  let _partCameraPanel     = null
  let _partAnimPanel       = null
  let _partFeatureLogPanel = null

  const assemblyPanel = initAssemblyPanel(store, {
    api,
    onInstanceSelect: (id) => store.setState({ activeInstanceId: id }),
    beforePatchDesign: (instanceId) => assemblyRenderer.invalidateInstance(instanceId),
    onDefineConnector: (instanceId) => _defineAssemblyConnector(instanceId),
    onDefineMate: () => _defineAssemblyMate(),
    onPartContextChange: (instanceId, design, patchFn) => {
      if (instanceId && design) {
        _partCameraPanel?.setPartContext(instanceId, design, patchFn)
        _partAnimPanel?.setPartContext(instanceId, design, patchFn)
        if (!store.getState().assemblyActive) _partFeatureLogPanel?.setPartContext(instanceId, design, patchFn)
        clusterPanel?.syncInstanceDesign(instanceId, design)
      } else {
        _partCameraPanel?.clearPartContext()
        _partAnimPanel?.clearPartContext()
        if (!store.getState().assemblyActive) _partFeatureLogPanel?.clearPartContext()
      }
    },
  })

  // ── Library panel (welcome screen) ───────────────────────────────────────────

  async function _openPartFromServer(path, name) {
    _showFileLoad('Opening Part')
    _flAppendLog(`Path: ${path}`)
    try {
      _flSetProgress(0, 'Fetching file…')
      const result = await api.getLibraryFileContent(path)
      if (!result?.content) {
        _flAppendLog('Server returned no content.', 'error')
        _flShowError('Could not load part.')
        return
      }
      _flAppendLog(`File fetched — ${Math.round(result.content.length / 1024)} KB`)
      _flSetProgress(50, 'Importing design…')
      _flAppendLog('Parsing and validating design…')
      _resetForNewDesign()
      const ok = await api.importDesign(result.content)
      if (ok) {
        _flAppendLog('Design imported successfully.', 'success')
        _setFileName(name ?? path)
        _setWorkspacePath(path)
        _hideWelcome()
        workspace.hide()
        _fitToView()
        await _flShowSuccess('Part loaded successfully')
      } else {
        const err = store.getState().lastError
        _flAppendLog(`Import failed: ${err?.message ?? 'unknown error'}`, 'error')
        _flShowError('Failed to import part.')
        _showWelcome()
      }
    } catch (e) {
      _flAppendLog(`Exception: ${e?.message ?? String(e)}`, 'error')
      _flShowError('Could not load part.')
    }
  }

  async function _openAssemblyFromServer(path) {
    _showFileLoad('Opening Assembly')
    _flAppendLog(`Path: ${path}`)
    let _hasInstanceErrors = false
    try {
      _flSetProgress(0, 'Fetching file…')
      const result = await api.getLibraryFileContent(path)
      if (!result?.content) {
        _flAppendLog('Server returned no content.', 'error')
        _flShowError('Could not load assembly.')
        return
      }
      _flAppendLog(`File fetched — ${Math.round(result.content.length / 1024)} KB`)
      _flSetProgress(25, 'Importing assembly…')
      _flAppendLog('Parsing and validating assembly…')
      const ok = await api.importAssembly(result.content)
      if (!ok) {
        const err = store.getState().lastError
        _flAppendLog(`Import failed: ${err?.message ?? 'unknown error'}`, 'error')
        _flShowError('Failed to import assembly.')
        return
      }

      const assembly = store.getState().currentAssembly
      const instances = assembly?.instances ?? []
      const visible   = instances.filter(i => i.visible !== false)
      _flAppendLog(`Assembly parsed — ${visible.length} part${visible.length !== 1 ? 's' : ''}`, 'success')
      _flSetProgress(40, `Loading ${visible.length} part${visible.length !== 1 ? 's' : ''}…`)

      if (visible.length > 0) {
        _flAppendLog('Fetching part geometry…')
        await assemblyRenderer.rebuild(assembly, {
          onProgress: ({ stage, done, total, name, error }) => {
            if (stage === 'fetched') {
              _flAppendLog('Geometry received from server')
              _flSetProgress(55, `Building parts…`)
            } else if (stage === 'fetch_error') {
              _flAppendLog('Geometry fetch failed — trying per-part fallback…', 'warn')
            } else if (stage === 'instance_built') {
              const pct = 55 + Math.round((done / total) * 45)
              _flSetProgress(pct, `Part ${done} / ${total}`)
              _flAppendLog(`  ✓ ${name ?? `Part ${done}`}`, 'success')
            } else if (stage === 'instance_error') {
              const pct = 55 + Math.round((done / total) * 45)
              _flSetProgress(pct, `Part ${done} / ${total}`)
              _flAppendLog(`  ✗ ${name ?? `Part ${done}`}: ${error}`, 'error')
              _hasInstanceErrors = true
            }
          },
        })
      }

      _assemblyName = path.replace(/\.nass$/i, '')
      _assemblyFileHandle = null
      _setAssemblyWorkspacePath(path)

      if (_hasInstanceErrors) {
        _flAppendLog('Assembly loaded with errors.', 'warn')
        _enterAssemblyMode()
        _fitToView()
        _flShowError('Some parts failed to load.')
      } else {
        _flAppendLog('All parts loaded successfully.', 'success')
        _enterAssemblyMode()
        _fitToView()
        await _flShowSuccess('Assembly loaded successfully')
      }
    } catch (e) {
      _flAppendLog(`Exception: ${e?.message ?? String(e)}`, 'error')
      _flShowError('Could not load assembly.')
    }
  }

  function _pickLattice() {
    return new Promise(resolve => {
      const overlay = document.createElement('div')
      overlay.style.cssText = 'position:fixed;inset:0;z-index:9100;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center'
      const box = document.createElement('div')
      box.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:8px;width:280px;padding:20px;font-family:var(--font-ui);display:flex;flex-direction:column;gap:14px'
      box.tabIndex = -1

      const titleEl = document.createElement('div')
      titleEl.textContent = 'Lattice type'
      titleEl.style.cssText = 'color:#c9d1d9;font-size:13px;font-weight:500'

      const optsEl = document.createElement('div')
      optsEl.style.cssText = 'display:flex;flex-direction:column;gap:8px'

      let selected = 'HONEYCOMB'
      const labels = []
      for (const [val, name, desc] of [['HONEYCOMB', 'Honeycomb', 'Standard — 10.5 bp/turn avg'], ['SQUARE', 'Square', 'Square lattice — 10 bp/turn avg']]) {
        const lbl = document.createElement('label')
        lbl.style.cssText = 'display:flex;align-items:flex-start;gap:10px;cursor:pointer;padding:8px 10px;border-radius:5px;border:1px solid ' + (val === 'HONEYCOMB' ? '#388bfd' : '#21262d')
        const radio = document.createElement('input')
        radio.type = 'radio'; radio.name = 'pick-lattice'; radio.value = val; radio.checked = val === 'HONEYCOMB'
        radio.style.marginTop = '2px'
        radio.addEventListener('change', () => {
          selected = val
          labels.forEach((l, i) => { l.style.borderColor = [val === 'HONEYCOMB' ? '#388bfd' : '#21262d', val === 'SQUARE' ? '#388bfd' : '#21262d'][i] })
        })
        const text = document.createElement('div')
        const n = document.createElement('div'); n.textContent = name; n.style.cssText = 'color:#c9d1d9;font-size:12px'
        const d = document.createElement('div'); d.textContent = desc; d.style.cssText = 'color:#484f58;font-size:var(--text-xs);margin-top:2px'
        text.append(n, d); lbl.append(radio, text); optsEl.appendChild(lbl); labels.push(lbl)
      }

      const btnsEl = document.createElement('div')
      btnsEl.style.cssText = 'display:flex;justify-content:flex-end;gap:8px'
      const cancelBtn = document.createElement('button')
      cancelBtn.textContent = 'Cancel'; cancelBtn.style.cssText = 'padding:5px 14px;background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:4px;cursor:pointer;font-family:var(--font-ui);font-size:12px'
      const createBtn = document.createElement('button')
      createBtn.textContent = 'Create'; createBtn.style.cssText = 'padding:5px 14px;background:#1f6feb;border:none;color:#fff;border-radius:4px;cursor:pointer;font-family:var(--font-ui);font-size:12px'
      const done = (v) => { document.body.removeChild(overlay); resolve(v) }
      cancelBtn.addEventListener('click', () => done(null))
      createBtn.addEventListener('click', () => done(selected))
      box.addEventListener('keydown', e => { if (e.key === 'Escape') done(null); if (e.key === 'Enter') done(selected) })
      btnsEl.append(cancelBtn, createBtn)
      box.append(titleEl, optsEl, btnsEl)
      overlay.appendChild(box)
      document.body.appendChild(overlay)
      setTimeout(() => { box.focus() }, 30)
    })
  }

  const libraryPanel = initLibraryPanel({
    api,
    onImportCadnano:  _importCadnanoWithAutodetection,
    onImportScadnano: _importScadnanoWithAutodetection,
    onNewPart: async () => {
      const dest = await openFileBrowser({ title: 'New Part — Choose Location', mode: 'save', fileType: 'part', suggestedName: 'Untitled', suggestedExt: '.nadoc', noOverwrite: true, api })
      if (!dest) return
      const lattice = await _pickLattice()
      if (!lattice) return
      _resetForNewDesign()
      _fileHandle = null
      _setFileName(dest.name)
      _hideWelcome()
      workspace.show(lattice)
      await api.createDesign(dest.name, lattice)
      const wsResult = await api.saveDesignAs(dest.path, false)
      if (wsResult) { _setWorkspacePath(dest.path); libraryPanel?.refresh() }
    },
    onNewAssembly: async () => {
      const dest = await openFileBrowser({ title: 'New Assembly — Choose Location', mode: 'save', fileType: 'assembly', suggestedName: 'Untitled', suggestedExt: '.nass', noOverwrite: true, api })
      if (!dest) return
      const r = await api.createAssembly(dest.name)
      if (!r) return
      _assemblyName = r.assembly?.metadata?.name ?? dest.name
      _assemblyFileHandle = null
      const saveResult = await api.saveAssemblyAs(dest.path, false)
      if (saveResult) _setAssemblyWorkspacePath(dest.path)
      libraryPanel?.refresh()
      _enterAssemblyMode()
    },
    onOpenPart:     (path, name) => _openPartFromServer(path, name),
    onOpenAssembly: (path) => _openAssemblyFromServer(path),
  })

  // Deferred welcome refresh — called here because libraryPanel wasn't available
  // at the session-restore block (lines ~2477) where restoration failure is detected.
  if (window.nadocDebug?.verbose)
    console.log('[restore] libraryPanel ready — _needsWelcomeOnBoot:', _needsWelcomeOnBoot,
      '| assemblyActive:', store.getState().assemblyActive,
      '| persistedMode:', api.getPersistedMode())
  if (_needsWelcomeOnBoot) {
    console.warn('[restore] showing welcome screen (restore failed or no prior session)')
    _showWelcome()
  }

  // ── Sync status badge + debug panel ──────────────────────────────────────────

  const _syncStatusDot  = document.querySelector('#sync-status .sync-dot')
  const _syncStatusText = document.getElementById('sync-status-text')
  const _syncDebugPanel = document.getElementById('sync-debug-panel')
  document.getElementById('sync-debug-close')?.addEventListener('click', () => {
    _syncDebugPanel?.classList.remove('visible')
  })

  function _setSyncStatus(state, label) {
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
    if (_syncStatusDot)  { _syncStatusDot.className = `sync-dot ${state}` }
    if (_syncStatusText) { _syncStatusText.textContent = `${label} ${ts}` }
  }

  function _syncLog(level, tag, msg) {
    const cls = level === 'err' ? 'error' : level === 'warn' ? 'warn' : 'log'
    console[cls](`[SYNC][${tag}] ${msg}`)
    const body = document.getElementById('sync-debug-body')
    if (!body) return
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
    const row  = document.createElement('div');  row.className  = 'sdp-row'
    const tsEl = document.createElement('span'); tsEl.className = 'sdp-ts';         tsEl.textContent = ts
    const tagEl= document.createElement('span'); tagEl.className= `sdp-type ${level==='err'?'err':level==='warn'?'warn':'info'}`; tagEl.textContent = tag
    const msgEl= document.createElement('span'); msgEl.className= 'sdp-msg';        msgEl.textContent = msg
    row.append(tsEl, tagEl, msgEl)
    body.insertBefore(row, body.firstChild)
    while (body.children.length > 150) body.removeChild(body.lastChild)
  }

  window.__nadocSyncDebug = {
    status() {
      return {
        workspacePath:         _workspacePath,
        assemblyWorkspacePath: _assemblyWorkspacePath,
        selfSavedPaths:        [..._selfSavedPaths],
        reloadingFromSSE:      _reloadingFromSSE,
        savingAssembly:        _savingAssembly,
        assemblyActive:        store.getState().assemblyActive,
      }
    },
    forceResync() {
      _syncLog('warn', 'FORCE', 'Manual force resync triggered')
      if (store.getState().assemblyActive) {
        const asm = store.getState().currentAssembly
        ;(asm?.instances ?? []).forEach(i => {
          assemblyRenderer.invalidateInstance(i.id)
          _syncLog('info', 'FORCE', `invalidated instance ${i.id} (${i.name})`)
        })
        assemblyRenderer.rebuild(asm).then(() => assemblyRenderer.rebuildLinkers(asm))
        _setSyncStatus('yellow', 'resyncing…')
      } else {
        api.getDesign().then(() => api.getGeometry())
        _syncLog('info', 'FORCE', 'Re-fetched design+geometry')
      }
    },
    show() { _syncDebugPanel?.classList.add('visible') },
    hide() { _syncDebugPanel?.classList.remove('visible') },
  }

  registerShortcut({
    key: 'd', ctrl: true, shift: true,
    description: 'Toggle sync debug panel',
    handler(e) {
      e.preventDefault()
      _syncDebugPanel?.classList.toggle('visible')
    },
  })

  // ── Auto-save: debounced write-back to workspace files ────────────────────────
  // Loop-prevention flags:
  //   _savingAssembly   — set while saveAssemblyToWorkspace is in-flight so its
  //                       own store update doesn't re-trigger the subscriber
  //   _reloadingFromSSE — set while reloading a design from an SSE event so the
  //                       resulting store update doesn't re-trigger design auto-save
  //   _selfSavedPaths   — paths saved by THIS tab; SSE echoes for these are skipped
  let _savingAssembly   = false
  let _reloadingFromSSE = false
  const _selfSavedPaths = new Set()
  let _designSaveTimer  = null
  let _assemblySaveTimer = null
  let _partSaveTimer = null

  store.subscribeSlice('design', (newState, prevState) => {
    if (_partEditContext) {
      if (newState.currentDesign === prevState.currentDesign) return
      _setSyncStatus('yellow', 'auto-saving…')
      clearTimeout(_partSaveTimer)
      _partSaveTimer = setTimeout(() => {
        _savePartToAssembly({ silent: true })
      }, 900)
      return
    }
    if (!_workspacePath || _reloadingFromSSE) return
    if (newState.currentDesign === prevState.currentDesign) return
    _setSyncStatus('yellow', 'saving…')
    clearTimeout(_designSaveTimer)
    _designSaveTimer = setTimeout(async () => {
      const path = _workspacePath
      if (!path) return
      _syncLog('info', 'SAVE', `design → ${path}`)
      _selfSavedPaths.add(path)
      try {
        await api.saveDesignToWorkspace(path)
        _setSyncStatus('green', 'saved')
        setTimeout(() => _selfSavedPaths.delete(path), 5000)
      } catch (err) {
        _setSyncStatus('red', 'save error')
        _syncLog('err', 'SAVE', `failed: ${err?.message ?? err}`)
        setTimeout(() => _selfSavedPaths.delete(path), 5000)
      }
    }, 1500)
  })

  store.subscribeSlice('assembly', (newState, prevState) => {
    if (!_assemblyWorkspacePath || _savingAssembly) return
    if (newState.currentAssembly === prevState.currentAssembly) return
    _setSyncStatus('yellow', 'saving…')
    clearTimeout(_assemblySaveTimer)
    _assemblySaveTimer = setTimeout(async () => {
      if (!_assemblyWorkspacePath || _savingAssembly) return
      _savingAssembly = true
      try {
        const r = await api.saveAssemblyAs(_assemblyWorkspacePath)
        if (r?.path) _setAssemblyWorkspacePath(r.path)
        _syncLog('info', 'SAVE', `assembly → ${r?.path}`)
        _setSyncStatus('green', 'saved')
      } catch (err) {
        _setSyncStatus('red', 'save error')
        _syncLog('err', 'SAVE', `assembly failed: ${err?.message ?? err}`)
      } finally {
        _savingAssembly = false
      }
    }, 1500)
  })

  // ── Library SSE — live file-change events ────────────────────────────────────
	  function _handleLibraryEvent({ type, path, file_type }) {
    if (type !== 'file-changed' && type !== 'file-deleted') return
    libraryPanel.refresh()

    _syncLog('info', 'SSE', `${type} ${file_type}:${path}`)

    // Skip reacting to files we just saved ourselves (SSE echo)
    if (type === 'file-changed' && _selfSavedPaths.has(path)) {
      _syncLog('info', 'SSE', `skipped (self-saved echo)`)
      return
    }

    if (file_type === 'part' && store.getState().assemblyActive) {
      // Assembly tab: invalidate and rebuild instances using this file
      const assembly = store.getState().currentAssembly
      const affected = (assembly?.instances ?? []).filter(
        i => i.source?.type === 'file' && i.source.path === path,
      )
      _syncLog('info', 'SSE', `${affected.length} instance(s) affected, invalidating`)
      affected.forEach(i => {
        assemblyRenderer.invalidateInstance(i.id)
        _syncLog('info', 'SSE', `  invalidated ${i.id} (${i.name})`)
      })
      if (affected.length) {
        _setSyncStatus('yellow', 'syncing…')
        assemblyRenderer.rebuild(assembly)
          .then(() => assemblyRenderer.rebuildLinkers(assembly))
          .then(() => {
            _setSyncStatus('green', 'synced')
            _syncLog('info', 'SSE', 'rebuild done')
            // Refresh cluster panel entries for affected instances
            for (const inst of affected) {
              api.getInstanceDesign(inst.id)
                .then(r => { if (r?.design) clusterPanel?.syncInstanceDesign(inst.id, r.design) })
                .catch(() => {})
            }
          })
      }
    } else if (file_type === 'part' && !store.getState().assemblyActive && _workspacePath === path) {
      // Design tab: reload if this is the file we have open
      _syncLog('info', 'SSE', `reloading design from ${path}`)
      _setSyncStatus('yellow', 'syncing…')
      _reloadingFromSSE = true
      api.getLibraryFileContent(path)
        .then(result => result?.content ? api.importDesign(result.content) : null)
        .then(() => { _setSyncStatus('green', 'synced') })
        .catch(err => { _setSyncStatus('red', 'sync error'); _syncLog('err', 'SSE', `reload failed: ${err?.message ?? err}`) })
        .finally(() => { _reloadingFromSSE = false })
    }
	  }
	  api.subscribeLibraryEvents(_handleLibraryEvent)

  async function _refreshAssemblyPartInstance(instanceId, reason = 'part update') {
    if (!instanceId || !store.getState().assemblyActive) return
    _syncLog('info', 'ASM', `${reason}: refreshing ${instanceId}`)
    _setSyncStatus('yellow', 'syncing part…')
    assemblyRenderer.invalidateInstance(instanceId)
    const result = await api.getAssembly()
    const assembly = result?.assembly ?? store.getState().currentAssembly
    if (!assembly) return
    await assemblyRenderer.rebuild(assembly)
    assemblyRenderer.rebuildLinkers(assembly)
    _syncAssemblyBluntEnds()
    assemblyJointRenderer.rebuild(assembly)
    try {
      const r = await api.getInstanceDesign(instanceId)
      if (r?.design) clusterPanel?.syncInstanceDesign(instanceId, r.design)
    } catch { /* sidebar cache refresh is best-effort */ }
    _setSyncStatus('green', 'part synced')
  }

  /**
   * Show or hide ALL design-level scene geometry.
   * Called when toggling assembly mode so the loaded design doesn't bleed through
   * while assembly instances are shown (or while the scene is empty).
   *
   * SCENE GEOMETRY RULE — every element that renders design data must be listed here:
   *   1. designRenderer  — _helixCtrl.root: beads, slabs, axis arrows, extension beads,
   *                        extra-base crossover beads+slabs (children of root — ONE scene object)
   *   2. bluntEnds       — helix-end rings + number-sprite axis labels
   *   3. endExtrudeArrows — drag-to-resize handles on helix ends
   *   4. jointRenderer   — cluster joint axis indicators
   *   5. unfoldView      — crossover arc LINE geometry (_arcGroup / 'xoverArcLines')
   *                        NB: arc lines are a SEPARATE scene object from root.
   *                        Extra-base beads+slabs are children of root (no separate call needed).
   *                        Arc lines require an explicit unfoldView.setArcsVisible() call.
   *
   * If you add a new scene module that renders design geometry, add its
   * setVisible() call here so assembly mode automatically suppresses it.
   * Use window.__nadocDebugXovers() in the browser console to verify.
   */
  function _setDesignGeometryVisible(visible) {
    designRenderer.setDesignVisible(visible)
    bluntEnds.setVisible(visible)
    endExtrudeArrows.setVisible(visible)
    jointRenderer.setVisible(visible)
    unfoldView.setArcsVisible(visible)       // arc line segments (_arcGroup 'xoverArcLines')
    overhangLinkArcs?.setVisible?.(visible)
  }

  /**
   * Browser console debug tool — inspect the visibility state of every
   * crossover-arc-related scene object.
   *
   * Usage: window.__nadocDebugXovers()
   *
   * Reports on four layers (design_renderer is now 1 scene object, not 2):
   *   'designRoot'       — _helixCtrl.root (beads, slabs, extra-base beads/slabs as children)
   *   'xoverExtraBeads'  — extra-base bead InstancedMesh (child of root, inherited visibility)
   *   'arcLines'         — unfoldView._arcGroup (LINE geometry; 'xoverArcLines')
   *   'bluntEnds'        — blunt-end rings + number labels
   */
  window.__nadocDebugXovers = function () {
    // Scan the live scene (including children) for objects by their debug names.
    const found = {}
    scene.traverse(obj => {
      if (obj.name) found[obj.name] = obj
    })

    const fmt = (obj, extra = {}) => obj
      ? { visible: obj.visible, parentVisible: obj.parent?.visible ?? null, ...extra }
      : 'NOT IN SCENE'

    const arcInfo = unfoldView.getArcDebugInfo()
    const root = designRenderer.getHelixCtrl()?.root

    const report = {
      // Layer 1 — design_renderer (single scene object; extra-base beads are children)
      designRoot: root
        ? { visible: root.visible, childCount: root.children.length }
        : 'no root (design not loaded)',
      xoverExtraBeads: found['xoverExtraBeads']
        ? fmt(found['xoverExtraBeads'], {
            count: found['xoverExtraBeads'].count,
            // 'crossoverConnections' group is the parent; root is grandparent
            groupVisible: found['crossoverConnections']?.visible ?? null,
          })
        : 'not built (design has no extra-base crossovers)',

      // Layer 5 — unfold_view arc lines (still a separate scene sibling)
      arcLines: {
        group:    fmt(found['xoverArcLines'], { childCount: found['xoverArcLines']?.children.length ?? 0 }),
        scaffold: found['xoverArcMerged_scaffold']
          ? fmt(found['xoverArcMerged_scaffold'], { arcCount: found['xoverArcMerged_scaffold'].userData.arcCount, xoverIds: found['xoverArcMerged_scaffold'].userData.arcXoverIds })
          : 'not built',
        staple:   found['xoverArcMerged_staple']
          ? fmt(found['xoverArcMerged_staple'],   { arcCount: found['xoverArcMerged_staple'].userData.arcCount,   xoverIds: found['xoverArcMerged_staple'].userData.arcXoverIds })
          : 'not built',
        perArcDetail: arcInfo,
      },
    }

    console.group('[NADOC] Crossover Arc Visibility Debug')
    console.log('assemblyActive:', store.getState().assemblyActive)
    console.log('──── Design root (single scene object):', report.designRoot)
    console.log('     extra-base beads (child of root):', report.xoverExtraBeads)
    console.log('──── Arc lines (_arcGroup, separate scene sibling):', report.arcLines.group)
    console.log('     scaffold merged:', report.arcLines.scaffold)
    console.log('     staple   merged:', report.arcLines.staple)
    console.log('──── Per-arc summary:',
      `total=${arcInfo.totalArcs}`,
      `hidden=${arcInfo.hiddenArcs}`,
      `scaffold=${arcInfo.arcsByType.scaffold}`,
      `staple=${arcInfo.arcsByType.staple}`,
    )
    if (arcInfo.arcs.length) console.table(arcInfo.arcs)
    console.groupEnd()

    return report
  }

  // Drive assembly panel + assembly renderer from the assembly slice
  store.subscribeSlice('assembly', (newState, prevState) => {
    const modeChanged     = newState.assemblyActive    !== prevState.assemblyActive
    const assemblyChanged = newState.currentAssembly   !== prevState.currentAssembly
    const activeChanged   = newState.activeInstanceId  !== prevState.activeInstanceId

    if (modeChanged) {
      animPanel?.setAssemblyMode(newState.assemblyActive)
      if (newState.assemblyActive) {
        _setDesignGeometryVisible(false)
        assemblyPanel.show()
        assemblyPanel.rebuild(newState)
        if (newState.currentAssembly) {
          assemblyRenderer.rebuild(newState.currentAssembly)
            .then(() => {
              assemblyRenderer.rebuildLinkers(newState.currentAssembly)
              _syncAssemblyBluntEnds()
            })
          assemblyJointRenderer.rebuild(newState.currentAssembly)
        }
        controls.addEventListener('change', _updateFixedLockPositions)
        canvas.addEventListener('pointerdown',  _onAssemblyPointerDown)
        canvas.addEventListener('click',        _onAssemblyClick)
        canvas.addEventListener('contextmenu',  _onAssemblyContextMenu)
      } else {
        if (_hasAssemblyPending()) {
          _commitAssemblyPending().catch(err => console.error('[assembly] pending commit on exit:', err))
        }
        _rebuildFixedLocks(null)
        controls.removeEventListener('change', _updateFixedLockPositions)
        _setDesignGeometryVisible(true)
        assemblyPanel.hide()
        assemblyContextMenu.hide()
        instanceGizmo.detach()
        _assemblyPendingTransforms.clear()
        _assemblyPendingPartJoints.clear()
        assemblyRenderer.dispose()
        assemblyJointRenderer.rebuild(null)   // clear all joint indicators
        canvas.removeEventListener('pointerdown',  _onAssemblyPointerDown)
        canvas.removeEventListener('click',        _onAssemblyClick)
        canvas.removeEventListener('contextmenu',  _onAssemblyContextMenu)
        // Clean up any in-flight free drag
        if (_pendingFreeDrag || _freeDrag) {
          canvas.removeEventListener('pointermove', _onAssemblyDragMove)
          canvas.removeEventListener('pointerup',   _onAssemblyDragUp)
          _pendingFreeDrag = null
          _freeDrag        = null
          controls.enabled = true
        }
        // Gizmo exit: detach if the tool was active during mode switch
        if (_translateRotateActive) {
          _translateRotateActive = false
          store.setState({ translateRotateActive: false })
          instanceGizmo.detach()
          _confirmBtn.style.display = 'none'
        }
      }
    }

    // ── Assembly menu item enable/disable ──────────────────────────────────
    if (modeChanged || activeChanged) {
      const hasActive = !!newState.activeInstanceId
      const inAssembly = newState.assemblyActive
      document.getElementById('menu-assembly-define-joint')
        ?.toggleAttribute('disabled', !(inAssembly && hasActive))
      document.getElementById('menu-assembly-define-mate')
        ?.toggleAttribute('disabled', !inAssembly)
    }

    if (!modeChanged && newState.assemblyActive) {
      if (assemblyChanged) {
        // Hide the assembly welcome when the first part is added
        const prevCount = prevState.currentAssembly?.instances?.length ?? 0
        const newCount  = newState.currentAssembly?.instances?.length ?? 0
        if (prevCount === 0 && newCount > 0) _hideWelcome()

        assemblyPanel.rebuild(newState)
        assemblyRenderer.rebuild(newState.currentAssembly)
          .then(() => {
            assemblyRenderer.rebuildLinkers(newState.currentAssembly)
            _syncAssemblyBluntEnds()
            // If the active instance is anchored, rebuild locks with updated topology
            if (newState.activeInstanceId) {
              const depths = computeFixedDepths(newState.currentAssembly)
              if (depths.has(newState.activeInstanceId)) _rebuildFixedLocks(newState.currentAssembly)
            }
          })
        assemblyJointRenderer.rebuild(newState.currentAssembly)
      }
      if (activeChanged) {
        // Clear cluster glow and sidebar selection whenever the active instance changes
        _selectedAssemblyCluster = null
        clusterGlowLayer.clear()
        clusterPanel?.selectAssemblyCluster?.(null, null)
        assemblyRenderer.setActiveInstance(newState.activeInstanceId)
        if (newState.activeInstanceId) {
          clusterPanel?.expandInstance?.(newState.activeInstanceId)
        }
        const newInst = newState.currentAssembly?.instances?.find(i => i.id === newState.activeInstanceId)
        if (newState.activeInstanceId && !newInst?.fixed) {
          _attachGroupGizmo(newState.activeInstanceId)
        } else {
          instanceGizmo.detach()
        }
        // Show locks for all anchored parts when an anchored part is selected; hide otherwise
        const depths = computeFixedDepths(newState.currentAssembly)
        if (newState.activeInstanceId && depths.has(newState.activeInstanceId)) {
          _rebuildFixedLocks(newState.currentAssembly)
        } else {
          _rebuildFixedLocks(null)
        }
      }
    }
  })

  // ── Fixed-instance lock indicators (persistent while assembly mode is active) ──
  const _fixedLockEls = new Map()   // instanceId → wrapper HTMLElement

  function _rebuildFixedLocks(assembly) {
    for (const el of _fixedLockEls.values()) el.remove()
    _fixedLockEls.clear()
    if (!assembly) return

    const depths    = computeFixedDepths(assembly)
    const container = canvas.parentElement
    if (!container || !depths.size) return

    for (const [instId, depth] of depths) {
      const wrap = document.createElement('div')
      wrap.className = 'asm-fixed-indicator'

      const lockSpan = document.createElement('span')
      lockSpan.className = 'asm-fixed-lock'
      lockSpan.textContent = '🔒'
      wrap.appendChild(lockSpan)

      const depthSpan = document.createElement('span')
      depthSpan.className = 'asm-fixed-depth'
      depthSpan.textContent = String(depth)
      wrap.appendChild(depthSpan)

      container.appendChild(wrap)
      _fixedLockEls.set(instId, wrap)
    }

    _updateFixedLockPositions()
  }

  function _updateFixedLockPositions() {
    if (!_fixedLockEls.size) return
    const cRect = canvas.getBoundingClientRect()
    const pRect = canvas.parentElement?.getBoundingClientRect()
    if (!pRect) return

    for (const [instId, el] of _fixedLockEls) {
      const mat = assemblyRenderer.getLiveTransform(instId)
      if (!mat) { el.style.visibility = 'hidden'; continue }
      const ndc = new THREE.Vector3().setFromMatrixPosition(mat).project(camera)
      if (ndc.z > 1) { el.style.visibility = 'hidden'; continue }
      el.style.visibility = ''
      el.style.left = `${(ndc.x  *  0.5 + 0.5) * cRect.width  + (cRect.left - pRect.left)}px`
      el.style.top  = `${(-ndc.y * 0.5 + 0.5) * cRect.height + (cRect.top  - pRect.top)}px`
    }
  }

  // ── Rigid-body group gizmo attachment ────────────────────────────────────────
  const _assemblyPendingTransforms = new Map()
  const _assemblyPendingPartJoints = new Map()

  function _matrixFromInstance(inst) {
    return new THREE.Matrix4().fromArray(inst.transform.values).transpose()
  }

  function _effectiveInstanceMatrix(inst) {
    return _assemblyPendingTransforms.get(inst.id)?.clone() ?? _matrixFromInstance(inst)
  }

  function _createAssemblyTransformContext(instanceId) {
    const assembly = store.getState().currentAssembly
    if (!assembly) return null

    const { anchored } = isGroupAnchored(assembly, instanceId)
    if (anchored) return null

    const groupIds = getRigidBodyGroup(assembly, instanceId)
    const groupStartTransforms = new Map()
    for (const id of groupIds) {
      const gi = assembly.instances.find(i => i.id === id)
      if (!gi) continue
      groupStartTransforms.set(id, _effectiveInstanceMatrix(gi))
    }
    const primaryStart = groupStartTransforms.get(instanceId)
    if (!primaryStart) return null
    return { instanceId, assembly, groupStartTransforms, primaryStart }
  }

  function _applyAssemblyPrimaryLive(ctx, primaryMat4) {
    if (!ctx || !primaryMat4) return
    const delta = primaryMat4.clone().multiply(ctx.primaryStart.clone().invert())
    const asm = store.getState().currentAssembly
    for (const [id, startMat] of ctx.groupStartTransforms) {
      const liveMat = delta.clone().multiply(startMat)
      assemblyRenderer.setLiveTransform(id, liveMat)
      assemblyJointRenderer.setLiveJointTransform(id, liveMat, asm)
    }
    _applyFKLive(asm, delta, [...ctx.groupStartTransforms.keys()])
  }

  function _queueAssemblyPrimaryCommit(ctx, primaryMat4) {
    if (!ctx || !primaryMat4) return
    _assemblyPendingTransforms.set(ctx.instanceId, primaryMat4.clone())
  }

  async function _commitAssemblyPending() {
    const pendingPartJoints = [..._assemblyPendingPartJoints.values()]
    _assemblyPendingPartJoints.clear()
    for (const patch of pendingPartJoints) {
      await api.patchInstanceClusterTransform(patch.instanceId, patch.body)
    }

    const pendingTransforms = [..._assemblyPendingTransforms.entries()]
    _assemblyPendingTransforms.clear()
    for (const [instanceId, mat] of pendingTransforms) {
      await api.propagateFk(instanceId, mat.clone().transpose().toArray())
    }
  }

  function _hasAssemblyPending() {
    return _assemblyPendingTransforms.size > 0 || _assemblyPendingPartJoints.size > 0
  }

  function _attachGroupGizmo(instanceId, ctx = null) {
    ctx ??= _createAssemblyTransformContext(instanceId)
    if (!ctx) return

    instanceGizmo.attach(
      instanceId, scene, camera, canvas,
      // onLiveTransform: apply delta to ALL group members + FK descendants each frame
      (primaryMat4) => {
        _applyAssemblyPrimaryLive(ctx, primaryMat4)
        if (_mrAssemblyCtx?.instanceId === instanceId) _mrSetTransformValuesFromMatrix(primaryMat4)
      },
      // onCommit: keep the transform local until the selection is cleared.
      (primaryMat4) => {
        _queueAssemblyPrimaryCommit(ctx, primaryMat4)
      },
      ctx.primaryStart,
    )
  }

  // ── Forward kinematics live visual propagation ───────────────────────────────
  /**
   * Apply a world-space delta to all kinematic descendants of rootIds.
   * Reads committed transforms from assembly (store snapshot captured at drag-start).
   * @param {Object}         assembly  - store's currentAssembly (captured at drag-start)
   * @param {THREE.Matrix4}  delta     - world-space transform delta
   * @param {string|string[]} rootIds  - instances already moved by caller (seed visited set)
   */
  function _applyFKLive(assembly, delta, rootIds) {
    if (!assembly) return
    const visited = new Set(Array.isArray(rootIds) ? rootIds : [rootIds])
    const queue   = [...visited]
    while (queue.length) {
      const parentId = queue.shift()
      for (const { childId } of getKinematicChildren(assembly, parentId)) {
        if (visited.has(childId)) continue
        const childInst = assembly.instances?.find(i => i.id === childId)
        if (!childInst || childInst.fixed) continue
        const childOld = new THREE.Matrix4().fromArray(childInst.transform.values).transpose()
        const childLiveMat = delta.clone().multiply(childOld)
        assemblyRenderer.setLiveTransform(childId, childLiveMat)
        assemblyJointRenderer.setLiveJointTransform(childId, childLiveMat, assembly)
        visited.add(childId)
        // Expand child's rigid group so they all follow
        for (const memberId of getRigidBodyGroup(assembly, childId)) {
          if (visited.has(memberId)) continue
          const m = assembly.instances?.find(i => i.id === memberId)
          if (!m || m.fixed) continue
          const memberLiveMat = delta.clone().multiply(new THREE.Matrix4().fromArray(m.transform.values).transpose())
          assemblyRenderer.setLiveTransform(memberId, memberLiveMat)
          assemblyJointRenderer.setLiveJointTransform(memberId, memberLiveMat, assembly)
          visited.add(memberId)
          queue.push(memberId)
        }
        queue.push(childId)
      }
    }
  }

  function _applyClusterMateFKLive(assembly, instanceId, clusterId, delta, startTransforms) {
    if (!assembly) return
    const visited = new Set([instanceId])
    const queue = []

    function _jointSideClusterIds(joint, side) {
      const ids = new Set()
      if (side === 'a') {
        if (joint.cluster_id_a) ids.add(joint.cluster_id_a)
        if (!joint.instance_a_id || !joint.connector_a_label) return ids
        const inst = assembly.instances?.find(i => i.id === joint.instance_a_id)
        const ipClusterId = inst?.interface_points?.find(p => p.label === joint.connector_a_label)?.cluster_id
        if (ipClusterId) ids.add(ipClusterId)
        for (const cid of assemblyRenderer.getConnectorClusterIds?.(joint.instance_a_id, joint.connector_a_label) ?? []) {
          if (cid) ids.add(cid)
        }
        return ids
      }
      if (joint.cluster_id_b) ids.add(joint.cluster_id_b)
      const inst = assembly.instances?.find(i => i.id === joint.instance_b_id)
      const ipClusterId = inst?.interface_points?.find(p => p.label === joint.connector_b_label)?.cluster_id
      if (ipClusterId) ids.add(ipClusterId)
      for (const cid of assemblyRenderer.getConnectorClusterIds?.(joint.instance_b_id, joint.connector_b_label) ?? []) {
        if (cid) ids.add(cid)
      }
      return ids
    }

    function _startMat(id) {
      const inst = assembly.instances?.find(i => i.id === id)
      return startTransforms.get(id) ?? (inst ? _matrixFromInstance(inst) : null)
    }

    function _moveSeed(seedId) {
      if (!seedId || visited.has(seedId)) return
      const seedInst = assembly.instances?.find(i => i.id === seedId)
      if (!seedInst || seedInst.fixed) return
      const seedStart = _startMat(seedId)
      if (!seedStart) return
      const seedLiveMat = delta.clone().multiply(seedStart)
      assemblyRenderer.setLiveTransform(seedId, seedLiveMat)
      assemblyJointRenderer.setLiveJointTransform(seedId, seedLiveMat, assembly)
      visited.add(seedId)
      queue.push(seedId)

      for (const memberId of getRigidBodyGroup(assembly, seedId)) {
        if (visited.has(memberId)) continue
        const memberInst = assembly.instances?.find(i => i.id === memberId)
        if (!memberInst || memberInst.fixed) continue
        const memberStart = _startMat(memberId)
        if (!memberStart) continue
        const memberLiveMat = delta.clone().multiply(memberStart)
        assemblyRenderer.setLiveTransform(memberId, memberLiveMat)
        assemblyJointRenderer.setLiveJointTransform(memberId, memberLiveMat, assembly)
        visited.add(memberId)
        queue.push(memberId)
      }
    }

    for (const joint of assembly.joints ?? []) {
      if (joint.instance_a_id === instanceId && _jointSideClusterIds(joint, 'a').has(clusterId)) {
        _moveSeed(joint.instance_b_id)
      } else if (joint.instance_b_id === instanceId && _jointSideClusterIds(joint, 'b').has(clusterId)) {
        _moveSeed(joint.instance_a_id)
      }
    }

    while (queue.length) {
      const parentId = queue.shift()
      for (const { childId } of getKinematicChildren(assembly, parentId)) {
        _moveSeed(childId)
      }
    }
  }

  function _clusterTransformAfterJointDelta(cluster, joint, deltaRad) {
    const axisDir = new THREE.Vector3(...joint.axis_direction).normalize()
    const J = new THREE.Vector3(...joint.axis_origin)
    const P0 = new THREE.Vector3(...(cluster.pivot ?? [0, 0, 0]))
    const R0 = new THREE.Quaternion(...(cluster.rotation ?? [0, 0, 0, 1]))
    const T0 = new THREE.Vector3(...(cluster.translation ?? [0, 0, 0]))
    const R_delta = new THREE.Quaternion().setFromAxisAngle(axisDir, deltaRad)
    const R_new = R_delta.clone().multiply(R0)

    const inner = J.clone().sub(P0).applyQuaternion(R0).add(P0).add(T0).sub(J)
    const T_new = inner.clone().applyQuaternion(R_delta)
    const P0_minus_J = P0.clone().sub(J)
    const T_new_c = P0_minus_J.clone().applyQuaternion(R_new).sub(P0_minus_J).add(T_new)

    return {
      ...cluster,
      translation: [T_new_c.x, T_new_c.y, T_new_c.z],
      rotation: [R_new.x, R_new.y, R_new.z, R_new.w],
      pivot: [P0.x, P0.y, P0.z],
    }
  }

  // ── Camera-plane free drag (non-revolute parts) ──────────────────────────────
  let _assemblyPtrDownAt = null
  let _pendingFreeDrag   = null   // { instId, startNdc, startX, startY }
  let _freeDrag          = null   // { instId, groupStartTransforms, plane, startHit, currentDelta }
  let _partJointDrag     = null
  let _assemblySelectedPartJoint = null
  let _selectedAssemblyCluster   = null  // { instanceId, clusterId } | null

  function _updateFreeDragPosition(e) {
    if (!_freeDrag) return
    const rc = new THREE.Raycaster()
    rc.setFromCamera(_canvasNdc(e), camera)
    const hit = new THREE.Vector3()
    if (!rc.ray.intersectPlane(_freeDrag.plane, hit)) return
    _freeDrag.currentDelta.copy(hit).sub(_freeDrag.startHit)
    const dM = new THREE.Matrix4().makeTranslation(
      _freeDrag.currentDelta.x, _freeDrag.currentDelta.y, _freeDrag.currentDelta.z)
    for (const [id, startMat] of _freeDrag.groupStartTransforms) {
      const liveMat = dM.clone().multiply(startMat)
      assemblyRenderer.setLiveTransform(id, liveMat)
      assemblyJointRenderer.setLiveJointTransform(id, liveMat, _freeDrag.assembly)
    }
    _applyFKLive(_freeDrag.assembly, dM, [..._freeDrag.groupStartTransforms.keys()])
  }

  function _updatePartJointDrag(e) {
    if (!_partJointDrag) return
    const hit = ringPlaneHit(
      _partJointDrag.raycaster,
      e,
      camera,
      canvas,
      _partJointDrag.worldAxis,
      _partJointDrag.worldOrigin,
    )
    if (!hit) return
    const angle = angleInRing(hit, _partJointDrag.worldOrigin, _partJointDrag.worldAxis, _partJointDrag.refVec)
    const delta = angle - _partJointDrag.startAngle
    _partJointDrag.currentDelta = delta

    const qLocal = new THREE.Quaternion().setFromAxisAngle(_partJointDrag.localAxis, delta)
    assemblyRenderer.applyInstanceClusterTransform(
      _partJointDrag.instId,
      _partJointDrag.cluster,
      _partJointDrag.localOrigin,
      _partJointDrag.localOrigin,
      qLocal,
    )

    const worldDelta = new THREE.Matrix4()
      .makeRotationAxis(_partJointDrag.worldAxis, delta)
      .premultiply(new THREE.Matrix4().makeTranslation(
        _partJointDrag.worldOrigin.x,
        _partJointDrag.worldOrigin.y,
        _partJointDrag.worldOrigin.z,
      ))
      .multiply(new THREE.Matrix4().makeTranslation(
        -_partJointDrag.worldOrigin.x,
        -_partJointDrag.worldOrigin.y,
        -_partJointDrag.worldOrigin.z,
      ))
    _partJointDrag.currentWorldDelta.copy(worldDelta)
    _applyClusterMateFKLive(
      _partJointDrag.assembly,
      _partJointDrag.instId,
      _partJointDrag.cluster.id,
      worldDelta,
      _partJointDrag.startTransforms,
    )
  }

  function _onAssemblyDragMove(e) {
    if (_partJointDrag) {
      _updatePartJointDrag(e)
      return
    }
    if (_pendingFreeDrag) {
      const dx = e.clientX - _pendingFreeDrag.startX
      const dy = e.clientY - _pendingFreeDrag.startY
      if (dx * dx + dy * dy < 25) return   // below threshold

      const { instId, startNdc } = _pendingFreeDrag
      _pendingFreeDrag   = null
      _assemblyPtrDownAt = null   // prevent click-to-select on the upcoming click event

      store.setState({ activeInstanceId: instId })
      controls.enabled = false

      const assembly = store.getState().currentAssembly
      if (!assembly) return

      const groupIds = getRigidBodyGroup(assembly, instId)
      const groupStartTransforms = new Map()
      for (const id of groupIds) {
        const gi = assembly.instances.find(i => i.id === id)
        if (gi) groupStartTransforms.set(id,
          new THREE.Matrix4().fromArray(gi.transform.values).transpose())
      }
      const primaryMat = groupStartTransforms.get(instId)
      if (!primaryMat) return

      const worldPos = new THREE.Vector3().setFromMatrixPosition(primaryMat)
      const camDir   = new THREE.Vector3()
      camera.getWorldDirection(camDir)
      const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camDir, worldPos)

      const rc       = new THREE.Raycaster()
      rc.setFromCamera(startNdc, camera)
      const startHit = new THREE.Vector3()
      if (!rc.ray.intersectPlane(plane, startHit)) return

      _freeDrag = { instId, groupStartTransforms, assembly, plane, startHit, currentDelta: new THREE.Vector3() }
      _updateFreeDragPosition(e)
    } else if (_freeDrag) {
      _updateFreeDragPosition(e)
    }
  }

  function _onAssemblyDragUp() {
    canvas.removeEventListener('pointermove', _onAssemblyDragMove)
    canvas.removeEventListener('pointerup',   _onAssemblyDragUp)
    controls.enabled = true
    _pendingFreeDrag = null
    if (_partJointDrag) {
      const drag = _partJointDrag
      _partJointDrag = null
      if (Math.abs(drag.currentDelta) < 1e-8) return
      const clusterTransform = _clusterTransformAfterJointDelta(drag.cluster, drag.joint, drag.currentDelta)
      _assemblyPendingPartJoints.set(`${drag.instId}:${drag.cluster.id}`, {
        instanceId: drag.instId,
        body: {
          cluster_id: drag.cluster.id,
          cluster_transform: clusterTransform,
          joint_id: drag.joint.id,
          joint_value: (drag.inst.joint_states?.[drag.joint.id] ?? 0) + drag.currentDelta,
          delta_transform: { values: drag.currentWorldDelta.clone().transpose().toArray() },
        },
      })
      return
    }
    if (_freeDrag) {
      const drag = _freeDrag
      _freeDrag = null
      if (drag.currentDelta.lengthSq() < 1e-10) return   // no movement — nothing to commit
      const dM           = new THREE.Matrix4().makeTranslation(
        drag.currentDelta.x, drag.currentDelta.y, drag.currentDelta.z)
      const primaryStart = drag.groupStartTransforms.get(drag.instId)
      const primaryFinal = dM.clone().multiply(primaryStart)
      api.propagateFk(drag.instId, primaryFinal.clone().transpose().toArray())
        .catch(err => console.error('[assembly] free drag commit:', err))
    }
  }

  // ── Assembly canvas pointer handler (joint ring pick + instance selection) ──
  function _onAssemblyPointerDown(e) {
    if (e.button === 0) {
      // Priority 1: joint ring drag
      const jointId = assemblyJointRenderer.pickJointRing(e)
      if (jointId) { assemblyJointRenderer.beginRingDrag(jointId, e); return }

      if (!_translateRotateActive && !assemblyJointRenderer.isMateMode()) {
        const partJointHit = assemblyRenderer.pickPartJoint?.(_canvasNdc(e), camera)
        if (partJointHit?.inst?.id === store.getState().activeInstanceId) {
          _assemblySelectedPartJoint = {
            instanceId: partJointHit.inst.id,
            jointId: partJointHit.joint.id,
            clusterId: partJointHit.cluster.id,
          }
          _assemblyPtrDownAt = null
          e.stopPropagation()
          return
        }

        // Priority 2b: cluster already selected (via panel/re-click) + allow_part_joints
        // → drag rotates the cluster around its joint without requiring a prior ring click
        if (_selectedAssemblyCluster) {
          const { instanceId: selInstId, clusterId: selClusterId } = _selectedAssemblyCluster
          const assembly = store.getState().currentAssembly
          const inst = assembly?.instances?.find(i => i.id === selInstId)
          const pickedInst = assemblyRenderer.pickInstance(_canvasNdc(e), camera)
          if (inst?.allow_part_joints && !inst.fixed && pickedInst?.id === selInstId) {
            const design = assemblyRenderer.getInstanceDesign(selInstId)
            const cluster = design?.cluster_transforms?.find(c => c.id === selClusterId)
            const joint   = design?.cluster_joints?.find(j => j.cluster_id === selClusterId)
            if (cluster && joint) {
              const instMat = assemblyRenderer.getLiveTransform(selInstId)
                ?? new THREE.Matrix4().fromArray(inst.transform.values).transpose()
              const localOrigin = new THREE.Vector3(...joint.axis_origin)
              const localAxis   = new THREE.Vector3(...joint.axis_direction).normalize()
              const worldOrigin = localOrigin.clone().applyMatrix4(instMat)
              const worldAxis   = localAxis.clone().transformDirection(instMat).normalize()
              const raycaster   = new THREE.Raycaster()
              const startHit    = ringPlaneHit(raycaster, e, camera, canvas, worldAxis, worldOrigin)
              if (startHit) {
                const refVec = makeRefVec(worldAxis)
                const startTransforms = new Map()
                for (const asmInst of (assembly?.instances ?? [])) {
                  startTransforms.set(asmInst.id, new THREE.Matrix4().fromArray(asmInst.transform.values).transpose())
                }
                assemblyRenderer.captureInstanceClusterBase(selInstId, cluster)
                controls.enabled  = false
                _assemblyPtrDownAt = null
                _partJointDrag = {
                  instId: selInstId,
                  inst,
                  cluster,
                  joint,
                  assembly,
                  localOrigin,
                  localAxis,
                  worldOrigin,
                  worldAxis,
                  refVec,
                  raycaster,
                  startAngle: angleInRing(startHit, worldOrigin, worldAxis, refVec),
                  currentDelta: 0,
                  currentWorldDelta: new THREE.Matrix4(),
                  startTransforms,
                }
                canvas.addEventListener('pointermove', _onAssemblyDragMove)
                canvas.addEventListener('pointerup',   _onAssemblyDragUp)
                return
              }
            }
          }
        }

        const clusterHit = assemblyRenderer.pickInstanceCluster(_canvasNdc(e), camera)
        const selectedPartJoint = _assemblySelectedPartJoint
        const selectedJointMatchesCluster = selectedPartJoint &&
          clusterHit?.inst?.id === selectedPartJoint.instanceId &&
          clusterHit?.cluster?.id === selectedPartJoint.clusterId
        if (clusterHit?.inst?.allow_part_joints && !clusterHit.inst.fixed && selectedJointMatchesCluster) {
          const { inst, cluster } = clusterHit
          const joint = clusterHit.design?.cluster_joints?.find(j => j.id === selectedPartJoint.jointId) ?? clusterHit.joint
          store.setState({ activeInstanceId: inst.id })
          controls.enabled = false

          const instMat = assemblyRenderer.getLiveTransform(inst.id)
            ?? new THREE.Matrix4().fromArray(inst.transform.values).transpose()
          const localOrigin = new THREE.Vector3(...joint.axis_origin)
          const localAxis = new THREE.Vector3(...joint.axis_direction).normalize()
          const worldOrigin = localOrigin.clone().applyMatrix4(instMat)
          const worldAxis = localAxis.clone().transformDirection(instMat).normalize()
          const raycaster = new THREE.Raycaster()
          const startHit = ringPlaneHit(raycaster, e, camera, canvas, worldAxis, worldOrigin)
          if (startHit) {
            const refVec = makeRefVec(worldAxis)
            const assembly = store.getState().currentAssembly
            const startTransforms = new Map()
            for (const asmInst of (assembly?.instances ?? [])) {
              startTransforms.set(asmInst.id, _effectiveInstanceMatrix(asmInst))
            }
            assemblyRenderer.captureInstanceClusterBase(inst.id, cluster)
            _partJointDrag = {
              instId: inst.id,
              inst,
              cluster,
              joint,
              assembly,
              localOrigin,
              localAxis,
              worldOrigin,
              worldAxis,
              refVec,
              raycaster,
              startAngle: angleInRing(startHit, worldOrigin, worldAxis, refVec),
              currentDelta: 0,
              currentWorldDelta: new THREE.Matrix4(),
              startTransforms,
            }
            canvas.addEventListener('pointermove', _onAssemblyDragMove)
            canvas.addEventListener('pointerup',   _onAssemblyDragUp)
            return
          }
          controls.enabled = true
        }

      }

      // Priority 3: record for click-to-select
      _assemblyPtrDownAt = { x: e.clientX, y: e.clientY }
    }
  }

  async function _onAssemblyClick(e) {
    if (e.button !== 0) return
    if (_translateRotateActive) return   // gizmo handles its own pointer events
    if (!_assemblyPtrDownAt) return
    const dx = e.clientX - _assemblyPtrDownAt.x
    const dy = e.clientY - _assemblyPtrDownAt.y
    _assemblyPtrDownAt = null
    if (dx * dx + dy * dy > 25) return   // was a drag, not a click
    const inst   = assemblyRenderer.pickInstance(_canvasNdc(e), camera)
    const prevId = store.getState().activeInstanceId

    // Re-clicking the already-active instance → pick cluster and highlight
    if (inst && inst.id === prevId) {
      const clusterHit = assemblyRenderer.pickInstanceCluster(_canvasNdc(e), camera, { scopeInstId: inst.id })
      if (clusterHit?.cluster) {
        const { entries, matrixWorld } = assemblyRenderer.getInstanceBackboneEntries(inst.id)
        const design = assemblyRenderer.getInstanceDesign(inst.id)
        const localEntries = _clusterBackboneEntries(clusterHit.cluster, design, entries)
        const worldEntries = localEntries.map(e2 => ({ ...e2, pos: e2.pos.clone().applyMatrix4(matrixWorld) }))
        clusterGlowLayer.setEntries(worldEntries)
        clusterPanel?.selectAssemblyCluster?.(inst.id, clusterHit.cluster.id)
        _selectedAssemblyCluster = { instanceId: inst.id, clusterId: clusterHit.cluster.id }
        instanceGizmo.detach()
      }
      return
    }

    const newId = inst ? inst.id : null
    if (newId !== prevId && _hasAssemblyPending()) {
      _showProgress('Updating Assembly', 'Applying part transform…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        await _commitAssemblyPending()
      } finally {
        _hideProgress()
      }
    }
    if (newId !== prevId) _assemblySelectedPartJoint = null
    store.setState({ activeInstanceId: newId })
  }

  async function _onAssemblyContextMenu(e) {
    e.preventDefault()
    e.stopPropagation()
    // If the right-click hit an overhang arrow, selection_manager's
    // contextmenu listener already routes it to the overhang length dialog.
    // Skip the part context menu so it doesn't appear on top.
    if (overhangLocations?.isVisible?.()) {
      const rc = new THREE.Raycaster()
      rc.setFromCamera(_canvasNdc(e), camera)
      if (overhangLocations.hitTest(rc)) return
    }
    const inst = assemblyRenderer.pickInstance(_canvasNdc(e), camera)
    if (!inst) return
    if (inst.id !== store.getState().activeInstanceId && _hasAssemblyPending()) {
      await _commitAssemblyPending()
      _assemblySelectedPartJoint = null
    }
    store.setState({ activeInstanceId: inst.id })
    assemblyContextMenu.show(inst, e.clientX, e.clientY)
  }

  let clusterPanel = null
  clusterPanel = initClusterPanel(store, {
    onAssemblyClusterClick: (instanceId, clusterId) => {
      if (!instanceId || !clusterId) {
        _selectedAssemblyCluster = null
        clusterGlowLayer.clear()
        // Re-attach gizmo since cluster is deselected
        const { activeInstanceId, currentAssembly } = store.getState()
        const activeInst = currentAssembly?.instances?.find(i => i.id === activeInstanceId)
        if (activeInstanceId && !activeInst?.fixed) _attachGroupGizmo(activeInstanceId)
        return
      }
      const { entries, matrixWorld } = assemblyRenderer.getInstanceBackboneEntries(instanceId)
      const design  = assemblyRenderer.getInstanceDesign(instanceId)
      const cluster = design?.cluster_transforms?.find(c => c.id === clusterId)
      if (!cluster) { clusterGlowLayer.clear(); return }
      const localEntries = _clusterBackboneEntries(cluster, design, entries)
      const worldEntries = localEntries.map(e => ({ ...e, pos: e.pos.clone().applyMatrix4(matrixWorld) }))
      clusterGlowLayer.setEntries(worldEntries)
      _selectedAssemblyCluster = { instanceId, clusterId }
      instanceGizmo.detach()
    },
    onClusterClick: async (clusterId) => {
      if (!_translateRotateActive) {
        // Simple highlight toggle — no gizmo, no API calls.
        const current = store.getState().activeClusterId
        store.setState({ activeClusterId: current === clusterId ? null : clusterId })
        return
      }
      // Tool active: switch gizmo to the clicked cluster.
      if (clusterId === store.getState().activeClusterId) return
      await _refreshClusterPivotForAttach(clusterId)
      clusterGizmo.attach(clusterId, scene, camera, canvas)
      _mrSyncClusterDropdown(clusterId)
    },
    api,
    onVisibilityChange: (hiddenClusterIds) => {
      const { currentDesign } = store.getState()
      const clusters = currentDesign?.cluster_transforms ?? []
      const nucKeys = new Set()
      // Track which strand IDs / helix IDs are hidden so we can include extensions.
      const hiddenStrandIds = new Set()
      const hiddenHelixIds  = new Set()
      const strandMap = new Map((currentDesign?.strands ?? []).map(s => [s.id, s]))
      for (const c of clusters) {
        if (!hiddenClusterIds.has(c.id)) continue
        if (c.domain_ids?.length) {
          // Mixed cluster: bridge helices hidden by domain key; exclusive helices
          // (in helix_ids but not touched by any domain_ids entry) hidden whole.
          const bridgeHelixIds = new Set()
          for (const d of c.domain_ids) {
            const dom = strandMap.get(d.strand_id)?.domains?.[d.domain_index]
            if (dom) bridgeHelixIds.add(dom.helix_id)
            nucKeys.add(`d:${d.strand_id}:${d.domain_index}`)
            hiddenStrandIds.add(d.strand_id)
          }
          for (const hid of c.helix_ids) {
            if (!bridgeHelixIds.has(hid)) {
              nucKeys.add(`h:${hid}`)
              hiddenHelixIds.add(hid)
            }
          }
        } else {
          // Helix-level cluster — hide whole helices
          for (const hid of c.helix_ids) {
            nucKeys.add(`h:${hid}`)
            hiddenHelixIds.add(hid)
          }
        }
      }
      // Include extension beads attached to hidden strands / helices.
      // Extension nucs have helix_id = '__ext_<id>', matched by 'h:__ext_<id>' keys.
      for (const ext of currentDesign?.extensions ?? []) {
        if (hiddenStrandIds.has(ext.strand_id)) {
          nucKeys.add('h:__ext_' + ext.id)
        } else if (hiddenHelixIds.size) {
          const strand  = currentDesign.strands.find(s => s.id === ext.strand_id)
          const termDom = strand && (ext.end === 'five_prime'
            ? strand.domains[0]
            : strand.domains[strand.domains.length - 1])
          if (termDom && hiddenHelixIds.has(termDom.helix_id)) nucKeys.add('h:__ext_' + ext.id)
        }
      }
      designRenderer.setHiddenNucs(nucKeys)
      const hiddenXoverIds = unfoldView.setHiddenNucs(nucKeys)
      designRenderer.setHiddenCrossovers(hiddenXoverIds)
    },
  })

  // Sync cluster panel assembly mode with assemblyActive + instance list changes
  store.subscribe((newState, prevState) => {
    const asmChanged  = newState.assemblyActive  !== prevState.assemblyActive
    const instChanged = newState.currentAssembly !== prevState.currentAssembly
    if (!asmChanged && !instChanged) return
    if (newState.assemblyActive) {
      clusterPanel?.setAssemblyMode(newState.currentAssembly?.instances ?? [])
    } else if (asmChanged) {
      clusterPanel?.clearAssemblyMode()
    }
  })

  // ── Joints panel ────────────────────────────────────────────────────────────
  initJointsPanel(store, {
    api,
    jointRenderer,
    onJointHighlight: (jointId) => jointRenderer.highlightJoint(jointId),
    onJointAdded: (clusterId) => {
      // If move/rotate tool is active and the joint belongs to the active cluster,
      // refresh the pivot dropdown so the new joint appears immediately.
      if (_translateRotateActive && store.getState().activeClusterId === clusterId) {
        const joints = store.getState().currentDesign?.cluster_joints?.filter(j => j.cluster_id === clusterId) ?? []
        _mrSetPivotOptions(joints)
      }
    },
    onJointRotate: (joint) => _rotateJoint(joint),
  })

  async function _animateAssemblyConfiguration(cfg) {
    const assembly = store.getState().currentAssembly
    if (!assembly || !cfg) return
    if (_hasAssemblyPending()) await _commitAssemblyPending()

    const stateById = new Map((cfg.instance_states ?? []).map(s => [s.instance_id, s]))
    const animItems = []
    for (const inst of assembly.instances ?? []) {
      const state = stateById.get(inst.id)
      if (!state?.transform?.values) continue
      const startMat = assemblyRenderer.getLiveTransform(inst.id)
        ?? new THREE.Matrix4().fromArray(inst.transform.values).transpose()
      const endMat = new THREE.Matrix4().fromArray(state.transform.values).transpose()
      const sp = new THREE.Vector3(), ss = new THREE.Vector3()
      const sq = new THREE.Quaternion()
      const ep = new THREE.Vector3(), es = new THREE.Vector3()
      const eq = new THREE.Quaternion()
      startMat.decompose(sp, sq, ss)
      endMat.decompose(ep, eq, es)
      animItems.push({ id: inst.id, sp, sq, ss, ep, eq, es })
    }
    if (!animItems.length) {
      await api.restoreAssemblyConfiguration(cfg.id)
      return
    }

    const duration = 650
    const start = performance.now()
    const mat = new THREE.Matrix4()
    const pos = new THREE.Vector3()
    const quat = new THREE.Quaternion()
    const scale = new THREE.Vector3()
    const ease = t => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2

    await new Promise(resolve => {
      function frame(now) {
        const t = Math.min(1, (now - start) / duration)
        const k = ease(t)
        for (const item of animItems) {
          pos.copy(item.sp).lerp(item.ep, k)
          quat.copy(item.sq).slerp(item.eq, k)
          scale.copy(item.ss).lerp(item.es, k)
          mat.compose(pos, quat, scale)
          assemblyRenderer.setLiveTransform(item.id, mat)
          assemblyJointRenderer.setLiveJointTransform(item.id, mat, assembly)
        }
        if (t < 1) requestAnimationFrame(frame)
        else resolve()
      }
      requestAnimationFrame(frame)
    })
    await api.restoreAssemblyConfiguration(cfg.id)
  }

  // ── Animation tab support panels ─────────────────────────────────────────────
  initAssemblyConfigPanel(store, { api, onAnimateConfiguration: _animateAssemblyConfiguration })
  _partCameraPanel = initCameraPanel(store, { captureCurrentCamera, animateCameraTo, api })

  // ── Feature Log panel ────────────────────────────────────────────────────────
  _partFeatureLogPanel = initFeatureLogPanel(store, {
    api: { ...api, seekFeatures: _seekFeaturesWithDelta, deleteFeature: _deleteFeatureWithDelta },
    onEditFeature: _onEditFeature,
    onAnimateConfiguration: _animateAssemblyConfiguration,
    // Linker-add log entries delegate their ✎ click here so the user lands
    // directly in the Overhangs Manager with the linker's two overhangs
    // pre-selected, mirroring the right-click → Manager flow.
    onOpenOverhangsManager: (ovhgIds) => {
      const { currentDesign } = store.getState()
      if (!currentDesign?.helices?.length) return
      openOverhangsManager(ovhgIds)
    },
  })


  // ── Left panel tab controller ────────────────────────────────────────────────
  // Three tabs (Feature Log / Dynamics / Scene) on a vertical strip that is
  // always visible. Click an inactive tab → expand + switch; click the active
  // tab while expanded → collapse; switch between tabs while expanded → swap
  // content without changing collapsed state. The toggle arrow at the top of
  // the strip is a dedicated collapse/expand affordance that mirrors the
  // active-tab click. Persists (activeTab, collapsed) to localStorage so the
  // sidebar restores its prior state across reloads.
  let _leftSidebar = null
  {
    const TABS = ['feature-log', 'dynamics', 'scene']
    const STORAGE_KEY = 'nadoc.leftSidebar.v1'
    const leftPanel = document.getElementById('left-panel')
    const tabStrip  = document.getElementById('left-tab-strip')
    const toggleBtn = document.getElementById('left-tab-toggle')
    if (leftPanel && tabStrip) {
      const btns  = Object.fromEntries(TABS.map(id => [id, tabStrip.querySelector(`[data-tab="${id}"]`)]))
      const panes = Object.fromEntries(TABS.map(id => [id, document.getElementById(`tab-content-${id}`)]))

      let activeTab = 'feature-log'
      let collapsed = true

      // Restore persisted state.
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
        if (saved && TABS.includes(saved.activeTab)) {
          activeTab = saved.activeTab
          collapsed = saved.collapsed !== false   // missing → default collapsed
        }
      } catch { /* ignore corrupt state */ }

      function _persist() {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ activeTab, collapsed })) } catch {}
      }

      function _render() {
        for (const id of TABS) {
          if (btns[id])  btns[id].classList.toggle('active', id === activeTab && !collapsed)
          if (panes[id]) panes[id].hidden = (id !== activeTab)
        }
        // While locked (welcome screen / part-context), force visual hidden
        // regardless of the controller's internal `collapsed` state, so the
        // persisted "expanded" state doesn't leak through and pop the panel
        // open at the welcome screen.
        const locked = leftPanel.classList.contains('locked-hidden')
        leftPanel.classList.toggle('hidden', collapsed || locked)
        if (toggleBtn) {
          toggleBtn.textContent = collapsed ? '▶' : '◀'
          toggleBtn.title       = collapsed ? 'Show sidebar' : 'Hide sidebar'
        }
      }

      // Called whenever the visible state of the Animations (formerly Scene)
      // tab changes from "active + expanded" → anything else. Stops any
      // in-flight playback (frees baked geometry) and re-seeks the design
      // to the feature-log slider's current cursor so the live model
      // matches what the slider says rather than the last lerped frame.
      function _leaveAnimationsTab() {
        try {
          animPlayer?.stop?.()
          animPlayer?.setDisablePoses?.(false)
          const d = store.getState().currentDesign
          const cursor = d?.feature_log_cursor ?? -1
          const subCursor = d?.feature_log_sub_cursor ?? null
          // Re-issue a seek with the same cursor so the backend rebuilds the
          // design at exactly that index and the renderer subscribes pick up
          // the canonical state. -1 (no features) and -2 (pre-F0) both round-trip
          // through seekFeatures correctly.
          _seekFeaturesWithDelta(cursor, subCursor)
        } catch (err) {
          console.warn('[left-tabs] reset on tab leave failed:', err)
        }
      }

      function setActiveTab(tabId) {
        if (leftPanel.classList.contains('locked-hidden')) return
        if (!TABS.includes(tabId)) return
        const wasOnAnimations = !collapsed && activeTab === 'scene'
        if (collapsed) {
          collapsed = false
          activeTab = tabId
        } else if (tabId === activeTab) {
          collapsed = true
        } else {
          activeTab = tabId
        }
        const nowOnAnimations = !collapsed && activeTab === 'scene'
        if (wasOnAnimations && !nowOnAnimations) _leaveAnimationsTab()
        _render()
        _persist()
      }

      function toggleCollapsed() {
        if (leftPanel.classList.contains('locked-hidden')) return
        const wasOnAnimations = !collapsed && activeTab === 'scene'
        collapsed = !collapsed
        if (wasOnAnimations && collapsed) _leaveAnimationsTab()
        _render()
        _persist()
      }

      for (const id of TABS) {
        if (btns[id]) btns[id].addEventListener('click', () => setActiveTab(id))
      }
      if (toggleBtn) toggleBtn.addEventListener('click', toggleCollapsed)

      // Apply initial state without firing persistence.
      _render()

      // Expose the controller for assembly-mode entry/exit handlers and tests.
      _leftSidebar = {
        setActiveTab,
        toggleCollapsed,
        getActiveTab: () => activeTab,
        isCollapsed:  () => collapsed,
        // Re-applies visual state from internal `collapsed` + `locked-hidden`.
        // Used by `_setLeftPanelEnabled` so unlocking the panel restores the
        // user's persisted expanded/collapsed preference.
        refresh: _render,
      }
      window.__leftSidebar = _leftSidebar
    }
  }

  // ── Animation panel ──────────────────────────────────────────────────────────
  let animPanel = null
  _partAnimPanel = animPanel = initAnimationPanel(store, {
    player: animPlayer,
    captureCurrentCamera,
    api,
    exportVideo,
    renderer,
    scene,
    camera,
  })

  // Populate transform fields and pivot options when the active cluster changes.
  store.subscribe((newState, prevState) => {
    if (newState.activeClusterId === prevState.activeClusterId) return
    if (!newState.activeClusterId || !newState.translateRotateActive) return
    const cluster = newState.currentDesign?.cluster_transforms?.find(c => c.id === newState.activeClusterId)
    if (!cluster) return
    const [rx, ry, rz] = _quatToEulerDeg(cluster.rotation)
    _mrSetTransformValues(cluster.translation[0], cluster.translation[1], cluster.translation[2], rx, ry, rz)
    const joints = newState.currentDesign?.cluster_joints?.filter(j => j.cluster_id === newState.activeClusterId) ?? []
    _mrSetPivotOptions(joints)
    _mrSetSelectedPivot('centroid')
    _mrSyncClusterDropdown(newState.activeClusterId)
    clusterGizmo.setConstraint('centroid', null)
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
          strands: true, domains: false, ends: false, crossoverArcs: false,
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
    _refreshClusterPivotForAttach(cluster.id).then(() => {
      clusterGizmo.attach(cluster.id, scene, camera, canvas)
    })
  })

  // Mutual exclusion: cancel translate/rotate when the deform tool starts.
  store.subscribe((newState, prevState) => {
    if (newState.deformToolActive && !prevState.deformToolActive && _translateRotateActive) {
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
    const entries = _clusterBackboneEntries(cluster, newState.currentDesign)
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
      arrow.classList.toggle('is-collapsed', !(_expanded))
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

    // ── Right-click context menu: delete all strands of this bin length ──────
    const _histCtx       = document.getElementById('hist-ctx-menu')
    const _histCtxHeader = document.getElementById('hist-ctx-header')
    const _histCtxCount  = document.getElementById('hist-ctx-count')
    const _histCtxDelete = document.getElementById('hist-ctx-delete-btn')
    let _ctxBar = null

    function _hideHistCtx() {
      if (_histCtx) _histCtx.style.display = 'none'
      _ctxBar = null
    }

    canvas.addEventListener('contextmenu', e => {
      e.preventDefault()
      const rect   = canvas.getBoundingClientRect()
      const scaleX = canvas.width / rect.width
      const mx     = (e.clientX - rect.left) * scaleX
      for (const bar of _barData) {
        if (mx >= bar.x && mx <= bar.x + bar.w) {
          _ctxBar = bar
          if (_histCtxHeader) _histCtxHeader.textContent = `${bar.length} nt`
          if (_histCtxCount)  _histCtxCount.textContent  = bar.strandIds.length
          if (_histCtx) {
            _histCtx.style.left    = `${e.clientX}px`
            _histCtx.style.top     = `${e.clientY}px`
            _histCtx.style.display = 'block'
          }
          return
        }
      }
    })

    document.addEventListener('pointerdown', e => {
      if (_histCtx?.style.display !== 'none' && !_histCtx.contains(e.target)) _hideHistCtx()
    })

    _histCtxDelete?.addEventListener('click', async () => {
      if (!_ctxBar) return
      const bar = _ctxBar
      _hideHistCtx()
      if (bar.strandIds.length === 1) await api.deleteStrand(bar.strandIds[0])
      else await api.deleteStrandsBatch(bar.strandIds)
    })

    // Redraw when design changes and histogram is visible; reset cycle state
    store.subscribe((newState, prevState) => {
      if (_expanded && newState.currentDesign !== prevState.currentDesign) {
        _lastClickedLength = null
        _cycleIndex = 0
        _redraw(newState.currentDesign)
      }
    })
  })()


  // ── Import helpers ─────────────────────────────────────────────────────────────

  // Prompt Save As for an already-imported design, then add it as an assembly part.
  async function _importAsAssemblyPart(suggestedName) {
    const saveResult = await openFileBrowser({
      title: 'Save New Part As',
      mode: 'save',
      fileType: 'part',
      suggestedName,
      suggestedExt: '.nadoc',
      api,
    })
    if (!saveResult) {
      store.setState({ currentDesign: null })
      return
    }
    const saved = await api.saveDesignAs(saveResult.path, saveResult.overwrite ?? false)
    if (!saved) { alert('Failed to save part.'); store.setState({ currentDesign: null }); return }
    store.setState({ currentDesign: null })
    await api.addInstance({ source: { type: 'file', path: saveResult.path }, name: saveResult.name.replace(/\.nadoc$/i, '') })
    libraryPanel?.refresh()
    showToast(`Part "${saveResult.name}" added to assembly.`)
  }

  // ── Library panel import callbacks (cadnano / scadnano with autodetection) ──────

  async function _importCadnanoWithAutodetection() {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.json'
    const file = await new Promise(r => { input.onchange = () => r(input.files?.[0] ?? null); input.click() })
    if (!file) return
    const content = await file.text()
    _resetForNewDesign()
    const result = await api.importCadnanoDesign(content)
    if (!result) {
      alert('Failed to import caDNAno file: ' + (store.getState().lastError?.message ?? 'Unknown error'))
      if (!store.getState().assemblyActive) _showWelcome()
      return
    }
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
    showToast('Note: caDNAno designs appear upside down due to the original caDNAno coordinate convention.', 8000)
    api.addRecentFile(file.name, content, 'cadnano')
    _renderRecentMenu()

    const design = store.getState().currentDesign
    const clusters = (design?.cluster_transforms ?? []).filter(c => !c.is_default)
    const overhangs = design?.overhangs ?? []
    const suggestedName = (design?.metadata?.name ?? file.name.replace(/\.[^.]+$/, '')).replace(/[^a-zA-Z0-9-_ ]/g, '_')

    _hideWelcome(); workspace.hide()

    const dest = await openFileBrowser({
      title: 'Save Imported Design',
      mode: 'save', fileType: 'part',
      suggestedName, suggestedExt: '.nadoc', api,
      autodetection: (clusters.length || overhangs.length) ? { clusters, overhangs } : null,
    })
    if (!dest) return

    if (dest.includeClusters === false && clusters.length) {
      for (const cl of clusters) await api.deleteCluster(cl.id)
    }
    if (dest.includeOverhangs === false && overhangs.length) {
      await api.clearOverhangs()
    }

    const r = await api.saveDesignAs(dest.path, dest.overwrite ?? false)
    if (r) {
      _fileHandle = null
      _setWorkspacePath(dest.path)
      _setFileName(dest.name)
      _setSyncStatus('green', 'saved')
      libraryPanel?.refresh()
    }
  }

  async function _importScadnanoWithAutodetection() {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.sc'
    const file = await new Promise(r => { input.onchange = () => r(input.files?.[0] ?? null); input.click() })
    if (!file) return
    const content = await file.text()
    const baseName = file.name.replace(/\.sc$/i, '')
    _resetForNewDesign()
    const result = await api.importScadnanoDesign(content, baseName)
    if (!result) {
      alert('Failed to import scadnano file: ' + (store.getState().lastError?.message ?? 'Unknown error'))
      if (!store.getState().assemblyActive) _showWelcome()
      return
    }
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
    showToast('Note: scadnano designs appear upside down due to the original scadnano coordinate convention.', 8000)
    api.addRecentFile(file.name, content, 'scadnano')
    _renderRecentMenu()

    const design = store.getState().currentDesign
    const clusters = (design?.cluster_transforms ?? []).filter(c => !c.is_default)
    const overhangs = design?.overhangs ?? []
    const suggestedName = (design?.metadata?.name ?? baseName).replace(/[^a-zA-Z0-9-_ ]/g, '_')

    _hideWelcome(); workspace.hide()

    const dest = await openFileBrowser({
      title: 'Save Imported Design',
      mode: 'save', fileType: 'part',
      suggestedName, suggestedExt: '.nadoc', api,
      autodetection: (clusters.length || overhangs.length) ? { clusters, overhangs } : null,
    })
    if (!dest) return

    if (dest.includeClusters === false && clusters.length) {
      for (const cl of clusters) await api.deleteCluster(cl.id)
    }
    if (dest.includeOverhangs === false && overhangs.length) {
      await api.clearOverhangs()
    }

    const r = await api.saveDesignAs(dest.path, dest.overwrite ?? false)
    if (r) {
      _fileHandle = null
      _setWorkspacePath(dest.path)
      _setFileName(dest.name)
      _setSyncStatus('green', 'saved')
      libraryPanel?.refresh()
    }
  }

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
        if (!store.getState().assemblyActive) _showWelcome()
        return
      }
      if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
      showToast('Note: caDNAno designs appear upside down due to the original caDNAno coordinate convention.', 8000)
      api.addRecentFile(file.name, content, 'cadnano')
      _renderRecentMenu()
      const design = store.getState().currentDesign
      const suggestedName = (design?.metadata?.name ?? file.name.replace(/\.[^.]+$/, '')).replace(/[^a-zA-Z0-9-_ ]/g, '_')
      if (store.getState().assemblyActive) {
        await _importAsAssemblyPart(suggestedName)
      } else {
        _hideWelcome()
        workspace.hide()
        await _saveAs()
      }
    }
    input.click()
  })

  // ── Import scadnano ────────────────────────────────────────────────────────────
  document.getElementById('menu-file-import-scadnano')?.addEventListener('click', () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.sc'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const content = await file.text()
      const baseName = file.name.replace(/\.sc$/i, '')
      _resetForNewDesign()
      const result = await api.importScadnanoDesign(content, baseName)
      if (!result) {
        alert('Failed to import scadnano file: ' + (store.getState().lastError?.message ?? 'Unknown error'))
        if (!store.getState().assemblyActive) _showWelcome()
        return
      }
      if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
      showToast('Note: scadnano designs appear upside down due to the original scadnano coordinate convention.', 8000)
      api.addRecentFile(file.name, content, 'scadnano')
      _renderRecentMenu()
      const design = store.getState().currentDesign
      const suggestedName = (design?.metadata?.name ?? baseName).replace(/[^a-zA-Z0-9-_ ]/g, '_')
      if (store.getState().assemblyActive) {
        await _importAsAssemblyPart(suggestedName)
      } else {
        _hideWelcome()
        workspace.hide()
        await _saveAs()
      }
    }
    input.click()
  })

  // ── Import PDB ──────────────────────────────────────────────���─────────────────
  document.getElementById('menu-file-import-pdb')?.addEventListener('click', () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.pdb'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const content = await file.text()
      const merge = !!store.getState().currentDesign
      _resetForNewDesign()
      const result = await api.importPdbDesign(content, merge)
      if (!result) {
        alert('Failed to import PDB file: ' + (store.getState().lastError?.message ?? 'Unknown error'))
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

  // ── Export GROMACS complete package (background job) ─────────────────────────
  {
    const toast   = document.getElementById('gromacs-job-toast')
    const label   = document.getElementById('gromacs-job-label')
    const dlBtn   = document.getElementById('gromacs-job-download')
    const dismiss = document.getElementById('gromacs-job-dismiss')

    dismiss?.addEventListener('click', () => { toast.className = '' })

    // ── GROMACS export dialog ─────────────────────────────────────────────────
    const gmxModal   = document.getElementById('gromacs-export-modal')
    const gmxName    = document.getElementById('gmx-export-name')
    const gmxSteps   = document.getElementById('gmx-export-nvt-steps')
    const gmxSolvate = document.getElementById('gmx-export-solvate')
    const gmxIonsRow = document.getElementById('gmx-export-ions-row')

    gmxSolvate?.addEventListener('change', () => {
      if (gmxIonsRow) gmxIonsRow.style.display = gmxSolvate.checked ? 'block' : 'none'
      // Update NVT steps default: 50 000 (100 ps) for solvated, 25 000 (50 ps) for vacuum
      if (gmxSteps) {
        const current = parseInt(gmxSteps.value, 10)
        if (gmxSolvate.checked && current === 25000) gmxSteps.value = '50000'
        else if (!gmxSolvate.checked && current === 50000) gmxSteps.value = '25000'
      }
    })

    document.getElementById('gmx-export-cancel')?.addEventListener('click', () => {
      if (gmxModal) gmxModal.style.display = 'none'
    })

    gmxModal?.addEventListener('click', e => {
      if (e.target === gmxModal) gmxModal.style.display = 'none'
    })

    document.getElementById('gmx-export-confirm')?.addEventListener('click', async () => {
      if (gmxModal) gmxModal.style.display = 'none'

      const packageName  = gmxName?.value.trim() || undefined
      const useDeformed  = document.querySelector('input[name="gmx-export-positions"]:checked')?.value === 'deformed'
      const nvtSteps     = parseInt(gmxSteps?.value ?? '', 10) || undefined
      const useCG        = document.getElementById('gmx-export-use-cg')?.checked ?? false

      // If a job is already running, don't start a second one
      if (toast.classList.contains('visible') && !toast.classList.contains('done') && !toast.classList.contains('error')) return

      // Reset to running state
      toast.className = 'visible'
      label.textContent = useCG ? 'Running oxDNA pre-relax…' : 'Building package…'
      dlBtn.onclick = null

      const params = new URLSearchParams()
      if (packageName) params.set('package_name', packageName)
      if (!useCG) params.set('use_deformed', String(useDeformed))
      if (nvtSteps !== undefined) params.set('nvt_steps', String(nvtSteps))

      const endpoint = useCG ? 'gromacs-cg-start' : 'gromacs-start'

      let jobId
      try {
        const r = await fetch(`/api/design/export/${endpoint}?${params}`, { method: 'POST' })
        if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).detail) ?? r.statusText)
        jobId = (await r.json()).job_id
      } catch (err) {
        toast.className = 'visible error'
        label.textContent = `Failed to start: ${err.message}`
        return
      }

      const poll = async () => {
        try {
          const r = await fetch(`/api/design/export/gromacs-status/${jobId}`)
          if (!r.ok) throw new Error('Status check failed')
          const { status, error, name } = await r.json()

          if (status === 'done') {
            toast.className = 'visible done'
            label.textContent = 'Package ready'
            dlBtn.onclick = async () => {
              const res = await fetch(`/api/design/export/gromacs-result/${jobId}`)
              if (!res.ok) { label.textContent = 'Download failed'; return }
              const blob = await res.blob()
              const url  = URL.createObjectURL(blob)
              const a    = document.createElement('a')
              a.href = url
              a.download = `${name}_gromacs.zip`
              a.click()
              URL.revokeObjectURL(url)
              setTimeout(() => { if (toast.classList.contains('done')) toast.className = '' }, 1200)
            }
          } else if (status === 'error') {
            toast.className = 'visible error'
            label.textContent = error ?? 'Export failed'
          } else {
            setTimeout(poll, 2000)
          }
        } catch (err) {
          toast.className = 'visible error'
          label.textContent = err.message
        }
      }

      setTimeout(poll, 2000)
    })

    // Open the dialog when the menu item is clicked
    document.getElementById('menu-file-export-gromacs-complete')?.addEventListener('click', () => {
      const { currentDesign } = store.getState()
      if (!currentDesign) { alert('No design loaded.'); return }

      // Pre-populate name from current design
      if (gmxName) gmxName.value = (currentDesign.metadata?.name || '').replace(/\s+/g, '_')
      if (gmxModal) gmxModal.style.display = 'flex'
    })
  }

  // ── Unified representation radio ──────────────────────────────────────────────
  // All six representations are mutually exclusive.  Exactly one is active at
  // a time; switching to any one deactivates all others.
  //
  //  'full'      — CG beads + slabs (LOD 0)
  //  'beads'     — CG beads only    (LOD 1)
  //  'cylinders' — domain cylinders (LOD 2)
  //  'vdw'       — atomistic VDW space-fill
  //  'ballstick' — atomistic ball-and-stick
  //  'surface'   — molecular surface

  const _ALL_REPRS = [
    { id: 'menu-view-detail-full',        repr: 'full'      },
    { id: 'menu-view-detail-beads',       repr: 'beads'     },
    { id: 'menu-view-detail-cylinders',   repr: 'cylinders' },
    { id: 'menu-view-atomistic-vdw',      repr: 'vdw'       },
    { id: 'menu-view-atomistic-ballstick',repr: 'ballstick' },
    { id: 'menu-view-surface',            repr: 'surface'    },
    { id: 'menu-view-hull-prism',         repr: 'hull-prism' },
  ]

  // Keep a forward-compat alias so any remaining call sites still work.
  function _updateAtomisticRadio() {}  // no-op — superseded by _updateReprRadio

  function _updateReprRadio(activeRepr) {
    for (const { id, repr } of _ALL_REPRS) {
      document.getElementById(id)?.classList.toggle('is-checked', repr === activeRepr)
    }
    _updateColoringMenuAvailability(activeRepr)
  }

  // Per-representation support matrix for the View → Coloring submenu.
  // Cylinders span multiple bps so 'base' is meaningless there; CPK is only
  // meaningful on atomistic; Hull Prism has no per-strand colour at all.
  // Surface vertices are keyed by strand_id only (no per-bp letter), so 'base'
  // is unsupported there; 'cluster' rides on the strand→cluster colour map.
  const _COLORING_SUPPORT = {
    'full':       new Set(['strand', 'base', 'cluster']),
    'beads':      new Set(['strand', 'base', 'cluster']),
    'cylinders':  new Set(['strand', 'cluster']),
    'vdw':        new Set(['strand', 'base', 'cluster', 'cpk']),
    'ballstick':  new Set(['strand', 'base', 'cluster', 'cpk']),
    'surface':    new Set(['strand', 'cluster']),
    'hull-prism': new Set(),
  }

  function _updateColoringMenuAvailability(activeRepr) {
    const supported = _COLORING_SUPPORT[activeRepr] ?? new Set(['strand', 'base', 'cluster'])
    const map = {
      strand:  'menu-view-coloring-strand',
      base:    'menu-view-coloring-base',
      cluster: 'menu-view-coloring-cluster',
      cpk:     'menu-view-coloring-cpk',
    }
    for (const [mode, id] of Object.entries(map)) {
      const el = document.getElementById(id)
      if (!el) continue
      el.disabled = !supported.has(mode)
    }
    // If the active mode is no longer supported, fall back to strand so the
    // menu's checkmark always reflects an enabled item.  Hull Prism supports
    // nothing — leave the mode untouched there.
    const current = store.getState().coloringMode || 'strand'
    if (!supported.has(current) && supported.has('strand')) {
      _setColoringMode('strand')
    }
  }

  function _reprOptionSliders(repr) {
    document.getElementById('repr-bead-radius-row')?.style.setProperty(
      'display', (repr === 'full' || repr === 'beads') ? '' : 'none')
    document.getElementById('repr-cyl-radius-row')?.style.setProperty(
      'display', repr === 'cylinders' ? '' : 'none')
    _setAtomisticSlidersVisible(repr === 'vdw' || repr === 'ballstick')
    _setSurfacePanelVisible(repr === 'surface')
  }

  async function _setRepresentation(repr) {
    // ── Deactivate any currently active exclusive mode ────────────────────────
    if (repr !== 'vdw' && repr !== 'ballstick' && atomisticRenderer.getMode() !== 'off') {
      atomisticRenderer.setMode('off')
      store.setState({ atomisticMode: 'off' })
    }
    if (repr !== 'surface' && _surfaceMode !== 'off') {
      _applySurfaceMode('off')
      store.setState({ surfaceMode: 'off' })
    }
    if (repr !== 'hull-prism') {
      jointRenderer?.setHullRepr(false)
    }

    // ── Activate the new representation ──────────────────────────────────────
    if (repr === 'full' || repr === 'beads' || repr === 'cylinders') {
      _setCGVisible(true)
      const lvl = { full: 0, beads: 1, cylinders: 2 }[repr]
      overhangLinkArcs?.setRepresentation?.(repr)
      if (lvl !== _lastDetailLevel) {
        _lastDetailLevel = lvl
        _lodMode = repr
        designRenderer.setDetailLevel(lvl)
        unfoldView?.setArcsVisible(lvl < 2)
      }
    } else if (repr === 'vdw' || repr === 'ballstick') {
      await _applyAtomisticMode(repr)
      store.setState({ atomisticMode: repr })
    } else if (repr === 'surface') {
      await _applySurfaceMode('on')
      store.setState({ surfaceMode: 'on' })
    } else if (repr === 'hull-prism') {
      _setCGVisible(false)
      jointRenderer?.setHullRepr(true)
    }

    _updateReprRadio(repr)
    _reprOptionSliders(repr)
  }

  for (const { id, repr } of _ALL_REPRS) {
    document.getElementById(id)?.addEventListener('click', async () => {
      const { currentDesign, assemblyActive, currentAssembly } = store.getState()

      // ── Assembly mode: apply repr to all instances ───────────────────────────
      if (assemblyActive) {
        const instances = currentAssembly?.instances ?? []
        if (!instances.length) return

        if (repr === 'surface') {
          alert('Surface representation is not supported for assembly parts.')
          return
        }
        if (repr === 'vdw' || repr === 'ballstick') {
          const ok = window.confirm(
            'Atomistic rendering will be computed for every part in the assembly and ' +
            'can be slow for large designs.\n\nApply anyway?'
          )
          if (!ok) return
        }

        _updateReprRadio(repr)
        await Promise.all(instances.map(inst => api.patchInstance(inst.id, { representation: repr })))
        return
      }

      // ── Design mode: existing single-design behaviour ────────────────────────
      if (!currentDesign) { alert('No design loaded.'); return }
      await _setRepresentation(repr)
    })
  }

  // Initial availability (default repr = 'full' per HTML is-checked).
  _updateColoringMenuAvailability('full')

  // ── Representation option sliders ─────────────────────────────────────────────
  const _slBeadRadius = document.getElementById('sl-bead-radius')
  const _svBeadRadius = document.getElementById('sv-bead-radius')
  _slBeadRadius?.addEventListener('input', () => {
    const r = parseFloat(_slBeadRadius.value)
    _currentBeadRadius = r
    if (_svBeadRadius) _svBeadRadius.textContent = r.toFixed(2)
    if (_lodMode === 'full' || _lodMode === 'beads') designRenderer.setBeadRadius(r)
  })

  const _slCylRadius = document.getElementById('sl-cyl-radius')
  const _svCylRadius = document.getElementById('sv-cyl-radius')
  _slCylRadius?.addEventListener('input', () => {
    const r = parseFloat(_slCylRadius.value)
    if (_svCylRadius) _svCylRadius.textContent = r.toFixed(2)
    if (_lodMode === 'cylinders') designRenderer.setCylinderRadius(r)
  })

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

  document.getElementById('menu-view-overhang-names')?.addEventListener('click', () => {
    const { showOverhangNames } = store.getState()
    store.setState({ showOverhangNames: !showOverhangNames })
    _setMenuToggle('menu-view-overhang-names', !showOverhangNames)
  })

  // ── Highlight Undefined Bases toggle ─────────────────────────────────────────
  let _undefinedHighlightOn = false

  function _refreshUndefinedHighlight() {
    const { currentDesign } = store.getState()
    if (!currentDesign) { designRenderer.clearUndefinedHighlight(); return }

    // Build loop/skip map: "helixId:bp" → delta
    const lsMap = new Map()
    for (const helix of currentDesign.helices ?? []) {
      for (const ls of helix.loop_skips ?? []) {
        lsMap.set(`${helix.id}:${ls.bp_index}`, ls.delta)
      }
    }

    // Build a set of strand IDs with no sequence, and a set of "helixId:bp" keys
    // where the assigned character is 'N' (skip/loop-aware).
    const nullStrandIds = new Set()
    const nPosKeys      = new Set()

    for (const strand of currentDesign.strands ?? []) {
      if (!strand.sequence) {
        nullStrandIds.add(strand.id)
      } else {
        let seqIdx = 0
        for (const domain of strand.domains ?? []) {
          // Overhang domains: sequence is from overhang spec, not helix bp positions.
          // Advance seqIdx by domain length and skip position-level checking.
          if (domain.overhang_id != null) {
            seqIdx += Math.abs(domain.end_bp - domain.start_bp) + 1
            continue
          }
          const isForward = domain.direction === 'FORWARD'
          const step      = isForward ? 1 : -1
          const endBp     = domain.end_bp + step   // exclusive sentinel
          for (let bp = domain.start_bp; bp !== endBp; bp += step) {
            const delta = lsMap.get(`${domain.helix_id}:${bp}`) ?? 0
            if (delta <= -1) continue   // skip — no nucleotide in sequence
            const nCopies = delta + 1   // 1 for normal bp, 2 for loop (+1)
            let isN = false
            for (let c = 0; c < nCopies; c++) {
              if (strand.sequence[seqIdx] === 'N') isN = true
              seqIdx++
            }
            if (isN) nPosKeys.add(`${domain.helix_id}:${bp}`)
          }
        }
      }
    }

    const entries = designRenderer.getBackboneEntries().filter(entry => {
      if (nullStrandIds.has(entry.nuc?.strand_id)) return true
      if (nPosKeys.has(`${entry.nuc?.helix_id}:${entry.nuc?.bp_index}`)) return true
      return false
    })

    if (entries.length > 0) {
      designRenderer.setUndefinedHighlight(entries)
    } else {
      designRenderer.clearUndefinedHighlight()
    }
  }

  document.getElementById('menu-view-undefined-bases')?.addEventListener('click', () => {
    _undefinedHighlightOn = !_undefinedHighlightOn
    _setMenuToggle('menu-view-undefined-bases', _undefinedHighlightOn)
    if (_undefinedHighlightOn) {
      _refreshUndefinedHighlight()
    } else {
      designRenderer.clearUndefinedHighlight()
    }
  })

  // Refresh undefined highlight whenever the design changes (if toggle is on).
  store.subscribe((newState, prevState) => {
    if (_undefinedHighlightOn && newState.currentDesign !== prevState.currentDesign) {
      _refreshUndefinedHighlight()
    }
  })

  // ── Fluorescence + FRET Checker ──────────────────────────────────────────────
  let _fluorescenceOn = false
  let _fretOn         = false

  // Förster radii (nm) for donor→acceptor pairs supported by NADOC modifications.
  const _FRET_PAIRS = [
    { donor: 'cy3',     acceptor: 'cy5',     r0: 5.4 },
    { donor: 'fam',     acceptor: 'tamra',   r0: 4.6 },
    { donor: 'atto488', acceptor: 'atto550', r0: 6.3 },
    { donor: 'fam',     acceptor: 'bhq1',    r0: 4.2 },
    { donor: 'fam',     acceptor: 'bhq2',    r0: 4.2 },
    { donor: 'cy3',     acceptor: 'bhq2',    r0: 4.5 },
    { donor: 'tamra',   acceptor: 'bhq2',    r0: 4.5 },
  ]
  // Build donor → [acceptor list] and pair → r0 lookup tables.
  const _FRET_DONOR_MAP = new Map()  // donor mod key → [acceptor mod keys]
  const _FRET_R0_MAP    = new Map()  // "donor:acceptor" → r0 (nm)
  for (const { donor, acceptor, r0 } of _FRET_PAIRS) {
    if (!_FRET_DONOR_MAP.has(donor)) _FRET_DONOR_MAP.set(donor, [])
    _FRET_DONOR_MAP.get(donor).push(acceptor)
    _FRET_R0_MAP.set(`${donor}:${acceptor}`, r0)
  }

  // Sprite scale for a donor whose energy is being transferred (≈3 nm diameter).
  const _FRET_QUENCHED_SCALE = 3

  /**
   * Return the set of fluoroEntries that are donors currently within their
   * Förster radius of at least one compatible acceptor.
   */
  function _fretQuenchedDonors(allEntries) {
    const quenched = new Set()
    for (const entry of allEntries) {
      const mod          = entry.nuc?.modification
      const acceptorKeys = _FRET_DONOR_MAP.get(mod)
      if (!acceptorKeys) continue
      for (const other of allEntries) {
        if (other === entry) continue
        const otherMod = other.nuc?.modification
        if (!otherMod) continue
        const r0 = _FRET_R0_MAP.get(`${mod}:${otherMod}`)
        if (r0 === undefined) continue
        if (entry.pos.distanceTo(other.pos) <= r0) { quenched.add(entry); break }
      }
    }
    return quenched
  }

  /**
   * Unified glow refresh for Fluorescence and FRET Checker modes.
   * Fluorescence: all fluorophores glow at full size (10 nm radius).
   * FRET: same, but donors within Förster radius of a compatible acceptor
   *       are shown at ~1.5 nm radius (scale 3) to indicate energy transfer.
   * Both modes share one setFluorescenceGlow() call; FRET takes priority on scale.
   */
  function _refreshGlowModes() {
    if (!_fluorescenceOn && !_fretOn) { designRenderer.clearFluorescenceGlow(); return }

    const all      = designRenderer.getFluoroEntries()   // includes BHQ/Biotin for distance checks
    const quenched = _fretOn ? _fretQuenchedDonors(all) : new Set()

    const entries = all
      .filter(fe => FLUORO_EMISSION_COLORS.has(fe.nuc?.modification))
      .map(fe => ({
        pos:          fe.pos,
        emissionColor: FLUORO_EMISSION_COLORS.get(fe.nuc.modification),
        scale:        quenched.has(fe) ? _FRET_QUENCHED_SCALE : undefined,
      }))

    if (entries.length > 0) designRenderer.setFluorescenceGlow(entries)
    else                    designRenderer.clearFluorescenceGlow()
  }

  document.getElementById('menu-view-fluorescence')?.addEventListener('click', () => {
    _fluorescenceOn = !_fluorescenceOn
    _setMenuToggle('menu-view-fluorescence', _fluorescenceOn)
    _refreshGlowModes()
  })

  document.getElementById('menu-view-fret')?.addEventListener('click', () => {
    _fretOn = !_fretOn
    _setMenuToggle('menu-view-fret', _fretOn)
    _refreshGlowModes()
  })

  document.getElementById('menu-view-joints')?.addEventListener('click', () => {
    const on = !jointRenderer?.isVisible()
    jointRenderer?.setVisible(on)
    _setMenuToggle('menu-view-joints', on)
  })

  // Rebuild glow whenever the geometry reloads while either mode is on.
  store.subscribe((newState, prevState) => {
    if ((_fluorescenceOn || _fretOn) && newState.currentGeometry !== prevState.currentGeometry) {
      _refreshGlowModes()
    }
  })

  // ── Help / Hotkeys modal ─────────────────────────────────────────────────────
  const helpModal = document.getElementById('help-modal')
  document.getElementById('menu-help-hotkeys')?.addEventListener('click', () => helpModal.classList.add('visible'))
  document.getElementById('help-modal-close')?.addEventListener('click', () => helpModal.classList.remove('visible'))
  helpModal?.addEventListener('click', e => { if (e.target === helpModal) helpModal.classList.remove('visible') })

  function _logOvhgMapReport() {
    const n = _ovhgSpecMap.size
    console.group(`[OH roots] Lookup table report  (${n} overhangs)`)
    console.log(`  1. specMap      ${n}/${n}`)

    // Map 2 cross-validation
    console.log(`  2. domainMap    ${_ovhgDomainMap.size}/${n}  (design path)  ` +
      `geom path: ${_xval_domainGeo.size}`)
    const dom2Fail = []
    for (const [id, de] of _ovhgDomainMap) {
      const ge = _xval_domainGeo.get(id)
      if (!ge) { dom2Fail.push(`${id}: geom path missed it`); continue }
      if (ge.domIdx !== de.domIdx) dom2Fail.push(`${id}: design domIdx=${de.domIdx} geom domIdx=${ge.domIdx}`)
    }
    for (const id of _xval_domainGeo.keys())
      if (!_ovhgDomainMap.has(id)) dom2Fail.push(`${id}: only geom path found it`)
    if (dom2Fail.length) console.warn('    domain xval mismatches:', dom2Fail)
    else console.log('    domain xval: OK')

    const missingDomain = [..._ovhgSpecMap.keys()].filter(id => !_ovhgDomainMap.has(id))
    if (missingDomain.length)
      console.warn(`    missing from domainMap (${missingDomain.length}):`, missingDomain)

    // Map 3 cross-validation
    console.log(`  3. junctionMap  ${_ovhgJunctionMap.size}/${n}  (domain-endpoint path)  ` +
      `crossover path: ${_xval_junctionXover.size}`)
    const jx3Fail = []
    for (const [id, dv] of _ovhgJunctionMap) {
      const xv = _xval_junctionXover.get(id)
      if (!xv) { jx3Fail.push(`${id}: crossover path missed it`); continue }
      if (xv.junctionBp !== dv.junctionBp || xv.junctionDir !== dv.junctionDir)
        jx3Fail.push(`${id}: domain=(${dv.junctionBp},${dv.junctionDir}) xover=(${xv.junctionBp},${xv.junctionDir})`)
    }
    for (const [id, xv] of _xval_junctionXover)
      if (!_ovhgJunctionMap.has(id))
        jx3Fail.push(`${id}: only crossover path found it  (bp=${xv.junctionBp},dir=${xv.junctionDir})`)
    if (jx3Fail.length) console.warn('    junction xval mismatches:', jx3Fail)
    else console.log('    junction xval: OK')

    const missingJunction = [..._ovhgDomainMap.keys()].filter(id => !_ovhgJunctionMap.has(id))
    if (missingJunction.length)
      console.warn(`    missing from junctionMap (${missingJunction.length}):`, missingJunction)

    // Map 4
    console.log(`  4. rootMap      ${_ovhgRootMap.size}/${n}`)
    const missingRoot = [..._ovhgJunctionMap.keys()].filter(id => !_ovhgRootMap.has(id))
    if (missingRoot.length)
      console.warn(`    missing from rootMap (${missingRoot.length}):`, missingRoot)

    console.groupEnd()
  }

  document.getElementById('menu-help-oh-roots')?.addEventListener('click', function () {
    _ohRootsGlowActive = !_ohRootsGlowActive
    this.textContent = _ohRootsGlowActive ? 'Hide OH Roots' : 'Show OH Roots'
    if (_ohRootsGlowActive) { _applyOhRootsGlow(); _logOvhgMapReport() }
    else designRenderer.clearGlow()
  })

  document.getElementById('menu-show-domain-ends')?.addEventListener('click', function () {
    _domainEndsGlowActive = !_domainEndsGlowActive
    this.textContent = _domainEndsGlowActive ? 'Hide Domain Ends' : 'Show Domain Ends'
    if (_domainEndsGlowActive) _applyDomainEndsGlow()
    else designRenderer.clearGlow()
  })

  document.getElementById('menu-help-linker-debug')?.addEventListener('click', function () {
    const next = !linkerAnchorDebug.isVisible()
    linkerAnchorDebug.setVisible(next)
    this.textContent = next ? 'Hide Linker Anchor Debug' : 'Show Linker Anchor Debug'
  })

  document.getElementById('menu-help-fjc-sim')?.addEventListener('click', async () => {
    // Lazy-load the modal so the dev bundle stays slim until the user opens it.
    const { showLinkerConfigModal } = await import('./ui/linker_config_modal.js')
    showLinkerConfigModal({ readOnly: true })
  })

  document.getElementById('menu-create-seam')?.addEventListener('click', async function () {
    const design = store.getState().currentDesign
    if (!design) return

    const isHC = design.lattice_type === 'HONEYCOMB'
    const period = isHC ? 21 : 32

    // Scaffold crossover lookup tables (mirrors pathview.js constants)
    const HC_SCAF_XOVER_MAP = {
      '1_1':[ 0,+1],'1_2':[ 0,+1],'1_11':[ 0,+1],'1_12':[ 0,+1],
      '1_8':[-1, 0],'1_9':[-1, 0],'1_18':[-1, 0],'1_19':[-1, 0],
      '1_4':[ 0,-1],'1_5':[ 0,-1],'1_15':[ 0,-1],'1_16':[ 0,-1],
      '0_1':[ 0,-1],'0_2':[ 0,-1],'0_11':[ 0,-1],'0_12':[ 0,-1],
      '0_8':[+1, 0],'0_9':[+1, 0],'0_18':[+1, 0],'0_19':[+1, 0],
      '0_4':[ 0,+1],'0_5':[ 0,+1],'0_15':[ 0,+1],'0_16':[ 0,+1],
    }
    const SQ_SCAF_XOVER_MAP = {
      '1_4':[ 0,+1],'1_5':[ 0,+1],'1_15':[ 0,+1],'1_16':[ 0,+1],'1_26':[ 0,+1],'1_27':[ 0,+1],
      '1_7':[+1, 0],'1_8':[+1, 0],'1_18':[+1, 0],'1_19':[+1, 0],'1_28':[+1, 0],'1_29':[+1, 0],
      '1_0':[ 0,-1],'1_10':[ 0,-1],'1_11':[ 0,-1],'1_20':[ 0,-1],'1_21':[ 0,-1],'1_31':[ 0,-1],
      '1_2':[-1, 0],'1_3':[-1, 0],'1_12':[-1, 0],'1_13':[-1, 0],'1_23':[-1, 0],'1_24':[-1, 0],
      '0_4':[ 0,-1],'0_5':[ 0,-1],'0_15':[ 0,-1],'0_16':[ 0,-1],'0_26':[ 0,-1],'0_27':[ 0,-1],
      '0_7':[-1, 0],'0_8':[-1, 0],'0_18':[-1, 0],'0_19':[-1, 0],'0_28':[-1, 0],'0_29':[-1, 0],
      '0_0':[ 0,+1],'0_10':[ 0,+1],'0_11':[ 0,+1],'0_20':[ 0,+1],'0_21':[ 0,+1],'0_31':[ 0,+1],
      '0_2':[+1, 0],'0_3':[+1, 0],'0_12':[+1, 0],'0_13':[+1, 0],'0_23':[+1, 0],'0_24':[+1, 0],
    }
    // mods where bowDir=+1 (lowerBp = bp-1) — mirrors pathview.js _XOVER_BOW_RIGHT_*_SCAF
    const HC_SCAF_BOW_RIGHT = new Set([2,5,9,12,16,19])
    const SQ_SCAF_BOW_RIGHT = new Set([0,3,5,8,11,13,16,19,21,24,27,29])

    const xoverMap   = isHC ? HC_SCAF_XOVER_MAP  : SQ_SCAF_XOVER_MAP
    const bowRightSet = isHC ? HC_SCAF_BOW_RIGHT  : SQ_SCAF_BOW_RIGHT

    function isForward(row, col) { return (((row + col) % 2) + 2) % 2 === 0 }

    function scaffoldXoverNeighbor(row, col, bp) {
      const fwd = isForward(row, col)
      const mod = ((bp % period) + period) % period
      const d   = xoverMap[`${fwd ? 1 : 0}_${mod}`]
      return d ? [row + d[0], col + d[1]] : null
    }

    function nickBpForStrand(xoverBp, strand) {
      const mod     = ((xoverBp % period) + period) % period
      const lowerBp = bowRightSet.has(mod) ? xoverBp - 1 : xoverBp
      return strand === 'FORWARD' ? lowerBp : lowerBp + 1
    }

    // Build scaffold coverage map: helixId → [{lo, hi}] bp intervals from scaffold strands.
    // Intervals are merged post-collection so that scaffold strands already split by prior
    // seam crossovers collapse back into their original contiguous regions.
    const scaffoldCoverage = new Map()
    for (const s of design.strands) {
      if (s.strand_type !== 'scaffold') continue
      for (const d of s.domains) {
        const lo = Math.min(d.start_bp, d.end_bp)
        const hi = Math.max(d.start_bp, d.end_bp)
        if (!scaffoldCoverage.has(d.helix_id)) scaffoldCoverage.set(d.helix_id, [])
        scaffoldCoverage.get(d.helix_id).push({ lo, hi })
      }
    }
    // Merge overlapping or adjacent (gap ≤ 1 bp) intervals per helix.
    for (const [id, ivs] of scaffoldCoverage) {
      const s = ivs.slice().sort((a, b) => a.lo - b.lo)
      const m = [{ ...s[0] }]
      for (let i = 1; i < s.length; i++) {
        if (s[i].lo <= m[m.length - 1].hi + 1) m[m.length - 1].hi = Math.max(m[m.length - 1].hi, s[i].hi)
        else m.push({ ...s[i] })
      }
      scaffoldCoverage.set(id, m)
    }

    // Build lookups
    const helixByGridPos = new Map()
    const allHelixById = new Map()
    for (const h of design.helices) {
      allHelixById.set(h.id, h)
      if (h.grid_pos) helixByGridPos.set(`${h.grid_pos[0]}_${h.grid_pos[1]}`, h)
    }

    // Compute the intersection of two scaffold-coverage interval arrays.
    // Returns all overlapping sub-intervals, which define the bp range where a
    // Holliday junction between two helices is physically valid.
    function intersectCoverage(cA, cB) {
      const result = []
      for (const a of cA) {
        for (const b of cB) {
          const lo = Math.max(a.lo, b.lo)
          const hi = Math.min(a.hi, b.hi)
          if (lo <= hi) result.push({ lo, hi })
        }
      }
      return result
    }

    // Collect all scaffold helices that have a grid position.
    const scaffoldHelices = []
    for (const [helixId] of scaffoldCoverage) {
      const h = allHelixById.get(helixId)
      if (h?.grid_pos) scaffoldHelices.push(h)
    }

    // Build a global adjacency graph: edge between hA and hB exists if there is at
    // least one bp that (a) lies in the intersection of their scaffold coverage and
    // (b) is a valid HC/SQ scaffold crossover from hA to hB.
    // This naturally produces cross-section-change edges (arm ↔ core) alongside
    // same-section edges, so a single Hamiltonian path handles all structure types.
    const globalAdj = new Map(scaffoldHelices.map(h => [h.id, new Set()]))
    for (let ai = 0; ai < scaffoldHelices.length; ai++) {
      const hA = scaffoldHelices[ai]
      const [rowA, colA] = hA.grid_pos
      const covA = scaffoldCoverage.get(hA.id)
      for (let bi = ai + 1; bi < scaffoldHelices.length; bi++) {
        const hB = scaffoldHelices[bi]
        if (!hB.grid_pos) continue
        const covB = scaffoldCoverage.get(hB.id)
        const overlap = intersectCoverage(covA, covB)
        if (!overlap.length) continue
        let found = false
        outer: for (const { lo, hi } of overlap) {
          for (let bp = lo; bp <= hi; bp++) {
            const nb = scaffoldXoverNeighbor(rowA, colA, bp)
            if (nb && nb[0] === hB.grid_pos[0] && nb[1] === hB.grid_pos[1]) { found = true; break outer }
          }
        }
        if (found) {
          globalAdj.get(hA.id).add(hB.id)
          globalAdj.get(hB.id).add(hA.id)
        }
      }
    }

    // Find connected components (handles fully-disconnected sub-structures).
    const _visited = new Set()
    const components = []
    for (const h of scaffoldHelices) {
      if (_visited.has(h.id)) continue
      const comp = []
      const stack = [h.id]
      while (stack.length) {
        const id = stack.pop()
        if (_visited.has(id)) continue
        _visited.add(id); comp.push(id)
        for (const nb of globalAdj.get(id)) { if (!_visited.has(nb)) stack.push(nb) }
      }
      components.push(comp)
    }

    // Hamiltonian path via DFS with degree-ascending neighbor ordering.
    // startFrom, if provided, is tried as the first starting candidate.
    const findHamiltonianPath = (ids, adjMap, startFrom = null) => {
      const vis = new Set(), p = []
      const dfs = id => {
        vis.add(id); p.push(id)
        if (p.length === ids.length) return true
        const nbs = [...adjMap.get(id)].filter(nb => !vis.has(nb))
          .sort((a, b) => adjMap.get(a).size - adjMap.get(b).size)
        for (const nb of nbs) { if (dfs(nb)) return true }
        vis.delete(id); p.pop(); return false
      }
      const sorted = [...ids].sort((a, b) => adjMap.get(a).size - adjMap.get(b).size)
      const starters = startFrom != null
        ? [startFrom, ...sorted.filter(id => id !== startFrom)]
        : sorted
      for (const s of starters) { if (dfs(s)) return p }
      return null
    }

    const placements = []

    for (const comp of components) {
      if (comp.length < 4) continue

      // Group helices by coverage signature (sorted lo:hi intervals).
      // In a dumbbell, arm helices and core helices have different signatures and must
      // be chained via exactly one bridge edge so each arm has exactly one rail.
      const covSig = id => scaffoldCoverage.get(id)
        .slice().sort((a, b) => a.lo - b.lo).map(({lo, hi}) => `${lo}:${hi}`).join('|')
      const sigMap = new Map()
      for (const id of comp) {
        const sig = covSig(id)
        if (!sigMap.has(sig)) sigMap.set(sig, [])
        sigMap.get(sig).push(id)
      }
      const groups = [...sigMap.values()]

      let path
      if (groups.length === 1) {
        path = findHamiltonianPath(comp, globalAdj)
      } else {
        // Multi-section design (dumbbell etc.).
        // Sort groups ascending by total scaffold bp so arm groups come before core.
        groups.sort((a, b) => {
          const bp = ids => scaffoldCoverage.get(ids[0]).reduce((s, {lo, hi}) => s + hi - lo + 1, 0)
          return bp(a) - bp(b)
        })

        // Local adjacency within each group (no cross-group edges).
        const localAdjs = groups.map(grpIds => {
          const idSet = new Set(grpIds)
          const adj = new Map(grpIds.map(id => [id, new Set()]))
          for (const id of grpIds)
            for (const nb of globalAdj.get(id))
              if (idSet.has(nb)) adj.get(id).add(nb)
          return adj
        })

        // Chain: find path within arm group, orient its bridge endpoint last,
        // then find path within core group starting from the bridge core helix.
        // This gives: arm_rail…arm_bridge | core_bridge…core_rail
        // producing exactly 1 outer rail, 1 outer↔outer pair, 1 outer↔core junction.
        path = findHamiltonianPath(groups[0], localAdjs[0]) ?? groups[0].slice()
        for (let gi = 1; gi < groups.length; gi++) {
          const nextIds  = groups[gi]
          const nextSet  = new Set(nextIds)

          // Orient current path so its last element has a cross-group edge into nextIds.
          const endHasEdge = id => [...(globalAdj.get(id) ?? [])].some(nb => nextSet.has(nb))
          if (!endHasEdge(path[path.length - 1]) && endHasEdge(path[0])) path.reverse()

          const bridgeCore = [...(globalAdj.get(path[path.length - 1]) ?? [])].find(nb => nextSet.has(nb))
          if (bridgeCore) {
            // Find path in next group starting at the bridge core helix.
            let nextPath = findHamiltonianPath(nextIds, localAdjs[gi], bridgeCore)
              ?? findHamiltonianPath(nextIds, localAdjs[gi])
            if (nextPath && nextPath[0] !== bridgeCore) nextPath.reverse()
            path = [...path, ...(nextPath ?? nextIds)]
          } else {
            path = [...path, ...(findHamiltonianPath(nextIds, localAdjs[gi]) ?? nextIds)]
          }
        }
      }

      if (!path || path.length < 4) {
        console.warn(`[CreateSeam] No Hamiltonian path for component of ${comp.length} helices`)
        continue
      }

      // path[0] and path[last] are rails. Interior consecutive pairs get Holliday junctions.
      for (let i = 1; i < path.length - 2; i += 2) {
        const hA = allHelixById.get(path[i])
        const hB = allHelixById.get(path[i + 1])
        if (!hA?.grid_pos || !hB?.grid_pos) continue

        const [rowA, colA] = hA.grid_pos
        const fwdA    = isForward(rowA, colA)
        const strandA = fwdA ? 'FORWARD' : 'REVERSE'
        const strandB = fwdA ? 'REVERSE' : 'FORWARD'

        // One Holliday junction per merged intersection interval.
        // Core↔core pairs have a single interval [0,N] → one junction.
        // Outer↔outer and bridge pairs have two intervals (one per arm) → one junction each.
        // Interval merging earlier ensures re-run split strands don't produce spurious extras.
        const covA = scaffoldCoverage.get(hA.id)
        const covB = scaffoldCoverage.get(hB.id)
        const overlap = intersectCoverage(covA, covB)
        if (!overlap.length) continue

        for (const { lo, hi } of overlap) {
          const intervalMid = Math.round((lo + hi) / 2)

          const validBps = []
          for (let bp = lo; bp <= hi; bp++) {
            const nb = scaffoldXoverNeighbor(rowA, colA, bp)
            if (nb && nb[0] === hB.grid_pos[0] && nb[1] === hB.grid_pos[1]) validBps.push(bp)
          }
          if (validBps.length < 2) continue

          let bp1 = validBps[0], bp2 = validBps[1], bestDist = Infinity
          for (let j = 0; j < validBps.length - 1; j++) {
            if (validBps[j + 1] === validBps[j] + 1) {
              const dist = Math.abs((validBps[j] + validBps[j + 1]) / 2 - intervalMid)
              if (dist < bestDist) { bestDist = dist; bp1 = validBps[j]; bp2 = validBps[j + 1] }
            }
          }
          if (bestDist === Infinity) continue

          for (const xoverBp of [bp1, bp2]) {
            placements.push({
              halfA: { helix_id: hA.id, index: xoverBp, strand: strandA },
              halfB: { helix_id: hB.id, index: xoverBp, strand: strandB },
              nickBpA: nickBpForStrand(xoverBp, strandA),
              nickBpB: nickBpForStrand(xoverBp, strandB),
            })
          }
        }
      }
    }

    if (placements.length > 0) await api.placeCrossoverBatch(placements)
  })

  // ── Create Near Ends ──────────────────────────────────────────────────────────
  // Places Holliday junctions at the near (-Z) face of the bundle between
  // adjacent helix pairs that do NOT already have seam crossovers.  Extends the
  // helix and scaffold domain at the near end by 4 bp below the crossover site.
  document.getElementById('menu-create-near-ends')?.addEventListener('click', async function () {
    const design = store.getState().currentDesign
    if (!design) return

    const isHC = design.lattice_type === 'HONEYCOMB'
    const period = isHC ? 21 : 32

    // Reuse the same lookup tables and helpers as Create Seam.
    const HC_SCAF_XOVER_MAP = {
      '1_1':[ 0,+1],'1_2':[ 0,+1],'1_11':[ 0,+1],'1_12':[ 0,+1],
      '1_8':[-1, 0],'1_9':[-1, 0],'1_18':[-1, 0],'1_19':[-1, 0],
      '1_4':[ 0,-1],'1_5':[ 0,-1],'1_15':[ 0,-1],'1_16':[ 0,-1],
      '0_1':[ 0,-1],'0_2':[ 0,-1],'0_11':[ 0,-1],'0_12':[ 0,-1],
      '0_8':[+1, 0],'0_9':[+1, 0],'0_18':[+1, 0],'0_19':[+1, 0],
      '0_4':[ 0,+1],'0_5':[ 0,+1],'0_15':[ 0,+1],'0_16':[ 0,+1],
    }
    const SQ_SCAF_XOVER_MAP = {
      '1_4':[ 0,+1],'1_5':[ 0,+1],'1_15':[ 0,+1],'1_16':[ 0,+1],'1_26':[ 0,+1],'1_27':[ 0,+1],
      '1_7':[+1, 0],'1_8':[+1, 0],'1_18':[+1, 0],'1_19':[+1, 0],'1_28':[+1, 0],'1_29':[+1, 0],
      '1_0':[ 0,-1],'1_10':[ 0,-1],'1_11':[ 0,-1],'1_20':[ 0,-1],'1_21':[ 0,-1],'1_31':[ 0,-1],
      '1_2':[-1, 0],'1_3':[-1, 0],'1_12':[-1, 0],'1_13':[-1, 0],'1_23':[-1, 0],'1_24':[-1, 0],
      '0_4':[ 0,-1],'0_5':[ 0,-1],'0_15':[ 0,-1],'0_16':[ 0,-1],'0_26':[ 0,-1],'0_27':[ 0,-1],
      '0_7':[-1, 0],'0_8':[-1, 0],'0_18':[-1, 0],'0_19':[-1, 0],'0_28':[-1, 0],'0_29':[-1, 0],
      '0_0':[ 0,+1],'0_10':[ 0,+1],'0_11':[ 0,+1],'0_20':[ 0,+1],'0_21':[ 0,+1],'0_31':[ 0,+1],
      '0_2':[+1, 0],'0_3':[+1, 0],'0_12':[+1, 0],'0_13':[+1, 0],'0_23':[+1, 0],'0_24':[+1, 0],
    }
    const HC_SCAF_BOW_RIGHT = new Set([2,5,9,12,16,19])
    const SQ_SCAF_BOW_RIGHT = new Set([0,3,5,8,11,13,16,19,21,24,27,29])

    const xoverMap    = isHC ? HC_SCAF_XOVER_MAP : SQ_SCAF_XOVER_MAP
    const bowRightSet = isHC ? HC_SCAF_BOW_RIGHT  : SQ_SCAF_BOW_RIGHT

    function isForward(row, col) { return (((row + col) % 2) + 2) % 2 === 0 }

    function scaffoldXoverNeighbor(row, col, bp) {
      const fwd = isForward(row, col)
      const mod = ((bp % period) + period) % period
      const d   = xoverMap[`${fwd ? 1 : 0}_${mod}`]
      return d ? [row + d[0], col + d[1]] : null
    }

    function nickBpForStrand(xoverBp, strand) {
      const mod     = ((xoverBp % period) + period) % period
      const lowerBp = bowRightSet.has(mod) ? xoverBp - 1 : xoverBp
      return strand === 'FORWARD' ? lowerBp : lowerBp + 1
    }

    // Build scaffold coverage map with interval merging (same as Create Seam).
    const scaffoldCoverage = new Map()
    for (const s of design.strands) {
      if (s.strand_type !== 'scaffold') continue
      for (const d of s.domains) {
        const lo = Math.min(d.start_bp, d.end_bp)
        const hi = Math.max(d.start_bp, d.end_bp)
        if (!scaffoldCoverage.has(d.helix_id)) scaffoldCoverage.set(d.helix_id, [])
        scaffoldCoverage.get(d.helix_id).push({ lo, hi })
      }
    }
    for (const [id, ivs] of scaffoldCoverage) {
      const s = ivs.slice().sort((a, b) => a.lo - b.lo)
      const m = [{ ...s[0] }]
      for (let i = 1; i < s.length; i++) {
        if (s[i].lo <= m[m.length - 1].hi + 1) m[m.length - 1].hi = Math.max(m[m.length - 1].hi, s[i].hi)
        else m.push({ ...s[i] })
      }
      scaffoldCoverage.set(id, m)
    }

    const allHelixById   = new Map()
    const helixByGridPos = new Map()
    for (const h of design.helices) {
      allHelixById.set(h.id, h)
      if (h.grid_pos) helixByGridPos.set(`${h.grid_pos[0]}_${h.grid_pos[1]}`, h)
    }

    function intersectCoverage(cA, cB) {
      const result = []
      for (const a of cA) {
        for (const b of cB) {
          const lo = Math.max(a.lo, b.lo)
          const hi = Math.min(a.hi, b.hi)
          if (lo <= hi) result.push({ lo, hi })
        }
      }
      return result
    }

    const scaffoldHelices = []
    for (const [helixId] of scaffoldCoverage) {
      const h = allHelixById.get(helixId)
      if (h?.grid_pos) scaffoldHelices.push(h)
    }

    // Build global adjacency (same as Create Seam).
    const globalAdj = new Map(scaffoldHelices.map(h => [h.id, new Set()]))
    for (let ai = 0; ai < scaffoldHelices.length; ai++) {
      const hA = scaffoldHelices[ai]
      const [rowA, colA] = hA.grid_pos
      const covA = scaffoldCoverage.get(hA.id)
      for (let bi = ai + 1; bi < scaffoldHelices.length; bi++) {
        const hB = scaffoldHelices[bi]
        if (!hB.grid_pos) continue
        const covB = scaffoldCoverage.get(hB.id)
        const overlap = intersectCoverage(covA, covB)
        if (!overlap.length) continue
        let found = false
        outer: for (const { lo, hi } of overlap) {
          for (let bp = lo; bp <= hi; bp++) {
            const nb = scaffoldXoverNeighbor(rowA, colA, bp)
            if (nb && nb[0] === hB.grid_pos[0] && nb[1] === hB.grid_pos[1]) { found = true; break outer }
          }
        }
        if (found) {
          globalAdj.get(hA.id).add(hB.id)
          globalAdj.get(hB.id).add(hA.id)
        }
      }
    }

    // Find connected components (same as Create Seam).
    const _visited = new Set()
    const components = []
    for (const h of scaffoldHelices) {
      if (_visited.has(h.id)) continue
      const comp = []
      const stack = [h.id]
      while (stack.length) {
        const id = stack.pop()
        if (_visited.has(id)) continue
        _visited.add(id); comp.push(id)
        for (const nb of globalAdj.get(id)) { if (!_visited.has(nb)) stack.push(nb) }
      }
      components.push(comp)
    }

    // Hamiltonian path via DFS with degree-ascending ordering (same as Create Seam).
    const findHamiltonianPath = (ids, adjMap, startFrom = null) => {
      const vis = new Set(), p = []
      const dfs = id => {
        vis.add(id); p.push(id)
        if (p.length === ids.length) return true
        const nbs = [...adjMap.get(id)].filter(nb => !vis.has(nb))
          .sort((a, b) => adjMap.get(a).size - adjMap.get(b).size)
        for (const nb of nbs) { if (dfs(nb)) return true }
        vis.delete(id); p.pop(); return false
      }
      const sorted = [...ids].sort((a, b) => adjMap.get(a).size - adjMap.get(b).size)
      const starters = startFrom != null
        ? [startFrom, ...sorted.filter(id => id !== startFrom)]
        : sorted
      for (const s of starters) { if (dfs(s)) return p }
      return null
    }

    // Derive near-end pairs from the Hamiltonian path.
    // Seam HJs sit at odd starting indices: (path[1],path[2]), (path[3],path[4]), …
    // Near-end pairs sit at even starting indices: (path[0],path[1]), (path[2],path[3]), …
    // These two index sets are disjoint, so each helix appears in at most one near-end pair.
    const nearEndPairs = []

    for (const comp of components) {
      if (comp.length < 4) continue

      const covSig = id => scaffoldCoverage.get(id)
        .slice().sort((a, b) => a.lo - b.lo).map(({lo}) => `${lo}`).join('|')
      const sigMap = new Map()
      for (const id of comp) {
        const sig = covSig(id)
        if (!sigMap.has(sig)) sigMap.set(sig, [])
        sigMap.get(sig).push(id)
      }
      const groups = [...sigMap.values()]

      let path
      if (groups.length === 1) {
        path = findHamiltonianPath(comp, globalAdj)
      } else {
        groups.sort((a, b) => {
          const bp = ids => scaffoldCoverage.get(ids[0]).reduce((s, {lo, hi}) => s + hi - lo + 1, 0)
          return bp(a) - bp(b)
        })
        const localAdjs = groups.map(grpIds => {
          const idSet = new Set(grpIds)
          const adj = new Map(grpIds.map(id => [id, new Set()]))
          for (const id of grpIds)
            for (const nb of globalAdj.get(id))
              if (idSet.has(nb)) adj.get(id).add(nb)
          return adj
        })
        path = findHamiltonianPath(groups[0], localAdjs[0]) ?? groups[0].slice()
        for (let gi = 1; gi < groups.length; gi++) {
          const nextIds = groups[gi]
          const nextSet = new Set(nextIds)
          const endHasEdge = id => [...(globalAdj.get(id) ?? [])].some(nb => nextSet.has(nb))
          if (!endHasEdge(path[path.length - 1]) && endHasEdge(path[0])) path.reverse()
          const bridgeCore = [...(globalAdj.get(path[path.length - 1]) ?? [])].find(nb => nextSet.has(nb))
          if (bridgeCore) {
            let nextPath = findHamiltonianPath(nextIds, localAdjs[gi], bridgeCore)
              ?? findHamiltonianPath(nextIds, localAdjs[gi])
            if (nextPath && nextPath[0] !== bridgeCore) nextPath.reverse()
            path = [...path, ...(nextPath ?? nextIds)]
          } else {
            path = [...path, ...(findHamiltonianPath(nextIds, localAdjs[gi]) ?? nextIds)]
          }
        }
      }

      if (!path) continue
      for (let i = 0; i < path.length - 1; i += 2) {
        nearEndPairs.push([path[i], path[i + 1]])
      }
    }

    const placements = []

    for (const [hAId, hBId] of nearEndPairs) {
      const hA = allHelixById.get(hAId)
      const hB = allHelixById.get(hBId)
      if (!hA?.grid_pos || !hB?.grid_pos) continue

      const [rowA, colA] = hA.grid_pos
      const covA = scaffoldCoverage.get(hAId)
      const covB = scaffoldCoverage.get(hBId)
      const overlap = intersectCoverage(covA, covB)

      for (const { lo } of overlap) {
        // Only process lo faces — intervals where BOTH helices have a domain
        // terminus at exactly `lo`. This covers the near face of each arm in
        // dumbbell designs (e.g. bp=0 AND bp=126 for outer helices in 10-6-10).
        if (!covA.some(iv => iv.lo === lo) || !covB.some(iv => iv.lo === lo)) continue

        // Search backward from lo-3 for the first valid crossover bp,
        // guaranteeing ≥3 bp of extension beyond the domain terminus.
        // new_lo = xoverBp: extend scaffold exactly to the crossover so the
        // strand terminus coincides with it → no exposed 5'/3' ends.
        let xoverBp = null
        for (let bp = lo - 3; bp >= lo - period; bp--) {
          const nb = scaffoldXoverNeighbor(rowA, colA, bp)
          if (nb && nb[0] === hB.grid_pos[0] && nb[1] === hB.grid_pos[1]) {
            xoverBp = bp
            break
          }
        }
        if (xoverBp === null) {
          console.warn(`[CreateNearEnds] No valid xover found for pair ${hAId}↔${hBId} near bp=${lo}`)
          continue
        }

        const fwdA    = isForward(rowA, colA)
        const strandA = fwdA ? 'FORWARD' : 'REVERSE'
        const strandB = fwdA ? 'REVERSE' : 'FORWARD'

        placements.push({
          helix_id_a: hAId,
          helix_id_b: hBId,
          face_bp:    lo,
          new_lo:     xoverBp,
          xover_bp:   xoverBp,
          strand_a:   strandA,
          strand_b:   strandB,
          nick_bp_a:  nickBpForStrand(xoverBp, strandA),
          nick_bp_b:  nickBpForStrand(xoverBp, strandB),
        })
      }
    }

    if (placements.length > 0) await api.createNearEnds(placements)
  })

  // ── Create Far Ends ──────────────────────────────────────────────────────────
  document.getElementById('menu-create-far-ends')?.addEventListener('click', async function () {
    const design = store.getState().currentDesign
    if (!design) return

    const isHC = design.lattice_type === 'HONEYCOMB'
    const period = isHC ? 21 : 32

    const HC_SCAF_XOVER_MAP = {
      '1_1':[ 0,+1],'1_2':[ 0,+1],'1_11':[ 0,+1],'1_12':[ 0,+1],
      '1_8':[-1, 0],'1_9':[-1, 0],'1_18':[-1, 0],'1_19':[-1, 0],
      '1_4':[ 0,-1],'1_5':[ 0,-1],'1_15':[ 0,-1],'1_16':[ 0,-1],
      '0_1':[ 0,-1],'0_2':[ 0,-1],'0_11':[ 0,-1],'0_12':[ 0,-1],
      '0_8':[+1, 0],'0_9':[+1, 0],'0_18':[+1, 0],'0_19':[+1, 0],
      '0_4':[ 0,+1],'0_5':[ 0,+1],'0_15':[ 0,+1],'0_16':[ 0,+1],
    }
    const SQ_SCAF_XOVER_MAP = {
      '1_4':[ 0,+1],'1_5':[ 0,+1],'1_15':[ 0,+1],'1_16':[ 0,+1],'1_26':[ 0,+1],'1_27':[ 0,+1],
      '1_7':[+1, 0],'1_8':[+1, 0],'1_18':[+1, 0],'1_19':[+1, 0],'1_28':[+1, 0],'1_29':[+1, 0],
      '1_0':[ 0,-1],'1_10':[ 0,-1],'1_11':[ 0,-1],'1_20':[ 0,-1],'1_21':[ 0,-1],'1_31':[ 0,-1],
      '1_2':[-1, 0],'1_3':[-1, 0],'1_12':[-1, 0],'1_13':[-1, 0],'1_23':[-1, 0],'1_24':[-1, 0],
      '0_4':[ 0,-1],'0_5':[ 0,-1],'0_15':[ 0,-1],'0_16':[ 0,-1],'0_26':[ 0,-1],'0_27':[ 0,-1],
      '0_7':[-1, 0],'0_8':[-1, 0],'0_18':[-1, 0],'0_19':[-1, 0],'0_28':[-1, 0],'0_29':[-1, 0],
      '0_0':[ 0,+1],'0_10':[ 0,+1],'0_11':[ 0,+1],'0_20':[ 0,+1],'0_21':[ 0,+1],'0_31':[ 0,+1],
      '0_2':[+1, 0],'0_3':[+1, 0],'0_12':[+1, 0],'0_13':[+1, 0],'0_23':[+1, 0],'0_24':[+1, 0],
    }
    const HC_SCAF_BOW_RIGHT = new Set([2,5,9,12,16,19])
    const SQ_SCAF_BOW_RIGHT = new Set([0,3,5,8,11,13,16,19,21,24,27,29])

    const xoverMap    = isHC ? HC_SCAF_XOVER_MAP : SQ_SCAF_XOVER_MAP
    const bowRightSet = isHC ? HC_SCAF_BOW_RIGHT  : SQ_SCAF_BOW_RIGHT

    function isForward(row, col) { return (((row + col) % 2) + 2) % 2 === 0 }

    function scaffoldXoverNeighbor(row, col, bp) {
      const fwd = isForward(row, col)
      const mod = ((bp % period) + period) % period
      const d   = xoverMap[`${fwd ? 1 : 0}_${mod}`]
      return d ? [row + d[0], col + d[1]] : null
    }

    function nickBpForStrand(xoverBp, strand) {
      const mod     = ((xoverBp % period) + period) % period
      const lowerBp = bowRightSet.has(mod) ? xoverBp - 1 : xoverBp
      return strand === 'FORWARD' ? lowerBp : lowerBp + 1
    }

    // Build scaffold coverage map with interval merging (same as Create Seam / Near Ends).
    const scaffoldCoverage = new Map()
    for (const s of design.strands) {
      if (s.strand_type !== 'scaffold') continue
      for (const d of s.domains) {
        const lo = Math.min(d.start_bp, d.end_bp)
        const hi = Math.max(d.start_bp, d.end_bp)
        if (!scaffoldCoverage.has(d.helix_id)) scaffoldCoverage.set(d.helix_id, [])
        scaffoldCoverage.get(d.helix_id).push({ lo, hi })
      }
    }
    for (const [id, ivs] of scaffoldCoverage) {
      const s = ivs.slice().sort((a, b) => a.lo - b.lo)
      const m = [{ ...s[0] }]
      for (let i = 1; i < s.length; i++) {
        if (s[i].lo <= m[m.length - 1].hi + 1) m[m.length - 1].hi = Math.max(m[m.length - 1].hi, s[i].hi)
        else m.push({ ...s[i] })
      }
      scaffoldCoverage.set(id, m)
    }

    const allHelixById = new Map()
    for (const h of design.helices) allHelixById.set(h.id, h)

    function intersectCoverage(cA, cB) {
      const result = []
      for (const a of cA) {
        for (const b of cB) {
          const lo = Math.max(a.lo, b.lo)
          const hi = Math.min(a.hi, b.hi)
          if (lo <= hi) result.push({ lo, hi })
        }
      }
      return result
    }

    // Derive far-end pairs directly from the create_near_ends crossovers already on
    // the design.  Running an independent Hamiltonian path here risks a different
    // ordering (due to changed lo-face coverage after near-end extension), which
    // would pair the wrong helices and produce scaffold loops disconnected from
    // the rest of the design.
    const nearEndXovers = design.crossovers.filter(xo => xo.process_id === 'create_near_ends')
    if (nearEndXovers.length === 0) {
      alert('Create Near Ends must be run before Create Far Ends.')
      return
    }
    const _pairSeen = new Set()
    const farEndPairs = []
    for (const xo of nearEndXovers) {
      const aId = xo.half_a.helix_id
      const bId = xo.half_b.helix_id
      const key  = [aId, bId].sort().join('|')
      if (!_pairSeen.has(key)) {
        _pairSeen.add(key)
        farEndPairs.push([aId, bId])
      }
    }

    // Identify the one pair to skip: the pair containing the helix with the lowest
    // design array index. Connecting this pair would close the scaffold into a loop.
    const helixArrayIndex = id => design.helices.findIndex(h => h.id === id)
    let skipHelixId = null
    let lowestIdx = Infinity
    for (const [hAId, hBId] of farEndPairs) {
      const minIdx = Math.min(helixArrayIndex(hAId), helixArrayIndex(hBId))
      if (minIdx < lowestIdx) { lowestIdx = minIdx; skipHelixId = helixArrayIndex(hAId) <= helixArrayIndex(hBId) ? hAId : hBId }
    }

    const placements = []

    for (const [hAId, hBId] of farEndPairs) {
      // Skip the pair containing the lowest-indexed helix to prevent loop formation.
      if (hAId === skipHelixId || hBId === skipHelixId) continue

      const hA = allHelixById.get(hAId)
      const hB = allHelixById.get(hBId)
      if (!hA?.grid_pos || !hB?.grid_pos) continue

      const [rowA, colA] = hA.grid_pos
      const covA = scaffoldCoverage.get(hAId)
      const covB = scaffoldCoverage.get(hBId)
      const overlap = intersectCoverage(covA, covB)

      for (const { hi } of overlap) {
        // Only process hi faces — intervals where BOTH helices have a domain terminus at exactly `hi`.
        if (!covA.some(iv => iv.hi === hi) || !covB.some(iv => iv.hi === hi)) continue

        // Search forward from hi+3 for the first valid crossover bp,
        // guaranteeing ≥3 bp of extension beyond the domain terminus.
        let xoverBp = null
        for (let bp = hi + 3; bp <= hi + period; bp++) {
          const nb = scaffoldXoverNeighbor(rowA, colA, bp)
          if (nb && nb[0] === hB.grid_pos[0] && nb[1] === hB.grid_pos[1]) {
            xoverBp = bp
            break
          }
        }
        if (xoverBp === null) {
          console.warn(`[CreateFarEnds] No valid xover found for pair ${hAId}↔${hBId} near bp=${hi}`)
          continue
        }

        const fwdA    = isForward(rowA, colA)
        const strandA = fwdA ? 'FORWARD' : 'REVERSE'
        const strandB = fwdA ? 'REVERSE' : 'FORWARD'

        placements.push({
          helix_id_a: hAId,
          helix_id_b: hBId,
          face_bp:    hi,
          new_hi:     xoverBp,
          xover_bp:   xoverBp,
          strand_a:   strandA,
          strand_b:   strandB,
          nick_bp_a:  nickBpForStrand(xoverBp, strandA),
          nick_bp_b:  nickBpForStrand(xoverBp, strandB),
        })
      }
    }

    if (placements.length > 0) await api.createFarEnds(placements)
  })

  // ── Debug > MrDNA Round-Trip Test ────────────────────────────────────────────
  document.getElementById('menu-debug-mrdna-roundtrip')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { alert('No design loaded.'); return }

    const btn = document.getElementById('menu-debug-mrdna-roundtrip')
    const origText = btn.textContent
    btn.textContent = 'Running… (may take ~10 s)'
    btn.disabled = true

    try {
      const r = await fetch('/api/design/debug/mrdna-roundtrip')
      if (!r.ok) {
        const msg = await r.text()
        alert(`Round-trip test failed:\n${msg}`)
        return
      }
      const blob = await r.blob()
      const cd   = r.headers.get('Content-Disposition') || ''
      const fnMatch = cd.match(/filename="([^"]+)"/)
      const filename = fnMatch ? fnMatch[1] : 'roundtrip.zip'
      const url = URL.createObjectURL(blob)
      const a   = document.createElement('a')
      a.href     = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(`Round-trip test error: ${err.message}`)
    } finally {
      btn.textContent = origText
      btn.disabled = false
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

    // Live FRET re-check — runs every frame so translate/rotate moves update glow instantly.
    if (_fretOn) _refreshGlowModes()

    // Pin unligated-crossover ⚠ markers to live bead midpoints so they
    // track the crossover through unfold view, cadnano view, expanded
    // helix spacing, the deform tool, and cluster move/rotate. Cheap —
    // at most a few sprites per design. Cursor (when over the canvas)
    // drives the hover-fade so the user can see through markers to the
    // crossover they're trying to fix.
    unligatedCrossoverMarkers.refreshPositions(
      designRenderer.getHelixCtrl(),
      (_canvasCursorX != null) ? { camera, canvas, x: _canvasCursorX, y: _canvasCursorY } : null,
    )

    // ── LOD (Level of Detail) — apply on first tick after design load (_lastDetailLevel = -1)
    if (designRenderer.getHelixCtrl()) {
      const targetLevel = { full: 0, beads: 1, cylinders: 2 }[_lodMode] ?? 0
      if (targetLevel !== _lastDetailLevel) {
        _lastDetailLevel = targetLevel
        designRenderer.setDetailLevel(targetLevel)
        overhangLinkArcs?.setDetailLevel?.(targetLevel)
        unfoldView.setArcsVisible(targetLevel < 2)
      }
    }

    requestAnimationFrame(tick)
  })()

  // ── Extension arc debug tools (dev only) ─────────────────────────────────
  if (import.meta.env.DEV) {
    /**
     * Snapshot + diff helpers for debugging extension arc cluster-lerp.
     *
     * Usage in browser console:
     *
     *   // Before clicking a config:
     *   __extDebug.snap('before')
     *
     *   // After the animation completes:
     *   __extDebug.snap('after')
     *
     *   // Show side-by-side diff of last two snaps:
     *   __extDebug.diff()
     *
     *   // Show _extArcMap 2D targets (unfold-view, only populated when unfold active):
     *   __extDebug.snapMap('before')   // before
     *   __extDebug.snapMap('after')    // after
     *   __extDebug.diffMap()
     *
     *   // Continuously log on every applyClusterExtArcUpdate call:
     *   __extDebug.watch(true)   // on
     *   __extDebug.watch(false)  // off
     *
     *   __extDebug.clear()       // wipe history
     */
    const _extSnaps    = []   // {label, data: Map<extId, {first,last}>}
    const _extMapSnaps = []   // {label, data: Map<extId, {first,last}>}

    function _v3str(v) {
      return `(${v.x.toFixed(3)}, ${v.y.toFixed(3)}, ${v.z.toFixed(3)})`
    }

    function _snapLiveExtArcs(label) {
      const entries = designRenderer.getBackboneEntries()
      const byExt   = new Map()   // extId → [{bp, x, y, z}]
      for (const e of entries) {
        const nuc = e.nuc
        if (!nuc.helix_id?.startsWith('__ext_')) continue
        if (!byExt.has(nuc.extension_id)) byExt.set(nuc.extension_id, [])
        byExt.get(nuc.extension_id).push({ bp: nuc.bp_index, x: e.pos.x, y: e.pos.y, z: e.pos.z })
      }
      const data = new Map()
      for (const [extId, beads] of byExt) {
        beads.sort((a, b) => a.bp - b.bp)
        data.set(extId, { first: beads[0], last: beads[beads.length - 1] })
      }
      _extSnaps.push({ label, data })
      console.groupCollapsed(`[extDebug] snap "${label}" — ${data.size} extension(s)`)
      for (const [id, { first, last }] of data) {
        console.log(`  ${id}`)
        console.log(`    bp=${first.bp}  ${_v3str(first)}  (first/terminus-end)`)
        console.log(`    bp=${last.bp}   ${_v3str(last)}  (last/tip)`)
      }
      console.groupEnd()
      return data
    }

    function _snapExtArcMap(label) {
      const m = unfoldView.getExtArcMap()
      const data = new Map()
      for (const [extId, beadMap] of m) {
        const sorted = [...beadMap.entries()].sort((a, b) => a[0] - b[0])
        if (!sorted.length) continue
        const [fi, fp] = sorted[0]
        const [li, lp] = sorted[sorted.length - 1]
        data.set(extId, {
          first: { bp: fi, x: fp.x, y: fp.y, z: fp.z },
          last:  { bp: li, x: lp.x, y: lp.y, z: lp.z },
        })
      }
      _extMapSnaps.push({ label, data })
      console.groupCollapsed(`[extDebug] snapMap "${label}" — ${data.size} extension(s)  (unfold _extArcMap)`)
      for (const [id, { first, last }] of data) {
        console.log(`  ${id}`)
        console.log(`    bp=${first.bp}  ${_v3str(first)}`)
        console.log(`    bp=${last.bp}   ${_v3str(last)}`)
      }
      console.groupEnd()
      return data
    }

    function _diffSnaps(snaps, tag) {
      if (snaps.length < 2) { console.warn(`[extDebug] need ≥ 2 ${tag} snaps`); return }
      const a = snaps[snaps.length - 2]
      const b = snaps[snaps.length - 1]
      const allIds = new Set([...a.data.keys(), ...b.data.keys()])
      console.group(`[extDebug] diff ${tag}: "${a.label}" → "${b.label}"`)
      for (const id of allIds) {
        const before = a.data.get(id)
        const after  = b.data.get(id)
        if (!before || !after) { console.warn(`  ${id}: missing in one snap`); continue }
        const df = { x: after.first.x - before.first.x, y: after.first.y - before.first.y, z: after.first.z - before.first.z }
        const dl = { x: after.last.x  - before.last.x,  y: after.last.y  - before.last.y,  z: after.last.z  - before.last.z  }
        const moved = Math.abs(df.x) + Math.abs(df.y) + Math.abs(df.z) > 0.001
          ? '✓ moved' : '✗ UNCHANGED'
        console.group(`  ${id}  ${moved}`)
        console.log(`    first (bp=${before.first.bp}):  before=${_v3str(before.first)}  after=${_v3str(after.first)}  Δ=${_v3str(df)}`)
        console.log(`    last  (bp=${before.last.bp}):   before=${_v3str(before.last)}   after=${_v3str(after.last)}   Δ=${_v3str(dl)}`)
        console.groupEnd()
      }
      console.groupEnd()
    }

    window.__extDebug = {
      snap(label = 'snap')    { return _snapLiveExtArcs(label) },
      snapMap(label = 'map')  { return _snapExtArcMap(label)   },
      diff()                  { _diffSnaps(_extSnaps,    'live')    },
      diffMap()               { _diffSnaps(_extMapSnaps, 'arcMap')  },
      clear()                 { _extSnaps.length = 0; _extMapSnaps.length = 0; console.log('[extDebug] cleared') },
      watch(on = true) {
        window.__extDebugWatch = on
        console.log(`[extDebug] watch ${on ? 'ON  — applyClusterExtArcUpdate will auto-snap' : 'OFF'}`)
      },
      history()  { return { live: _extSnaps, map: _extMapSnaps } },
    }

    // Auto-snap when watch mode is active — called from applyClusterExtArcUpdate.
    window.__extDebugWatch = false

    console.info(
      '%c[NADOC] ext arc debug  →  __extDebug.snap(before/after) · .diff() · .snapMap() · .diffMap() · .watch(true)',
      'color:#5bc8ff',
    )

    // ── Extension-arc cluster-update debug ────────────────────────────────────
    //
    //   __arcDebug.listExtArcs()   list _arcMeta entries with __ext_* endpoints
    //   __arcDebug.snap('before')  snapshot arc endpoint positions
    //   __arcDebug.snap('after')   snapshot again after dragging the cluster
    //   __arcDebug.diff()          show which endpoints moved vs stayed
    //   __arcDebug.clear()         wipe snap history
    //
    // Bug A signature (before fix):
    //   from (__ext_*): ✗ UNCHANGED    ← extension side stuck
    //   to   (h_HC_*):  ✓ moved        ← real-helix side follows cluster
    //
    const _arcSnaps      = []   // [{label, data: Map<arcKey, {fromHelixId,toHelixId,from3D,to3D}>}]
    const _renderedSnaps = []   // [{label, data: Map<arcKey, {fromHelixId,toHelixId,renderedFrom,renderedTo}>}]

    function _arcV3(v) { return `(${v.x.toFixed(3)}, ${v.y.toFixed(3)}, ${v.z.toFixed(3)})` }

    function _snapExtArcEndpoints(label) {
      const extArcs = unfoldView.getExtArcMeta?.() ?? []
      const data = new Map()
      for (const e of extArcs) {
        const key = `${e.fromHelixId}|${e.toHelixId}`
        data.set(key, {
          fromHelixId: e.fromHelixId,
          toHelixId:   e.toHelixId,
          from3D: { x: e.from3D.x, y: e.from3D.y, z: e.from3D.z },
          to3D:   { x: e.to3D.x,   y: e.to3D.y,   z: e.to3D.z   },
        })
      }
      _arcSnaps.push({ label, data })
      console.groupCollapsed(`[arcDebug] snap "${label}" — ${data.size} ext arc(s)`)
      for (const [key, d] of data) {
        console.log(`  ${key}`)
        console.log(`    from (${d.fromHelixId}): ${_arcV3(d.from3D)}`)
        console.log(`    to   (${d.toHelixId}):   ${_arcV3(d.to3D)}`)
      }
      console.groupEnd()
      return data
    }

    function _snapRenderedEndpoints(label) {
      const eps = unfoldView.getExtArcRenderedEndpoints?.() ?? []
      const data = new Map()
      for (const e of eps) {
        const key = `${e.fromHelixId}|${e.toHelixId}`
        data.set(key, {
          fromHelixId:  e.fromHelixId,
          toHelixId:    e.toHelixId,
          renderedFrom: { ...e.renderedFrom },
          renderedTo:   { ...e.renderedTo   },
        })
      }
      _renderedSnaps.push({ label, data })
      console.groupCollapsed(`[arcDebug] snapRendered "${label}" — ${data.size} ext arc(s)`)
      for (const [key, d] of data) {
        console.log(`  ${key}`)
        console.log(`    renderedFrom (${d.fromHelixId}): ${_arcV3(d.renderedFrom)}`)
        console.log(`    renderedTo   (${d.toHelixId}):   ${_arcV3(d.renderedTo)}`)
      }
      console.groupEnd()
      return data
    }

    window.__arcDebug = {
      listExtArcs() {
        const arcs = unfoldView.getExtArcMeta?.() ?? []
        console.group(`[arcDebug] ext arc entries — ${arcs.length}`)
        for (const e of arcs) {
          console.log(`  from: ${e.fromHelixId}  ${_arcV3(e.from3D)}`)
          console.log(`  to:   ${e.toHelixId}    ${_arcV3(e.to3D)}`)
        }
        console.groupEnd()
        return arcs
      },
      // snap() reads base 3D positions — useful for cluster-drag bug verification.
      snap(label = 'snap') { return _snapExtArcEndpoints(label) },
      // snapRendered() reads the actual vertex buffer — use for unfold transition bug.
      snapRendered(label = 'snap') { return _snapRenderedEndpoints(label) },
      diff() {
        // Prefer rendered snaps if available; fall back to base-3D snaps.
        const snaps = _renderedSnaps.length >= 2 ? _renderedSnaps : _arcSnaps
        const fKey  = _renderedSnaps.length >= 2 ? 'renderedFrom' : 'from3D'
        const tKey  = _renderedSnaps.length >= 2 ? 'renderedTo'   : 'to3D'
        const mode  = _renderedSnaps.length >= 2 ? 'rendered vertices' : 'base 3D'
        if (snaps.length < 2) { console.warn('[arcDebug] need ≥ 2 snaps'); return }
        const a = snaps[snaps.length - 2]
        const b = snaps[snaps.length - 1]
        const allKeys = new Set([...a.data.keys(), ...b.data.keys()])
        console.group(`[arcDebug] diff "${a.label}" → "${b.label}"  [${mode}]`)
        for (const key of allKeys) {
          const before = a.data.get(key), after = b.data.get(key)
          if (!before || !after) { console.warn(`  ${key}: missing in one snap`); continue }
          const bf = before[fKey], af = after[fKey]
          const bt = before[tKey], at = after[tKey]
          const df = { x: af.x - bf.x, y: af.y - bf.y, z: af.z - bf.z }
          const dt = { x: at.x - bt.x, y: at.y - bt.y, z: at.z - bt.z }
          const fromMoved = Math.hypot(df.x, df.y, df.z) > 0.001
          const toMoved   = Math.hypot(dt.x, dt.y, dt.z) > 0.001
          console.group(`  ${key}`)
          console.log(`    from (${before.fromHelixId}): ${fromMoved ? '✓ moved' : '✗ UNCHANGED'}  before=${_arcV3(bf)}  after=${_arcV3(af)}  Δ=${_arcV3(df)}`)
          console.log(`    to   (${before.toHelixId}):   ${toMoved   ? '✓ moved' : '✗ UNCHANGED'}  before=${_arcV3(bt)}  after=${_arcV3(at)}  Δ=${_arcV3(dt)}`)
          console.groupEnd()
        }
        console.groupEnd()
      },
      extTargets() {
        const m = unfoldView.getExtArcMap?.()
        if (!m?.size) { console.log('[arcDebug] no ext arc targets (unfold not yet activated)'); return }
        console.group(`[arcDebug] extTargets — ${m.size} extension(s)`)
        for (const [extId, beadMap] of m) {
          console.log(`  ${extId}`)
          for (const [bp, pos] of [...beadMap.entries()].sort((a, b) => a[0] - b[0]))
            console.log(`    bp=${bp}  (${pos.x.toFixed(3)}, ${pos.y.toFixed(3)}, ${pos.z.toFixed(3)})`)
        }
        console.groupEnd()
        return m
      },
      clear() {
        _arcSnaps.length = 0
        _renderedSnaps.length = 0
        console.log('[arcDebug] cleared')
      },
      history() { return { arc: _arcSnaps, rendered: _renderedSnaps } },
    }

    console.info(
      '%c[NADOC] arc debug  →  .listExtArcs() · .snap() · .snapRendered() · .diff() · .extTargets() · .clear()',
      'color:#a8ff78',
    )

    // ── __xb__ / __ext__ bead positioning debug ──────────────────────────────
    //
    //   __xbDebug.dump()          full state dump — run before and after enter/exit cadnano
    //   __xbDebug.snap('label')   snapshot current __xb__ bead positions
    //   __xbDebug.snapExt('lbl')  snapshot current __ext__ bead positions
    //   __xbDebug.diff()          diff the two most recent __xb__ snaps
    //   __xbDebug.diffExt()       diff the two most recent __ext__ snaps
    //
    const _xbSnaps  = []
    const _extSnaps2 = []

    const _fmtV3 = v => {
      if (!v) return 'null'
      const x = v.x ?? v[0], y = v.y ?? v[1], z = v.z ?? v[2]
      return `(${(+x).toFixed(3)}, ${(+y).toFixed(3)}, ${(+z).toFixed(3)})`
    }

    window.__xbDebug = {
      /** Full internal-state dump — call any time to understand current build status. */
      dump() {
        const xbArcMap = unfoldView.getXbArcMap?.()    ?? new Map()
        const arcMeta  = unfoldView.getArcMeta?.()     ?? []
        const spMap    = unfoldView.getStraightPosMap?.() ?? null
        const entries  = designRenderer.getBackboneEntries?.() ?? []

        console.group('%c[xbDebug] state dump', 'color:#ffd700;font-weight:bold')

        // 1. _arcMeta crossover_id population
        const metaWithId    = arcMeta.filter(e => e.crossover_id != null)
        const metaWithout   = arcMeta.filter(e => e.crossover_id == null)
        console.group(`_arcMeta: ${arcMeta.length} total | ${metaWithId.length} have crossover_id | ${metaWithout.length} missing`)
        for (const e of metaWithId.slice(0, 5))
          console.log(`  ✓ crossover_id=${e.crossover_id}  from=${e.fromHelixId}  to=${e.toHelixId}`)
        if (metaWithout.length)
          console.warn(`  ✗ ${metaWithout.length} arc(s) have null crossover_id → those __xb__ beads get no arc`)
        console.groupEnd()

        // 2. _xbArcMap
        console.group(`_xbArcMap: ${xbArcMap.size} entries`)
        if (!xbArcMap.size) {
          console.warn('  EMPTY — __xb__ beads will always use else-branch (stay at t=0 anchor, no arc animation)')
        } else {
          let ci = 0
          for (const [id, arc] of xbArcMap) {
            if (ci++ >= 4) { console.log('  ...'); break }
            const s = arc.bezierAt(0.5)
            console.log(`  cb.id=${id}  bezierAt(0.5)=${_fmtV3(s)}`)
          }
        }
        console.groupEnd()

        // 3. _straightPosMap — __xb__ coverage
        const xbSpKeys = spMap ? [...spMap.keys()].filter(k => k.startsWith('__xb_')) : []
        const extSpKeys = spMap ? [...spMap.keys()].filter(k => k.startsWith('__ext_')) : []
        console.group(`_straightPosMap: ${spMap ? spMap.size + ' total' : 'NULL ← straightGeometry not fetched'} | __xb__ keys=${xbSpKeys.length} | __ext__ keys=${extSpKeys.length}`)
        if (!spMap) console.error('  straightPosMap is NULL — _buildXbArcMap used from3D/to3D as bezier anchors')
        for (const k of xbSpKeys.slice(0, 4)) console.log(`  ${k} → ${_fmtV3(spMap.get(k))}`)
        console.groupEnd()

        // 4. Live __xb__ bead positions
        const xbEntries = entries.filter(e => e.nuc?.helix_id?.startsWith('__xb_'))
        console.group(`Live __xb__ bead entries: ${xbEntries.length}`)
        for (const e of xbEntries.slice(0, 6)) {
          const nuc = e.nuc
          const bp  = nuc.backbone_position
          const spKey = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
          const sp  = spMap?.get(spKey)
          const arc = xbArcMap.get(nuc.crossover_bases_id)
          const arcTarget = arc ? _fmtV3(arc.bezierAt(0.5)) : 'NO ARC'
          const same3D = sp && Math.hypot(sp.x - bp[0], sp.y - bp[1], sp.z - bp[2]) < 0.001
          console.group(`  ${spKey}`)
          console.log(`    entry.pos (rendered)    = ${_fmtV3(e.pos)}`)
          console.log(`    nuc.backbone_position   = ${_fmtV3({ x: bp[0], y: bp[1], z: bp[2] })}  ← transformed?`)
          console.log(`    _straightPosMap entry   = ${sp ? _fmtV3(sp) + (same3D ? ' (SAME as backbone — untransformed)' : ' (DIFFERS — cluster moved)') : 'MISSING'}`)
          console.log(`    _xbArcMap bezierAt(0.5) = ${arcTarget}`)
          console.groupEnd()
        }
        console.groupEnd()

        // 5. Live __ext__ bead positions
        const extEntries = entries.filter(e => e.nuc?.helix_id?.startsWith('__ext_'))
        console.group(`Live __ext__ bead entries: ${extEntries.length}`)
        for (const e of extEntries.slice(0, 4)) {
          const nuc = e.nuc
          const bp  = nuc.backbone_position
          const sp  = spMap?.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
          console.log(`  ${nuc.helix_id}:${nuc.bp_index}  rendered=${_fmtV3(e.pos)}  backbone=${_fmtV3({ x: bp[0], y: bp[1], z: bp[2] })}  straight=${sp ? _fmtV3(sp) : 'MISSING'}`)
        }
        console.groupEnd()

        console.groupEnd()
      },

      /** Snapshot current rendered positions of __xb__ beads. */
      snap(label = 'snap') {
        const data = []
        for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
          if (!e.nuc?.helix_id?.startsWith('__xb_')) continue
          data.push({ key: `${e.nuc.helix_id}:${e.nuc.bp_index}`, x: e.pos.x, y: e.pos.y, z: e.pos.z })
        }
        _xbSnaps.push({ label, data })
        console.groupCollapsed(`[xbDebug] snap "${label}" — ${data.length} __xb__ bead(s)`)
        for (const d of data) console.log(`  ${d.key}  pos=${_fmtV3(d)}`)
        console.groupEnd()
        return data
      },

      /** Snapshot current rendered positions of __ext__ beads. */
      snapExt(label = 'snap') {
        const data = []
        for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
          if (!e.nuc?.helix_id?.startsWith('__ext_')) continue
          data.push({ key: `${e.nuc.helix_id}:${e.nuc.bp_index}`, x: e.pos.x, y: e.pos.y, z: e.pos.z })
        }
        _extSnaps2.push({ label, data })
        console.groupCollapsed(`[xbDebug] snapExt "${label}" — ${data.length} __ext__ bead(s)`)
        for (const d of data) console.log(`  ${d.key}  pos=${_fmtV3(d)}`)
        console.groupEnd()
        return data
      },

      /** Diff the two most recent __xb__ snaps. */
      diff() {
        if (_xbSnaps.length < 2) { console.warn('[xbDebug] need ≥ 2 snaps'); return }
        const a = _xbSnaps[_xbSnaps.length - 2]
        const b = _xbSnaps[_xbSnaps.length - 1]
        console.group(`[xbDebug] diff "${a.label}" → "${b.label}"`)
        const bMap = new Map(b.data.map(d => [d.key, d]))
        for (const da of a.data) {
          const db = bMap.get(da.key)
          if (!db) { console.warn(`  ${da.key}: missing in second snap`); continue }
          const delta = Math.hypot(db.x - da.x, db.y - da.y, db.z - da.z)
          const moved = delta > 0.001
          console.log(`  ${moved ? '✓ moved' : '✗ UNCHANGED'}  ${da.key}  before=${_fmtV3(da)}  after=${_fmtV3(db)}  Δ=${delta.toFixed(3)}`)
        }
        console.groupEnd()
      },

      /** Diff the two most recent __ext__ snaps. */
      diffExt() {
        if (_extSnaps2.length < 2) { console.warn('[xbDebug] need ≥ 2 snapExt calls'); return }
        const a = _extSnaps2[_extSnaps2.length - 2]
        const b = _extSnaps2[_extSnaps2.length - 1]
        console.group(`[xbDebug] diffExt "${a.label}" → "${b.label}"`)
        const bMap = new Map(b.data.map(d => [d.key, d]))
        for (const da of a.data) {
          const db = bMap.get(da.key)
          if (!db) { console.warn(`  ${da.key}: missing in second snap`); continue }
          const delta = Math.hypot(db.x - da.x, db.y - da.y, db.z - da.z)
          const moved = delta > 0.001
          console.log(`  ${moved ? '✓ moved' : '✗ UNCHANGED'}  ${da.key}  before=${_fmtV3(da)}  after=${_fmtV3(db)}  Δ=${delta.toFixed(3)}`)
        }
        console.groupEnd()
      },

      clear() {
        _xbSnaps.length = 0
        _extSnaps2.length = 0
        console.log('[xbDebug] cleared')
      },
    }

    console.info(
      '%c[NADOC] xb/ext debug  →  __xbDebug.dump() · .snap(lbl) · .snapExt(lbl) · .diff() · .diffExt() · .clear()',
      'color:#ffd700',
    )
  }

  // ── Test helpers (dev only — used by Playwright e2e tests) ───────────────
  if (import.meta.env.DEV) {
    window.__nadocTest = {
      scene,
      getAtomisticRenderer: () => atomisticRenderer,
      getPeriodicMdOverlay: () => periodicMdOverlay,
      isCGVisible: () => !!(designRenderer.getHelixCtrl()?.root?.visible),
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

  // ── Cadnano editor sync ───────────────────────────────────────────────────────
  // Re-fetch the full design whenever the cadnano editor (running in another
  // tab/window) commits a mutation (nick, crossover, strand paint, etc.).
  // The cadnano editor emits 'design-changed' via BroadcastChannel after every
  // successful API call; the 3D view responds by pulling the latest design and
  // geometry so nicks and crossover connections appear automatically.

  // Flag to suppress re-broadcasting when multiSelectedStrandIds is set from an
  // incoming 'selection-changed' message (prevents A→B→A infinite loops).
  let _syncingFromBroadcast = false

  // Emit 'selection-changed' whenever the 3D view's multi-selection changes
  // (e.g. from user Ctrl+drag lasso in the 3D viewport).
  store.subscribe((newState, prevState) => {
    if (newState.multiSelectedStrandIds === prevState.multiSelectedStrandIds) return
    if (_syncingFromBroadcast) return
    const ids = newState.multiSelectedStrandIds ?? []
    // Don't broadcast deselection — each window manages its own deselect state.
    // Only positive selections sync cross-window.
    if (ids.length === 0) return
    nadocBroadcast.emit('selection-changed', { strandIds: ids })
  })

  // Emit 'selection-changed' for single-strand clicks (selectedObject).
  store.subscribe((newState, prevState) => {
    if (newState.selectedObject === prevState.selectedObject) return
    if (_syncingFromBroadcast) return
    const sel = newState.selectedObject
    if (!sel) return
    const ids = sel.data?.strand_ids ?? (sel.data?.strand_id ? [sel.data.strand_id] : [])
    if (ids.length) nadocBroadcast.emit('selection-changed', { strandIds: ids })
  })

  nadocBroadcast.onMessage(async ({ type, strandIds, source, windowName, designName, instanceId }) => {
    if (type === 'design-changed') {
      // Assembly windows ignore design-changed: their currentDesign is unused
      // while assemblyActive=true, and pulling it in can re-enter the auto-save /
      // overlay-rebuild chain with stale data. Part-edit / cadnano tabs still
      // refresh because they aren't in assembly mode.
      if (store.getState().assemblyActive) return
      // Fetch design first (strand topology), then geometry (nucleotide positions +
      // strand_id assignments).  Both are needed: design alone gives wrong strand_id
      // groupings (nicks invisible); geometry alone gives wrong axis cylinders.
      // _reloadingFromSSE suppresses the auto-save subscriber during this passive fetch
      // so a broadcast → getDesign → store-update → auto-save → SSE → broadcast loop
      // can't form.
      _reloadingFromSSE = true
      try {
        await api.getDesign()
        await api.getGeometry()
      } finally {
        _reloadingFromSSE = false
      }
    }
    if (type === 'selection-changed') {
      _syncingFromBroadcast = true
      selectionManager.setMultiHighlight(strandIds ?? [])
      _syncingFromBroadcast = false
    }
    if (type === 'editor-announce' || type === 'editor-title-changed') {
      _editorRegistry.set(source, { windowName, designName })
      _renderEditorDropdown()
    }
    if (type === 'editor-goodbye') {
      _editorRegistry.delete(source)
      _renderEditorDropdown()
    }
    if (type === 'part-design-updated') {
      _syncLog('info', 'BC-RX', `part-design-updated id=${instanceId}`)
      await _refreshAssemblyPartInstance(instanceId, 'broadcast')
      // Part-edit tabs (?part-instance=<id>) show this instance's design as
      // their active design. Re-import from the backend so the topology in
      // this tab reflects the assembly window's mutation. Re-import also
      // emits 'design-changed', which refreshes any open cadnano editor.
      if (_partEditContext?.instanceId === instanceId) {
        try {
          const r = await fetch(`/api/assembly/instances/${instanceId}/design`)
          if (r.ok) {
            const body = await r.json()
            if (body?.design) await api.importDesign(JSON.stringify(body.design))
          }
        } catch (err) {
          console.warn('[sync] part-edit re-import failed:', err?.message ?? err)
        }
      }
    }
    if (type === 'session-closed') {
      // Another NADOC tab closed the session. Try window.close() first
      // (works for script-opened tabs); if the browser blocks it (tab was
      // opened by URL bar / duplicate / bookmark), fall back to reloading
      // this tab to the welcome screen so it's not stuck showing a part
      // that another tab just closed. setTimeout fires only if the close
      // didn't actually tear down the tab.
      try { window.close() } catch { /* best-effort */ }
      setTimeout(() => { window.location.href = '/' }, 50)
    }
  })

  // ── Editor tab registry ──────────────────────────────────────────────────────
  // Tracks open cadnano editor tabs via BroadcastChannel announcements.
  // Populates the "Origami Editor" dropdown when 1+ editors are open.
  const _editorRegistry = new Map()  // tabId → { windowName, designName }

  function _renderEditorDropdown() {
    const dropdown = document.getElementById('editor-tab-dropdown')
    if (!dropdown) return
    dropdown.innerHTML = ''

    if (_editorRegistry.size === 0) {
      dropdown.style.display = 'none'
      return
    }

    for (const [, { windowName, designName }] of _editorRegistry) {
      const btn = document.createElement('button')
      btn.className = 'dropdown-item'
      btn.textContent = designName || 'Untitled'
      btn.addEventListener('click', () => {
        const win = window.open('', windowName)
        if (win) win.focus()
      })
      dropdown.appendChild(btn)
    }

    const sep = document.createElement('hr')
    sep.style.cssText = 'border:none;border-top:1px solid #30363d;margin:4px 0'
    dropdown.appendChild(sep)

    const newBtn = document.createElement('button')
    newBtn.className = 'dropdown-item'
    newBtn.textContent = 'Open New Editor ↗'
    newBtn.addEventListener('click', () => {
      // Open with a unique target so this one gets a fresh tab
      window.open('/cadnano-editor.html', 'nadoc-editor-' + Date.now())
    })
    dropdown.appendChild(newBtn)

    dropdown.style.display = ''
  }

  // Request roll-call so any already-open editors re-announce themselves.
  nadocBroadcast.emit('editor-list-request')

}

// ── Debug helpers ─────────────────────────────────────────────────────────────
// Registered at module scope — available even if main() throws or hasn't finished.
// Paste the standalone snippet in src/debug_snippet.js into DevTools if this
// object isn't reachable (e.g. the module failed to parse).
window.nadocDebug = (() => {
  function _cache() {
    const lines = []
    const add = (k, v) => lines.push([k, v])
    add('mode (session)     ', sessionStorage.getItem('nadoc:mode'))
    add('workspace-path     ', localStorage.getItem('nadoc:workspace-path'))
    add('asm-workspace-path ', localStorage.getItem('nadoc:assembly-workspace-path'))
    try {
      const d = JSON.parse(localStorage.getItem('nadoc:design') || 'null')
      add('cached design      ', d ? { id: d.id, name: d.metadata?.name,
        helices: d.helices?.length, strands: d.strands?.length } : null)
    } catch { add('cached design      ', 'PARSE ERROR') }
    try {
      const a = JSON.parse(localStorage.getItem('nadoc:assembly') || 'null')
      add('cached assembly    ', a ? { name: a.metadata?.name, instances: a.instances?.length } : null)
      if (a?.instances?.length) {
        add('  instance sources ', a.instances.map(i => ({
          id: i.id, name: i.name,
          src: i.source?.type === 'file' ? `file:${i.source.path}` : `inline:${i.source?.design?.id ?? '?'}`,
        })))
      }
    } catch { add('cached assembly    ', 'PARSE ERROR') }
    console.group('[nadocDebug] localStorage cache')
    lines.forEach(([k, v]) => console.log(k + ':', v))
    console.groupEnd()
  }

  function _storeState() {
    const s = store.getState()
    console.group('[nadocDebug] store')
    console.log('mode             :', api.getPersistedMode())
    console.log('assemblyActive   :', s.assemblyActive)
    console.log('lastError        :', s.lastError)
    console.log('currentDesign    :', s.currentDesign
      ? { id: s.currentDesign.id, name: s.currentDesign.metadata?.name,
          helices: s.currentDesign.helices?.length, strands: s.currentDesign.strands?.length }
      : null)
    if (s.currentAssembly) {
      console.log('currentAssembly  :', { name: s.currentAssembly.metadata?.name,
        instances: s.currentAssembly.instances?.length, joints: s.currentAssembly.joints?.length })
      console.log('  instances      :', s.currentAssembly.instances?.map(i => ({
        id: i.id, name: i.name, visible: i.visible,
        src: i.source?.type === 'file' ? `file:${i.source.path}` : `inline:${i.source?.design?.id ?? '?'}`,
      })))
    } else {
      console.log('currentAssembly  :', null)
    }
    console.groupEnd()
    return s
  }

  async function _backend() {
    console.group('[nadocDebug] backend (live API)')
    for (const url of ['/api/design', '/api/assembly']) {
      try {
        const r = await fetch(url)
        const body = await r.json().catch(() => null)
        if (!r.ok) {
          console.log(`${url} → ${r.status} ${r.statusText}${r.status === 404 ? ' (nothing loaded on server — normal if assembly mode)' : ''}`)
        } else if (url.includes('assembly') && body?.assembly) {
          const a = body.assembly
          console.log(`${url} → ok`, { name: a.metadata?.name, instances: a.instances?.length,
            instance_sources: a.instances?.map(i => ({
              id: i.id, name: i.name,
              src: i.source?.type === 'file' ? `file:${i.source.path}` : `inline:${i.source?.design?.id ?? '?'}`,
            })) })
        } else if (body?.design) {
          const d = body.design
          console.log(`${url} → ok`, { id: d.id, name: d.metadata?.name,
            helices: d.helices?.length, strands: d.strands?.length })
        } else {
          console.log(`${url} → ok (empty)`, body)
        }
      } catch (e) { console.warn(`${url} → network error`, e) }
    }
    console.groupEnd()
  }

  const obj = {
    cache:   _cache,
    store:   _storeState,
    backend: _backend,
    async all() { _cache(); _storeState(); await _backend() },
    // Boot/restore-path diagnostics: set window.nadocDebug.verbose = true to enable.
    verbose: false,
  }
  console.debug('[nadocDebug] registered — run `await nadocDebug.all()` in DevTools')
  return obj
})()

main().catch(err => {
  console.error('NADOC boot error:', err)
  const box = document.getElementById('prompt-box')
  if (box) box.innerHTML = `<p style="color:#ff6b6b">Boot error: ${err.message}</p>`
})

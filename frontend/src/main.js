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
import { buildStapleColorMap } from './scene/helix_renderer.js'
import { initSelectionManager }      from './scene/selection_manager.js'
import { initSlicePlane }            from './scene/slice_plane.js'
import { initClusterClipboard }      from './scene/cluster_clipboard.js'
import { initExtrudePanel }          from './ui/extrude_panel.js'
import { initPrimitiveLibrary }      from './ui/primitive_library.js'
import { axesVisibleForDesign }      from './ui/extrude_panel_logic.js'
import { bundleMidOffset }           from './scene/bundle_geometry.js'
import { quatToEulerDeg, extractJointAngleDeg } from './scene/rotation_math.js'
import { initMeasurementTool }       from './scene/measurement_tool.js'
import { intersectCoverage, findHamiltonianPath } from './scene/scaffold_coverage.js'
import { initCreateSeam } from './scene/create_seam.js'
import { strandLengthNt } from './scene/strand_length.js'
import { buildSpecMap, buildDomainMapFromDesign, buildJunctionMapFromDomains, buildRootMap } from './scene/overhang_maps.js'
import { initGroupGizmo } from './scene/group_gizmo.js'
import { initAssemblyTransform } from './scene/assembly_transform.js'
import { matrixFromInstance, sameInstanceTransform, assemblyTransformOnlyChange, constraintRelevantChanged } from './scene/assembly_diff.js'
import { flexAnchorKey, connIdForBead, flexibleRunForBead, duplexClusterForOverhang } from './scene/design_queries.js'
import { computeGroupHiddenInstanceIds } from './scene/assembly_groups_util.js'
import { initAssemblyPointer } from './scene/assembly_pointer.js'
import { hexFromInt } from './scene/color_util.js'
import { initFretChecker } from './scene/fret_checker.js'
import { initUndefinedHighlight } from './scene/undefined_highlight.js'
import { assemblyDuplicateOffset } from './scene/assembly_layout.js'
import { selectionBBox } from './scene/selection_bbox.js'
import { initAssemblyMultiBox } from './scene/assembly_multi_box.js'
import { initAssemblyConfigAnimator } from './scene/assembly_config_animator.js'
import { clientToNdc } from './scene/ndc.js'
import { initFlexRelax } from './scene/flex_relax.js'
import { initResponseDelta } from './scene/response_delta.js'
import { initJointPick } from './scene/joint_pick.js'
import { initEmptySpaceMenu } from './scene/empty_space_menu.js'
import { initAssemblyLasso, toggleInstanceSelection } from './scene/assembly_lasso.js'
import { initOverhangHoverPicker } from './scene/overhang_hover_picker.js'
import { initScaffoldModal } from './ui/scaffold_modal.js'
import { initAutoscaffoldPicker } from './ui/autoscaffold_picker.js'
import { initNewDesignModal } from './ui/new_design_modal.js'
import { initSliceHighlighter } from './scene/slice_highlighter.js'
import { vecClose } from './scene/vec_math.js'
import { initDomainEnds }            from './scene/domain_ends.js'
import { initEndExtrudeArrows }      from './scene/end_extrude_arrows.js'
import { initCommandPalette }  from './ui/command_palette.js'
import { initStrandLengthHistogram } from './ui/strand_length_histogram.js'
import { initOverhangSequencesPanel } from './ui/overhang_sequences_panel.js'
import { initStrandGroupsPanel } from './ui/strand_groups_panel.js'
import { initSelectionFilter } from './ui/selection_filter.js'
import { initPropertiesPanel } from './ui/properties_panel.js'
import { initOverhangOrientationMenu } from './ui/overhang_orientation_menu.js'
import { initBluntEndMenus } from './ui/blunt_end_menus.js'
import { createScriptRunner }  from './ui/script_runner.js'
import { store, popGroupUndo } from './state/store.js'
import * as api                from './api/client.js'
import { initDeformationEditor, startTool, startToolForEdit as startDeformToolForEdit,
         isActive as isDeformActive,
         handlePointerMove as deformPointerMove,
         handlePointerDown as deformPointerDown,
         handlePointerUp   as deformPointerUp,
         handleEscape as deformEscape,
         exitTool as deformExitTool,
         confirmDeformation, cancelDeformation, previewDeformation,
         markEditCommitted as markDeformEditCommitted,
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
import { initAssemblyOverhangsManagerPopup,
         open as openAssemblyOverhangsManager,
       } from './ui/assembly_overhangs_manager_popup.js'
import { initOverhangConnectionsPanel } from './ui/overhang_connections_panel.js'
import { initPolymerizePanel }     from './ui/polymerize_panel.js'
import { initBeltPathPanel }       from './ui/belt_path_panel.js'
import { initStrandAnimPanel }     from './ui/strand_anim_panel.js'
import { openProteinAttachModal }  from './ui/protein_attach_modal.js'
import { initProteinSubsystem }    from './scene/protein_subsystem.js'
import { initConjugateManager }    from './ui/conjugate_manager.js'
import { initUnfoldView }          from './scene/unfold_view.js'
import { initCadnanoView }         from './scene/cadnano_view.js'
import { initDeformView }          from './scene/deform_view.js'
import { initLoopSkipHighlight }   from './scene/loop_skip_highlight.js'
import { initOverhangLocations }   from './scene/overhang_locations.js'
import { initOverhangLinkArcs }    from './scene/overhang_link_arcs.js'
import { initFlexibleArcs }        from './scene/flexible_arcs.js'
import { initOverhangUnzipOverlay } from './scene/overhang_unzip_overlay.js'
import { initMultiOverhangStrandAnim } from './scene/overhang_strand_anim.js'
import { initUnligatedCrossoverMarkers } from './scene/unligated_crossover_markers.js'
import { initOverhangNameOverlay } from './scene/overhang_name_overlay.js'
import { initCrossSectionMinimap } from './scene/cross_section_minimap.js'
import { initDevtoolsDebug } from './scene/debug/devtools_helpers.js'
import { initViewCube }            from './scene/view_cube.js'
import { initDebugOverlay }        from './scene/debug_overlay.js'
import { initSequenceOverlay }     from './scene/sequence_overlay.js'
import { initAtomisticRenderer }   from './scene/atomistic_renderer.js'
import { initSurfaceRenderer }     from './scene/surface_renderer.js'
import { initAtomSurfaceDisplay }  from './scene/atom_surface_display.js'
import { overhangsToSegments, editOverridesForSegments, createRepresentationMenuItem } from './scene/representation_overrides.js'
import { initSpreadsheet } from './ui/spreadsheet.js'
import { initExportMenu }          from './ui/export_menu.js'
import { initImportMenu }          from './ui/import_menu.js'
import { initAssemblyPanel }        from './ui/assembly_panel.js'
import { initAssemblyContextMenu }  from './ui/assembly_context_menu.js'
import { initLibraryPanel }         from './ui/library_panel.js'
import { pickLattice }              from './ui/lattice_picker.js'
import { openFileBrowser }          from './ui/file_browser.js'
import { initFileIo, initFileOpen, initFileSave } from './ui/file_io.js'
import { initSyncBadge, countCoeditingSiblings } from './ui/sync_badge.js'
import { createAssemblyRenderer }   from './scene/assembly_renderer.js'
import { initNavController }        from './scene/nav_controller.js'
import { initAssemblyJointRenderer } from './scene/assembly_joint_renderer.js'
import { initKinematicsTicker }      from './scene/kinematics_ticker.js'
import { applyBeltRiders, beltCurvePoints, beltLoopLength } from './scene/belt_geometry.js'
import { initBeltPolymerize } from './scene/belt_polymerize.js'
import { initAssemblyRefresh } from './scene/assembly_refresh.js'
import { initConnectionMonitor, initAutosaveSync } from './app/lifecycle.js'
import { initDocSpawn } from './app/doc_spawn.js'
import { initBeltPathRenderer }      from './scene/belt_path_renderer.js'
import { computeFixedDepths } from './scene/assembly_constraint_graph.js'
import { initClusterPanel, helixIdsFromStrandIds } from './ui/cluster_panel.js'
import { initPlateView }                           from './ui/plate_view.js'
import { STAPLE_PALETTE as PLATE_STAPLE_PALETTE } from './scene/helix_renderer/palette.js'
import { initJointsPanel }                          from './ui/joints_panel.js'
import { initJointRenderer }                       from './scene/joint_renderer.js'
import { initCameraPanel }                        from './ui/camera_panel.js'
import { initAnimationPanel }                     from './ui/animation_panel.js'
// initAssemblyConfigPanel removed 2026-05-17: configurations consolidated into
// the Feature Log panel (target dropdown → "Configurations").
import { initFeatureLogPanel }                    from './ui/feature_log_panel.js'
import { initAnimationPlayer }                    from './scene/animation_player.js'
import { applyAnimationTextOverlay }              from './scene/animation_text_overlay.js'
import { exportVideo }          from './scene/export_video.js'
import { initClusterGizmo, computeClusterPivotFromEntries, rebaseClusterTranslationForPivot } from './scene/cluster_gizmo.js'
import { initSubDomainGizmo } from './scene/sub_domain_gizmo.js'
import { initInstanceGizmo }       from './scene/instance_gizmo.js'
import { initMoveRotatePanel }      from './scene/move_rotate_panel.js'
import { initTranslateRotateTool }  from './scene/translate_rotate_tool.js'
import { initForceCrossoverTool }   from './scene/force_crossover_tool.js'
import { initOverhangOrientationPanel } from './ui/overhang_orientation_panel.js'
import { showToast, showPersistentToast, dismissToast } from './ui/toast.js'
import { showOpProgress, hideOpProgress }                from './ui/op_progress.js'
import { BDNA_RISE_PER_BP, HELIX_RADIUS } from './constants.js'
import { initZoomScope }           from './scene/zoom_scope.js'
import { initExpandedSpacing }     from './scene/expanded_spacing.js'
import { registerShortcut } from './input/shortcuts.js'
import { initKeyboardShortcuts } from './ui/keyboard_shortcuts.js'
import { initViewToolButtons } from './ui/view_tool_buttons.js'
import { initToolFilterToggles } from './ui/tool_filter_toggles.js'
import { initViewLegends } from './ui/view_legends.js'
import { initViewMenuPills } from './ui/view_menu_pills.js'
import { showConfirm }                         from './ui/primitives/confirm.js'
import { initSidebarResize }                   from './ui/sidebar_resize.js'
import { initSceneInspector }                  from './scene/scene_inspector.js'
import { createModal }                         from './ui/primitives/modal.js'
import { createButton }                        from './ui/primitives/button.js'
import { initBackgroundModal }                 from './ui/background_modal.js'
import { initFileLoadDialog }                  from './ui/file_load_dialog.js'
import { nadocBroadcast } from './shared/broadcast.js'
import { getDocId, mintDocId, docHeaders, docHeadersFor, docKey } from './shared/doc_id.js'
import { initMdOverlay }             from './scene/md_overlay.js'
import { initMdSegmentationOverlay } from './scene/md_segmentation_overlay.js'
import { initMdPanel }    from './ui/md_panel.js'
import { initReprOptionSliders } from './ui/repr_option_sliders.js'
import { initColoringOptionsPanel } from './ui/coloring_options_panel.js'
import { initRepresentationSwitcher } from './ui/representation_switcher.js'
import { initMdJobsPanel } from './ui/md_jobs_panel.js'
import { initChainSimPanel } from './ui/chain_sim_panel.js'
import { initClusterConnection } from './ui/cluster_connection.js'
import { initBenchmarkPanel } from './ui/benchmark_panel.js'
import { initAnchorGlow } from './scene/anchor_glow.js'
import { initClashOverlay } from './scene/clash_overlay.js'
import { initOxdnaDisplay } from './ui/oxdna_display.js'
import { mdVizApiAdapter } from './ui/md_viz_adapter.js'
import { initOxdnaJobsPanel } from './ui/oxdna_jobs_panel.js'
import { initMrdnaDisplay } from './ui/mrdna_display.js'
import { initMrdnaJobsPanel } from './ui/mrdna_jobs_panel.js'
import { initLammpsJobsPanel } from './ui/lammps_jobs_panel.js'
import { initLammpsForcesSetup } from './ui/lammps_forces_setup.js'
import { initCandoJobsPanel } from './ui/cando_jobs_panel.js'
import { initEngineSelector } from './ui/engine_selector.js'
import { initJobsPanelBase } from './ui/jobs_panel_base.js'
import { initCandoDisplay } from './ui/cando_display.js'
import { initCandoLegend } from './ui/cando_legend.js'
import { initEngineActivityHeaders } from './ui/engine_activity_headers.js'
import { initCandoCylinders } from './scene/cando_cylinders.js'
import { initMrdnaConnections } from './scene/mrdna_connections.js'
import { initOxdnaLive } from './ui/oxdna_live_controller.js'
import { initMdEngines }   from './ui/md_engines.js'
import { initEfieldGizmo } from './scene/efield_gizmo.js'
import { initForcesCard } from './ui/forces_card.js'
import { initOxdnaFloorSetup } from './ui/oxdna_floor_setup.js'
import { initOxdnaAnchorsSetup } from './ui/oxdna_anchors_setup.js'
import { createPhotoRenderer } from './scene/photo_renderer.js'
import { initPhotoMode }      from './scene/photo_mode.js'
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
    setRenderFn, resetRenderFn,
  } = initScene(canvas)

  // Bundle scene context for cadnano_view (and future modules that need camera/renderer switching).
  const sceneCtx = { scene, camera, renderer, controls, setRenderCamera, restoreRenderCamera, getRenderCamera, getActiveControls, setResizeCallback, clearResizeCallback, pushControls, popControls, captureCurrentCamera, animateCameraTo, setRenderFn, resetRenderFn }

  // ── World-origin axes (toggleable via View > Toggle Origin Axes). On by
  // default for an EMPTY part: a new/empty file shows the XYZ origin triad as an
  // orientation reference (the Extrude tool is how you start adding DNA). A
  // populated part hides it (its own geometry is the reference); the helix-count
  // subscriber below + _resetForNewDesign keep this in sync, and the View toggle
  // still lets the user override. ──────────────────────────────────────────────
  const originAxes = new THREE.AxesHelper(4)
  originAxes.visible = true
  scene.add(originAxes)
  // Show/sync the triad whenever the design transitions to empty (force-on only —
  // never auto-hide on populate, so a user's explicit View-menu choice survives).
  function _syncOriginAxesForEmpty() {
    const { currentDesign, assemblyActive } = store.getState()
    if (axesVisibleForDesign(currentDesign, assemblyActive) && !originAxes.visible) {
      originAxes.visible = true
      _setMenuToggle('menu-view-axes', true)
    }
  }

  // ── Design renderer (reactive — shows helices when store has geometry) ───────
  const designRenderer = initDesignRenderer(scene, store)

  // ── Assembly renderer (shows PartInstance geometry when assembly mode active) ─
  // Phase 7e (2026-05-20): the shared-instancing renderer is now the DEFAULT
  // for every assembly (path-to-thousands flip). The old per-instance renderer
  // stays as a fallback for one release; a later cleanup PR removes it.
  // Opt OUT of shared (back to per-instance) via either:
  //   • `?shared=0` in the URL (per-tab), or
  //   • `localStorage.NADOC_SHARED_RENDERER = 'false'` then reload (sticky).
  const _sharedParam = new URLSearchParams(location.search).get('shared')
  const useShared =
    _sharedParam !== '0' &&
    localStorage.getItem('NADOC_SHARED_RENDERER') !== 'false' &&
    window.NADOC_SHARED_RENDERER !== false
  const assemblyRenderer = createAssemblyRenderer({
    scene, store, api,
    useShared,
  })

  // Debug hook (gated on shared flag for now): expose enough state for in-
  // browser diagnostic probes without leaking everything to prod. Remove
  // once shared renderer is stable.
  if (useShared) {
    // ── Continuous-loop FPS tracker (path-to-thousands LOD benchmark) ───────
    // scene.js renders every frame via setAnimationLoop, so each frame-callback
    // tick == one on-screen frame.  We keep an EMA of instantaneous FPS for the
    // HUD plus per-frame draw-call / triangle counts (read from renderer.info,
    // which reflects the prior frame — off-by-one is negligible).  sampleFps()
    // turns on a fixed-duration capture window the automated sweep awaits.
    const _frameStats = {
      last: performance.now(), dt: 0, ema: 0, drawCalls: 0, triangles: 0,
      _samples: null,
    }
    addFrameCallback(() => {
      const now = performance.now()
      const dt = now - _frameStats.last
      _frameStats.last = now
      _frameStats.dt = dt
      const fps = dt > 0 ? 1000 / dt : 0
      _frameStats.ema = _frameStats.ema ? _frameStats.ema * 0.9 + fps * 0.1 : fps
      const ri = renderer.info.render
      _frameStats.drawCalls = ri.calls
      _frameStats.triangles = ri.triangles
      if (_frameStats._samples) _frameStats._samples.push(dt)
    })

    window.__NADOC_DBG__ = {
      scene, camera, renderer, assemblyRenderer, store, THREE, controls, animateCameraTo,
      designRenderer,
      get unfoldView() { return unfoldView },

      // Crossover-tube validation metric — select a crossover, then call this to read
      // the LIVE tube geometry (sides / completeness / NaN). See getSelectionArcTubeStats.
      tubeStats: () => designRenderer.getSelectionArcTubeStats(),

      /**
       * Track-B diagnostic. Pre-conditions:
       *   1. window.NADOC_DBG_RENDER_TRACE = true   (BEFORE the assembly built)
       *   2. Reload the page and let the assembly finish loading.
       *
       * Then call __NADOC_DBG__.traceFrame() to render one frame with reset
       * counters and dump structured stats: total draw calls, triangles,
       * lines, per-shared-mesh onBeforeRender hit counts. Lets us see
       * whether the bp InstancedMeshes are actually being drawn each frame.
       */
      traceFrame() {
        if (renderer._nadocTrace) renderer._nadocTrace.clear()
        renderer.info.reset()
        renderer.render(scene, camera)
        const info = renderer.info
        console.log('--- traceFrame ---')
        console.log('renderer.info.render:', { ...info.render })
        console.log('renderer.info.memory:', { ...info.memory })
        console.log('renderer.info.programs.length:', info.programs?.length)
        if (renderer._nadocTrace && renderer._nadocTrace.size > 0) {
          console.log('Per-shared-mesh onBeforeRender hits this frame:')
          for (const [id, hits] of renderer._nadocTrace.entries()) {
            console.log(' ', id, '→', hits)
          }
        } else {
          console.log('No traces — was window.NADOC_DBG_RENDER_TRACE = true at rebuild time?')
        }
        // Also collect the shared meshes that should be drawn this frame
        const shared = []
        scene.traverse(o => {
          if (o.isInstancedMesh && o.count > 0 && o.material?.userData?.shader?.uniforms?.u_instanceXform) {
            shared.push({
              name: o.name || '(unnamed)',
              id: o.id,
              count: o.count,
              visible: o.visible,
              materialVisible: o.material.visible,
              frustumCulled: o.frustumCulled,
              parentVisible: o.parent?.visible,
            })
          }
        })
        console.log('Shared-renderer InstancedMeshes that COULD draw:', shared.length)
        shared.forEach(s => console.log(' ', s))
      },

      /**
       * Angular-LOD diagnostic.  Prints a table of every source's last-frame
       * bucket counts (close/mid/far), the pixel-size range across visible
       * instances, and the current closePx/farPx thresholds.  Run this
       * while zooming to see whether maxPxSize is crossing closePx (=60
       * by default).  If maxPxSize stays below closePx no matter how close
       * you zoom, the angular math has an upstream bug — call out
       * pxFactor / bboxDiag values.
       */
      probeLod() {
        const snap = assemblyRenderer.probeLod?.()
        if (!snap) { console.warn('[dbg] probeLod not exposed (shared path off?)'); return }
        console.log('--- LOD probe ---')
        console.log('thresholds:', { closePx: snap.closePx, farPx: snap.farPx })
        console.table(snap.sources)
        return snap
      },

      /**
       * Tune the angular-LOD thresholds without a reload.  Lower closePx
       * to make close-LOD trigger more easily; lower farPx to delay the
       * far billboard.  Example:
       *   __NADOC_DBG__.setLodThresholds({ closePx: 20, farPx: 4 })
       */
      setLodThresholds(opts) {
        assemblyRenderer.setLodThresholds?.(opts)
        console.log('[dbg] new thresholds applied:', opts)
      },

      /**
       * Toggleable on-canvas HUD that updates every frame with the current
       * LOD bucket counts + pixel-size range, per source.  Call once to
       * show; call again to hide.  Useful while zooming/panning to see
       * the bucket transitions live.
       */
      toggleLodHud() {
        if (window.__NADOC_LOD_HUD__) {
          window.__NADOC_LOD_HUD__.remove()
          window.__NADOC_LOD_HUD__ = null
          if (window.__NADOC_LOD_HUD_RAF__) {
            cancelAnimationFrame(window.__NADOC_LOD_HUD_RAF__)
            window.__NADOC_LOD_HUD_RAF__ = null
          }
          console.log('[dbg] LOD HUD off')
          return
        }
        const hud = document.createElement('div')
        hud.style.cssText = `
          position: fixed; top: 80px; right: 12px; z-index: 10000;
          background: rgba(13,17,23,0.88); color: #c9d1d9;
          padding: 8px 12px; border-radius: 6px;
          font-family: ui-monospace, monospace; font-size: 11px;
          line-height: 1.5; pointer-events: none;
          border: 1px solid #30363d; white-space: pre;
        `
        document.body.appendChild(hud)
        window.__NADOC_LOD_HUD__ = hud
        const tick = () => {
          const fpsLine = `${_frameStats.ema.toFixed(0)} fps  ${_frameStats.dt.toFixed(1)} ms  `
            + `${_frameStats.drawCalls} draws  ${(_frameStats.triangles / 1e3).toFixed(0)}k tris`
          const snap = assemblyRenderer.probeLod?.()
          if (!snap || snap.sources.length === 0) {
            hud.textContent = `LOD HUD\n${fpsLine}\n(no sources)`
          } else {
            const lines = [`LOD HUD  closePx=${snap.closePx}  farPx=${snap.farPx}`, fpsLine]
            for (const s of snap.sources) {
              const c = s.counts ?? { close: '-', mid: '-', far: '-', hull: '-' }
              const px = (s.minPxSize == null || s.maxPxSize == null)
                ? '(no data)'
                : `${s.minPxSize.toFixed(1)}…${s.maxPxSize.toFixed(1)} px`
              const key = s.srcKey.length > 28 ? s.srcKey.slice(-28) : s.srcKey
              lines.push(
                `${key}\n  N=${s.numInstances}  close=${c.close} mid=${c.mid} far=${c.far} hull=${c.hull ?? '-'}\n  pxSize=${px}  bboxDiag=${s.bboxDiag?.toFixed(0) ?? '?'}`,
              )
            }
            hud.textContent = lines.join('\n')
          }
          window.__NADOC_LOD_HUD_RAF__ = requestAnimationFrame(tick)
        }
        tick()
        console.log('[dbg] LOD HUD on (call toggleLodHud() again to dismiss)')
      },

      /** Live frame-stats snapshot: smoothed FPS, last frame ms, draw calls,
       *  triangles.  Cheap — read it any time. */
      fps() {
        return {
          fps: +_frameStats.ema.toFixed(1),
          frameMs: +_frameStats.dt.toFixed(2),
          drawCalls: _frameStats.drawCalls,
          triangles: _frameStats.triangles,
        }
      },

      /**
       * Collect a fixed-duration FPS sample window (default 2 s) and return a
       * Promise of summary stats.  The automated sweep awaits this AFTER it has
       * positioned the camera + let the LOD settle.  p5Fps is the 5th-percentile
       * (worst-case stutter) FPS — the number that decides whether a config is
       * actually smooth, not just smooth-on-average.
       */
      async sampleFps(durationMs = 2000) {
        _frameStats._samples = []
        await new Promise(r => setTimeout(r, durationMs))
        const dts = _frameStats._samples
        _frameStats._samples = null
        if (!dts || !dts.length) return { frames: 0 }
        const fpsArr = dts.map(d => 1000 / d).sort((a, b) => a - b)
        const q = p => fpsArr[Math.min(fpsArr.length - 1,
          Math.max(0, Math.floor(p * fpsArr.length)))]
        const avg = fpsArr.reduce((s, v) => s + v, 0) / fpsArr.length
        return {
          frames: dts.length,
          avgFps: +avg.toFixed(1),
          medianFps: +q(0.5).toFixed(1),
          p5Fps: +q(0.05).toFixed(1),
          minFps: +fpsArr[0].toFixed(1),
          drawCalls: renderer.info.render.calls,
          triangles: renderer.info.render.triangles,
        }
      },

      /**
       * Patch every assembly instance to one representation so the LOD ladder
       * is exercised at that rep.  full/beads → close-LOD eligible (cap 0);
       * cylinders → mid floor (cap 1); hull-prism → hull bucket (cap 3).
       * Returns the instance count.  Single batched PATCH → one renderer
       * rebuild (slow at scale for 'full' — that IS the cold-build cost).
       */
      async setAllRep(repr) {
        const insts = store.getState().currentAssembly?.instances ?? []
        if (!insts.length) { console.warn('[dbg] no assembly instances'); return 0 }
        await api.batchPatchInstances(insts.map(i => ({ id: i.id, representation: repr })))
        console.log(`[dbg] set ${insts.length} instances → '${repr}'`)
        return insts.length
      },

      /**
       * Distance (nm) that frames the whole assembly to the viewport height.
       * margin > 1 zooms out a touch so nothing clips the edge.
       */
      fitDist(margin = 1.2) {
        const box = assemblyRenderer.getBoundingBox?.()
        if (!box || box.isEmpty()) return null
        const radius = box.getBoundingSphere(new THREE.Sphere()).radius
        const fov = camera.fov * Math.PI / 180
        return +(radius * margin / Math.tan(fov / 2)).toFixed(1)
      },

      /**
       * Place the camera at distance d (nm) from the assembly centre along the
       * current view direction, looking at the centre.  Reproducible framing
       * for the camera-distance sweep + manual runs.  Returns {radius, dist}.
       */
      setCameraDist(d, dirArr) {
        const box = assemblyRenderer.getBoundingBox?.()
        if (!box || box.isEmpty()) { console.warn('[dbg] no assembly bbox'); return null }
        const center = box.getCenter(new THREE.Vector3())
        const radius = box.getBoundingSphere(new THREE.Sphere()).radius
        const dir = Array.isArray(dirArr)
          ? new THREE.Vector3(dirArr[0], dirArr[1], dirArr[2])
          : camera.position.clone().sub(controls.target)
        if (dir.lengthSq() < 1e-9) dir.set(0, 0, 1)
        dir.normalize()
        camera.position.copy(center).add(dir.multiplyScalar(d))
        controls.target.copy(center)
        camera.near = Math.max(0.1, d - radius * 2)
        camera.far = d + radius * 4
        camera.updateProjectionMatrix()
        controls.update()
        return { radius: +radius.toFixed(1), dist: d }
      },
    }
  }

  // ── Camera nav: OrbitControls + always-on smooth WASD pan ───────────────
  // (Removed: auto-transition to fly mode at high zoom-out — was distracting
  // when fitting large polymer chains in view.)
  const navController = initNavController({
    scene, camera, controls, canvas,
    store, assemblyRenderer, designRenderer,
    addFrameCallback,
  })

  // Forward-declared so the per-frame camera-clip callback below (which reads
  // photoRenderer.getFloorReach) is safe before photoRenderer is created far
  // below. Without this, any boot path that yields to requestAnimationFrame
  // before that creation (e.g. the part-editor tab, which awaits its design
  // fetch early) hits a `const` temporal-dead-zone throw INSIDE the frame
  // callback — and since three.js reschedules the loop only AFTER the callback,
  // one throw kills the render loop permanently (blank workspace). null until
  // assigned; the callback no-ops via `?.` until then. (mirrors `clusterPanel`.)
  let photoRenderer = null

  // ── Adaptive camera clipping for large assemblies ─────────────────────────
  // The camera's far plane is a fixed 2000 nm (sized for a single design — see
  // scene.js). A large assembly spans far more, so instances past 2000 nm from
  // the camera were hard-clipped — the "cutoff beyond which far parts stop
  // rendering". In assembly mode we bracket near/far around the assembly's
  // bounding sphere every frame so even distant parts draw, while keeping the
  // depth range tight enough for z-precision. The O(N) bounds recompute is
  // throttled (every 15 frames); the per-frame cost is a single distance calc.
  // Outside assembly mode we restore the 0.1 / 2000 default.
  {
    const _clipCtr  = new THREE.Vector3()
    const _clipSize = new THREE.Vector3()
    let _clipRadius = 0
    let _clipTick   = 0
    const _applyClip = (far, near) => {
      if (near >= far) near = far * 1e-4
      if (Math.abs(camera.far - far) > far * 1e-3 ||
          Math.abs(camera.near - near) > Math.max(near, 0.01) * 1e-2) {
        camera.far  = far
        camera.near = near
        camera.updateProjectionMatrix()
      }
    }
    // Photo-mode floor reach (world centre + half-extent) or null. When a floor
    // is active the far clip must reach past it, or the floor gets cropped near
    // the content — this is what made the "infinite" floor still look small,
    // especially in assembly mode where far brackets the content tightly.
    const _floorReach = () => photoRenderer?.getFloorReach?.() ?? null
    addFrameCallback(() => {
      if (!store.getState().assemblyActive) {
        // Part mode: far is normally pinned at 2000. If a photo floor is up,
        // extend far to include the whole plane so it reaches a far horizon.
        const floor = _floorReach()
        if (floor?.center) {
          const d   = camera.position.distanceTo(floor.center)
          const far = Math.max(2000, d + floor.reach + 1)
          _applyClip(far, Math.max(0.1, far / 1e5))
        } else if (camera.near !== 0.1 || camera.far !== 2000) {
          camera.near = 0.1; camera.far = 2000; camera.updateProjectionMatrix()
        }
        return
      }
      if ((_clipTick++ % 15) === 0) {
        const box = assemblyRenderer.getBoundingBox?.()
        if (box && !box.isEmpty()) {
          box.getCenter(_clipCtr)
          _clipRadius = box.getSize(_clipSize).length() * 0.5
        } else {
          _clipRadius = 0
        }
      }
      if (_clipRadius <= 1e-3) return
      const d = camera.position.distanceTo(_clipCtr)
      // Expand the effective radius to enclose the photo floor (if any) so the
      // far clip doesn't crop it. near still tracks the CONTENT radius so the
      // depth buffer stays tight around the parts.
      let reach = _clipRadius
      const floor = _floorReach()
      if (floor?.center) reach = Math.max(reach, floor.center.distanceTo(_clipCtr) + floor.reach)
      const margin = reach * 0.1 + 1
      const far  = d + reach + margin
      // Tightest near that still covers the content, floored both absolutely
      // (0.1 nm) and relative to far (cap the depth-buffer ratio so distant
      // billboards don't z-fight the near parts into mush).
      const near = Math.max(d - _clipRadius - (_clipRadius * 0.1 + 1), far / 1e5, 0.1)
      _applyClip(far, near)
    })
  }

  // ── Cross-tab sync ──────────────────────────────────────────────────────────
  // Reuses the existing nadocBroadcast channel + the established
  // "part-design-updated" message type (already emitted from part-edit Save
  // and handled below by `_assemblyRefresh.requestRefresh` for assembly windows).
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

  // ── Extrude preview (ghost cylinders) ──────────────────────────────────────
  // A "Show preview" toggle in each extrude popup (slice-plane ctx-menu, handled
  // inside slice_plane.js; and the overhang-extrude dialog, handled here) shows a
  // translucent preview of the DNA the extrude will add. Default ON, persisted.
  let _extrudePreviewEnabled = localStorage.getItem('NADOC_EXTRUDE_PREVIEW') !== 'false'  // default ON
  let _ovhgGhost = null              // THREE.Mesh — overhang preview cylinder, or null
  let _refreshOverhangGhost = () => {}  // set by the overhang dialog while it is open

  function _clearOverhangGhost() {
    if (!_ovhgGhost) return
    scene.remove(_ovhgGhost)
    _ovhgGhost.geometry.dispose()
    _ovhgGhost.material.dispose()
    _ovhgGhost = null
  }

  /**
   * Build/refresh the overhang-extrude ghost cylinder for the pending arrow.
   * Mirrors backend make_overhang_extrude geometry: a new helix at the neighbour
   * cell, bp 0 at the nick Z, extending length_bp × rise along the axis in the
   * overhang_z_dir direction (derived from the nick end-type + strand direction
   * + the parent helix's Z-sign).  Design-mode only (skips assembly instances).
   */
  function _showOverhangGhost(entry, lengthBp) {
    _clearOverhangGhost()
    if (!_extrudePreviewEnabled || !entry || entry.instanceId) return
    if (!Number.isFinite(lengthBp) || lengthBp < 1) return
    if (!entry.pos3D || !entry.dir) return
    const design = store.getState().currentDesign
    const h = design?.helices?.find(x => x.id === entry.helixId)
    if (!h) return

    const zSign        = (h.axis_end.z - h.axis_start.z) >= 0 ? 1 : -1
    const strandZDir   = entry.direction === 'FORWARD' ? zSign : -zSign
    const overhangZDir = entry.isFivePrime ? strandZDir : -strandZDir

    // World axial direction: +Z (× sign), rotated by the helix's cluster pose if any.
    const axial = new THREE.Vector3(0, 0, overhangZDir)
    const ct = (design.cluster_transforms ?? []).find(t => t.helix_ids?.includes(entry.helixId))
    if (ct) axial.applyQuaternion(new THREE.Quaternion(ct.rotation[0], ct.rotation[1], ct.rotation[2], ct.rotation[3]))
    axial.normalize()

    const HC_SPACING = 2.25  // nm — helix centre-to-centre (matches overhang_locations)
    const start = entry.pos3D.clone().addScaledVector(entry.dir.clone().normalize(), HC_SPACING)
    const lengthNm = lengthBp * BDNA_RISE_PER_BP

    const geo = new THREE.CylinderGeometry(HELIX_RADIUS, HELIX_RADIUS, lengthNm, 16, 1, true)
    const mat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff, transparent: true, opacity: 0.25, depthWrite: false, side: THREE.DoubleSide,
    })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.name = 'overhang-extrude-preview'
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axial)
    mesh.position.copy(start).addScaledVector(axial, lengthNm / 2)
    mesh.renderOrder = 4
    scene.add(mesh)
    _ovhgGhost = mesh
  }

  // ── Selection-filter row ─────────────────────────────────────────────────────
  // The #select-filter button row is extracted to ui/selection_filter.js.
  // `reflectDrillLevel` is injected into initSelectionManager (below) as
  // `onDrillLevel`. `attachFilterButtons()` registers the button handlers +
  // subscribers at the original ~4852 spot (subscription order preserved).
  // selectionManager doesn't exist yet → reached via a lazy getter (all callers
  // fire on user action, post-init).
  const selectionFilter = initSelectionFilter({
    store,
    getSelectionManager: () => selectionManager,
  })

  // ── Selection manager ───────────────────────────────────────────────────────
  // Forward ref to the atomistic/surface display subsystem (initialized after
  // surfaceRenderer is built, ~1000 ln below). Lazy callers (selection picking,
  // animation player onEvent/onFetchSurfaceBatch, periodic-MD) only fire post-boot,
  // so this resolves by then (boot-capture pattern, #81).
  let _atomSurface = null
  const selectionManager = initSelectionManager(canvas, camera, designRenderer, {
    getProteinRenderer: () => proteinRenderer,
    // Per-region overlay renderers (mixed rep) — lazy getters resolve after they're
    // created below; used for atom/surface picking in atomistic/surface regions.
    getRegionVdwRenderer:       () => _atomSurface.getRegionVdwRenderer(),
    getRegionBallstickRenderer: () => _atomSurface.getRegionBallstickRenderer(),
    getRegionSurfaceRenderer:   () => _atomSurface.getRegionSurfaceRenderer(),
    onDrillLevel: selectionFilter.reflectDrillLevel,
    onNick: async ({ helixId, bpIndex, direction }) => {
      _clearStapleChecks()
      // A nick is a topology change; drop the scaffold-routing indicator (the
      // unified scaffold context menu's "Nick here" routes through here).
      _clearScaffoldChecks()
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
    onScaffoldAssignSequence: (strandId) => {
      // "Assign sequence…" in the unified scaffold context menu (selection_manager).
      _scaffoldModal.openModal(strandId)
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
    onFlexibleSegmentRightClick: async (nuc, action, extra) => {
      // Flexible ssDNA segments (pose & explore mechanisms). Mark/unmark the
      // contiguous unpaired RUN containing the clicked bead, unmark a whole
      // connection (right-click its arc), or clear all. Display-layer only.
      try {
        if (action === 'clear') {
          await api.batchFlexibleSegment({ replace: true })
          showToast('Cleared all flexible segments')
          return
        }
        if (action === 'relax_all') { await _flexRelax.relaxFlexible('all'); return }
        if (action === 'relax_one') {
          let connId = extra
          if (!connId && nuc) connId = connIdForBead(nuc, store.getState().currentDesign)
          if (!connId) { showToast('No flexible connection here', { severity: 'error' }); return }
          await _flexRelax.relaxFlexible('one', connId)
          return
        }
        if (action === 'unmark_connection') {
          const cd = store.getState().currentDesign
          const conn = (cd?.flexible_connections ?? []).find(c => c.id === extra)
          if (!conn) return
          const segKeys = new Set((conn.segment_bead_keys ?? [])
            .map(k => `${k.strand_id}:${k.domain_index}:${k.bp_index}:${k.direction}`))
          const keep = (cd?.flexible_segment_marks ?? [])
            .filter(m => !segKeys.has(`${m.strand_id}:${m.domain_index}:${m.bp_index}:${m.direction}`))
            .map(m => ({ strand_id: m.strand_id, domain_index: m.domain_index, bp_index: m.bp_index, direction: m.direction }))
          await api.batchFlexibleSegment({ marks: keep, replace: true })
          showToast('Unmarked flexible segment')
          return
        }
        const { currentDesign, currentGeometry } = store.getState()
        const run = flexibleRunForBead(currentDesign, currentGeometry, nuc)
        if (!run.length) return
        if (action === 'mark') {
          const existing = currentDesign?.flexible_segment_marks ?? []
          const keep = existing.map(m => ({
            strand_id: m.strand_id, domain_index: m.domain_index,
            bp_index: m.bp_index, direction: m.direction,
          }))
          await api.batchFlexibleSegment({ marks: [...keep, ...run], replace: true })
          showToast(`Marked ${run.length}-base flexible segment`)
        } else if (action === 'unmark') {
          const runKeys = new Set(run.map(r => `${r.strand_id}:${r.domain_index}:${r.bp_index}:${r.direction}`))
          const keep = (currentDesign?.flexible_segment_marks ?? [])
            .filter(m => !runKeys.has(`${m.strand_id}:${m.domain_index}:${m.bp_index}:${m.direction}`))
            .map(m => ({ strand_id: m.strand_id, domain_index: m.domain_index, bp_index: m.bp_index, direction: m.direction }))
          await api.batchFlexibleSegment({ marks: keep, replace: true })
          showToast('Unmarked flexible segment')
        }
      } catch (err) {
        showToast(err?.message || String(err), { severity: 'error' })
      }
    },
    onOverhangRightClick: (ovhgIds, clientX, clientY) => {
      _orientMenu.show(ovhgIds, clientX, clientY)
    },
    onOpenOverhangsManager: (ovhgIds) => {
      const { currentDesign } = store.getState()
      if (!currentDesign?.helices?.length) return
      openOverhangsManager(ovhgIds)
    },
    onClusterMoveRotate: async (clusterId) => {
      // Right-click on a selected cluster → activate the move/rotate gizmo
      // targeting that cluster (same path as the toolbar Move/Rotate button).
      store.setState({ activeClusterId: clusterId })
      await _activateTranslateRotateTool(clusterId)
    },
    onEmptyContextMenu: (clientX, clientY) => {
      // Right-click on empty 3D space → minimal "Extrude" menu. Suppressed while the
      // slice plane / Extrude tool is already up (it owns its own interaction) and
      // in assembly mode (separate context menu).
      if (store.getState().assemblyActive) return
      if (slicePlane.isVisible() || _extrudePanel?.isActive()) return
      emptySpaceMenu.show(clientX, clientY)
    },
    // Lazy getters — defined later in this init sequence.
    getUnfoldView:          () => unfoldView,
    getOverhangLocations:   () => overhangLocations,
    getOverhangLinkArcs:    () => overhangLinkArcs,
    getFlexibleArcs:        () => flexibleArcs,
    getLoopSkipHighlight:   () => loopSkipHighlight,
    controls,
    getHoverEntry: () => zoomScope.getHoverEntry(),
    getCamera:     () => sceneCtx.getRenderCamera(),
    isDisabled:    () => slicePlane?.isContinuation() || store.getState().forceXoverActive,
  })

  // ── End extrusion arrows ──────────────────────────────────────────────────────
  // Thick arrows pointing outward along the helix axis at each selected 5'/3' end.
  const endExtrudeArrows = initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, controls, {
    getCamera:   () => sceneCtx.getRenderCamera(),
    getControls: () => sceneCtx.getActiveControls(),
  })

  // ── Measurement tool ─────────────────────────────────────────────────────────
  // 3D line + distance readout between exactly 2 ctrl-clicked beads (press 'M';
  // not valid in unfold view). Self-wires to ctrl-bead changes and also refreshes
  // the selection-count HUD on each change. _updateSelectionHud is hoisted (defined
  // just below), so the callback resolves it lazily.
  const measurementTool = initMeasurementTool({
    scene,
    selectionManager,
    onSelectionHudChange: () => _updateSelectionHud(),
  })

  // One-time hint about the 2026-05-17 selection-modifier remap. Ctrl was
  // overloaded (lasso AND measurement-bead pick); measurement bead now lives
  // on Alt-click and Shift-click is the new additive-selection modifier.
  const _SEL_HINT_KEY = 'nadoc.hint.selModifiers.v1'
  if (!localStorage.getItem(_SEL_HINT_KEY)) {
    setTimeout(() => {
      showToast(
        'Selection: Alt-click = measure distance · Shift-click = add to selection · Ctrl-drag = lasso',
        { duration: 8000 },
      )
      localStorage.setItem(_SEL_HINT_KEY, '1')
    }, 1500)
  }

  // ── Selection-count HUD ─────────────────────────────────────────────────────
  // Persistent indicator at the bottom of the viewport for whatever has multi-
  // selection state. Lasso/multi-pick are easy to forget about; this gives the
  // user a fixed glanceable count.
  const _selHudEl = document.getElementById('selection-count-hud')
  function _updateSelectionHud() {
    if (!_selHudEl) return
    const st = store.getState()
    const parts = []
    const ns = st.multiSelectedStrandIds?.length ?? 0
    const nd = st.multiSelectedDomainIds?.length ?? 0
    const no = (selectionManager.getMultiOverhangs?.() ?? []).length
    const nx = (selectionManager.getMultiCrossoverArcs?.() ?? []).length
    const nb = selectionManager.getCtrlBeads?.().length ?? 0
    if (ns) parts.push(`${ns} strand${ns === 1 ? '' : 's'}`)
    if (nd) parts.push(`${nd} domain${nd === 1 ? '' : 's'}`)
    if (no) parts.push(`${no} overhang${no === 1 ? '' : 's'}`)
    if (nx) parts.push(`${nx} crossover${nx === 1 ? '' : 's'}`)
    if (nb) parts.push(`${nb} bead${nb === 1 ? '' : 's'}`)
    if (!parts.length) { _selHudEl.style.display = 'none'; return }
    _selHudEl.textContent = parts.join(' · ') + ' selected'
    _selHudEl.style.display = 'flex'
  }
  store.subscribe((ns, ps) => {
    if (ns.multiSelectedStrandIds !== ps.multiSelectedStrandIds ||
        ns.multiSelectedDomainIds !== ps.multiSelectedDomainIds) {
      _updateSelectionHud()
    }
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

      <label style="display:flex;align-items:center;gap:6px;margin-top:10px;font-size:11px;color:#c9d1d9;cursor:pointer"
             title="Show a translucent preview of the overhang this will add">
        <input id="ovhg-preview-toggle" type="checkbox" checked style="cursor:pointer"> Show preview
      </label>

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
    const previewToggle = overlay.querySelector('#ovhg-preview-toggle')

    // bp length for the active tab — drives the live ghost preview.
    function _currentOverhangLen() {
      if (_activeTab === 'length') return parseInt(lenInput.value, 10)
      return seqInput.value.replace(/\s/g, '').length
    }
    function _refreshGhost() { _showOverhangGhost(_pendingEntry, _currentOverhangLen()) }

    // "Show preview" lives in this popup; mirror the shared flag + persist + sync slice plane.
    previewToggle.addEventListener('change', () => {
      _extrudePreviewEnabled = previewToggle.checked
      localStorage.setItem('NADOC_EXTRUDE_PREVIEW', String(_extrudePreviewEnabled))
      slicePlane.setPreviewEnabled(_extrudePreviewEnabled)
      _refreshGhost()   // shows or clears based on the flag
    })

    function _switchTab(tab) {
      _activeTab = tab
      const isLen = tab === 'length'
      tabLength.style.cssText  = isLen ? tabActiveStyle : tabStyle
      tabSeq.style.cssText     = isLen ? tabStyle : tabActiveStyle
      panelLen.style.display   = isLen ? '' : 'none'
      panelSeq.style.display   = isLen ? 'none' : ''
      okBtn.textContent        = isLen ? 'Extrude' : 'Extrude + Assign'
      setTimeout(() => (isLen ? lenInput : seqInput).focus(), 0)
      _refreshGhost()
    }

    tabLength.addEventListener('click', () => _switchTab('length'))
    tabSeq.addEventListener('click',    () => _switchTab('seq'))

    lenInput.addEventListener('input', _refreshGhost)
    seqInput.addEventListener('input', () => {
      const n = seqInput.value.replace(/\s/g, '').length
      seqLenEl.textContent = `${n} bp`
      seqLenEl.style.color = n > 0 ? '#8b949e' : '#484f58'
      _refreshGhost()
    })

    function _hide() {
      overlay.style.display = 'none'
      _pendingEntry = null
      seqInput.value  = ''
      nameInput.value = ''
      seqLenEl.textContent = '0 bp'
      seqLenEl.style.color = '#484f58'
      _clearOverhangGhost()
      _refreshOverhangGhost = () => {}
    }

    _showOverhangLengthDialog = function(entry, clientX, clientY) {
      _pendingEntry = entry
      overlay.style.left    = `${Math.min(clientX, window.innerWidth  - 290)}px`
      overlay.style.top     = `${Math.min(clientY, window.innerHeight - 200)}px`
      overlay.style.display = 'block'
      _switchTab('length')
      lenInput.value  = '10'
      nameInput.value = ''
      previewToggle.checked = _extrudePreviewEnabled
      nameInput.focus()
      _refreshOverhangGhost = _refreshGhost
      _refreshGhost()
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

  // Circular (loop) staples are flagged purely by the warning highlight in the 3D
  // + cadnano views (driven by store.loopStrandIds). There is intentionally no
  // auto-nick suggestion UI — the user linearizes manually via the generic
  // "Nick here" context-menu action.

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

  // oxDNA controls consolidated into the single #oxdna-jobs-panel (initOxdnaJobsPanel).

  // ── Bend/Twist deformation editor ──────────────────────────────────────────

  // Context set while editing an existing feature; cleared on confirm or cancel.
  let _editContext = null  // { priorCursor, pendingParams }

  initDeformationEditor(scene, camera, canvas, controls, designRenderer,
    () => {
      // onExit: restore mode indicator + (for an unconfirmed edit) restore
      // the original op that _onEditFeature peeled off the design.
      //
      // The deformation editor's preview-op DELETE already happened inside
      // _exitTool → _clearPreviewSession. But the ORIGINAL op was peeled off
      // separately by _onEditFeature, so design.deformations is missing it
      // until we replay the log. A seek to priorCursor handles that — the
      // backend re-runs the log and the original op pops back with its
      // original params. Triggered when _editContext is still set on exit
      // (Cancel / Escape paths). onConfirm clears _editContext BEFORE
      // exiting, so the seek-restore is skipped on the confirm path
      // (editFeature already updated the log and rebuilt design.deformations).
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      const ctx = _editContext
      _editContext = null
      if (ctx?.editingFeatureType === 'deformation' && ctx.origOpId) {
        _seekFeaturesWithDelta(ctx.priorCursor ?? -1).catch(() => {})
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
        // Edit-confirm: the bent GHOST is currently held by a preview op
        // (added by previewDeformation while the original op was peeled off
        // in _onEditFeature). editFeature updates the log entry's snapshot
        // and rebuilds design.deformations from the log — the backend
        // explicitly drops any preview op as part of that rebuild
        // (see backend _edit_deformation_feature). So a single editFeature
        // call commits the new params and cleans the overlay in one shot.
        const planes = getDeformPlanes()
        const bpA = planes.a?.bp ?? 0
        const bpB = planes.b?.bp ?? 0
        const editBody = {
          type:       getDeformToolType() ?? 'twist',
          plane_a_bp: Math.min(bpA, bpB),
          plane_b_bp: Math.max(bpA, bpB),
          params,
          cluster_ids: ctx.clusterIds ?? [],
        }
        markDeformEditCommitted()   // so the exit below does NOT revert the op
        const resp = await api.editFeature(ctx.featureIndex, editBody)
        if (resp == null) {
          showToast(`Edit failed: ${store.getState().lastError?.message ?? 'unknown error'}`, 4000)
        } else if (ctx.priorCursor != null && ctx.priorCursor !== -1) {
          // editFeature leaves the cursor at latest; if the user was mid-scrub
          // when they hit edit, return the slider to where they were.
          await _seekFeaturesWithDelta(ctx.priorCursor)
        }
        _editContext = null
        deformExitTool()
        _watchDeformState()
        return
      }
      _editContext = null   // clear before confirm; addDeformation takes over
      await confirmDeformation(params)
      _watchDeformState()
    },
    onCancel: () => {
      // For an edit-cancel, leave _editContext set so onExit (called below
      // via deformExitTool → _exitTool) sees it and restores the original
      // op via seek. Escape goes through the same _exitTool path with the
      // same restore. New-op cancels (no _editContext) just exit cleanly.
      deformExitTool()
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
      const editClusterIds = _editContext ? (_editContext.clusterIds ?? []) : null
      // Edit mode now uses the preview-op flow (the original op was peeled off
      // in _onEditFeature). Let the initial preview fire so the popup's first
      // previewDeformation call lands beginDeformPreview (SOLID = un-deformed)
      // and adds the bent overlay (GHOST = deformed). The new-deformation
      // path obviously also wants the initial preview.
      const skipInitialPreview = false
      openDeformPopup(
        getDeformToolType() ?? 'twist',
        a?.bp ?? 0, b?.bp ?? 0,
        editParams,
        editClusterIds,
        skipInitialPreview,
      )
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
      _orientPanel.open(ovhgIds)
      return
    }

    // ── Move/rotate (cluster_op) edit — highlight cluster and open tool ─────
    if (entry.feature_type === 'cluster_op') {
      const clusterId = entry.cluster_id
      if (!clusterId) return
      // Editing an EARLIER op (a later cluster_op for this cluster exists): seek
      // the feature log to this op first so the cluster shows THIS step's pose
      // while you adjust it; commit/cancel seeks back to where the cursor was
      // (the latest pose). Only this step's pose is rewritten — the latest op
      // keeps defining the final pose. Editing the latest op needs no seek (the
      // live pose already == that op), preserving the in-place edit path.
      const log = store.getState().currentDesign?.feature_log ?? []
      const hasLater = log.slice(featureIndex + 1).some(e =>
        e.feature_type === 'cluster_op' && e.cluster_id === clusterId)
      let seekRestoreCursor = null
      if (hasLater) {
        seekRestoreCursor = store.getState().currentDesign?.feature_log_cursor ?? -1
        await api.seekFeatures(featureIndex)
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
        seekRestoreCursor,
      }
      return
    }

    const op = entry.op_snapshot
    if (!op) return

    const design = store.getState().currentDesign
    const priorCursor = design?.feature_log_cursor ?? -1

    // Edit flow: peel the original op off the design (silent DELETE preview=true)
    // so the live geometry becomes the pre-op (un-deformed) state. The popup's
    // first previewDeformation then freezes THAT as the SOLID reference and
    // re-adds the op as a preview overlay (the bent GHOST), restoring the
    // "before/after" visual comparison that's most useful when tuning bends.
    // The original log entry is untouched; Apply commits the new params via
    // editFeature(featureIndex, …) and the design rebuilds from the log;
    // Cancel deletes the preview overlay and seeks to priorCursor, replaying
    // the log to restore the original op with its original params.
    _editContext = {
      priorCursor,
      pendingParams:    op.params,
      featureIndex,
      editingFeatureType: entry.feature_type,
      clusterIds:       op.cluster_ids ?? [],
      // Original op id captured so cancel can no-op-restore it via the log
      // replay; the deformation editor's preview-op flow takes ownership of
      // the design from here.
      origOpId: op.id,
    }

    // Transient DELETE — exposes the un-deformed design under the bent overlay.
    let peeled = false
    try {
      const resp = await api.deleteDeformation(op.id, /*preview=*/true)
      peeled = resp != null
    } catch {
      // Non-fatal: if the delete fails the user falls back to the old in-place
      // edit (bent solid, no ghost). Without `peeled` the seek-restore below
      // is also skipped so the editor doesn't replay the log unnecessarily.
    }
    if (!peeled) _editContext.origOpId = null

    // Open editor in NEW-OP (preview) flow — _editOpId stays null so the
    // popup's first previewDeformation goes through addDeformation(preview=true),
    // producing a fresh preview op that owns the bent GHOST layer.
    startDeformToolForEdit(op.type, op.plane_a_bp, op.plane_b_bp, /*opId=*/null, op.params)

    document.getElementById('mode-indicator').textContent =
      `EDIT ${op.type.toUpperCase()} F${featureIndex + 1} — adjust params · Apply to save · Esc to cancel`

    // Open the popup now rather than waiting for a canvas pointerdown to fire it.
    _watchDeformState()
  }

  // ── 2D Unfold view ──────────────────────────────────────────────────────────
  // bluntEnds is initialized below; use a getter so unfoldView can call it lazily.
  const unfoldView = initUnfoldView(scene, designRenderer, () => bluntEnds, () => loopSkipHighlight, () => sequenceOverlay, () => overhangLocations, null)
  // Crossover arcs (owned by unfold_view) follow applyFemPositions (mrDNA/oxDNA display).
  designRenderer.setFemArcUpdater?.((updates) => unfoldView.applyFemArcs(updates))
  // …and follow the RMSF scalar recolour (oxDNA flexibility map).
  designRenderer.setScalarArcUpdater?.((colorByKey) => unfoldView.applyFemArcColors(colorByKey))

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
    getOverhangUnzipOverlay: () => overhangUnzipOverlay,
    getMultiOverhangStrandAnim: () => multiOverhangStrandAnim,
    getDesignGeometry:      () => store.getState().currentGeometry,
    // Pass through any opts (signal, suppressBusy) the player provides — the
    // bake loop wires its own AbortController and asks _request to skip the
    // generic "Working…" auto-popup so the panel's "Rendering Animation"
    // popup stays in front.
    onFetchGeometryBatch:   (positions, opts) => api.getGeometryBatch(positions, opts),
    // Trajectory keyframes: fetch a job's composite trajectory (all frames + stage
    // markers, aligned to the design) once per job — oxDNA or NAMD/MD by engine.
    onFetchTrajectory:      (jobId, engine) => engine === 'namd'
      ? api.getMdTrajectory(jobId)
      : api.getOxdnaTrajectory(jobId),
    // Heavy reps following a trajectory: per-frame atomistic / surface for a
    // downsampled subset of frame indices (same wire format as the batch calls).
    // oxDNA reconstructs the design's atoms; NAMD renders its own heavy atoms.
    onFetchTrajectoryAtomistic: (jobId, frameIndices, engine) => engine === 'namd'
      ? api.getMdFramesAtomistic(jobId, frameIndices)
      : api.getOxdnaFramesAtomistic(jobId, frameIndices),
    onFetchTrajectorySurface:   (jobId, frameIndices, engine) => {
      if (engine === 'namd') {
        return api.getMdFramesSurface(jobId, frameIndices, {
          probe_radius: _atomSurface.getSurfaceProbeRadius(),
        })
      }
      const { surfaceColorMode } = store.getState()
      return api.getOxdnaFramesSurface(jobId, frameIndices, {
        color_mode: surfaceColorMode,
        probe_radius: _atomSurface.getSurfaceProbeRadius(),
      })
    },
    // Restore the DESIGN atom set in the atomistic renderer after a NAMD
    // trajectory segment swapped in the MD model's own atoms (Phase 2b).
    onRestoreDesignAtomistic: () => {
      const mode = atomisticRenderer.getMode?.()
      if (mode && mode !== 'off') {
        _atomSurface.invalidateAtomCache()
        _atomSurface.applyAtomisticMode(mode)
      }
    },
    onFetchAtomisticBatch:  (positions, opts) => api.getAtomisticBatch(positions, opts),
    getAtomisticRenderer:   () => atomisticRenderer,
    onFetchSurfaceBatch: (positions, opts) => {
      const { surfaceColorMode } = store.getState()
      return api.getSurfaceBatch(positions, surfaceColorMode, _atomSurface.getSurfaceProbeRadius(), undefined, opts)
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
          _atomSurface.invalidateAtomCache()
          _atomSurface.applyAtomisticMode(atomisticRenderer.getMode())
        }
        if (_atomSurface.getSurfaceMode() !== 'off') {
          _atomSurface.invalidateSurfaceCache()
          _atomSurface.applySurfaceMode(_atomSurface.getSurfaceMode())
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
  // Also rebuild whenever the assembly renderer finishes a rebuild pass.
  // Every rebuild disposes the old instance Group and creates a new one;
  // arrows previously parented to the dead group would otherwise vanish
  // until the user manually flipped activeInstanceId. This closes the gap
  // for every assembly-rebuild path (initial load, SSE echo, mate resolve,
  // refresh-instance, etc.) without requiring caller-side discipline.
  assemblyRenderer.onRebuildComplete(() => _rebuildOverhangLocations())

  // ── Overhang Link Arcs (white tubes for design.overhang_connections) ────────
  const overhangLinkArcs = initOverhangLinkArcs(scene)
  const flexibleArcs = initFlexibleArcs(scene, designRenderer, () => store.getState().currentHelixAxes)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    overhangLinkArcs.rebuild(newState.currentDesign, newState.currentGeometry)
    flexibleArcs.rebuild(newState.currentDesign)
  })
  // Initial rebuild — when the persisted design was applied to the store
  // before this subscription was registered, the listener never fires.
  {
    const s = store.getState()
    if (s.currentDesign && s.currentGeometry) {
      overhangLinkArcs.rebuild(s.currentDesign, s.currentGeometry)
      flexibleArcs.rebuild(s.currentDesign)
    }
  }

  // Display-only unzip animation driven by the animation player during bind/unbind
  // φ playback. Moves the REAL overhang beads via the helix renderer (no synthetic
  // geometry, no store subscription — the player calls update()/clear() itself).
  const overhangUnzipOverlay = initOverhangUnzipOverlay({
    getHelixCtrl: () => designRenderer.getHelixCtrl(),
    getDesign:    () => store.getState().currentDesign,
  })

  // Rich strand-animation multi-driver for keyframe playback: one per-overhang
  // un/hybridization driver (overhang_strand_anim.js) per active overhang, sharing
  // the right-sidebar panel's math. The player calls setActive()/clear() itself.
  const multiOverhangStrandAnim = initMultiOverhangStrandAnim({
    getHelixCtrl: () => designRenderer.getHelixCtrl(),
    getGeometry:  () => store.getState().currentGeometry,
    getDesign:    () => store.getState().currentDesign,
    getScene:     () => scene,
  })


  // Right-click a rendered protein → "Conjugate protein to ssDNA…" → Conjugate Manager.
  canvas.addEventListener('contextmenu', (e) => {
    const rect = canvas.getBoundingClientRect()
    const ndc = {
      x:  ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      y: -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    }
    const rc = new THREE.Raycaster()
    rc.setFromCamera(ndc, camera)
    const pick = proteinRenderer?.raycastPick?.(rc)
    if (!pick) return
    const attId = pick.atom?.helix_id?.replace('__protein__', '')
    const assetId = store.getState().currentDesign?.protein_attachments?.find(a => a.id === attId)?.asset_id
    if (!assetId) return
    e.preventDefault()
    e.stopPropagation()
    conjugateManager.showConjugateMenu({ x: e.clientX, y: e.clientY, assetId })
  }, { capture: true })

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
  // Four maps built in dependency order on every geometry/design change. Feeds the
  // Overhang Orientation panel (junction bead positions via _ovhgRootMap).
  //
  //  Map 1  _ovhgSpecMap      id → OverhangSpec
  //  Map 2  _ovhgDomainMap    id → { strand, domIdx, domain }
  //  Map 3  _ovhgJunctionMap  id → { junctionBp, junctionDir }
  //  Map 4  _ovhgRootMap      id → { entry: BackboneEntry, pos: THREE.Vector3 }
  //
  // FINDINGS recorded during construction:
  //  • d.overhang_id === spec.id is the safe domain match; d.helix_id is ambiguous when
  //    a strand visits the same helix twice (latent bug in original _findOvhgRootEntry)
  //  • helixCtrl.lookupEntry("helix_id:bp_index:direction") is O(1) — preferred over
  //    backboneEntries.find() linear scan

  let _ovhgSpecMap         = new Map()
  let _ovhgDomainMap       = new Map()
  let _ovhgJunctionMap     = new Map()
  let _ovhgRootMap         = new Map()

  // Master build — called on every geometry/design change.
  function _buildOvhgMaps(design) {
    const helixCtrl = designRenderer.getHelixCtrl()
    _ovhgSpecMap        = buildSpecMap(design)
    _ovhgDomainMap      = buildDomainMapFromDesign(design, _ovhgSpecMap)
    _ovhgJunctionMap    = buildJunctionMapFromDomains(_ovhgDomainMap)
    _ovhgRootMap        = buildRootMap(_ovhgSpecMap, _ovhgJunctionMap, helixCtrl)
  }

  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    _buildOvhgMaps(newState.currentDesign)
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

  // ── Protein subsystem (imported proteins; independent of the DNA atomistic
  // mode so proteins coexist with cylinders/beads/atomistic DNA). Owns its own
  // atomistic renderer + transform gizmo + coalesced refresh + 2 subscribers. ──
  const proteinSubsystem = initProteinSubsystem({ scene, store, controls, camera, canvas })
  const proteinRenderer = proteinSubsystem.renderer
  const proteinGizmo = proteinSubsystem.gizmo
  const _refreshProteins = proteinSubsystem.refresh
  // Conjugate Manager — isolated modal showing azide-oligo attachment sites on a
  // protein. Opened from Tools ▸ Conjugate Manager… and the protein right-click.
  const conjugateManager = initConjugateManager({ api, store })

  // Rebuild the atomistic / surface mesh from the live design so a stopped MD/oxDNA
  // overlay drops back to the design's equilibrium pose in the SAME representation —
  // never reverting an atomistic/surface scene to the CG bead model.  Shared by the
  // live MD display, the MD viz (flex/traj), and the oxDNA display controllers.
  // (_atomSurface is assigned below at ~1995; this only fires on a user toggle-off,
  // post-boot, so the lazy reference is resolved by then.)
  const _restoreDesignHeavy = () => {
    if (atomisticRenderer.getMode?.() !== 'off') {
      _atomSurface.invalidateAtomCache()
      _atomSurface.applyAtomisticMode(atomisticRenderer.getMode())
    }
    if (_atomSurface.getSurfaceMode?.() !== 'off') {
      _atomSurface.invalidateSurfaceCache()
      _atomSurface.applySurfaceMode(_atomSurface.getSurfaceMode())
    }
  }

  // ── MD overlay + panel ───────────────────────────────────────────────────────
  const mdOverlay         = initMdOverlay(scene)
  const mdDisplayController = initMdPanel(store, {
    designRenderer, mdOverlay, atomisticRenderer,
    onRestoreDesignHeavy: _restoreDesignHeavy,
  })
  // getOxdnaDisplay is a lazy getter (oxdnaDisplay is declared below at ~1808): a
  // seeded MD run with no MD frame yet shows the inherited oxDNA-seed positions via it.
  // ── Compute-cluster (Alpine) connection chip (Phase 1 remote-execution backend) ─
  const clusterConn = initClusterConnection({ mount: document.getElementById('md-cluster-connection-mount') })

  // Chain Simulations: a live queue mode (built below, after the engine panels + selector
  // exist). The engine panels read `chainSim.isEnabled()` at click time and enqueue into
  // it instead of launching; declared here so the panel factories can bind lazily.
  let chainSim = null
  const _chainMode = () => chainSim?.isEnabled() ?? false

  const mdPanel = initMdJobsPanel({
    mdDisplayController,
    getWorkspacePath: () => _workspacePath,
    getOxdnaDisplay: () => oxdnaDisplay,
    // mdViz is declared below (~after oxdnaDisplay): the MD trajectory-scrub +
    // flexibility-map tools reuse the oxDNA display controller via an MD api adapter.
    getMdViz: () => mdViz,
    // Phase 4: gate the Alpine run-target on the live cluster-connection state.
    getClusterState: () => clusterConn?.getState?.() ?? 'disconnected',
    // N2: the shared anchor-scope picker resolves the 3D selection to fixedAtoms scopes.
    getSelection: () => store.getState(),
    // Chain Simulations: Relax/Production → "Queue …" when chain mode is on.
    getChainMode: _chainMode,
    enqueueChainStage: (protocol) => chainSim?.enqueue('namd', protocol),
  })

  // ── Benchmark controls (auto-tune oxDNA/NAMD hardware config per machine) ─────
  const benchmarkPanel = initBenchmarkPanel({ api, getWorkspacePath: () => _workspacePath })
  benchmarkPanel.mountOxdna(document.getElementById('oxdna-benchmark-mount'))
  benchmarkPanel.mountNamd(document.getElementById('md-benchmark-mount'))

  // ── oxDNA relaxation panel + display (deforms NADOC model to relaxed CG) ──────
  const oxdnaDisplay = initOxdnaDisplay({
    designRenderer, api, proteinRenderer,
    getAtomisticRenderer: () => atomisticRenderer,
    getSurfaceRenderer:   () => surfaceRenderer,   // const declared ~1918 (resolved lazily)
    getCurrentRepr:       () => _currentRepr,       // let declared ~2976 (resolved lazily)
    // Toggle-off / job-switch: rebuild the atomistic + surface meshes from the
    // live design so they drop the oxDNA overlay (mirrors the animation player's
    // stop handler).
    onRestoreDesignHeavy: _restoreDesignHeavy,
    // A heavy (atomistic/surface) frame rebuild started/finished — forward to the
    // panel so it can show a "building…" spinner instead of looking frozen.
    onHeavyStatus: (d) => window.dispatchEvent(
      new CustomEvent('nadoc:oxdna-heavy-status', { detail: d })),
    // Flexible ssDNA beads are excluded from the rigid mesh, so applyFemPositions
    // never moves them — redraw them at the frame's simulated positions instead of
    // leaving a stale geometric arc floating over the sim (null reverts to the arc).
    onFrame: (u) => flexibleArcs.applySimPositions(u),
  })
  // When the scene representation changes while an oxDNA overlay is active, re-apply
  // the current frame to the freshly-built atomistic/surface mesh.
  window.addEventListener('nadoc:representation-change', () => oxdnaDisplay.reapplyForRepr())
  // Ephemeral "Live" oxDNA mode (in-process oxpy, nothing stored): owns the Live
  // toggle, seeds from the panel's selected relaxed job, and pushes field re-aims.
  // Lazy getters resolve the panel + field/anchor cards (all declared below).
  let oxdnaPanel = null
  // Both the "Full Sim" run AND the Live session compose the same independently-
  // enabled elements (field / hard surface / anchors).
  const _oxdnaRunElements = () => ({
    field: efieldSetup?.getFieldSpec?.(),
    surface: oxdnaFloorSetup?.getSurfaceSpec?.(),
    anchors: oxdnaAnchorsSetup?.getAnchors?.() || [],
  })
  // Echo a run's conditions back into the oxDNA cards (used by both the panel's
  // click-a-job handler and the Chain Simulations click-a-queued-stage handler).
  const _oxdnaApplyConfig = (cfg = {}) => {
    efieldSetup?.applyConfig?.(cfg.field)
    oxdnaFloorSetup?.applyConfig?.(cfg.surface)
    oxdnaAnchorsSetup?.applyConfig?.(cfg.anchors)
  }
  const oxdnaLive = initOxdnaLive({
    oxdnaDisplay,
    getSelectedJob: () => oxdnaPanel?.getSelectedJob?.() || null,
    getRunElements: _oxdnaRunElements,
    // Stale-job guard (design changed after a relax) lives in the panel — the live
    // controller delegates the roll-or-cancel popup to it before starting.
    ensureJobCurrent: (label) => oxdnaPanel?.ensureJobCurrent?.(label),
  })

  // ── MD-job visualization (trajectory scrub + flexibility map) ─────────────────
  // A SECOND display controller, identical wiring to oxdnaDisplay but pointed at the
  // MD job endpoints via mdVizApiAdapter.  The CG (nadoc-bead) trajectory + RMSF
  // payloads are byte-identical to oxDNA's, so the whole scrub/colour machinery is
  // reused for NAMD jobs without touching the validated oxDNA controller.
  const mdViz = initOxdnaDisplay({
    designRenderer, api: mdVizApiAdapter(api), proteinRenderer,
    getAtomisticRenderer: () => atomisticRenderer,
    getSurfaceRenderer:   () => surfaceRenderer,
    getCurrentRepr:       () => _currentRepr,
    onRestoreDesignHeavy: _restoreDesignHeavy,
    onHeavyStatus: (d) => window.dispatchEvent(
      new CustomEvent('nadoc:md-heavy-status', { detail: d })),
    onFrame: (u) => flexibleArcs.applySimPositions(u),
  })
  window.addEventListener('nadoc:representation-change', () => {
    if (mdViz.isActive?.()) mdViz.reapplyForRepr()
  })
  // oxDNA jobs panel — uses the remote's Live wiring (oxdnaLive); the MD viz panel
  // (initMdJobsPanel) is wired to mdViz separately above via getMdViz.
  oxdnaPanel = initOxdnaJobsPanel({
    oxdnaDisplay, oxdnaLive, getWorkspacePath: () => _workspacePath,
    getRunElements: _oxdnaRunElements,
    getDesignLattice: () => store.getState().currentDesign?.lattice_type ?? null,
    // Lazy: the CanDo panel is created below, so the compare card's getSources reads its
    // selected job at generate time (C5 — the CanDo column of the cross-engine card).
    getCandoJob: () => candoPanel?.getSelectedJob?.(),
    // Lazy: the mrDNA panel is created below; the compare card reads its selection at
    // generate time (M5 — the mrDNA column of the cross-engine card).
    getMrdnaJob: () => mrdnaPanel?.getSelectedJob?.(),
    // N4 — the MD panel (created above) supplies the NAMD column, the GOLD-OVERRIDE
    // reference; the compare card reads its selection at generate time.
    getMdJob: () => mdPanel?.getSelectedJob?.(),
    // Clicking a job echoes its run conditions into every card (field arrow,
    // surface, anchor chips + 3D glow) — what was used during that run.
    applyRunConfig: _oxdnaApplyConfig,
    // Scrubbing a trajectory re-aims the field arrow at whichever run in the chain
    // is on screen (null = a relaxation stage → arrow hidden), so a chained run with
    // different field directions shows the direction used at each frame.
    onTrajectoryField: (field) => efieldSetup?.applyConfig?.(field),
    // Chain Simulations: Relax/Production → "Queue …" when chain mode is on.
    getChainMode: _chainMode,
    enqueueChainStage: (protocol) => chainSim?.enqueue('oxdna', protocol),
  })
  // mrDNA (coarse ARBD relaxation) — sibling of the oxDNA panel, single Run button.
  // CG-beads mode is a STANDALONE rep: bead cloud (md_overlay InstancedMesh) +
  // bond connections (line segments) with the native NADOC model hidden.
  const mrdnaBeadOverlay = initMdOverlay(scene)
  const mrdnaConnOverlay = initMrdnaConnections(scene)
  const mrdnaDisplay = initMrdnaDisplay({
    designRenderer, api,
    beadOverlay:       mrdnaBeadOverlay,
    connectionOverlay: mrdnaConnOverlay,
    setDesignVisible:  (v) => _setDesignGeometryVisible(v),  // hoisted fn decl (defined below)
  })
  const mrdnaPanel = initMrdnaJobsPanel({ mrdnaDisplay, getWorkspacePath: () => _workspacePath })
  // (LAMMPS panel + its External-forces cards are wired after the anchor-glow / View-grid
  // setup below, so they can reuse the SAME purple anchor halo + surface grid as oxDNA.)
  // CanDo FEM (native shape predictor) — sibling of the mrDNA panel, in-process
  // solver. The "Predicted shape (deform model)" toggle deforms the NADOC model to
  // the FEM-predicted positions via applyFemPositions (display-only, Three-Layer).
  // "CanDo style output" toggle draws the predicted shape as CanDo's jointed-cylinder
  // tubes (a standalone rep — native model hidden, like the mrDNA CG-beads mode).
  const candoCylinderOverlay = initCandoCylinders(scene)
  const candoDisplay = initCandoDisplay({
    designRenderer, api,
    cylinderOverlay:  candoCylinderOverlay,
    setDesignVisible: (v) => _setDesignGeometryVisible(v),
    legend:           initCandoLegend(),
  })
  const candoPanel = initCandoJobsPanel({ candoDisplay, getWorkspacePath: () => _workspacePath, getSelection: () => store.getState() })
  // (Editing OR seeking the design refetches the oxDNA/MD job lists so the out-of-date
  // ⚠ markers update immediately — driven by the client's `nadoc:design-changed` event
  // on every design sync; both panels self-listen, so no store subscription here.)
  // E-field setup: direction/magnitude arrow gizmo + anchor picker + Run field
  // (appends a field stage to the panel's selected completed oxDNA job).
  let _viewToolButtons = null   // assigned at initViewToolButtons (further down)
  const efieldGizmo = initEfieldGizmo(scene, camera, canvas, controls)

  // Purple halo over the anchored (fixed) elements while a field run is being set up.
  // Shown only when the field is enabled AND there are anchors — the thick arrow shows
  // the field direction, the purple glow shows what's pinned.  Both setups call
  // _refreshAnchorGlow on change (never during construction → no TDZ on the consts below).
  const anchorGlow = initAnchorGlow({ designRenderer, store })
  // Steric-clash overlay (the "clash" view-tool button) — owns its on/off + red
  // glow + count badge; re-fetches GET /design/clashes on posed-geometry change.
  const clashOverlay = initClashOverlay({ store, designRenderer })
  const _refreshAnchorGlow = () => {
    const fieldOn = efieldSetup?.isEnabled?.()
    const anchors = oxdnaAnchorsSetup?.getAnchors?.() || []
    anchorGlow.setAnchors(fieldOn && anchors.length ? anchors : [])
  }

  const efieldSetup = initForcesCard({
    engine: 'oxdna',
    gizmo: efieldGizmo,
    // Field changed (gizmo drag / input edit): refresh the anchor halo AND, if a
    // live session is running, update it — re-aim the field live (magnitude/dir) or
    // recompose the engine if the field was just toggled on/off.
    onChange: () => { _refreshAnchorGlow(); oxdnaLive?.onElementsChanged?.() },
    // Total base count → scales the arrow's force range so big origami get finer
    // per-nt control (the arrow encodes total push; per-nt ∝ 1/N).
    getBaseCount: () => store.getState().currentGeometry?.length || 0,
  })
  if (import.meta.env.DEV) window.__nadocEfield = { setup: efieldSetup, gizmo: efieldGizmo }

  const oxdnaFloorSetup = initOxdnaFloorSetup({
    // The hard-surface card drives the shared View grid (renders the wall + flips
    // the grid button on).  _viewToolButtons is created later in main(); this only
    // fires on user interaction, so the lazy reference is safe.
    setSurfaceGrid: (cfg) => _viewToolButtons?.setSurfaceGrid?.(cfg),
    // Toggling the hard floor while Live is running recomposes the live engine.
    onChange: () => oxdnaLive?.onElementsChanged?.(),
  })
  const oxdnaAnchorsSetup = initOxdnaAnchorsSetup({
    getSelection: () => store.getState(),
    // Changing anchors refreshes the halo AND recomposes a running live session.
    onChange: () => { _refreshAnchorGlow(); oxdnaLive?.onElementsChanged?.() },
  })
  // Leaving the Dynamics tab drops the field gizmo (forces_card) — clear the anchor
  // halo too so it never lingers in other tabs.
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.activeTab !== 'dynamics') anchorGlow.clear()
  })
  if (import.meta.env.DEV) window.__nadocOxdnaFloor = oxdnaFloorSetup

  // CPU-parallel oxDNA (LAMMPS CG-DNA): own field-direction arrow (separate gizmo
  // instance) + the Electric field / Anchors / Surface cards.  Reuses the SAME purple
  // anchor halo (anchorGlow) and View surface grid (_viewToolButtons) as the oxDNA
  // panel — the LAMMPS anchors glow whenever ≥1 is marked; the Surface toggle drives
  // the grid.  onChange never fires during construction (lammps_forces_setup gates it).
  const _refreshLammpsAnchorGlow = () => {
    const anchors = lammpsForcesSetup?.getAnchors?.() || []
    anchorGlow.setAnchors(anchors.length ? anchors : [])
  }
  const lammpsForcesSetup = initLammpsForcesSetup({
    gizmo: initEfieldGizmo(scene, camera, canvas, controls, 'lammps-efield-gizmo'),
    getSelection: () => store.getState(),
    getBaseCount: () => store.getState().currentGeometry?.length || 0,
    onChange: _refreshLammpsAnchorGlow,
    setSurfaceGrid: (cfg) => _viewToolButtons?.setSurfaceGrid?.(cfg),
  })
  initLammpsJobsPanel({
    designRenderer, getWorkspacePath: () => _workspacePath, forcesSetup: lammpsForcesSetup,
  })
  // Spinner on each engine's section header while that engine has a running/preparing
  // job (one shared /api/jobs/active poll drives all five headers).
  initEngineActivityHeaders()

  // Simulate section: one engine dropdown fronts the 5 stacked engine panels —
  // shows the selected engine's panel, hides the rest. (U4)
  const engineSelector = initEngineSelector({
    selectorMount: document.getElementById('engine-selector-mount'),
    panelEls: {
      oxdna:  document.getElementById('oxdna-jobs-panel'),
      lammps: document.getElementById('lammps-jobs-panel'),
      mrdna:  document.getElementById('mrdna-jobs-panel'),
      cando:  document.getElementById('cando-jobs-panel'),
      namd:   document.getElementById('md-jobs-panel'),
    },
  })

  // Chain Simulations panel (above Simulate): a named-project queue of oxDNA/NAMD
  // relax→production stages that Launch turns into unattended MdPipeline chains. Wires
  // the enable flag + enqueue into the engine panels declared above (bound lazily).
  chainSim = initChainSimPanel({
    store, api,
    engines: {
      oxdna: {
        getRunElements: _oxdnaRunElements,
        applyRunConfig: _oxdnaApplyConfig,
        getSelectedJob: () => oxdnaPanel?.getSelectedJob?.(),
        refreshJobs: () => oxdnaPanel?.refresh?.(),
        selectJob: (jobId) => oxdnaPanel?.selectJob?.(jobId),
        getAdvanced: () => ({
          run_target: 'local',
          steps: parseInt(document.getElementById('oxdna-jobs-prod-steps')?.value || '', 10) || null,
        }),
      },
      namd: {
        getRunElements: () => mdPanel?.getRunElements?.() || {},
        applyRunConfig: (cfg) => mdPanel?.applyRunConfig?.(cfg),
        getSelectedJob: () => mdPanel?.getSelectedJob?.(),
        refreshJobs: () => mdPanel?.refresh?.(),
        selectJob: (jobId) => mdPanel?.selectJob?.(jobId),
        getAdvanced: () => mdPanel?.getAdvanced?.() || {},
      },
    },
    selectEngine: (key) => engineSelector?.select?.(key),
    getBaseCount: () => store.getState().currentGeometry?.length || 0,
    // Stamped onto spawned jobs so they land in the per-design engine job list (same
    // value the launch cards pass as design_source_path).
    getDesignSourcePath: () => _workspacePath,
    // Preflight uses each stage's stored seed metadata; a live list is optional (flags a
    // seed job that has since been deleted). Left empty to avoid a synchronous job fetch.
    getCompletedJobs: () => [],
    getThroughput: () => {
      const hd = store.getState().currentDesign?.hardware_defaults || {}
      const first = Object.values(hd)[0]
      return { oxdnaStepsPerSec: first?.oxdna?.steps_per_s ?? null, namdNsPerDay: first?.namd?.ns_per_day ?? null }
    },
  })

  // The Simulate section collapses as one (its header owns the collapse; each engine
  // header is a static label). Reuse the shared jobs-panel base for persist + arrow.
  initJobsPanelBase({
    section: 'simulate-panel',
    els: {
      heading: document.getElementById('simulate-heading'),
      body:    document.getElementById('simulate-body'),
      arrow:   document.getElementById('simulate-arrow'),
    },
    arrowStyle: 'class',
  }).initCollapsed(false)   // default expanded

  // ── Surface renderer (VdW / SES) ─────────────────────────────────────────────
  const surfaceRenderer = initSurfaceRenderer(scene)
  // ── Atomistic + surface display controllers → scene/atom_surface_display.js (#86)
  // Owns the atomistic (Phase AA) + VdW/SES surface + per-region mixed-rep
  // overlays: their shared atom-data cache, strand->colour map, CG-visibility
  // toggle, the surface/atom slider listeners, and the 7 store subscribers (which
  // register HERE, at the original spot, so atom-cache-invalidate stays ordered
  // before region-overlay re-apply). atomisticRenderer + surfaceRenderer stay in
  // main (shared with the animation player / MD panel / repr switcher) and are
  // injected; the 3 region-overlay renderers are owned by the module. Alias-consts
  // below keep every external call site (repr_option_sliders #83, switcher #84,
  // reset spine, periodic-MD) byte-identical.
  _atomSurface = initAtomSurfaceDisplay({
    scene, store, api, designRenderer, atomisticRenderer, surfaceRenderer,
    unfoldView, overhangLinkArcs,
  })
  const _applySurfaceMode           = _atomSurface.applySurfaceMode
  const _applyAtomisticMode         = _atomSurface.applyAtomisticMode
  const _setCGVisible               = _atomSurface.setCGVisible
  const _setSurfacePanelVisible     = _atomSurface.setSurfacePanelVisible
  const _setAtomisticSlidersVisible = _atomSurface.setAtomisticSlidersVisible
  // ── Phase 3d-A: live strand-color updates on the shared assembly renderer.
  // designRenderer.setStrandColor (called from selection_manager + spreadsheet)
  // pushes the new hex into store.strandColors AND into the design's helixCtrl.
  // For assemblies the per-source `bpColorTex` was baked at rebuild time —
  // without a hook here, UI color changes silently fail to repaint instances.
  // We diff strandColors and forward each changed strand to the assembly
  // renderer's `updateStrandColor` (no-op on per-instance path; rewrites the
  // per-source `bpColorTex` rows on the shared path).
  store.subscribe((newState, prevState) => {
    if (newState.strandColors === prevState.strandColors) return
    const prev = prevState.strandColors ?? {}
    const next = newState.strandColors ?? {}
    const seen = new Set()
    for (const sid of Object.keys(next)) {
      seen.add(sid)
      if (prev[sid] !== next[sid]) assemblyRenderer.updateStrandColor?.(sid, next[sid])
    }
    // Strand removed from the override map → revert to design.strands[i].color.
    // Per-source customColors keeps the most-recent hex even after removal;
    // for the common UI path (user just picked a new color) this case rarely
    // fires. If it does, fall back to the design's stored color when present.
    for (const sid of Object.keys(prev)) {
      if (seen.has(sid)) continue
      // No explicit revert color available without a design lookup — leave the
      // current source customColors entry intact. A full assembly rebuild
      // (e.g. design reload) will reset it anyway.
    }
  })

  // ── Overhang sequences panel ─────────────────────────────────────────────────
  initOverhangSequencesPanel({ store, selectionManager, api, overhangNameOverlay })

  // ── Strand groups panel ──────────────────────────────────────────────────────
  initStrandGroupsPanel({ store, selectionManager })

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

  // ── Browser dev-tools debug helpers (window._nadocDebug) — see scene/debug/devtools_helpers.js ──
  window._nadocDebug = initDevtoolsDebug({ designRenderer, store, api, overhangLinkArcs, selectionManager, scene })

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

    // Atomistic representation has no 2D-unfold layout — block entering and explain.
    if (!unfoldView.isActive() && store.getState().atomisticMode !== 'off') {
      showToast('Unfold view is not available in atomistic representation — exit atomistic first')
      return
    }

    // U key while cadnano is active: exit cadnano but stay in unfold view,
    // rather than toggling unfold off (which would break cadnano's internal state).
    if (cadnanoView.isActive()) {
      await cadnanoView.deactivate({ keepUnfold: true })
      if (!slicePlane.isVisible()) {
        crossSectionMinimap.clearSlice()
        crossSectionMinimap.hide()
        sliceHighlighter.clear()
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

    // Atomistic representation has no 2D-cadnano layout — block entering and explain.
    if (!cadnanoView.isActive() && store.getState().atomisticMode !== 'off') {
      showToast('Cadnano view is not available in atomistic representation — exit atomistic first')
      return
    }

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
      sliceHighlighter.clear()
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
  // Forward-declared: onExtrude/onCancel below reference the Extrude panel, which
  // is constructed just after slicePlane (deferred handlers, so it's assigned by
  // the time they fire). Mirrors the `let clusterPanel = null` pattern.
  let _extrudePanel = null
  let _clusterClipboard = null
  const slicePlane = initSlicePlane(scene, camera, canvas, controls, {
    onExtrude: async ({ cells, lengthBp, plane, offsetNm, continuationMode, newBundle, latticeType = 'HONEYCOMB', deformedFrame, refHelixId, sourceBp = null, strandFilter = 'both', ligateAdjacent = true }) => {
      // A "new bundle" only RESETS the workspace when it's empty. With a part
      // already present, an empty-space extrude adds the new bundle additively (a
      // fresh, disconnected set of helices in the SAME design) via the bundle-
      // segment route, so repeated extrudes never wipe existing structure.
      const freshBundle = newBundle && (store.getState().currentDesign?.helices?.length ?? 0) === 0

      let result
      if (freshBundle) {
        // Preserve the user's design name across bundle creation — _fileName is set
        // by the "New Design" modal or by opening a file; fall back to the current
        // design's metadata name, then to nothing (server default).
        const bundleName = _fileName ?? store.getState().currentDesign?.metadata?.name
        result = await api.createBundle({ cells, lengthBp, plane, strandFilter, latticeType, ligateAdjacent, ...(bundleName ? { name: bundleName } : {}) })
      } else if (deformedFrame) {
        result = await api.addBundleDeformedContinuation({ cells, lengthBp, plane, frame: deformedFrame, refHelixId, sourceBp })
      } else if (continuationMode) {
        result = await api.addBundleContinuation({ cells, lengthBp, plane, offsetNm, strandFilter, ligateAdjacent })
      } else {
        // Slice-plane segment AND empty-space "new bundle" on a populated design.
        result = await api.addBundleSegment({ cells, lengthBp, plane, offsetNm, strandFilter, ligateAdjacent })
      }
      if (!result) {
        const err = store.getState().lastError
        throw new Error(err?.message ?? (freshBundle ? 'Bundle creation failed' : 'Segment extrusion failed'))
      }
      if (freshBundle) {
        // Record plane and helix creation order for the unfold view.
        const newHelices = store.getState().currentDesign?.helices?.slice(-cells.length) ?? []
        store.setState({ currentPlane: plane, unfoldHelixOrder: newHelices.map(h => h.id) })
        _extrudePanel?.hide()
      } else {
        // Append new helix IDs to the unfold order (preserving existing order).
        const existing = store.getState().unfoldHelixOrder ?? []
        const newIds   = cells.map(([row, col]) => `h_${plane}_${row}_${col}`)
        const toAdd    = newIds.filter(id => !existing.includes(id))
        if (toAdd.length) store.setState({ unfoldHelixOrder: [...existing, ...toAdd] })
        _extrudePanel?.hide()
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
      sliceHighlighter.update(offsetNm, effectivePlane)
    },
    onPreviewToggle: (enabled) => {
      // "Show preview" checkbox in the slice extrude popup → persist + sync overhang ghost.
      _extrudePreviewEnabled = enabled
      localStorage.setItem('NADOC_EXTRUDE_PREVIEW', String(enabled))
      _refreshOverhangGhost()
    },
    // The sidebar Extrude panel's Cancel button tears down the whole tool.
    onCancel: () => _extrudePanel?.hide(),
    // Primitive placement commit: drop the footprint as an additive segment, then
    // exit (one placement per selection). cells are already lattice-translated. A
    // circle carries per-cell lengths (centred disc) → circle-segment route; a
    // uniform primitive carries one lengthBp → bundle-segment route.
    onPlace: async ({ cells, lengthBp, cellLengths, plane, offsetNm, strandFilter, ligateAdjacent, continuationMode, deformedFrame, refHelixId, sourceBp = null }) => {
      // continuationMode → placed on an existing part's face: cells over existing
      // helix-ends extend them, fresh cells make new helices. A bent face carries a
      // deformedFrame. Otherwise it's an origin-plane placement (circle → circle-
      // segment; beam → bundle-segment).
      const result = continuationMode
        ? deformedFrame
          ? await api.addBundleDeformedContinuation({ cells, lengthBp, plane, frame: deformedFrame, refHelixId, sourceBp })
          : await api.addBundleContinuation({ cells, lengthBp, plane, offsetNm, strandFilter, ligateAdjacent })
        : cellLengths
          ? await api.addCircleSegment({ cells, cellLengths, plane, offsetNm, strandFilter, ligateAdjacent })
          : await api.addBundleSegment({ cells, lengthBp, plane, offsetNm, strandFilter, ligateAdjacent })
      if (!result) {
        const err = store.getState().lastError
        showToast(err?.message ?? 'Primitive placement failed', { severity: 'error' })
        return
      }
      const existing = store.getState().unfoldHelixOrder ?? []
      const newIds   = cells.map(([row, col]) => `h_${plane}_${row}_${col}`)
      const toAdd    = newIds.filter(id => !existing.includes(id))
      if (toAdd.length) store.setState({ unfoldHelixOrder: [...existing, ...toAdd] })
      _primitiveLibrary?.exitPlacement()
      slicePlane.hide()
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    },
    // Lazy (bluntEnds is created later): lets placement YIELD a ring click to the
    // domain-end pick so it retargets the footprint onto that face.
    getBluntEnds: () => bluntEnds,
    // Lazy (clusterClipboard is created just below): a cluster-paste ghost commits here.
    onPlacePaste: (args) => _clusterClipboard?.onCommit(args),
  })

  // ── Cluster copy/paste (Ctrl+C / Ctrl+V) → scene/cluster_clipboard.js ────────
  _clusterClipboard = initClusterClipboard({ store, api, scene, slicePlane, showToast })

  // ── Extrude tool (right-sidebar panel + plane dropdown) → ui/extrude_panel.js ──
  // Owns #extrude-panel visibility, the "Extrude from" origin-plane dropdown, and
  // the tool lifecycle. Replaces the retired workspace.js plane-picker as the entry
  // to every extrude (new-bundle / segment / blunt-end / deformed continuation).
  _extrudePanel = initExtrudePanel({ store, slicePlane, expandedSpacing })

  // ── Primitives library (right-sidebar panel) → ui/primitive_library.js ──
  // Owns #primitives-panel; revealed by Tools → Add Primitive. Lists pre-validated
  // building blocks (6HB/18HB beams). Selecting one arms placement: the inline plane
  // dropdown + length input drive the slice-plane footprint ghost; a click commits
  // it as an additive bundle-segment (onPlace above). The `placement` dep is thin
  // wiring — the cohesive logic lives in primitive_library.js + slice_plane.js.
  const _primitiveLibrary = initPrimitiveLibrary({
    store, api,
    placement: {
      enter: (spec) => {
        slicePlane.showPlacement(spec.plane, spec)
        document.getElementById('mode-indicator').textContent =
          'PLACE PRIMITIVE — hover a lattice cell · click to place · Esc to cancel'
      },
      // Existing structure: arm without showing the origin grid; wait for the user to
      // pick an origin plane (dropdown) or click a blunt end.
      arm: (spec) => {
        slicePlane.armPlacement(spec)
        document.getElementById('mode-indicator').textContent =
          'ADD PRIMITIVE — choose an origin plane or click a blunt end · Esc to cancel'
      },
      setLength: (bp) => slicePlane.setPlacementLength(bp),
      setCircle: (fp) => slicePlane.setPlacementCircle(fp),
      cancel: () => {
        slicePlane.disarmPlacement()
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      },
    },
  })

  // Link slicePlane to unfoldView so the plane dimensions lerp during unfold animation.
  unfoldView.setSlicePlane(slicePlane)

  // Seed the slice-plane preview from the persisted toggle state (default ON).
  slicePlane.setPreviewEnabled(_extrudePreviewEnabled)

  // Auto-hide the slice plane when deformations are activated so the cross-section
  // always reflects the undeformed helix geometry.
  store.subscribe((newState, prevState) => {
    if (newState.deformVisuActive === prevState.deformVisuActive) return
    if (newState.deformVisuActive && newState.currentDesign?.deformations?.length) {
      if (slicePlane.isVisible()) {
        slicePlane.hide()
        crossSectionMinimap.clearSlice()
        crossSectionMinimap.hide()
        sliceHighlighter.clear()
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
      sliceHighlighter.clear()
      _setMenuToggle('menu-view-slice', false)
    }
    // Design emptied out (e.g. last helix deleted): close any open Extrude tool and
    // show the world-origin triad — same as a brand-new part. No forced plane-picker.
    _extrudePanel?.hide()
    _syncOriginAxesForEmpty()
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
    if (_extrudePanel?.isActive()) _extrudePanel.hide()
    if (sliceWasVisible) {
      crossSectionMinimap.clearSlice()
      crossSectionMinimap.hide()
      sliceHighlighter.clear()
      _setMenuToggle('menu-view-slice', false)
    }
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  })

  // World-origin axis triad: force it on whenever the design (re)enters an empty
  // state via any path (file load, undo, delete-last-helix, assembly exit).
  store.subscribe(() => _syncOriginAxesForEmpty())
  // Sync the View-menu pill with the boot default (axes on for the empty scene).
  _setMenuToggle('menu-view-axes', originAxes.visible)

  // ── Slice-plane backbone highlight ──────────────────────────────────────────
  // Colours all backbone beads at the slice plane's current bp position white,
  // restoring default colours when the plane moves or is hidden.

  // Slice-plane bead highlighter (factory in scene/slice_highlighter.js). All
  // callers are deferred handlers, so this const is constructed before any fire.
  const sliceHighlighter = initSliceHighlighter({
    designRenderer,
    getDesign: () => store.getState().currentDesign,
  })

  function _toggleSlicePlane() {
    if (slicePlane.isVisible()) {
      slicePlane.hide()
      crossSectionMinimap.clearSlice()
      crossSectionMinimap.hide()
      sliceHighlighter.clear()
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
    const offset = bundleMidOffset(currentDesign, currentPlane)
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
    slicePlane.show(currentPlane, offset, false, true)   // read-only: no lattice, no extrude
    crossSectionMinimap.show()
    _setMenuToggle('menu-view-slice', true)
    document.getElementById('mode-indicator').textContent =
      'SLICE PLANE — drag handle to reposition · Esc to close'
  }

  // ── Blunt end menus (sidebar panel + right-click ctx) → ui/blunt_end_menus.js (#88)
  const _bluntMenus = initBluntEndMenus({
    store, api, slicePlane, expandedSpacing, deformView,
    clusterDeformGuard: _clusterDeformGuard,
    extrudePanel: _extrudePanel,
  })

  // Scaffold right-click now uses the unified scaffold context menu built in
  // selection_manager.js (`_showScaffoldMenu`); the old raw-HTML menu was removed.

  // ── Overhang orientation context menu ────────────────────────────────────────
  // Builder lives in ui/overhang_orientation_menu.js (ISSUE-1 Phase 2a-orientation).
  // _orientPanel is created later in main(), so it's passed via a lazy getter.
  const _orientMenu = initOverhangOrientationMenu({
    api, store, assemblyRenderer, openOverhangsManager,
    getOrientPanel: () => _orientPanel,
    overhangsToSegments, editOverridesForSegments, createRepresentationMenuItem,
    // Reach the SAME extensions dialog the strand menu uses, for the overhang's
    // backing strand — so right-clicking any overhang (applied/relaxed/etc.) can add
    // a fluorophore/modification (StrandExtension). See selection_manager.
    onOpenExtensions: (strandIds, x, y) => selectionManager.openExtensionsForStrands(strandIds, x, y),
    // [[overhang-duplex-cluster]] P4: a duplex-backed overhang orients via its cluster gizmo.
    getDuplexClusterForOverhang: (ovhgId) => duplexClusterForOverhang(store.getState().currentDesign, ovhgId),
    onEditDuplexOrientation: (clusterId) => {
      store.setState({ activeClusterId: clusterId })
      _activateTranslateRotateTool(clusterId)   // defined later in main(); menu clicks fire post-init
    },
    onResetDuplexOrientation: async (clusterId) => {
      // Reset the duplex pose to identity (keep the pivot); commit skips the geometry
      // refetch, so refresh geometry so the reset paints immediately.
      await api.patchCluster(clusterId, { translation: [0, 0, 0], rotation: [0, 0, 0, 1], commit: true, log: true })
      await api.getGeometry()
    },
  })

  // ── Blunt end indicators ─────────────────────────────────────────────────────
  const bluntEnds = initDomainEnds(scene, camera, canvas, {
    onDomainEndClick: (info) => {
      // With a primitive armed, a blunt-end click RETARGETS the placement onto that
      // face (continuation extrude with the primitive's footprint) — even before any
      // origin grid is shown; otherwise it opens the normal blunt-end action panel.
      if (slicePlane.isArmed()) _bluntMenus.placeOnEnd(info)
      else _bluntMenus.showPanel(info)
    },
    onDomainEndRightClick: ({ clientX, clientY, ...info }) => {
      _bluntMenus.showCtx(clientX, clientY, info)
    },
    // Block blunt-end picking whenever a gizmo or modal tool is in front of
    // the user. Deform / cluster-gizmo / unfold all paint geometry that the
    // user is meant to click on; if a blunt-end ring is layered over that
    // geometry, its capture-phase pointerdown listener swallows the click
    // and the gizmo never gets it.
    isDisabled: () => {
      // Allow blunt-end clicks during primitive *placement* (so a face-click can
      // retarget the armed footprint), but keep them blocked for normal slice-plane
      // selection / read-only visibility.
      if (slicePlane.isVisible() && !slicePlane.isPlacement()) return true
      if (_isUnfoldActive()) return true
      if (isDeformActive()) return true
      const s = store.getState()
      if (s.deformToolActive) return true
      if (s.translateRotateActive) return true
      return false
    },
    getUnfoldView: () => unfoldView,
  })

  // The blank 3D scene starts empty (just the world-origin axis triad). Extrude is
  // started explicitly via Tools → Extrude (or right-click empty space), which opens
  // the #extrude-panel; there is no longer an auto plane-picker.
  camera.position.set(6, 3, 18)
  controls.target.set(6, 3, 0)
  controls.update()

  // After (re)opening a saved part with no helices (created but never extruded),
  // just show the world-origin triad — the user starts extruding via Tools →
  // Extrude. (Kept as a named dep for file_io; the axes subscriber also covers the
  // load path, so this is a belt-and-suspenders sync.)
  function _revealWorkspaceForEmptyPart() {
    _syncOriginAxesForEmpty()
  }

  // ── Empty-space context menu (start a new bundle / extrude) ─────────────────
  // Right-clicking empty 3D space (no strand/bead/arc/overhang under the cursor)
  // pops a minimal menu whose only item, "Extrude", which opens the Extrude panel
  // in new-bundle mode — the same flow as Tools → Extrude.
  async function _startEmptySpaceExtrude() {
    const { assemblyActive } = store.getState()
    if (assemblyActive) return
    // On an empty workspace this starts a fresh bundle; on a populated part the
    // extrude is additive (onExtrude routes new-bundle → bundle-segment), so the
    // existing structure is preserved and no destructive confirm is needed.
    _extrudePanel?.activate('newBundle')
  }

  const emptySpaceMenu = initEmptySpaceMenu({
    menuEl:     document.getElementById('empty-space-ctx-menu'),
    extrudeBtn: document.getElementById('empty-extrude-btn'),
    onExtrude:  _startEmptySpaceExtrude,
  })

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
      // Photo tab is exempt: it works on any scene (even empty) and manages
      // its own panel visibility, so it must stay clickable.
      leftPanel.classList.add('hidden', 'locked-hidden')
      for (const b of tabBtns) {
        if (b.dataset.tab !== 'photo') b.disabled = true
      }
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
    // Hide the whole view cube — cube wrapper AND the sibling #vc-roll roll buttons
    // (the direct #vc-wrap poke used to leave the 90° roll buttons floating on the
    // welcome screen). viewCube.hide() clears both.
    viewCube.hide()
  }

  function _hideWelcome() {
    _welcomeScreen?.classList.add('hidden')
    _setMenusEnabled(true)
    _setLeftPanelEnabled(true)
    // A freshly loaded part defaults to the Feature Log tab (regardless of
    // which tab was last persisted). selectTab preserves the user's
    // collapsed/expanded preference — it just picks the tab.
    window.__leftSidebar?.selectTab?.('feature-log')
    _setRightPanelEnabled(true)
    _setFilterStripEnabled(true)
    const spreadsheetPanel = document.getElementById('spreadsheet-panel')
    if (spreadsheetPanel) spreadsheetPanel.style.display = ''
    viewCube.show()
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
          showToast('Failed to reload recent file: ' + (store.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' })
          _setFileName(null)
          _showWelcome()
          return
        }
        _hideWelcome()
        _fileHandle = null
        _revealWorkspaceForEmptyPart()
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
      // Auto-save to workspace before clearing (skip while an export-rep upgrade
      // is in flight so the temporary high-detail reps aren't persisted).
      const hasInstances = (store.getState().currentAssembly?.instances?.length ?? 0) > 0
      if (hasInstances && !_photoMode.getExportRepActive()) {
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
  // Open-orchestration factory (ui/file_io.js initFileOpen, extraction #59).
  // Forward-declared here because the file-open menu handler (~3866) references
  // it textually ABOVE its real init (~7540, after the assembly-load stash vars).
  // All call sites invoke on user action / boot-action (post-init), so the bare
  // `let` resolves — no lazy `?.` wrapper needed (mirrors the deferred handlers).
  let _fileOpen           = null
  // Save/Save-As dispatch factory (ui/file_io.js initFileSave, extraction #60).
  // Forward-declared here because the menu-file-save listeners (~3924) and the
  // keyboard-shortcuts injection (~5134) reference it textually ABOVE its real
  // init (after `initPhotoMode`, whose getExportRepActive it reads). All call sites
  // invoke on user action (menu click / Ctrl+S) post-init, so wrapped as lazy arrows.
  let _fileSave           = null
  // Doc-scoped so each tab's filename/path metadata is independent (and the
  // cadnano editor opened with the same ?doc= reads the matching values).
  const _FNAME_KEY = docKey('nadoc:design-filename')
  function _setFileName(name) {
    _fileName = name
    // Best-effort: never let a full-quota localStorage surface as an exception on
    // open (the recovery cache evicts under pressure in api/client.js).
    try {
      if (name) localStorage.setItem(_FNAME_KEY, name)
      else      localStorage.removeItem(_FNAME_KEY)
    } catch { /* quota / private mode — ignore */ }
  }

  // Workspace paths — set when a file is opened from or saved to the workspace.
  // Auto-save subscribers use these to know which file to overwrite.
  const _WS_PATH_KEY  = docKey('nadoc:workspace-path')
  const _ASM_PATH_KEY = docKey('nadoc:assembly-workspace-path')
  let _workspacePath         = localStorage.getItem(_WS_PATH_KEY)  || null
  let _assemblyWorkspacePath = localStorage.getItem(_ASM_PATH_KEY) || null
  function _setWorkspacePath(path) {
    const previousPath = _workspacePath
    _workspacePath = path
    try {
      if (path) localStorage.setItem(_WS_PATH_KEY, path)
      else      localStorage.removeItem(_WS_PATH_KEY)
    } catch { /* quota / private mode — ignore */ }
    // Our file changed → tell siblings (so they can detect co-editing) and
    // recompute our own badge. Both are hoisted fn decls, only called post-init.
    _announceDocPresence?.()
    _refreshCoediting?.()
    if (path !== previousPath) {
      window.dispatchEvent(new CustomEvent('nadoc:workspace-path-change', {
        detail: { path, previousPath },
      }))
    }
  }
  function _setAssemblyWorkspacePath(path) {
    _assemblyWorkspacePath = path
    try {
      if (path) localStorage.setItem(_ASM_PATH_KEY, path)
      else      localStorage.removeItem(_ASM_PATH_KEY)
    } catch { /* quota / private mode — ignore */ }
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

  // ── Boot action — a tab opened by New/Open carries ?new=… or ?open=… and runs
  // that action against its own ?doc=<id> once init completes (dispatched at the
  // end of main()).  Suppress the welcome screen so it doesn't flash first.
  const _bootDocAction = (() => {
    const p = new URLSearchParams(window.location.search)
    const newKind = p.get('new')      // 'part' | 'assembly'
    const openPath = p.get('open')    // workspace-relative path
    if (newKind || openPath) {
      _needsWelcomeOnBoot = false
      // The welcome screen is visible by default in the DOM until a file loads.
      // Hide it NOW (direct DOM — `_welcomeScreen`/`_hideWelcome` aren't ready yet)
      // so this New/Open-spawned tab never flashes it before the action runs.
      document.getElementById('welcome-screen')?.classList.add('hidden')
      return { newKind, openPath, openType: p.get('open-type'), openName: p.get('open-name') }
    }
    return null
  })()

  // ── File-load overlay (factory) — used by part-edit init below ───────────────
  const _fileLoad      = initFileLoadDialog()
  const _showFileLoad  = _fileLoad.show
  const _hideFileLoad  = _fileLoad.hide
  const _flSetProgress = _fileLoad.setProgress
  const _flAppendLog   = _fileLoad.appendLog
  const _flShowSuccess = _fileLoad.showSuccess
  const _flShowError   = _fileLoad.showError

  const _flMenuBtn    = document.getElementById('flp-main-menu-btn')
  _flMenuBtn?.addEventListener('click', () => {
    _hideFileLoad()
    _showWelcome()
  })

  // ── Part-edit init — ?part-instance=<id> opens this tab as a part editor ────
  {
    const _partInstanceParam = new URLSearchParams(window.location.search).get('part-instance')
    // The assembly lives in ITS OWN doc (the assembly tab's). This part-editor
    // tab runs on its own isolated doc (so multiple open parts never clobber one
    // another's design slot) but must reach into the assembly's doc to fetch its
    // source design and to save edits back. That doc id rides in `?assembly-doc=`,
    // NOT `?doc=` — see onEditPart / assembly_panel.
    const _assemblyDocParam = new URLSearchParams(window.location.search).get('assembly-doc')
    if (_partInstanceParam) {
      _showFileLoad('Opening Part')
      let partDesign = null

      // Normal path: assembly is live on server (in the assembly's doc)
      try {
        _flSetProgress(0, 'Fetching part from assembly…')
        _flAppendLog(`Instance: ${_partInstanceParam}`)
        const resp = await fetch(`/api/assembly/instances/${_partInstanceParam}/design`, { headers: docHeadersFor(_assemblyDocParam) })
        if (resp.ok) {
          const body = await resp.json()
          partDesign = body.design
          if (partDesign && body.instance_name) {
            partDesign = {
              ...partDesign,
              metadata: { ...(partDesign.metadata ?? {}), name: body.instance_name },
            }
          }
          _flAppendLog('Part design received from server')
        } else {
          _flAppendLog(`Server returned ${resp.status} — trying local cache…`, 'warn')
        }
      } catch (e) {
        _flAppendLog(`Network error: ${e?.message ?? String(e)} — trying local cache…`, 'warn')
      }

      // Server-restart fallback: restore the assembly INTO ITS OWN doc from the
      // assembly tab's recovery cache (keyed by the assembly doc), then retry.
      if (!partDesign) {
        const cached = api.getPersistedAssembly(_assemblyDocParam)
        if (cached) {
          try {
            _flAppendLog('Restoring assembly from local cache…')
            const restoreResult = await api.importAssembly(JSON.stringify(cached), { docId: _assemblyDocParam })
            if (restoreResult) {
              const resp2 = await fetch(`/api/assembly/instances/${_partInstanceParam}/design`, { headers: docHeadersFor(_assemblyDocParam) })
              if (resp2.ok) {
                const body2 = await resp2.json()
                partDesign = body2.design
                if (partDesign && body2.instance_name) {
                  partDesign = {
                    ...partDesign,
                    metadata: { ...(partDesign.metadata ?? {}), name: body2.instance_name },
                  }
                }
                _flAppendLog('Part design received after cache restore')
              }
            }
          } catch { _flAppendLog('Cache restore failed.', 'error') }
        }
      }

      if (partDesign) {
        _flSetProgress(50, 'Importing design…')
        _flAppendLog('Parsing and validating design…')
        // Import into THIS tab's own (isolated) doc — the editable working copy.
        await api.importDesign(JSON.stringify(partDesign))
        const partName = partDesign?.metadata?.name ?? 'Part'
        _partEditContext = { instanceId: _partInstanceParam, name: partName, assemblyDoc: _assemblyDocParam }
        api.setPersistedMode('part-edit:' + _partInstanceParam)
        _setFileName(partName)
        _needsWelcomeOnBoot = false
        _hideWelcome()
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
    // A part-editor tab has no assembly in its own doc (the assembly lives in the
    // assembly tab's doc); skip so we don't write an empty/foreign assembly cache.
    if (!_partEditContext) api.persistAssembly()   // no-op if no assembly is loaded
    // Tell siblings we're gone so their co-editing badge count drops (ISSUE-2 sub-phase B).
    try { nadocBroadcast.emit('doc-goodbye') } catch { /* best-effort */ }
  })

  // ── File open / save ─────────────────────────────────────────────────────────
  // Tracks the File System Access API file handle so Ctrl+S can overwrite
  // the same file without re-opening a dialog.  Null when no file is open or
  // when the browser doesn't support the File System Access API.
  // (_fileHandle, _fileName, _assemblyFileHandle, _assemblyName, _partEditContext,
  //  _FNAME_KEY, and _setFileName are declared above the session-restore block.)
  let _lastDetailLevel  = 0      // LOD level last applied to designRenderer (0=full, 1=beads, 2=cylinders)
  let _lodMode          = 'full' // 'full' | 'beads' | 'cylinders'
  // The active design-view representation (full|beads|cylinders|vdw|ballstick|surface|
  // hull-prism). Tracked so e.g. the deform tool can drop the hull-prism solid for
  // an edit (its coarse envelope can't show the live preview and would persist
  // under the full-rep preview). Set by _setRepresentation.
  let _currentRepr      = 'full'

  /** Clear per-file state (slice plane, store) and return to workspace. */
  function _resetForNewDesign() {
    // Leave photo mode before tearing the scene down. Otherwise the photo
    // render override stays installed and the next loaded design comes up
    // "in photo mode" (no-op if not active). Runs first so deactivate() can
    // restore the live materials/lights while the meshes still exist.
    _photoMode.exit()
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
    proteinGizmo?.detach()
    // Deformed view stays ON after reset (it is always on by default).
    // If currently in straight view, reactivate before clearing state.
    if (!deformView.isActive()) deformView.activate()
    slicePlane.hide()
    _extrudePanel?.hide()
    crossSectionMinimap.clearSlice()
    crossSectionMinimap.hide()
    sliceHighlighter.clear()
    bluntEnds.clear()
    _bluntMenus.hidePanel()
    _setMenuToggle('menu-view-slice', false)
    // New/empty part: show the world-origin XYZ triad as the orientation reference.
    originAxes.visible = true
    _setMenuToggle('menu-view-axes', true)
    viewLegends.reset()
    // Tear down any active CanDo FEM display — restores the native model, clears the
    // cylinder overlay, and hides the CanDo RMSF/deviation legend (#cando-legend),
    // which otherwise lingered on the welcome screen after closing a session.
    candoDisplay.stopAndRestore()
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

  // The file-IO operations (getDesignContent / savePartToAssembly / saveToHandle /
  // saveAs / saveAssemblyToHandle / saveAssemblyAs) were extracted verbatim to
  // ui/file_io.js (extraction #52). The factory `_fileIo = initFileIo({...})` is
  // wired below at the autosave region (its deps _syncBadge.setSyncStatus /
  // _syncBadge.syncLog / libraryPanel are declared there). The mutable file/path state + setters +
  // _updateAssemblyTitle + the lifecycle spine (_resetForNewDesign /
  // _enterAssemblyMode / _exitAssemblyMode) stay here.

  // ── Assembly file save helpers ────────────────────────────────────────────────

  function _updateAssemblyTitle() {
    const name = _assemblyName ?? store.getState().currentAssembly?.metadata?.name ?? 'Untitled'
    document.title = `NADOC 3D — ${name}`
  }

  // IDs of right-panel sections that are design-only (hidden in assembly mode)
  const _DESIGN_PANEL_IDS = [
    'sel-row-bluntEnds',
    'selection-filter-section', 'properties-section',
    'blunt-panel', 'deform-panel', 'strand-hist-section',
    'groups-panel', 'overhang-panel',
    'oxdna-jobs-panel', 'lammps-jobs-panel', 'mrdna-jobs-panel', 'cando-jobs-panel', 'md-panel',
    'repr-options-section', 'reset-btn',
  ]
  let _savedDesignPanelDisplay = {}

  // Filter-view-strip controls that are design-only. Hidden in assembly mode so
  // the strip keeps only overhang-relevant tools (overhang-locations tool,
  // sequence/grid/overhang-name view toggles, expanded spacing). The whole
  // Selectable section is hidden — assembly overhang selection is done by
  // hovering/clicking overhangs in 3D, not via a selection filter.
  const _DESIGN_STRIP_SELECTORS = [
    '#select-filter',                            // entire Selectable section
    '#view-tools > .sf-divider:first-child',     // now-leading divider before Tools:
    '#view-tools [data-key="blunt"]',
    '#view-tools [data-key="fxover"]',
    '#view-tools [data-vt="lengthHeatmap"]',
    '#view-tools [data-vt="undefinedBases"]',
    '#view-tools [data-vt="deform"]',
    '#view-tools [data-vt="unfold"]',
    '#view-tools [data-vt="cadnano2d"]',
  ]
  let _hiddenStripEls = []

  function _enterAssemblyMode() {
    if (window.nadocDebug?.verbose)
      console.log('[restore] _enterAssemblyMode() — assemblyActive →', true)
    // A photo-mode session belongs to the design/assembly it was opened in;
    // entering an assembly (open/new) must drop it (no-op if not active).
    _photoMode.exit()
    _setDesignGeometryVisible(false)
    // Close any open Extrude tool and hide the world-origin triad — both are
    // design-only affordances that shouldn't leak into the assembly view.
    _extrudePanel?.hide()
    originAxes.visible = false
    _setMenuToggle('menu-view-axes', false)
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

    // Trim the filter-view strip down to the overhang-relevant controls.
    _hiddenStripEls = []
    for (const sel of _DESIGN_STRIP_SELECTORS) {
      for (const el of document.querySelectorAll(sel)) {
        _hiddenStripEls.push([el, el.style.display])
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

    // Restore the design-only filter-view-strip controls.
    for (const [el, display] of _hiddenStripEls) el.style.display = display
    _hiddenStripEls = []

    // Clear the assembly-scoped overhang selection + hover.
    store.setState({ assemblyOverhangSelection: [] })

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

  // Build a bbox over the currently selected nucleotides (multi-select strands +
  // domains + single selectedObject). Returns null if nothing is selected.
  function _selectionBBox() {
    const st = store.getState()
    return selectionBBox(st.currentGeometry, {
      strandIds:   new Set(st.multiSelectedStrandIds ?? []),
      domainIds:   new Set(st.multiSelectedDomainIds ?? []),
      selStrandId: st.selectedObject?.data?.strand_id ?? null,
    })
  }

  // F-key handler: frame the selection if there is one, otherwise fit the whole
  // design. Matches the standard CAD convention (Blender F, Fusion F, etc.).
  function _frameSelectionOrAll() {
    const box = _selectionBBox()
    if (!box) { _fitToView(); return }
    const center = box.getCenter(new THREE.Vector3())
    const size   = box.getSize(new THREE.Vector3())
    const radius = Math.max(size.x, size.y, size.z, 1) * 0.5
    const dist = (radius / Math.sin((camera.fov * 0.5) * Math.PI / 180)) * 1.4
    const dir  = camera.position.clone().sub(controls.target).normalize()
    controls.target.copy(center)
    camera.position.copy(center).addScaledVector(dir, dist)
    controls.update()
  }

  // ── Menu bar ─────────────────────────────────────────────────────────────────

  // ── Multi-document: New / Open spawn a new tab unless this space is empty ────
  // app/doc_spawn.js (extraction #58). Pure spaceHasContent + spawnDocTabIfBusy
  // (mints a ?doc=<id> tab when this space already holds content). Used by
  // file-new (via the injected dep below) / file-new-assembly / file-open.
  const _docSpawn = initDocSpawn({ store, mintDocId })

  // New Part modal (File → New Part + boot-doc-action) → ui/new_design_modal.js.
  // The lifecycle spine + multi-doc spawn guard stay inline and are injected;
  // libraryPanel is wired later → lazy getter. Owns the menu-file-new listener.
  const _newDesignModal = initNewDesignModal({
    store, api,
    resetForNewDesign: _resetForNewDesign,
    setFileName: _setFileName,
    hideWelcome: _hideWelcome,
    setWorkspacePath: _setWorkspacePath,
    setFileHandle: (v) => { _fileHandle = v },
    getLibraryPanel: () => libraryPanel,
    spawnDocTabIfBusy: _docSpawn.spawnDocTabIfBusy,
  })

  // Unified "Open File" — one picker shows both parts (.nadoc) and assemblies
  // (.nass); route to the right loader by extension.  Pick in this tab, but open
  // into a NEW tab when this space already holds content (multi-document).
  document.getElementById('menu-file-open')?.addEventListener('click', async () => {
    const result = await openFileBrowser({ title: 'Open File', mode: 'open', fileType: 'all', api })
    if (!result) return
    const isAssembly = /\.nass$/i.test(result.path || result.name || '')
    if (_docSpawn.spaceHasContent()) {
      const id = await mintDocId()
      if (id) {
        const q = new URLSearchParams({
          doc: id, open: result.path,
          'open-type': isAssembly ? 'assembly' : 'part',
          ...(result.name ? { 'open-name': result.name } : {}),
        })
        window.open(`/?${q.toString()}`, 'nadoc-doc-' + id)
        return
      }
    }
    if (isAssembly) await _fileOpen.openAssemblyFromServer(result.path)
    else            await _fileOpen.openPartFromServer(result.path, result.name)
  })

  // "Save File" / "Save As" dispatch by mode is provided by the ui/file_io.js
  // `initFileSave` factory (extraction #60); `_fileSave` is initialized later
  // (after `initPhotoMode`, whose getExportRepActive it reads). Lazy arrows defer
  // the deref to click time.
  document.getElementById('menu-file-save')?.addEventListener('click', () => _fileSave.saveDispatch())
  document.getElementById('menu-file-save-as')?.addEventListener('click', () => _fileSave.saveAsDispatch())

  document.getElementById('menu-file-new-assembly')?.addEventListener('click', async () => {
    if (await _docSpawn.spawnDocTabIfBusy('new=assembly')) return
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

  // Assembly save helpers (_saveAssembly / _saveAssemblyAsGuarded) moved into the
  // ui/file_io.js `initFileSave` factory (extraction #60); reached via
  // `_fileSave.*`. Ctrl+Shift+S calls them through a lazy injected wrapper.

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
    if (!data?.content) { showToast('Could not retrieve file from server.', { severity: 'error' }); return }
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

  document.getElementById('menu-assembly-define-belt')?.addEventListener('click', () => {
    beltPathPanel.open()
  })

  document.getElementById('menu-assembly-polymerize-origami')?.addEventListener('click', () => {
    polymerizePanel.open()
  })

  document.getElementById('menu-edit-undo')?.addEventListener('click', async () => {
    if (isDeformActive()) return
    if (popGroupUndo()) return
    const result = await api.undo()
    if (!result) {
      const err = store.getState().lastError
      if (err?.status === 404) showToast('Nothing to undo.', { severity: 'error' })
    } else {
      // diff_kind=cluster_only / positions_only deltas are applied inside
      // api.undo() via the registered _responseDeltaHandler (see
      // initResponseDelta in scene/response_delta.js). Do NOT re-apply here — that would
      // double-apply the rotation (cluster ends up at PRE − θ instead
      // of PRE) per the 2026-05-14 undo-after-relax regression.
      _clearScaffoldChecks()
      _clearStapleChecks()
      const { currentDesign } = store.getState()
      // If we undid back to an empty design, return to the empty scene (origin
      // triad + welcome). The axes subscriber re-shows the triad.
      if (!currentDesign?.helices?.length) {
        slicePlane.hide()
        _extrudePanel?.hide()
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
      if (err?.status === 404) showToast('Nothing to redo.', { severity: 'error' })
    } else {
      // Delta applied inside api.redo() via _responseDeltaHandler.
      _clearScaffoldChecks()
      _clearStapleChecks()
    }
  })

  // ── Operation progress popup helpers ──────────────────────────────────────
  // Thin wrappers around the shared module so client.js and tool flows share
  // one ref-counted progress widget — concurrent showers don't fight, and a
  // long API call (auto-shown by _request) layered on top of a tool-driven
  // progress (showProgress here) hides correctly when both finish.
  const _showProgress = showOpProgress
  const _hideProgress = hideOpProgress

  // ── Routing: Autoscaffold (seamed / seamless picker) ──────────────────────
  initAutoscaffoldPicker({ store, api, setRoutingCheck: _setRoutingCheck })


  document.getElementById('menu-routing-full-autostaple')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    _showProgress('Full autostaple', 'Assigning sequences and routing staples…')
    const result = await api.addFullAutostaple({ scaffold_name: 'M13mp18' })
    _hideProgress()
    if (!result) {
      showToast('Full autostaple failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
      return
    }
    const full = result.full_autostaple ?? {}
    showToast(`Full autostaple complete: ${full.auto_crossover?.placed ?? 0} crossovers placed.`)
  })

  document.getElementById('menu-routing-polymerization')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    const result = await api.routeForPolymerization()
    if (!result) {
      showToast('Route for polymerization failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
      return
    }
    const nBridges = result.seam_ligation_ids?.length ?? 0
    const warnings = result.warnings ?? []
    if (warnings.length) {
      showToast(`Routed ${nBridges} bridging staple(s). ${warnings[0]}`, { severity: 'warning' })
    } else {
      showToast(`Routed for polymerization: ${nBridges} bridging staple(s) across the seam.`)
    }
  })

  // Auto Crossover + Autobreak were retired from the Routing menu in favour of
  // one-click Full Autostaple ('2'); autobreak_modal.js is kept unwired for revival.

  // ── Sequencing ────────────────────────────────────────────────────────────

  // Assign Scaffold Sequence modal (menu + scaffold right-click) → ui/scaffold_modal.js.
  // The undefined-highlight module (_undefinedHighlight) is constructed later in main();
  // injected as lazy arrows since the apply path only runs on user action (post-boot).
  const _scaffoldModal = initScaffoldModal({
    store, api,
    showProgress: _showProgress,
    hideProgress: _hideProgress,
    getUndefinedHighlightOn: () => _undefinedHighlight.isOn(),
    refreshUndefinedHighlight: () => _undefinedHighlight.refresh(),
  })

  document.getElementById('menu-seq-assign-staples')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
    const scaffold = currentDesign.strands?.find(s => s.strand_type === 'scaffold')
    if (!scaffold?.sequence) {
      showToast('Scaffold has no sequence. Run "Assign Scaffold Sequence" first.', { severity: 'error' })
      return
    }
    _showProgress('Deriving complementary staple sequences…')
    const ok = await api.assignStapleSequences()
    _hideProgress()
    if (!ok) showToast('Assign staple sequences failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
  })

  document.getElementById('menu-seq-generate-overhangs')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
    const ovhgCount = currentDesign.overhangs?.length ?? 0
    if (ovhgCount === 0) { showToast('No overhangs found.', { severity: 'error' }); return }
    showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
    _showProgress(`Generating sequences for ${ovhgCount} overhang${ovhgCount !== 1 ? 's' : ''}…`)
    const result = await api.generateAllOverhangSequences()
    _hideProgress()
    if (!result?.ok) {
      showToast('Generate overhangs failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
    } else {
      showToast(`Sequences generated for ${result.count} overhang${result.count !== 1 ? 's' : ''}.`)
    }
  })

  document.getElementById('menu-seq-update-routing')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    const isSQ = currentDesign?.lattice_type === 'SQUARE'
    if (!currentDesign?.deformations?.length && !isSQ) { showToast('No deformation ops on the current design.', { severity: 'error' }); return }
    const hasCrossovers = currentDesign?.strands?.some(s =>
      s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
    )
    if (!hasCrossovers) { showToast('Place crossovers first (Auto Crossover) before adding loops/skips.', { severity: 'error' }); return }
    _showProgress('Add Loops/Skips', 'Applying loop/skip modifications…')
    const result = await api.applyAllDeformations()
    _hideProgress()
    if (!result) {
      showToast('Add Loops/Skips failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
    } else {
      showToast(
        'Loops/skips added — method of Dietz, Douglas & Shih, Science 2009 (doi:10.1126/science.1174251).',
        {
          duration: 8000,
          action: {
            label: 'View paper',
            onClick: () => window.open('https://doi.org/10.1126/science.1174251', '_blank', 'noopener'),
          },
        },
      )
    }
  })

  document.getElementById('menu-seq-clear-all-loop-skips')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
    const ok = await showConfirm({
      title: 'Clear loops & skips',
      message: 'Remove all loop/skip marks from the design?',
      danger: true,
      confirmLabel: 'Clear all',
    })
    if (!ok) return
    const result = await api.clearAllLoopSkips()
    if (!result) showToast('Clear failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
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

  // Tools → Extrude: open the Extrude panel in new-bundle mode on the default plane.
  // Unlike Twist/Bend, this is allowed on an empty design (that's the point — it's
  // how you start). On a populated part the new-bundle flow is destructive, so it
  // goes through the same confirm guard as the empty-space right-click.
  document.getElementById('menu-tools-extrude')?.addEventListener('click', () => {
    if (store.getState().assemblyActive) { showToast('Not available in assembly mode.', { severity: 'error' }); return }
    _startEmptySpaceExtrude()
  })

  document.getElementById('menu-tools-twist')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    if (!deformView.isActive() && currentDesign.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
      return
    }
    if (!_clusterDeformGuard()) return
    startTool('twist')
    document.getElementById('mode-indicator').textContent =
      'TWIST — click plane A (fixed), then plane B · Esc to exit'
  })

  document.getElementById('menu-tools-bend')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    if (!deformView.isActive() && currentDesign.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
      return
    }
    if (!_clusterDeformGuard()) return
    startTool('bend')
    document.getElementById('mode-indicator').textContent =
      'BEND — click plane A (fixed), then plane B · Esc to exit'
  })

  // Tools → Add Primitive: reveal the right-sidebar Primitives library.
  document.getElementById('menu-tools-add-primitive')?.addEventListener('click', () => {
    if (store.getState().assemblyActive) { showToast('Not available in assembly mode.', { severity: 'error' }); return }
    _primitiveLibrary.activate()
  })

  initOverhangsManagerPopup({ store })
  initOverhangConnectionsPanel({ store, scene, designRenderer, createGlowLayer })   // right-sidebar "Overhang Connections" section
  document.getElementById('menu-tools-overhangs-manager')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    openOverhangsManager()   // popup pulls preselect from store on its own
  })

  // Conjugate Manager — resolve which protein to show: the selected protein's
  // asset, else the first imported library asset, else nudge the user to import.
  document.getElementById('menu-tools-conjugate-manager')?.addEventListener('click', async () => {
    const sel = store.getState().selectedObject
    let assetId = null
    if (sel?.type === 'protein') {
      assetId = store.getState().currentDesign?.protein_attachments?.find(a => a.id === sel.id)?.asset_id
    }
    if (!assetId) {
      const lib = await api.listProteinLibrary().catch(() => null)
      assetId = lib?.assets?.[0]?.id ?? lib?.[0]?.id ?? null
    }
    if (!assetId) { showToast('Import a protein first (File ▸ Import PDB…).', { severity: 'error' }); return }
    conjugateManager.open(assetId)
  })

  initAssemblyOverhangsManagerPopup({ store })
  document.getElementById('menu-assembly-overhangs-manager')?.addEventListener('click', () => {
    const { currentAssembly } = store.getState()
    if (!currentAssembly) { showToast('No assembly loaded.', { severity: 'error' }); return }
    openAssemblyOverhangsManager()
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

  // ── Coloring submenu (Strand / Base / Cluster / Overhang / CPK) ─────────────
  function _setColoringMode(mode) {
    store.setState({ coloringMode: mode })
    document.getElementById('menu-view-coloring-strand') ?.classList.toggle('is-checked', mode === 'strand')
    document.getElementById('menu-view-coloring-base')   ?.classList.toggle('is-checked', mode === 'base')
    document.getElementById('menu-view-coloring-cluster')?.classList.toggle('is-checked', mode === 'cluster')
    document.getElementById('menu-view-coloring-overhang-only')?.classList.toggle('is-checked', mode === 'overhang-only')
    document.getElementById('menu-view-coloring-cpk')    ?.classList.toggle('is-checked', mode === 'cpk')
    document.getElementById('menu-view-coloring-source') ?.classList.toggle('is-checked', mode === 'source')
    // The sidebar coloring array (ui/coloring_options_panel.js) mirrors the
    // active mode on its own via a store.coloringMode subscription.
  }
  document.getElementById('menu-view-coloring-strand') ?.addEventListener('click', () => _setColoringMode('strand'))
  document.getElementById('menu-view-coloring-base')   ?.addEventListener('click', () => _setColoringMode('base'))
  document.getElementById('menu-view-coloring-cluster')?.addEventListener('click', () => _setColoringMode('cluster'))
  document.getElementById('menu-view-coloring-overhang-only')?.addEventListener('click', () => _setColoringMode('overhang-only'))
  document.getElementById('menu-view-coloring-cpk')    ?.addEventListener('click', () => _setColoringMode('cpk'))
  document.getElementById('menu-view-coloring-source') ?.addEventListener('click', () => _setColoringMode('source'))

  document.getElementById('menu-view-reset')?.addEventListener('click', () => {
    const { currentGeometry } = store.getState()
    if (currentGeometry && currentGeometry.length > 0) {
      camera.position.set(6, 3, 7)
      controls.target.set(0, 0, 7)
    } else {
      // Empty scene (origin triad only): reset to the default workspace framing.
      camera.position.set(6, 3, 18)
      controls.target.set(6, 3, 0)
    }
    controls.update()
  })

  initBackgroundModal()

  document.getElementById('menu-view-slice')?.addEventListener('click', _toggleSlicePlane)

  document.getElementById('menu-view-unfold')?.addEventListener('click', _toggleUnfold)

  document.getElementById('menu-view-cadnano')?.addEventListener('click', _toggleCadnano)

  document.getElementById('btn-open-editor')?.addEventListener('click', () => {
    // Editor must edit the SAME backend document as this 3D tab → carry our doc id.
    // In a part-editor tab this is the part's OWN isolated doc, so each open part
    // gets a distinct editor window (name `nadoc-editor-<doc>`) — no collision.
    const qs = getDocId() ? `?doc=${encodeURIComponent(getDocId())}` : ''
    window.open(`/cadnano-editor.html${qs}`, 'nadoc-editor' + (getDocId() ? '-' + getDocId() : ''))
  })

  document.getElementById('menu-view-deform')?.addEventListener('click', _toggleDeformView)

  // ── View legends (Loop/Skip + MD Segmentation) ──────────────────────────────
  // Extracted to ui/view_legends.js: the two fixed-position legend overlays + their
  // View-menu toggle handlers. `_resetForNewDesign` hides both via `viewLegends.reset()`.
  // `_setMenuToggle` is a hoisted fn decl (defined ~100 ln below) → safe to pass here.
  const viewLegends = initViewLegends({
    store, loopSkipHighlight, mdSegmentation,
    setMenuToggle: _setMenuToggle,
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

  // Pill-state subscriber + the 3 menu-visibility helpers extracted to
  // ui/view_menu_pills.js. `_setMenuToggle` (43-use shared util) stays here and is
  // injected. The factory registers its store subscriber + runs the initial
  // import-visibility sync at this exact point → subscription order preserved.
  initViewMenuPills({ store, setMenuToggle: _setMenuToggle })

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
        sliceHighlighter.clear()
        _setMenuToggle('menu-view-slice', false)
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      }
    }
  })

  // ── Tool Filter toggles — #view-tools .sf-btn[data-key] ─────────────────────
  // Extracted to ui/tool_filter_toggles.js. The #view-tools button row + the
  // toolFilters→renderer-visibility subscriber. overhangHoverPicker is created
  // later (~init order), so it's reached via a lazy getter.
  initToolFilterToggles({
    store, overhangLocations, designRenderer,
    rebuildOverhangLocations: _rebuildOverhangLocations,
    getOverhangHoverPicker: () => overhangHoverPicker,
  })

  // ── Force-Crossover tool — #view-tools [data-key="fxover"] ──────────────────
  // 3D forced ligation: click two matching strand ends to ligate them into one.
  // Owns its own button wiring + capture-phase gesture; main.js only constructs it.
  const forceCrossoverTool = initForceCrossoverTool({
    store, canvas, camera, designRenderer, selectionManager, api,
    getCamera: () => sceneCtx.getRenderCamera(),
  })

  // Save/restore selectableTypes when deform tool activates/deactivates so that
  // all selection code that reads selectableTypes sees the correct blocked state.
  let _savedSelectableTypes = null
  store.subscribe((newState, prevState) => {
    if (newState.deformToolActive === prevState.deformToolActive) return
    if (newState.deformToolActive) {
      // Deform editing previews the full/CG geometry. The hull-prism solid is a
      // coarse envelope that can't reflect the live preview AND would persist
      // underneath it (both reps visible at once). Drop to full for the edit so
      // only the deforming geometry shows. (No auto-restore — full is the clearest
      // view of the result; the user re-picks Hull Prism afterward if wanted.)
      if (_currentRepr === 'hull-prism') _setRepresentation('full')
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
  // Button handlers + 2 store subscribers extracted to ui/selection_filter.js.
  // Called here (not at factory construction) to preserve store-subscription order.
  selectionFilter.attachFilterButtons()

  // ── View tool buttons — length heatmap, seq, undef, grid, overhang names ──────
  // Extracted to ui/view_tool_buttons.js. Owns length-heatmap + grid state; the
  // shared undefined-highlight flag lives in scene/undefined_highlight.js
  // (_undefinedHighlight, constructed below) and is reached via lazy arrows.
  _viewToolButtons = initViewToolButtons({
    store, scene, designRenderer, expandedSpacing,
    setMenuToggle: _setMenuToggle,
    refreshUndefinedHighlight: () => _undefinedHighlight.refresh(),
    getUndefinedHighlightOn: () => _undefinedHighlight.isOn(),
    setUndefinedHighlightOn: (v) => _undefinedHighlight.setOn(v),
    toggleDeformView: () => _toggleDeformView(),
    toggleUnfold: () => _toggleUnfold(),
    toggleCadnano: () => _toggleCadnano(),
    toggleClashes: () => clashOverlay.toggle(),
    getClashesOn: () => clashOverlay.isOn(),
  })

  // ── Nucleotide Slab collapse toggle ──────────────────────────────────────────
  ;(function () {
    const heading = document.getElementById('slab-heading')
    const body    = document.getElementById('slab-body')
    const arrow   = document.getElementById('slab-arrow')
    if (!heading || !body || !arrow) return
    const setOpen = (open) => {
      body.style.display = open ? 'block' : 'none'
      arrow.classList.toggle('is-collapsed', !open)
    }
    heading.addEventListener('click', () => setOpen(body.style.display === 'none'))
    // Switching representation surfaces this section's options, so auto-expand it
    // whenever the representation changes (it starts collapsed by default).
    window.addEventListener('nadoc:representation-change', () => setOpen(true))
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

  // Track whether the current pointer gesture STARTED on the 3D canvas, so the
  // orbit relay below only fires for real canvas drags — not for clicks in side
  // panels (e.g. the Plates & tubes well grid), which must not reach the 3D
  // canvas's pointerup deselect (it would clear a selection the panel just made).
  let _gestureStartedOnCanvas = false
  document.addEventListener('pointerdown', e => {
    _gestureStartedOnCanvas = canvas.contains(e.target)
  }, { capture: true })

  // Orbit relay: when the left button is released OUTSIDE the canvas and the deform
  // tool is NOT active, forward a synthetic pointerup to the canvas so OrbitControls
  // can clean up its drag state. We skip this relay when deform is active because
  // our capture-phase handlers already manage pointer events correctly in that context,
  // and an extra synthetic event would only confuse things.
  document.addEventListener('pointerup', e => {
    if (e.button !== 0) return
    if (isDeformActive()) return          // deform tool manages its own state
    if (canvas.contains(e.target)) return // already on canvas — no relay needed
    if (!_gestureStartedOnCanvas) return  // gesture began off-canvas (a side panel) — don't relay
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
      // Empty scene (origin triad only): reset to the default workspace framing.
      camera.position.set(6, 3, 18)
      controls.target.set(6, 3, 0)
    }
    controls.update()
  })

  // ── Keyboard shortcuts ────────────────────────────────────────────────────────
  // All design-editor keyboard shortcuts are registered by
  // ui/keyboard_shortcuts.js (file/edit, view/tool toggles, number hotkeys,
  // Delete, Escape). 's'/'d' are reserved for WASD pan; the dispatch registry +
  // matcher live in input/shortcuts.js. The factory also attaches the single
  // document 'keydown' listener.
  initKeyboardShortcuts({
    store, api,
    slicePlane, expandedSpacing, debugOverlay, measurementTool, selectionManager,
    clusterClipboard: _clusterClipboard,
    extrudePanel: _extrudePanel, deformView, crossSectionMinimap, sliceHighlighter,
    primitiveLibrary: _primitiveLibrary,
    viewCube, camera, controls,
    isUnfoldActive:           _isUnfoldActive,
    isDeformActive,
    captureCurrentCamera,
    frameSelectionOrAll:      _frameSelectionOrAll,
    setMenuToggle:            _setMenuToggle,
    toggleUnfold:             _toggleUnfold,
    toggleCadnano:            _toggleCadnano,
    savePartToAssembly:       (opts) => _fileIo.savePartToAssembly(opts),
    saveAssemblyAsGuarded:    () => _fileSave.saveAssemblyAsGuarded(),
    setAssemblyWorkspacePath: _setAssemblyWorkspacePath,
    showWelcome:              _showWelcome,
    ooClose:                  () => _orientPanel.close(),
    cancelTranslateRotateTool: (...a) => _cancelTranslateRotateTool(...a),
    watchDeformState:         _watchDeformState,
    deformEscape,
    popGroupUndo,
    isTranslateRotateActive:  () => _translateRotateActive,
    getPartEditContext:       () => _partEditContext,
    getAssemblyWorkspacePath: () => _assemblyWorkspacePath,
    getOoActiveIds:           () => _orientPanel.getActiveIds(),
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
        const confirmed = await showConfirm({
          title: 'Delete strand',
          message: `Delete strand "${nuc.strand_id}"?`,
          danger: true,
          confirmLabel: 'Delete',
        })
        if (confirmed) await api.deleteStrand(nuc.strand_id)
      }
    },
  })

  // ── UI panels ───────────────────────────────────────────────────────────────
  // True when a part is periodic (its design has an is_periodic_seam forced
  // ligation). Inline sources embed the design on the instance; file-backed
  // sources resolve through the renderer's cached source design.
  function _instancePeriodic(inst) {
    const embedded = inst?.source?.design?.forced_ligations
    if (embedded) return embedded.some(fl => fl.is_periodic_seam)
    return !!assemblyRenderer.getInstanceDesign?.(inst?.id)?.forced_ligations?.some(fl => fl.is_periodic_seam)
  }

  initPropertiesPanel()
  // Periodic parts surface inside the Polymerize Origami panel's Mate dropdown
  // as "<part> — via periodic boundary" (unified with regular polymerize).
  // Assigned ~1000 ln below at its original definition site; these arrows run at
  // panel-interaction time (long after init), so the lazy reference is safe.
  let _beltPolymerize = null
  const polymerizePanel = initPolymerizePanel(store, {
    isInstancePeriodic: (id) =>
      !!assemblyRenderer.getInstanceDesign?.(id)?.forced_ligations?.some(fl => fl.is_periodic_seam),
    // Belt-loop polymerize: seed = an existing belt rider; geometry is JS-side.
    getBeltFillCount: (riderId) => _beltPolymerize?.beltFillInfo(riderId),
    onPolymerizeBelt: (riderId, count) => _beltPolymerize?.polymerizeBelt(riderId, count),
  })
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

  // Strand Animation sidebar section — un/hybridization of a selected overhang
  // + its binder, driving the real beads (ported from the strand-anim sandbox).
  initStrandAnimPanel(store, {
    getHelixCtrl: () => designRenderer.getHelixCtrl(),
    getGeometry:  () => store.getState().currentGeometry,
    getDesign:    () => store.getState().currentDesign,
    getScene:     () => scene,
    api,
    // Lazy: animPanel is assigned later in main() (~L12150). Only called on click.
    getAnimContext: () => animPanel?.getKeyframeContext?.() ?? null,
  })

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
      flexibleArcs.applyLiveUpdate(helixIds, centerVec, dummyPos, incrRotQuat)   // re-solve arcs + bow-away from live cylinders
      // Extra-base beads now live in crossoverConnections group — rebuilt on full scene rebuild.
      // DEBUG — log once per frame so you can see cone state during a drag
      helixCtrl?.logConeDebug('LIVE-FRAME')
    },
    (helixIds, domainIds, append = false) => {
      // `append` = add these beads to the existing base snapshot instead of clearing it —
      // needed when a drag captures MULTIPLE bodies (the dragged cluster + movable-link
      // bodies), so the second capture doesn't wipe the first (which froze the main cluster).
      const helixCtrl = designRenderer.getHelixCtrl()
      helixCtrl?.captureClusterBase(helixIds, domainIds, append)
      bluntEnds?.captureClusterBase(helixIds, append, domainIds)
      if (!domainIds?.length) jointRenderer?.captureClusterBase(helixIds, append)
      if (!domainIds?.length) overhangLocations.captureClusterBase(helixIds, append)
      // DEBUG — snapshot the bead positions at drag-start before any transform
      helixCtrl?.logConeDebug('DRAG-START')
    },
    (translation, quaternion) => {
      _clusterDirty = true
      const [rx, ry, rz] = quatToEulerDeg([quaternion.x, quaternion.y, quaternion.z, quaternion.w])
      _mrSetTransformValues(translation[0], translation[1], translation[2], rx, ry, rz)
      const activeJoint = clusterGizmo?.getActiveJoint()
      if (activeJoint) {
        _mrSetJointAngle(extractJointAngleDeg(quaternion, activeJoint))
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
  // DEBUG — instance-group bounding-box audit. Pass instanceId, or omit to audit
  // the active instance. Logs every Mesh / InstancedMesh contribution sorted by
  // extent. Outliers at the top of the list are what's bloating the BoxHelper.
  window.__nadocBoxAudit   = (instanceId = null) => assemblyRenderer.auditInstanceBox(instanceId)
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

  // ── Overhang Orientation panel (extracted → ui/overhang_orientation_panel.js, #64) ──
  // Plain `const` at the original spot: all call sites — _onEditFeature (~1390), the overhang
  // context menu (~2898), and the keyboard_shortcuts deps (~4748/4756) — fire post-boot, so
  // they reference `_orientPanel` after this line runs (TDZ-safe, mirrors #34/#38/#50). Deps
  // are all available here (bluntEnds ~3085, overhangLocations ~1568, assemblyRenderer ~235);
  // `_ovhgRootMap` is mutable (rebuilt ~1822) so it is passed as a getter. The factory's
  // internal store.subscribe registers at this position → subscription order preserved.
  const _orientPanel = initOverhangOrientationPanel({
    store, api, scene, camera, canvas, controls,
    designRenderer, bluntEnds, overhangLocations, assemblyRenderer,
    getOvhgRootMap: () => _ovhgRootMap,
  })

  const instanceGizmo = initInstanceGizmo(store, controls)
  const assemblyJointRenderer = initAssemblyJointRenderer(scene, camera, canvas, store, api, controls)

  // Assembly transform engine (pending-transform Maps + transform-context builder
  // + live-apply + commit-queue + forward-kinematics live propagation) — shared by
  // group_gizmo, the Move/Rotate panel shell, and the Translate/Rotate tool. Lifted
  // to scene/assembly_transform.js (carve-up keystone). Alias-consts below keep
  // every existing call site verbatim — only the function bodies moved.
  const _assemblyTransform = initAssemblyTransform({
    store, api, assemblyRenderer, assemblyJointRenderer,
  })
  const _assemblyPendingTransforms      = _assemblyTransform.pendingTransforms
  const _assemblyPendingPartJoints      = _assemblyTransform.pendingPartJoints
  const _effectiveInstanceMatrix        = _assemblyTransform.effectiveInstanceMatrix
  const _createAssemblyTransformContext = _assemblyTransform.createAssemblyTransformContext
  const _applyAssemblyPrimaryLive       = _assemblyTransform.applyAssemblyPrimaryLive
  const _queueAssemblyPrimaryCommit     = _assemblyTransform.queueAssemblyPrimaryCommit
  const _commitAssemblyPending          = _assemblyTransform.commitAssemblyPending
  const _hasAssemblyPending             = _assemblyTransform.hasAssemblyPending
  const _applyFKLive                    = _assemblyTransform.applyFKLive
  const _applyClusterMateFKLive         = _assemblyTransform.applyClusterMateFKLive
  const _analyzeMotionConstraints       = _assemblyTransform.analyzeMotionConstraints
  const _setMotionChip                  = _assemblyTransform.setMotionChip

  // ── Move/Rotate right-sidebar panel ──────────────────────────────────────────
  // Flexible ssDNA-segment relax + "ssDNA constrained" pivot gating → scene/flex_relax.js.
  // Kept in main (also used by the Translate/Rotate tool fns below) and injected
  // into the panel + tool.
  const _flexRelax = initFlexRelax({
    store, api, designRenderer, clusterGizmo,
    isTranslateRotateActive: () => _translateRotateActive,
  })

  // Recompute a cluster's pivot/translation from live bead positions before the
  // gizmo attaches to it. Tool-shared (panel cluster-dropdown + the tool's
  // gizmo-attach paths) so it stays in main and is injected into the panel.
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
    if (vecClose(cluster.pivot, pivot) && vecClose(cluster.translation, translation)) return

    clusterGizmo.setPendingTransform(clusterId, {
      pivot,
      translation,
      rotation: cluster.rotation,
    })
  }

  // Panel shell (numeric inputs + pivot/cluster dropdowns) → scene/move_rotate_panel.js.
  // Alias-consts below keep the tool fns + external call sites verbatim — only the
  // function bodies moved.
  const _moveRotatePanel = initMoveRotatePanel({
    store, scene, camera, canvas,
    clusterGizmo, instanceGizmo, flexRelax: _flexRelax,
    applyAssemblyPrimaryLive:     _applyAssemblyPrimaryLive,
    queueAssemblyPrimaryCommit:   _queueAssemblyPrimaryCommit,
    refreshClusterPivotForAttach: _refreshClusterPivotForAttach,
    setClusterRotationPoint:      api.setClusterRotationPoint,
    isTranslateRotateActive:      () => _translateRotateActive,
  })
  const _mrPanel                        = _moveRotatePanel.panel
  const _mrClusterSel                   = _moveRotatePanel.clusterSel
  const _mrPivotSel                     = _moveRotatePanel.pivotSel
  const _mrSetTransformValues           = _moveRotatePanel.setTransformValues
  const _mrSetTransformValuesFromMatrix = _moveRotatePanel.setTransformValuesFromMatrix
  const _mrSetJointAngle                = _moveRotatePanel.setJointAngle
  const _mrSetPivotOptions              = _moveRotatePanel.setPivotOptions
  const _mrSetSelectedPivot             = _moveRotatePanel.setSelectedPivot
  const _mrSetClusterOptions            = _moveRotatePanel.setClusterOptions
  const _mrSyncClusterDropdown          = _moveRotatePanel.syncClusterDropdown

  // Group/instance gizmo subsystem (revolute-drag angle accumulator + gear/belt
  // live-coupling engine + single-instance gizmo attach). The shared helpers it
  // leans on (transform-context builder, Move/Rotate live-apply + commit-queue,
  // motion analysis + chip) are function declarations hoisted within main(), so
  // they're already bound here even though defined further down.
  const _groupGizmo = initGroupGizmo({
    store, scene, camera, canvas,
    instanceGizmo, assemblyRenderer, assemblyJointRenderer, api,
    analyzeMotionConstraints:        _analyzeMotionConstraints,
    setMotionChip:                   _setMotionChip,
    createAssemblyTransformContext:  _createAssemblyTransformContext,
    applyAssemblyPrimaryLive:        _applyAssemblyPrimaryLive,
    queueAssemblyPrimaryCommit:      _queueAssemblyPrimaryCommit,
    getMrAssemblyCtx:                () => _moveRotatePanel.getAssemblyCtx(),
    setMrTransformValuesFromMatrix:  _mrSetTransformValuesFromMatrix,
    effectiveInstanceMatrix:         _effectiveInstanceMatrix,
    updateAssemblyMultiBox:          () => _assemblyMultiBox.update(),
  })
  const _attachGroupGizmo         = _groupGizmo.attachGroupGizmo
  const _attachGroupGizmoForGroup = _groupGizmo.attachGroupGizmoForGroup
  const beltPathRenderer = initBeltPathRenderer(scene)
  // Per-belt visibility (session-only; default visible). The persistent belt
  // tubes are suppressed while the define/edit panel is open (it shows its own
  // live preview), and rebuilt on assembly change + panel close + toggle.
  const _beltHiddenIds = new Set()
  function _rebuildBeltPaths() {
    beltPathRenderer.rebuild(store.getState().currentAssembly, {
      hiddenIds: _beltHiddenIds,
      suppress:  beltPathPanel.isOpen(),
    })
  }
  function _toggleBeltVisibility(beltId) {
    if (_beltHiddenIds.has(beltId)) _beltHiddenIds.delete(beltId)
    else _beltHiddenIds.add(beltId)
    _rebuildBeltPaths()
    assemblyPanel.rebuild(store.getState())   // refresh the row's eye icon
  }
  // Attach-part-to-belt: click a connector to select it (highlighted; click again
  // to deselect), then click the belt path to seat the part there. The belt must
  // be visible to be a click target, so force-show it first.
  function _attachPartToBelt(beltId) {
    if (_beltHiddenIds.has(beltId)) { _beltHiddenIds.delete(beltId); _rebuildBeltPaths() }
    showToast('Attach to belt: click a connector on a part, then click the belt path.')
    assemblyJointRenderer.enterAttachMode(beltId, {
      onSelect: (conn) => showToast(conn
        ? 'Connector selected — click the belt path to place it (or click it again to deselect).'
        : 'Connector deselected — pick a connector.'),
      onNeedConnector: () => showToast('Select a connector first, then click the belt path.'),
      onAttach: async (payload) => {
        const res = await api.createBeltRider(payload)
        if (res === null) showToast(`Attach failed: ${store.getState().lastError?.message ?? ''}`, { severity: 'error' })
        else showToast('Part attached to belt.')
      },
      onCancel: () => {},
    })
  }

  // ── Polymerize along a belt (seed = an existing belt rider) ─────────────────
  // Helpers extracted to scene/belt_polymerize.js. Assign the lazy reference
  // captured by the polymerizePanel dep arrows above.
  _beltPolymerize = initBeltPolymerize({ store, api, getAssemblyRenderer: () => assemblyRenderer })

  const beltPathPanel = initBeltPathPanel(store, { api, jointRenderer: assemblyJointRenderer,
    onOpen:  () => _rebuildBeltPaths(),   // suppress persistent tubes while previewing
    onClose: () => _rebuildBeltPaths() })
  if (window.__NADOC_DBG__) {
    window.__NADOC_DBG__.beltPathPanel = beltPathPanel
    window.__NADOC_DBG__.toggleBeltVisibility = _toggleBeltVisibility
    window.__NADOC_DBG__.beltFillCount = (riderId) => _beltPolymerize.beltFillInfo(riderId)
    window.__NADOC_DBG__.polymerizeBelt = (riderId, count) => _beltPolymerize.polymerizeBelt(riderId, count)
  }

  // ── Kinematics ticker: continuous-spin for revolute joints ────────────────
  // Integrates AssemblyJoint.angular_velocity_rpm per frame and rotates each
  // joint's child instance_b together with its entire rigid-body group via
  // setLiveTransform (parts attached by rigid joints, stopping at `fixed`
  // instances). Silent backend patches at ~5 Hz keep save/load consistent;
  // deeper kinematic chains are handled by backend FK on each silent patch.
  // Three-Layer Law: only mutates AssemblyJoint.current_value and the derived
  // PartInstance.transform.
  const kinematicsTicker = initKinematicsTicker({
    store,
    api,
    getAssemblyRenderer:      () => assemblyRenderer,
    getAssemblyJointRenderer: () => assemblyJointRenderer,
  })
  // Tab hidden → RAF freezes anyway, but explicitly flush the latest shadow
  // values so a save right after tab-switch doesn't drift more than ~0.2 s.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) kinematicsTicker.flushNow()
  })
  window.__NADOC_KINEMATICS__ = kinematicsTicker
  // Console diagnostic for gear mates (the dump itself lives in the ticker
  // module, which owns the gear graph + shadow state). From the browser console:
  // `nadocGearDebug()` prints + returns gear relations, the ticker's gear graph,
  // shadow values, and a per-joint summary.
  window.nadocGearDebug = () => kinematicsTicker.gearDebug()

  // ── Assembly blunt-end sync + cluster pick helpers ──────────────────────────
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

  // Active-cluster pick helpers → scene/joint_pick.js. Alias-consts keep every
  // existing call site (`_canvasNdc` / `_clusterBackboneEntries` /
  // `_pickActiveClusterEntry`) verbatim.
  const _jointPick = initJointPick({ canvas, camera, store, designRenderer })
  const _canvasNdc = _jointPick.canvasNdc
  const _clusterBackboneEntries = _jointPick.clusterBackboneEntries
  const _pickActiveClusterEntry = _jointPick.pickActiveClusterEntry

  // Compute a placement offset for Duplicate so the clone lands JUST OUTSIDE
  // the source's world-space bounding box along world +X.  Uses the bbox's
  // actual X-extent (not the max-radius) so a hinge oriented perpendicular
  // to X gets a tight offset matching its X-width, not its long-axis length.
  function _computeAssemblyDuplicateOffset(sourceId) {
    const entry = assemblyRenderer.getInstanceCenters().find(c => c.id === sourceId)
    return assemblyDuplicateOffset(entry)
  }

  const assemblyContextMenu = initAssemblyContextMenu({
    api,
    onMoveRotate: (...a) => _activateTranslateRotateTool(...a),
    onDefineConnector: (id) => assemblyJointRenderer.enterConnectorDefineMode(id, () => {}),
    onToggleVisible: async (inst) => {
      await api.patchInstance(inst.id, { visible: !inst.visible })
    },
    onEditPart: (inst) => {
      // The part editor reads its source design from (and saves back to) the
      // assembly's doc, but EDITS on its OWN isolated doc so multiple open parts
      // don't clobber one another.
      //
      // We must pass that doc EXPLICITLY — we cannot let the new tab synthesize
      // one: window.open() copies the opener's sessionStorage into the child, so
      // the assembly tab's sticky `nadoc:tab-doc` would leak in and every part
      // editor would resolve to the SAME doc (re-creating the clobber). An
      // explicit `?doc=` wins in _resolveDocId and is deterministic per instance
      // (uuid), so reopening the same part reuses its window + doc without reload.
      const asmDoc  = getDocId()
      const partDoc = `pe-${asmDoc ?? 'default'}-${inst.id}`
      const asm     = asmDoc ? `&assembly-doc=${encodeURIComponent(asmDoc)}` : ''
      window.open(`/?part-instance=${inst.id}&doc=${encodeURIComponent(partDoc)}${asm}`, `nadoc-part-${inst.id}`)
    },
    onDuplicate: async (inst) => {
      const offset = _computeAssemblyDuplicateOffset(inst.id)
      const result = await api.duplicateInstance(inst.id, offset ? { offset } : {})
      if (!result) {
        const err = store.getState().lastError
        showToast(`Duplicate failed: ${err?.message || 'unknown error'}`, { severity: 'error' })
      }
    },
    onPolymerize: (inst) => polymerizePanel.open(
      _instancePeriodic(inst) ? { periodicInstanceId: inst.id } : {},
    ),
    onDelete: async (inst) => {
      if (inst.id === store.getState().activeInstanceId) {
        store.setState({ activeInstanceId: null })
      }
      await api.deleteInstance(inst.id)
    },
    // Group / Ungroup — surface only when there's a multi-select OR the
    // right-clicked part already belongs to a group.
    onGroup: async (instanceIds) => {
      try {
        const res = await api.createGroup({ instanceIds })
        // Move the newly created group into single-select.
        const newGid = res?.assembly?.groups?.[res.assembly.groups.length - 1]?.id
        if (newGid) {
          store.setState({
            activeGroupId: newGid,
            activeInstanceId: null,
            multiSelectedInstanceIds: [],
          })
        }
      } catch (err) {
        showToast(`Group failed: ${err?.message || 'unknown error'}`, { severity: 'error' })
      }
    },
    onUngroup: async (groupId) => {
      if (groupId === store.getState().activeGroupId) {
        store.setState({ activeGroupId: null })
      }
      await api.ungroup(groupId)
    },
    getMultiSelectedInstanceIds: () => store.getState().multiSelectedInstanceIds ?? [],
    getOwningGroupId: (instanceId) => {
      const groups = store.getState().currentAssembly?.groups ?? []
      for (const g of groups) {
        if ((g.instance_ids ?? []).includes(instanceId)) return g.id
      }
      return null
    },
  })

  function _defineAssemblyConnector(instanceId = store.getState().activeInstanceId) {
    if (!instanceId) return
    assemblyJointRenderer.enterConnectorDefineMode(instanceId, () => {})
  }

  async function _defineAssemblyMate() {
    // Always feed blunt-end connectors in mate mode regardless of the
    // ambient "blunt ends" tool-filter — they're the mate-point candidates
    // the user needs to pick.  (_syncAssemblyBluntEnds gates on the filter,
    // which is for normal-view display only.)
    const inAssembly = store.getState().assemblyActive
    const bluntEnds = inAssembly
      ? (assemblyRenderer.getInstanceBluntEnds?.() ?? [])
      : []
    // Bend center-of-curvature connectors — CAD-style "mate by circle
    // centers". Async because each visible instance's centers come from
    // the backend (the math reuses _frame_at_bp's upstream-op composition).
    // Cached per instance on first fetch, so re-entering Define-Mate is
    // instant once a part has been visited.
    let bendCenters = []
    if (inAssembly) {
      try { bendCenters = (await assemblyRenderer.getInstanceBendCenters?.()) ?? [] }
      catch (e) { console.warn('[mate] bend-center fetch failed:', e); bendCenters = [] }
    }
    assemblyJointRenderer.setExtraConnectors([...bluntEnds, ...bendCenters])
    assemblyJointRenderer.enterMateDefineMode(
      () => {},
      (id, mat) => assemblyRenderer.setLiveTransform(id, mat),
    )
  }

  // Cyan glow layer for active-cluster highlight (distinct from the green selection glow).
  const clusterGlowLayer = createGlowLayer(scene, 0x58a6ff)
  let _translateRotateActive = false
  let _clusterDirty         = false   // true once any local transform changes during the active tool session

  const _responseDelta = initResponseDelta({
    store,
    api,
    designRenderer,
    getJointRenderer: () => jointRenderer,
    bluntEnds,
    unfoldView,
    flexibleArcs,
    overhangLinkArcs,
    overhangLocations,
    overhangNameOverlay,
    loopSkipHighlight,
    unligatedCrossoverMarkers,
  })
  api.registerResponseDeltaHandler(_responseDelta.applyResponseDelta)
  // Alias-const keeps the tool's rebake call sites verbatim (only the body moved).
  const _rebakeHelixAxesForClusterDelta = _responseDelta.rebakeHelixAxesForClusterDelta
  // Shared cluster-overlay refresh (single source of truth in response_delta.js).
  // The tool's commit historically did NOT rebuild flexible arcs → withFlexibleArcs:false.
  const _refreshClusterOverlays = _responseDelta.refreshClusterOverlays
  // Shared ds-linker bridge re-emit (single source of truth in response_delta.js).
  const _reemitClusterBridges = _responseDelta.reemitClusterBridges

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

  /**
   * Wraps api.seekInstanceFeatures with the fast-path geometry update:
   *   1. Pre-emptively marks the instance's file source as self-saved so
   *      the watchdog SSE echo doesn't trigger a redundant full
   *      invalidate + getInstanceGeometry refetch (a ~3 s killer on
   *      60 k-bp parts).
   *   2. After the seek response (which now includes inline geometry),
   *      decodes the compact nucleotide format once and feeds it to
   *      assemblyRenderer.applyInlineGeometry — that pushes the new DNA
   *      into every instance sharing the same source path in a single
   *      pass, no further HTTP calls.
   *   3. Clears the self-save marker after a few seconds so genuine
   *      external edits to the same file (other tab / editor) still
   *      trigger a refresh.
   */
  async function _seekInstanceFeaturesFast(instanceId, position, subPosition = null) {
    const inst = store.getState().currentAssembly?.instances?.find(i => i.id === instanceId)
    const sourcePath = inst?.source?.type === 'file' ? inst.source.path : null
    if (sourcePath) {
      _lifecycleSync.selfSavedPaths.add(sourcePath)
      setTimeout(() => _lifecycleSync.selfSavedPaths.delete(sourcePath), 5000)
    }
    const json = await api.seekInstanceFeatures(instanceId, position, subPosition)
    const geom = json?.geometry
    const path = json?.source_path ?? sourcePath
    if (geom && path) {
      const nucleotides = geom.nucleotides_compact
        ? api._expandCompactNucleotides(geom.nucleotides_compact)
        : (geom.nucleotides ?? [])
      try {
        await assemblyRenderer.applyInlineGeometry(path, json.design, nucleotides, geom.helix_axes)
      } catch (err) {
        console.warn('[assembly] applyInlineGeometry failed; falling back to full rebuild:', err)
      }
    }
    // If the backend auto-resolved mates because cluster_transforms moved,
    // surface the solve_status in the Mates panel so the user sees the
    // pre-resolve discrepancy markers and which joints were re-snapped.
    if (json?.auto_resolved && json.solve_status) {
      assemblyPanel?.applySolveStatus?.(json.solve_status)
    }
    return json
  }

  // ── Translate/Rotate tool → scene/translate_rotate_tool.js (#81) ─────────────
  // The session flag _translateRotateActive (22 sites incl. the lifecycle spine),
  // _clusterDirty, and the deform-editor-shared _editContext stay main `let`s; the
  // factory reaches them via get/set shims. jointRenderer is declared just below,
  // so it is injected lazily. Alias-consts keep every external call site verbatim.
  const _translateRotateTool = initTranslateRotateTool({
    store, scene, camera, canvas,
    designRenderer,
    getJointRenderer: () => jointRenderer,
    clusterGizmo, instanceGizmo,
    assemblyRenderer, assemblyJointRenderer,
    api,
    moveRotatePanel: _moveRotatePanel,
    mrPanel: _mrPanel, mrClusterSel: _mrClusterSel, mrPivotSel: _mrPivotSel,
    setTransformValues: _mrSetTransformValues,
    setTransformValuesFromMatrix: _mrSetTransformValuesFromMatrix,
    setPivotOptions: _mrSetPivotOptions,
    setSelectedPivot: _mrSetSelectedPivot,
    setClusterOptions: _mrSetClusterOptions,
    createAssemblyTransformContext: _createAssemblyTransformContext,
    hasAssemblyPending: _hasAssemblyPending,
    commitAssemblyPending: _commitAssemblyPending,
    assemblyPendingTransforms: _assemblyPendingTransforms,
    assemblyPendingPartJoints: _assemblyPendingPartJoints,
    attachGroupGizmo: _attachGroupGizmo,
    flexRelax: _flexRelax,
    refreshClusterPivotForAttach: _refreshClusterPivotForAttach,
    pickActiveClusterEntry: _pickActiveClusterEntry,
    syncAssemblyBluntEnds: _syncAssemblyBluntEnds,
    rebakeHelixAxesForClusterDelta: _rebakeHelixAxesForClusterDelta,
    reemitClusterBridges: _reemitClusterBridges,
    refreshClusterOverlays: _refreshClusterOverlays,
    getActive: () => _translateRotateActive,
    setActive: (v) => { _translateRotateActive = v; store.setState({ translateRotateActive: v }) },
    getClusterDirty: () => _clusterDirty,
    setClusterDirty: (v) => { _clusterDirty = v },
    getEditContext: () => _editContext,
    setEditContext: (v) => { _editContext = v },
  })
  const _activateTranslateRotateTool = _translateRotateTool.activate
  const _confirmTranslateRotateTool  = _translateRotateTool.confirm
  const _cancelTranslateRotateTool   = _translateRotateTool.cancel
  const _rotateJoint                 = _translateRotateTool.rotateJoint
  const _removeToolPickListeners     = _translateRotateTool.removeToolPickListeners

  // ── Joint renderer ────────────────────────────────────────────────────────────
  jointRenderer = initJointRenderer(scene, camera, canvas, store, api)

  // Always-available console handle for tuning the hull-prism cluster view
  // (works in the legacy design view, unlike __NADOC_DBG__ which is gated on
  // the shared renderer flag).  e.g. nadocHull.minSize(0.05) ; nadocHull.debug(true)
  window.nadocHull = {
    debug:   (on = true)  => jointRenderer?.setHullClusterDebug(on),
    minSize: (frac)       => jointRenderer?.setHullMinSizeFraction(frac),
    // mode('boxes'|'prism', boxFill?) — boxes (default) keeps inter-helix
    // grooves; boxFill (0..1) tunes groove width.
    mode:    (m, fill)    => jointRenderer?.setHullMode(m, fill),
    // scanTick(bp) — extrusion-scan margin (also on the X-section margin slider).
    scanTick: (bp)        => jointRenderer?.setHullScanTick(bp),
  }

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
      _mrSetPivotOptions(joints, n.activeClusterId)
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
    // Duplicate spawns the new instance JUST OUTSIDE the source's world-
    // space bounding box along +X — uses the bbox's actual X-extent rather
    // than the max-radius so a hinge oriented perpendicular to X gets a
    // tight side-to-side offset instead of a long-axis-length gap.
    // Mirrors _computeAssemblyDuplicateOffset above.
    computeDuplicateOffset: (sourceId) => {
      const entry = assemblyRenderer.getInstanceCenters().find(c => c.id === sourceId)
      if (!entry) return null
      const GAP = 2.0
      const MIN = 5
      const xExtent = entry.size?.x ?? (entry.radius * 2)
      const dx = Math.max(MIN, xExtent + GAP)
      return [dx, 0, 0]
    },
    onDefineConnector: (instanceId) => _defineAssemblyConnector(instanceId),
    onDefineMate: () => _defineAssemblyMate(),
    onEditBeltPath: (belt) => beltPathPanel.open(belt),
    isBeltHidden: (beltId) => _beltHiddenIds.has(beltId),
    onToggleBeltVisibility: (beltId) => _toggleBeltVisibility(beltId),
    onAttachToBelt: (beltId) => _attachPartToBelt(beltId),
    onDeleteBeltRider: (riderId) => api.deleteBeltRider(riderId),
    onMateHighlight: (frames) => assemblyJointRenderer.showMateConnectorHighlights(frames),
    onMateHighlightClear: () => assemblyJointRenderer.clearMateConnectorHighlights(),
    onMateDebugMarkers: (debugFrames) => assemblyJointRenderer.showMateDebugMarkers(debugFrames),
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

  // Open-orchestration (_openPartFromServer / _openAssemblyFromServer) extracted
  // to ui/file_io.js `initFileOpen` (extraction #59). The factory is initialized
  // at ~7540 (after the assembly-load stash vars its setters write); `_fileOpen`
  // is forward-declared near the file-state block so the file-open menu handler
  // and these libraryPanel callbacks can reference it.

  // Assigned later (the import-menu region near the bottom of main()); the
  // library panel only *invokes* these on user click, so a lazy wrapper is safe.
  let _importMenu = null
  const libraryPanel = initLibraryPanel({
    api,
    onImportCadnano:  () => _importMenu?.importCadnanoWithAutodetection(),
    onImportScadnano: () => _importMenu?.importScadnanoWithAutodetection(),
    onNewPart: async () => {
      const dest = await openFileBrowser({ title: 'New Part — Choose Location', mode: 'save', fileType: 'part', suggestedName: 'Untitled', suggestedExt: '.nadoc', noOverwrite: true, api })
      if (!dest) return
      const lattice = await pickLattice()
      if (!lattice) return
      _resetForNewDesign()
      _fileHandle = null
      _setFileName(dest.name)
      _hideWelcome()
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
    onOpenPart:     (path, name) => _fileOpen.openPartFromServer(path, name),
    onOpenAssembly: (path) => _fileOpen.openAssemblyFromServer(path),
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
  // Status dot + debug log panel extracted to ui/sync_badge.js. Pure DOM —
  // setSyncStatus / syncLog are called by the auto-save subscribers, the
  // connection monitor, the file-IO ops and the SSE handler. The flag-reading
  // __nadocSyncDebug helper below stays inline and drives the panel via show/hide.
  const _syncBadge = initSyncBadge()

  // Auto-save + Library-SSE subsystem (app/lifecycle.js, extraction #55). It owns
  // the loop-prevention flags; created at its natural design-subscriber spot in the
  // autosave region below. Forward-declared here so the connection monitor and the
  // sync-debug helper (both defined above the init) can reference it lazily.
  let _lifecycleSync = null

  window.__nadocSyncDebug = {
    status() {
      return {
        workspacePath:         _workspacePath,
        assemblyWorkspacePath: _assemblyWorkspacePath,
        selfSavedPaths:        [...(_lifecycleSync?.selfSavedPaths ?? [])],
        reloadingFromSSE:      _lifecycleSync?.getReloadingFromSSE() ?? false,
        savingAssembly:        _lifecycleSync?.getSavingAssembly() ?? false,
        assemblyActive:        store.getState().assemblyActive,
      }
    },
    forceResync() {
      _syncBadge.syncLog('warn', 'FORCE', 'Manual force resync triggered')
      if (store.getState().assemblyActive) {
        const asm = store.getState().currentAssembly
        ;(asm?.instances ?? []).forEach(i => {
          assemblyRenderer.invalidateInstance(i.id)
          _syncBadge.syncLog('info', 'FORCE', `invalidated instance ${i.id} (${i.name})`)
        })
        assemblyRenderer.rebuild(asm).then(() => assemblyRenderer.rebuildLinkers(asm))
        _syncBadge.setSyncStatus('yellow', 'resyncing…')
      } else {
        api.getDesign().then(() => api.getGeometry())
        _syncBadge.syncLog('info', 'FORCE', 'Re-fetched design+geometry')
      }
    },
    show() { _syncBadge.showDebugPanel() },
    hide() { _syncBadge.hideDebugPanel() },
  }

  // ── Backend connection monitor: status badge + silent restart recovery ───────
  // Extracted to app/lifecycle.js (extraction #53). The factory starts the
  // /api/health poll and handles silent recovery on server restart. The
  // `setReloadingFromSSE` shim drives the `_reloadingFromSSE` loop-prevention flag
  // now owned by the autosave/SSE module (initAutosaveSync, #55) created below —
  // the shim body runs only post-boot (on a real restart event), so the lazy
  // `_lifecycleSync?.` reference is safe.
  initConnectionMonitor({
    api,
    store,
    assemblyRenderer,
    setSyncStatus: _syncBadge.setSyncStatus,
    syncLog: _syncBadge.syncLog,
    setReloadingFromSSE: (v) => _lifecycleSync?.setReloadingFromSSE(v),
  })

  registerShortcut({
    key: 'd', ctrl: true, shift: true,
    description: 'Toggle sync debug panel',
    handler(e) {
      e.preventDefault()
      _syncBadge.toggleDebugPanel()
    },
  })

  // File-IO operations (extracted to ui/file_io.js, #52). Wired here — not at the
  // "File open / save" banner ~3580 — because its deps (_setSyncStatus / _syncLog /
  // libraryPanel) are declared above this autosave region. Every call site
  // (menu dispatchers, command palette, import menu, the autosave subscriber
  // just below) executes lazily/post-init, so the late wiring is safe.
  const _fileIo = initFileIo({
    store, api,
    setSyncStatus: _syncBadge.setSyncStatus,
    syncLog: _syncBadge.syncLog,
    libraryPanel,
    updateAssemblyTitle: _updateAssemblyTitle,
    setWorkspacePath: _setWorkspacePath,
    setFileName: _setFileName,
    setAssemblyWorkspacePath: _setAssemblyWorkspacePath,
    setFileHandle: (v) => { _fileHandle = v },
    setAssemblyFileHandle: (v) => { _assemblyFileHandle = v },
    setAssemblyName: (v) => { _assemblyName = v },
    getWorkspacePath: () => _workspacePath,
    getAssemblyWorkspacePath: () => _assemblyWorkspacePath,
    getAssemblyName: () => _assemblyName,
    getPartEditContext: () => _partEditContext,
  })

  // ── Auto-save + Library SSE (app/lifecycle.js, extraction #55) ────────────────
  // Owns the four loop-prevention flags + the self-saved-path set; registers both
  // autosave subscribers and the SSE handler on construction. Placed here so the
  // design subscriber registers at its original point (subscription order matters).
  // `_assemblyRefresh` is referenced lazily — it's wired just below — and in turn
  // shares this module's `selfSavedPaths` Set by reference.
  _lifecycleSync = initAutosaveSync({
    store, api,
    fileIo: _fileIo,
    syncBadge: _syncBadge,
    libraryPanel,
    getAssemblyRefresh: () => _assemblyRefresh,
    getPartEditContext: () => _partEditContext,
    getWorkspacePath: () => _workspacePath,
    getAssemblyWorkspacePath: () => _assemblyWorkspacePath,
    setAssemblyWorkspacePath: _setAssemblyWorkspacePath,
  })

  // Coalesced assembly part-refresh: a burst of part-edit broadcasts + watchdog
  // SSEs collapses to ONE getAssembly + rebuild. clusterPanel is wired ~1000 ln
  // later, so it's injected lazily.
  const _assemblyRefresh = initAssemblyRefresh({
    store,
    api,
    assemblyRenderer,
    assemblyJointRenderer,
    syncLog: _syncBadge.syncLog,
    setSyncStatus: _syncBadge.setSyncStatus,
    syncAssemblyBluntEnds: _syncAssemblyBluntEnds,
    selfSavedPaths: _lifecycleSync.selfSavedPaths,
    getClusterPanel: () => clusterPanel,
  })

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
    unfoldView.setArcsVisible(visible)  // arc lines (_arcGroup); LOD/rep gating is per-arc (refreshArcVisibility)
    unfoldView.refreshArcVisibility()
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

  // ── Auto-defaults for large assemblies ──────────────────────────────────────
  // When entering assembly mode for an assembly that contains more than two
  // origami-scale parts, switch to Cylinders + Overhang highlight by default
  // so the user can immediately see what's connected without being overwhelmed
  // by per-bp detail.  Threshold: a part counts as "full sized" when it has
  // ≥12 helices (rectangular origamis have 24, square 16, half-rect 12 — small
  // motifs/tiles fall below).  Fires once per mode entry; user can still pick
  // anything they want afterward via the View menu.
  // On every assembly load, force all parts to the Cylinders rep + the
  // Overhang highlight coloring.  Cylinders give the clearest at-a-glance
  // bundle silhouette, and overhang highlight makes mate-point candidates
  // pop visually — the most informative default regardless of assembly
  // size.  Skips the PATCH if every part is already cylinders (avoids
  // spurious backend round-trips on a re-saved file).
  // Called BEFORE the first renderer build on load, so the assembly builds
  // straight to cylinders — the saved per-instance representation is NOT built
  // first (it was always replaced by cylinders anyway, so that initial build was
  // pure wasted load time).
  function _applyAssemblyLoadDefaults(assembly) {
    const instances = assembly?.instances ?? []
    if (instances.length === 0) return

    _setColoringMode('overhang-only')
    _updateReprRadio('cylinders')

    const needsPatch = instances.some(inst => inst.representation !== 'cylinders')
    if (needsPatch) {
      // Force cylinders in-memory so the upcoming build renders cylinders
      // directly (no saved-rep build), then persist to the backend WITHOUT
      // re-syncing the response — re-syncing would trigger a second rebuild.
      for (const inst of instances) inst.representation = 'cylinders'
      api.batchPatchInstances(
        instances.map(inst => ({ id: inst.id, representation: 'cylinders' })),
        { skipSync: true },
      ).catch(err => console.error('[assembly] default rep PATCH failed:', err))
    }
  }

  // One-shot disk-load stash, set by initFileOpen.openAssemblyFromServer (via the
  // setter shims passed below) and consumed by
  // whichever subscriber branch performs the build (mode-enter for a fresh open,
  // assemblyChanged for a reload while already in assembly mode).  `onProgress`
  // drives the file-load dialog; `settle` resolves the caller's await once the
  // build finishes.  Both are nulled the instant they're consumed so ordinary
  // edits never pick them up.
  let _assemblyLoadOnProgress = null
  let _assemblyLoadSettle     = null

  // File-open orchestration (ui/file_io.js initFileOpen, extraction #59). Placed
  // HERE — after the assembly-load stash vars its setters mutate — not at the
  // "File open / save" banner. The spine + file-load overlay helpers + the stash
  // setters flow in; the lifted bodies are verbatim. All call sites (file-open
  // menu handler ~3866, libraryPanel onOpen* callbacks ~7090, boot action ~10300)
  // invoke post-init, so the forward-declared `let _fileOpen` resolves directly.
  _fileOpen = initFileOpen({
    store, api,
    showFileLoad: _showFileLoad,
    flAppendLog: _flAppendLog,
    flSetProgress: _flSetProgress,
    flShowError: _flShowError,
    flShowSuccess: _flShowSuccess,
    resetForNewDesign: _resetForNewDesign,
    setFileName: _setFileName,
    setWorkspacePath: _setWorkspacePath,
    hideWelcome: _hideWelcome,
    showWelcome: _showWelcome,
    revealWorkspaceForEmptyPart: _revealWorkspaceForEmptyPart,
    fitToView: _fitToView,
    enterAssemblyMode: _enterAssemblyMode,
    setAssemblyWorkspacePath: _setAssemblyWorkspacePath,
    setAssemblyName: (v) => { _assemblyName = v },
    setAssemblyFileHandle: (v) => { _assemblyFileHandle = v },
    setAssemblyLoadOnProgress: (v) => { _assemblyLoadOnProgress = v },
    setAssemblyLoadSettle: (v) => { _assemblyLoadSettle = v },
  })

  // Shared rebuild wiring for the assembly subscriber.  Routing both build
  // branches through here keeps the heavy geometry build in exactly ONE place.
  // `fitOnDone` frames the camera only for a fresh load (mode-enter / reload) —
  // ordinary edits must not yank it.  The camera fit lives in the .then() because
  // the assembly bounding box is empty until the build completes.
  // Transitive collection of every instance id inside a PartGroup whose
  // `visible` overlay is false (recursively walks subgroups). Used to drive
  // the renderer's group-visibility overlay AFTER each rebuild so per-instance
  // `visible` flags stay untouched (overlay-only semantics).

  function _runAssemblyRebuild(assembly, { fitOnDone = false, activeInstanceId = null } = {}) {
    const onProgress = _assemblyLoadOnProgress
    const settle     = _assemblyLoadSettle
    _assemblyLoadOnProgress = null
    _assemblyLoadSettle     = null
    assemblyRenderer.rebuild(assembly, onProgress ? { onProgress } : undefined)
      .then(() => {
        assemblyRenderer.rebuildLinkers(assembly)
        _syncAssemblyBluntEnds()
        if (activeInstanceId) {
          const depths = computeFixedDepths(assembly)
          if (depths.has(activeInstanceId)) _rebuildFixedLocks(assembly)
        }
        _syncAssemblyReprMenu(assembly)
        assemblyRenderer.applyGroupVisibilityOverlay?.(computeGroupHiddenInstanceIds(assembly))
        if (fitOnDone) _fitToView()
        settle?.resolve()
      })
      .catch(err => {
        console.error('[assembly] rebuild failed:', err)
        settle?.reject(err)
      })
    assemblyJointRenderer.rebuild(assembly)
  }

  // Multi-select union BoxHelper (purple box around every multi-selected /
  // active-group instance). Initialized here so it exists before the assembly
  // store subscriber below (and the group-gizmo drag handler) call `.update()`.
  const _assemblyMultiBox = initAssemblyMultiBox({ scene, store, assemblyRenderer })

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
        // Force the cylinders load-default + coloring BEFORE the panel rebuild AND
        // the geometry build: the renderer builds cylinders directly — never the
        // saved representation (a surface-saved assembly would otherwise pay a
        // ~24 s surface build here that's immediately discarded) — and the panel's
        // per-part Repr dropdown shows the rep that's actually on screen.
        if (newState.currentAssembly) _applyAssemblyLoadDefaults(newState.currentAssembly)
        assemblyPanel.rebuild(newState)
        if (newState.currentAssembly) {
          // _runAssemblyRebuild owns the build so the disk-load path doesn't ALSO
          // build separately.
          _runAssemblyRebuild(newState.currentAssembly, {
            fitOnDone: true,
            activeInstanceId: newState.activeInstanceId,
          })
        }
        controls.addEventListener('change', _updateFixedLockPositions)
        canvas.addEventListener('pointerdown',  _onAssemblyPointerDown)
        canvas.addEventListener('click',        _onAssemblyClick)
        canvas.addEventListener('pointermove',  overhangHoverPicker.onHoverMove)
        canvas.addEventListener('contextmenu',  _onAssemblyContextMenu)
      } else {
        if (_hasAssemblyPending()) {
          _commitAssemblyPending().catch(err => console.error('[assembly] pending commit on exit:', err))
        }
        _rebuildFixedLocks(null)
        controls.removeEventListener('change', _updateFixedLockPositions)
        _setDesignGeometryVisible(true)
        // Reset mixed-rep dot — only meaningful in assembly mode.
        document.getElementById('menu-view-repr-mixed-dot')?.style.setProperty('display', 'none')
        assemblyPanel.hide()
        assemblyContextMenu.hide()
        instanceGizmo.detach()
        _assemblyPendingTransforms.clear()
        _assemblyPendingPartJoints.clear()
        assemblyRenderer.dispose()
        assemblyJointRenderer.exitAttachMode()
        assemblyJointRenderer.rebuild(null)   // clear all joint indicators
        beltPathRenderer.rebuild(null)        // clear persistent belt tubes
        canvas.removeEventListener('pointerdown',  _onAssemblyPointerDown)
        canvas.removeEventListener('click',        _onAssemblyClick)
        canvas.removeEventListener('pointermove',  overhangHoverPicker.onHoverMove)
        canvas.removeEventListener('contextmenu',  _onAssemblyContextMenu)
        overhangHoverPicker.reset()
        // Clean up any in-flight free drag (handlers + state in assembly_pointer.js)
        _assemblyPointer.cancelDrag()
        assemblyLasso.cancel()
        // Drop the multi-select union box from the scene; setState below also
        // fires the subscriber which re-runs update() (which clears it), but
        // doing it inline keeps the scene clean even if the recursive setState
        // path is short-circuited. The factory stays reusable — a later
        // re-entry rebuilds the box on the next update().
        _assemblyMultiBox.dispose()
        _setMotionChip(null)
        // Mode exit should also drop any orphaned multi-selection so the
        // panel/contextmenu don't surface stale group-able candidates.
        if ((newState.multiSelectedInstanceIds ?? []).length || newState.activeGroupId) {
          store.setState({ multiSelectedInstanceIds: [], activeGroupId: null, groupDiveStack: [] })
        }
        // Gizmo exit: detach if the tool was active during mode switch
        if (_translateRotateActive) {
          _translateRotateActive = false
          store.setState({ translateRotateActive: false })
          instanceGizmo.detach()
          _translateRotateTool.hideConfirmBtn()
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

    // Belt path needs at least two revolute mates to wrap; re-evaluate whenever
    // the joint set may have changed (adding a mate fires assemblyChanged).
    if (modeChanged || activeChanged || assemblyChanged) {
      const inAssembly = newState.assemblyActive
      const revoluteCount = (newState.currentAssembly?.joints ?? [])
        .filter(j => j.joint_type === 'revolute').length
      document.getElementById('menu-assembly-define-belt')
        ?.toggleAttribute('disabled', !(inAssembly && revoluteCount >= 2))
    }

    if (!modeChanged && newState.assemblyActive) {
      if (assemblyChanged) {
        // Hide the assembly welcome when the first part is added
        const prevCount = prevState.currentAssembly?.instances?.length ?? 0
        const newCount  = newState.currentAssembly?.instances?.length ?? 0
        if (prevCount === 0 && newCount > 0) _hideWelcome()

        assemblyPanel.rebuild(newState)
        // A disk-load reload (already in assembly mode) must never take the
        // transform-only fast path: that skips the rebuild AND would leave
        // _openAssemblyFromServer's load promise unsettled (hang).  Force the
        // full rebuild whenever a load is in flight.
        const isLoad = !!_assemblyLoadSettle
        if (!isLoad && assemblyTransformOnlyChange(prevState.currentAssembly, newState.currentAssembly)) {
          // Transform-only change (e.g. a move/rotate commit via propagateFk):
          // push each instance's new world matrix straight into the renderer
          // instead of disposing + re-fetching geometry — avoids the whole
          // assembly blinking out and re-rendering.  Joint indicators are
          // cheap, so we still rebuild those to track moved anchors.
          //
          // Push ONLY instances whose transform actually changed.  A
          // connector-register / joint-add response carries unchanged
          // transforms; pushing all of them would snap a live mate preview
          // back to the stored pose (the "moves three times" jank) and
          // re-pack every row for nothing.  Diffing prev→next keeps the moved
          // part (and its FK children) live and leaves the rest untouched.
          const _prevById = new Map(
            (prevState.currentAssembly?.instances ?? []).map(i => [i.id, i]),
          )
          let _anyMoved = false
          for (const inst of newState.currentAssembly.instances) {
            const prev = _prevById.get(inst.id)
            if (prev && sameInstanceTransform(prev, inst)) continue
            assemblyRenderer.setLiveTransform(inst.id, matrixFromInstance(inst))
            _anyMoved = true
          }
          assemblyJointRenderer.rebuild(newState.currentAssembly)
          // Cross-part linkers are world-space geometry DERIVED from the part
          // transforms (binding-domain complements + connector arcs + ds bridge),
          // not GPU-instanced — so the setLiveTransform fast path moves the parts
          // but leaves every linker stale. If a part moved and the assembly
          // carries linkers, refetch + redraw them so the binding domains and
          // arcs track the new poses. Covers the indirect-linker relax (a
          // transform-only change) AND any plain part move that drags a linker —
          // and rebuilds ALL linkers, so others sharing the moved parts update too.
          if (_anyMoved && ((newState.currentAssembly?.assembly_strands?.length ?? 0) > 0
                            || (newState.currentAssembly?.overhang_connections?.length ?? 0) > 0)) {
            assemblyRenderer.rebuildLinkers?.(newState.currentAssembly)
          }
          // Re-apply the group visibility overlay — a transform-only patch
          // could have changed a group's `visible` flag without touching any
          // instance's `visible`. Cheap O(N) walk; no-op when no group is hidden.
          assemblyRenderer.applyGroupVisibilityOverlay?.(computeGroupHiddenInstanceIds(newState.currentAssembly))
          if (newState.activeInstanceId) {
            assemblyRenderer.setActiveInstance(newState.activeInstanceId)
            const depths = computeFixedDepths(newState.currentAssembly)
            if (depths.has(newState.activeInstanceId)) _rebuildFixedLocks(newState.currentAssembly)
          }
        } else {
          // Reload while already in assembly mode: apply the cylinders default +
          // frame the camera, same as a fresh mode-enter.  Ordinary edits
          // (isLoad false) keep their representation and camera untouched.
          if (isLoad) _applyAssemblyLoadDefaults(newState.currentAssembly)
          _runAssemblyRebuild(newState.currentAssembly, {
            fitOnDone: isLoad,
            activeInstanceId: newState.activeInstanceId,
          })
        }
        // Persistent belt-path tubes (create/edit/delete change belt_paths).
        _rebuildBeltPaths()
        // Drive belt riders to their live pose for the current pulley angles
        // (covers discrete rotations — ring/gizmo/group commits + load). Skip
        // while a joint is actively RPM-spinning: the ticker owns riders then,
        // and running both (store angle vs the ticker's live _shadow) would make
        // the rider hitch. Mutually exclusive with the ticker's gated update.
        const _spinning = (newState.currentAssembly?.joints ?? []).some(
          j => j.joint_type === 'revolute' && j.angular_velocity_rpm && !j.spin_paused)
        if (!_spinning) {
          applyBeltRiders(
            newState.currentAssembly,
            (id, j) => j.current_value ?? 0,
            (iid, mat) => assemblyRenderer.setLiveTransform(iid, mat),
          )
        }
      }
      // Multi-select union box: refresh whenever the multi-select set, the
      // active group, OR the assembly changed (move/rotate of a member shifts
      // the union extent). Run inside RAF so the renderer's per-instance
      // Three.js groups have their fresh matrixWorld + bounding boxes.
      if (
        assemblyChanged ||
        newState.multiSelectedInstanceIds !== prevState.multiSelectedInstanceIds ||
        newState.activeGroupId !== prevState.activeGroupId
      ) {
        requestAnimationFrame(() => _assemblyMultiBox.update())
      }

      // PartGroup gizmo lifecycle. Attach on group-select; re-attach when
      // the assembly mutates while a group is still selected (centroid +
      // member start transforms need recapture). Detach when group is
      // cleared AND no single instance is selected.
      const groupChanged = newState.activeGroupId !== prevState.activeGroupId
      if (groupChanged) {
        if (newState.activeGroupId) {
          _attachGroupGizmoForGroup(newState.activeGroupId)
        } else if (!newState.activeInstanceId) {
          instanceGizmo.detach()
          _setMotionChip(null)
        }
      } else if (assemblyChanged && newState.activeGroupId) {
        // Group still selected, members may have moved — re-anchor.
        _attachGroupGizmoForGroup(newState.activeGroupId)
      }

      // Single-instance gizmo re-evaluation when the assembly changes around
      // an already-selected part. Without this, editing a mate (joint type,
      // axis, or even `fixed` on a partner) leaves the gizmo locked to the
      // DOF the analyzer computed at original attach time. Guard against
      // mid-drag (skip during a live drag — TransformControls state would be
      // torn down) and against pending uncommitted moves (re-attach would
      // snap the gizmo back to the last committed pose, hiding the user's
      // in-flight edit). The group path above already does the same.
      if (
        assemblyChanged &&
        !groupChanged &&
        newState.activeInstanceId &&
        !newState.activeGroupId &&
        !instanceGizmo.isDragging() &&
        !_hasAssemblyPending() &&
        constraintRelevantChanged(prevState.currentAssembly, newState.currentAssembly, newState.activeInstanceId)
      ) {
        _attachGroupGizmo(newState.activeInstanceId)
      }

      if (activeChanged) {
        // Clear cluster glow and sidebar selection whenever the active instance changes
        _selectedAssemblyCluster = null
        clusterGlowLayer.clear()
        clusterPanel?.selectAssemblyCluster?.(null, null)
        assemblyRenderer.setActiveInstance(newState.activeInstanceId)
        // Joint/connector indicators draw only for the selected part (scale fix).
        assemblyJointRenderer.setActiveInstance(newState.activeInstanceId)
        if (newState.activeInstanceId) {
          clusterPanel?.expandInstance?.(newState.activeInstanceId)
        }
        const newInst = newState.currentAssembly?.instances?.find(i => i.id === newState.activeInstanceId)
        if (newState.activeInstanceId && !newInst?.fixed) {
          _attachGroupGizmo(newState.activeInstanceId)
        } else if (!newState.activeGroupId) {
          // Guard: don't detach the group gizmo just because activeInstanceId
          // went null. The groupChanged branch above owns gizmo lifecycle
          // while a group is selected.
          instanceGizmo.detach()
          _setMotionChip(null)
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
  // The revolute-drag angle accumulator + gear/belt live-coupling engine + the
  // single-instance gizmo attach now live in scene/group_gizmo.js (initGroupGizmo,
  // created below once its deps are available).
  //
  // The transform engine — pending-transform Maps + transform-context builder +
  // live-apply + commit-queue (_assemblyPendingTransforms/_assemblyPendingPartJoints/
  // _effectiveInstanceMatrix/_createAssemblyTransformContext/_applyAssemblyPrimaryLive/
  // _queueAssemblyPrimaryCommit/_commitAssemblyPending/_hasAssemblyPending) — moved to
  // scene/assembly_transform.js (carve-up keystone), along with forward-kinematics
  // live propagation (_applyFKLive/_applyClusterMateFKLive). It's constructed above
  // (right after assemblyJointRenderer) so group_gizmo + the Move/Rotate shell can
  // take it as deps; the alias-consts there keep every call site below unchanged.

  // ── Camera-plane free drag (non-revolute parts) ──────────────────────────────
  let _assemblyPtrDownAt = null
  // Right-button-down position. OrbitControls pans on right-drag, but the
  // browser still fires `contextmenu` on release — track this so the context
  // menu / selection is suppressed when the right-click was actually a pan.
  let _assemblyRightDownAt = null
  // Free/part-joint drag state moved into scene/assembly_pointer.js (sub-part a).
  let _assemblySelectedPartJoint = null
  let _selectedAssemblyCluster   = null  // { instanceId, clusterId } | null

  // ── Assembly-mode lasso (Ctrl-drag → multi-select PartInstances) ────────────
  // Mirrors design-mode lasso (selection_manager.js: _createLassoOverlay /
  // _updateLassoOverlay / _finalizeLasso) so the gesture is identical: hold
  // Ctrl (or Meta on macOS) and drag a rectangle; instances whose projected
  // world-space center falls inside the rect on pointerup populate
  // multiSelectedInstanceIds. Ctrl-click without drag toggles the picked
  // instance in/out of the set (see _onAssemblyClick).
  // Assembly drag-rectangle multi-select — factory in scene/assembly_lasso.js
  // (pure hit-test core unit-tested). Deferred handlers, so the const is built
  // before any fires; assemblyRenderer via a lazy getter.
  const assemblyLasso = initAssemblyLasso({
    canvas, camera, controls,
    getInstanceCenters: () => assemblyRenderer.getInstanceCenters?.() ?? [],
    onSelect: (hits, additive) => {
      const next = additive
        ? Array.from(new Set([...(store.getState().multiSelectedInstanceIds ?? []), ...hits]))
        : hits
      store.setState({ multiSelectedInstanceIds: next, activeInstanceId: null, activeGroupId: null })
    },
    // Ctrl-click (no drag) → toggle the picked instance in/out of the multi-select.
    onClick: (e) => {
      const hit = assemblyRenderer.pickInstance(_canvasNdc(e), camera)
      if (!hit) return
      const s = store.getState()
      const next = toggleInstanceSelection(s.multiSelectedInstanceIds, s.activeInstanceId, hit.id)
      store.setState({ multiSelectedInstanceIds: next, activeInstanceId: null, activeGroupId: null })
    },
  })

  // ── PartGroup helpers (id walks; mirror backend/core/assembly_groups.py) ────

  // Motion-constraint analyzer (_analyzeMotionConstraints) + status chip
  // (_setMotionChip + the chip DOM element) moved to scene/assembly_transform.js
  // (carve-up keystone, commit c); reached via the alias-consts above.

  // Multi-select union BoxHelper lifted to scene/assembly_multi_box.js
  // (carve-up Tier 3). `_assemblyMultiBox` is initialized earlier (before the
  // 'assembly' store subscriber that drives it); call `.update()` to re-fit.

  // Assembly canvas pointer-down + free/part-joint drag handlers lifted to
  // scene/assembly_pointer.js (carve-up Tier 3, sub-part a). _onAssemblyPointerDown
  // is now _assemblyPointer.onAssemblyPointerDown (wired below at the factory
  // init); the drag move/up handlers + exit-cleanup live in the module.

  // Push the overhang-selection highlight rings to the renderer on change.
  store.subscribe((newState, prevState) => {
    if (newState.assemblyOverhangSelection === prevState.assemblyOverhangSelection) return
    assemblyRenderer.setOverhangSelectionHighlight?.(newState.assemblyOverhangSelection ?? [])
  })

  // Medium screen radius for hovering/clicking near an overhang's label anchor.
  // Overhang hover/pick — proximity-based (no exact-sprite raycast). Factory in
  // scene/overhang_hover_picker.js (pure nearest-anchor core is unit-tested).
  // All callers are deferred handlers, so this const is built before any fires;
  // assemblyRenderer is reached via lazy getters (not captured at construction).
  const overhangHoverPicker = initOverhangHoverPicker({
    camera, canvas,
    getAnchors:    () => assemblyRenderer.getOverhangAnchors?.(),
    setHovered:    (oh) => assemblyRenderer.setHoveredOverhang?.(oh),
    getToolActive: () => !!store.getState().toolFilters?.overhangLocations,
  })

  // Assembly canvas click (instance / cluster selection) lifted to
  // scene/assembly_pointer.js (carve-up Tier 3, sub-part b). The four pieces of
  // mutable state below are owned here (sibling handlers — pointer-down,
  // contextmenu, cluster-context — also touch them) and passed in as get/set
  // shims; clusterPanel is wired ~200 ln below so it comes in as a lazy getter.
  // `_toggleAssemblyOverhangSelection` (single-use) moved into the module.
  const _assemblyPointer = initAssemblyPointer({
    store, camera, canvas, controls, api,
    assemblyRenderer, assemblyJointRenderer, instanceGizmo,
    clusterGlowLayer, overhangHoverPicker,
    assemblyContextMenu, overhangLocations,
    attachPartToBelt:            _attachPartToBelt,
    getClusterPanel:             () => clusterPanel,
    canvasNdc:                   _canvasNdc,
    clusterBackboneEntries:      _clusterBackboneEntries,
    confirmTranslateRotateTool:  _confirmTranslateRotateTool,
    activateTranslateRotateTool: _activateTranslateRotateTool,
    hasAssemblyPending:          _hasAssemblyPending,
    commitAssemblyPending:       _commitAssemblyPending,
    showProgress:                _showProgress,
    hideProgress:                _hideProgress,
    applyFKLive:                 _applyFKLive,
    applyClusterMateFKLive:      _applyClusterMateFKLive,
    effectiveInstanceMatrix:     _effectiveInstanceMatrix,
    assemblyPendingPartJoints:   _assemblyPendingPartJoints,
    polymerizePanel,
    assemblyLasso,
    getAssemblyPtrDownAt:        () => _assemblyPtrDownAt,
    setAssemblyPtrDownAt:        (v) => { _assemblyPtrDownAt = v },
    getAssemblyRightDownAt:      () => _assemblyRightDownAt,
    setAssemblyRightDownAt:      (v) => { _assemblyRightDownAt = v },
    getTranslateRotateActive:    () => _translateRotateActive,
    getSelectedAssemblyCluster:  () => _selectedAssemblyCluster,
    setSelectedAssemblyCluster:  (v) => { _selectedAssemblyCluster = v },
    getAssemblySelectedPartJoint:() => _assemblySelectedPartJoint,
    setAssemblySelectedPartJoint:(v) => { _assemblySelectedPartJoint = v },
  })
  const _onAssemblyClick = _assemblyPointer.onAssemblyClick
  const _onAssemblyPointerDown = _assemblyPointer.onAssemblyPointerDown
  // Right-click context-menu router (linker Relax / belt attach / part menu)
  // lifted into scene/assembly_pointer.js (sub-part c). Registered as the
  // canvas `contextmenu` listener in the assembly-mode subscriber above.
  const _onAssemblyContextMenu = _assemblyPointer.onAssemblyContextMenu

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
    onClusterClick: async (clusterId, { additive = false } = {}) => {
      // Ctrl/Shift+click → multi-select, never the gizmo (which drives ONE cluster).
      // The toggle nulls `selectedObject`, which auto-closes an auto-opened Move/Rotate.
      if (additive) {
        selectionManager.toggleCluster(clusterId)
        return
      }
      if (!_translateRotateActive) {
        // Unify with the 3D cluster-filter click: same green glow + bead scale +
        // cluster selectedObject. The selectedObject→activeClusterId sync below
        // mirrors it onto activeClusterId, which lights this sidebar row. Re-click
        // toggles off. No gizmo, no API calls.
        selectionManager.selectCluster(clusterId)
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
        _mrSetPivotOptions(joints, clusterId)
      }
    },
    onJointRotate: (joint) => _rotateJoint(joint),
  })

  // Animate the assembly into a saved configuration — factory in
  // scene/assembly_config_animator.js (pure interpolation core unit-tested).
  // Deferred callback (fires only on a Feature Log "animate to configuration"
  // click), so the const is safe here even though its consumer is wired below.
  const _configAnimator = initAssemblyConfigAnimator({
    store, api, assemblyRenderer, assemblyJointRenderer,
    hasAssemblyPending: _hasAssemblyPending,
    commitAssemblyPending: _commitAssemblyPending,
  })
  const _animateAssemblyConfiguration = (cfg) => _configAnimator.animate(cfg)

  // ── Animation tab support panels ─────────────────────────────────────────────
  // (Assembly Configurations panel removed 2026-05-17 — now in Feature Log.)
  _partCameraPanel = initCameraPanel(store, { captureCurrentCamera, animateCameraTo, api })

  // ── Feature Log panel ────────────────────────────────────────────────────────
  _partFeatureLogPanel = initFeatureLogPanel(store, {
    api: {
      ...api,
      seekFeatures:         _seekFeaturesWithDelta,
      deleteFeature:        _deleteFeatureWithDelta,
      seekInstanceFeatures: _seekInstanceFeaturesFast,
    },
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
    const TABS = ['feature-log', 'dynamics', 'scene', 'photo', 'plates']
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
      // Special case: if the saved active tab was 'photo', fall back to
      // 'feature-log'. Photo mode is in-memory only and isn't auto-restored on
      // reload, so we don't want to leave the sidebar parked on the Photo tab
      // (which won't actually be in photo mode and just shows stale controls).
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
        if (saved) {
          if (TABS.includes(saved.activeTab) && saved.activeTab !== 'photo') {
            activeTab = saved.activeTab
          }
          if (typeof saved.collapsed === 'boolean') collapsed = saved.collapsed
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
        // Switching to any tab other than Photo leaves photo mode (the render
        // override is in-memory only and otherwise stays installed). Pass
        // skipTabRestore so the exit doesn't yank us back to feature-log — the
        // switch below lands us on the tab the user actually clicked.
        if (tabId !== 'photo') _photoMode.exit({ skipTabRestore: true })
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
        window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', {
          detail: { activeTab, collapsed },
        }))
        _persist()
      }

      // Make `tabId` the active tab WITHOUT the click-toggle semantics
      // (clicking the active tab collapses; this never collapses). Preserves
      // the user's collapsed/expanded preference. Used to default a freshly
      // loaded part to the Feature Log tab regardless of which tab was last
      // persisted.
      function selectTab(tabId) {
        if (!TABS.includes(tabId)) return
        if (activeTab === tabId) { _render(); return }
        const wasOnAnimations = !collapsed && activeTab === 'scene'
        activeTab = tabId
        if (wasOnAnimations) _leaveAnimationsTab()
        _render()
        window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', {
          detail: { activeTab, collapsed },
        }))
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
        selectTab,
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

  // ── Plates and tubes tab (96-well plate layout + IDT tube list) ──────────────
  {
    const canvasEl  = document.getElementById('plate-canvas')
    const wrapEl    = document.getElementById('plate-canvas-wrap')
    const toolbarEl = document.getElementById('plate-toolbar')
    const tubesEl   = document.getElementById('plate-tubes')
    const paneEl    = document.getElementById('tab-content-plates')
    if (canvasEl && wrapEl && paneEl) {
      const MOD_NAMES = {
        cy3: 'Cy3', cy5: 'Cy5', fam: 'FAM', tamra: 'TAMRA', bhq1: 'BHQ-1',
        bhq2: 'BHQ-2', atto488: 'ATTO488', atto550: 'ATTO550', biotin: 'Biotin',
      }

      // Strand length in nt (domain bp + loop/skip deltas) — mirrors the cadnano
      // spreadsheet's strandLength().

      const plateView = initPlateView(canvasEl, {
        wrapEl,
        toolbarEl,
        getTubesContainer: () => tubesEl,
        enableGroupMode: true,
        onSaveLayout: (layout) => { api.savePlateLayout(layout) },
        onStrandClick: (sid) => {
          // Select the strand: glows it in the 3D scene AND sets selectedObject,
          // which the spreadsheet highlights + autoscrolls to. Empty well clears.
          if (sid) selectionManager.selectStrand(sid)
          else store.setState({ selectedObject: null })
        },
      })

      // Build the normalized staple list from the current design + store colors.
      function _buildRecords() {
        const { currentDesign, currentGeometry, strandColors, strandGroups } = store.getState()
        const design = currentDesign
        if (!design) return { records: [], saved: null }
        const helixById = Object.fromEntries((design.helices ?? []).map(h => [h.id, h]))

        // Effective per-strand colors (hex ints): strandColors + group overrides.
        const eff = { ...(strandColors ?? {}) }
        for (const g of strandGroups ?? []) {
          if (g.color) {
            const hex = parseInt(g.color.replace('#', ''), 16)
            for (const sid of g.strandIds) eff[sid] = hex
          }
        }
        // Palette map = the SAME per-strand palette the 3D scene paints (staples
        // with no explicit colour). Compute it directly from geometry so it never
        // depends on the renderer being in a built state; fall back to the live
        // controller map, then to the index-based palette (matches the scene's
        // STAPLE_PALETTE[strand_index] formula).
        const strandIdxOf = new Map((design.strands ?? []).map((s, i) => [s.id, i]))
        const paletteMap = (currentGeometry && currentGeometry.length)
          ? buildStapleColorMap(currentGeometry, design)
          : (designRenderer.getHelixCtrl()?.getPaletteColors() ?? new Map())

        // group order (array index = display order) + group id
        const groupOf = new Map()
        ;(strandGroups ?? []).forEach((g, i) => {
          for (const sid of g.strandIds) if (!groupOf.has(sid)) groupOf.set(sid, { order: i, id: g.id })
        })

        // first modification per strand
        const modOf = new Map()
        for (const e of design.extensions ?? []) {
          if (e.modification && !modOf.has(e.strand_id)) modOf.set(e.strand_id, e.modification)
        }

        const records = []
        let stapleIdx = 0
        for (const s of design.strands ?? []) {
          if (s.strand_type !== 'staple' || s.is_reference) continue
          stapleIdx += 1
          // Resolve exactly as the scene's nucColor: override (strandColors +
          // groups) wins, else the palette slot. Never falls back to a flat grey
          // — every staple gets its scene colour.
          let color
          if (s.id in eff) {
            color = hexFromInt(eff[s.id])
          } else {
            const pm = paletteMap.get(s.id)
            color = (pm != null)
              ? hexFromInt(pm)
              : hexFromInt(PLATE_STAPLE_PALETTE[(strandIdxOf.get(s.id) ?? 0) % PLATE_STAPLE_PALETTE.length])
          }
          const grp = groupOf.get(s.id)
          const mod = modOf.get(s.id) || null
          records.push({
            strandId:   s.id,
            color,
            lengthNt:   strandLengthNt(s, helixById),
            groupId:    grp?.id ?? null,
            groupOrder: grp ? grp.order : Infinity,
            hasMod:     !!mod,
            modName:    mod ? (MOD_NAMES[mod] || mod) : null,
            sequence:   s.sequence || '',
            name:       `S${stapleIdx}`,
          })
        }
        return { records, saved: design.plate_layout ?? null }
      }

      // Refresh only when the inputs that affect the plate change — NOT when only
      // plate_layout changes (our own saves), which would reset the view.
      let _lastSig = null
      function _inputsSig(design, strandColors, strandGroups) {
        if (!design) return 'null'
        const strands = (design.strands ?? [])
          .filter(s => s.strand_type === 'staple' && !s.is_reference)
          .map(s => `${s.id}:${s.color || ''}:${s.domains?.length ?? 0}`)
        const exts = (design.extensions ?? []).map(e => `${e.strand_id}:${e.modification || ''}`)
        return JSON.stringify([design.id, strands, exts,
          strandGroups, Object.entries(strandColors ?? {})])
      }
      function _refresh() {
        const { records, saved } = _buildRecords()
        plateView.setData(records, saved)
      }

      // Refresh + re-fit the plates whenever the tab becomes visible.
      const _vis = new MutationObserver(() => {
        if (paneEl.hasAttribute('hidden')) return
        _lastSig = _inputsSig(...(() => { const s = store.getState(); return [s.currentDesign, s.strandColors, s.strandGroups] })())
        _refresh()
        plateView.resetView()
      })
      _vis.observe(paneEl, { attributes: true, attributeFilter: ['hidden'] })

      // Refresh on relevant design/color/group changes while the pane is visible.
      store.subscribe((s) => {
        if (paneEl.hasAttribute('hidden')) return
        const sig = _inputsSig(s.currentDesign, s.strandColors, s.strandGroups)
        if (sig === _lastSig) return
        _lastSig = sig
        _refresh()
      })
    }
  }

  // ── Sidebar resize handles ───────────────────────────────────────────────────
  initSidebarResize()

  // ── Scene inspector (debug overlay) ──────────────────────────────────────────
  // Ctrl+Shift+I to toggle. Click any 3D object → console table + toast with
  // its name / type / material / ancestor chain. Use to identify mystery
  // gizmos, helper lines, or stale debug overlays.
  initSceneInspector({ scene, camera, canvas })

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
    // Enter feature-log "pick" mode and resolve with the selected feature
    // index (or null if the user cancelled). The animation panel's "Pin to
    // feature" button uses this to replace the flat <select> picker that
    // didn't scale past ~20 entries.
    pinToFeature: () => new Promise((resolve) => {
      const fl = _partFeatureLogPanel
      if (!fl?.enterPickMode) { resolve(null); return }
      window.__leftSidebar?.setActiveTab?.('feature-log')
      fl.enterPickMode((idx) => {
        // Switch back to the Scene tab so the user lands back on the
        // animation panel they were editing.
        window.__leftSidebar?.setActiveTab?.('scene')
        resolve(idx)
      })
    }),
    // Used by trajectory keyframes to filter oxDNA jobs to the active design.
    getWorkspacePath: () => _workspacePath,
  })

  // ── Photo mode + export representation → scene/photo_mode.js (#70) ───────────
  photoRenderer = createPhotoRenderer(sceneCtx)
  // The photo-mode pane + the export-only rep upgrade (every instance temporarily
  // set to the assembly's export_representation at full geometric detail for the
  // duration of a PNG/video render, then restored). `_photoMode.getExportRepActive()`
  // gates the save path below so that temporary upgrade never hits disk. Created
  // here — before `initFileSave`, which reads getExportRepActive. The lifecycle
  // spine calls `_photoMode.exit()` (forward-refs this closure const; only invoked
  // post-init, on file close/new/open / assembly-enter).
  const _photoMode = initPhotoMode({
    store, api, sceneCtx, photoRenderer, assemblyRenderer, designRenderer,
    bluntEnds, assemblyJointRenderer, viewCube, player: animPlayer, originAxes,
  })

  // Save/Save-As dispatch factory (ui/file_io.js initFileSave, extraction #60).
  // Placed here — not at the menu listeners (~3924) — because its deps span the
  // file: `_fileIo`/`_syncBadge`/`_lifecycleSync` (~7200-7240) AND `_photoMode`
  // (just above, for getExportRepActive). Initializing after the last dep means every value is concrete at
  // init time; the only forward references (`_fileSave` in the menu listeners +
  // keyboard-shortcuts injection, both textually above) resolve via lazy arrows
  // because they fire only on user action (post-init). `selfSavedPaths` flows in by
  // reference so the 5s self-save suppression shares the autosave subscribers' Set.
  _fileSave = initFileSave({
    store, api,
    fileIo:    _fileIo,
    syncBadge: _syncBadge,
    getWorkspacePath:          () => _workspacePath,
    getFileHandle:             () => _fileHandle,
    getAssemblyWorkspacePath:  () => _assemblyWorkspacePath,
    getAssemblyFileHandle:     () => _assemblyFileHandle,
    getExportRepActive:        _photoMode.getExportRepActive,
    setAssemblyWorkspacePath:  _setAssemblyWorkspacePath,
    selfSavedPaths:            _lifecycleSync.selfSavedPaths,
  })

  // Populate transform fields and pivot options when the active cluster changes.
  store.subscribe((newState, prevState) => {
    if (newState.activeClusterId === prevState.activeClusterId) return
    if (!newState.activeClusterId || !newState.translateRotateActive) return
    const cluster = newState.currentDesign?.cluster_transforms?.find(c => c.id === newState.activeClusterId)
    if (!cluster) return
    // Read from the gizmo's pending (pivot-rebased) transform when present so the number
    // boxes match the pivot the gizmo actually uses; a +45/reset/typed commit then keeps
    // position = pivot + field-translation instead of teleporting (duplex pivot bug).
    const _pend = clusterGizmo.getPendingTransform(newState.activeClusterId)
    const _t = _pend?.translation ?? cluster.translation
    const _r = _pend?.rotation ?? cluster.rotation
    const [rx, ry, rz] = quatToEulerDeg(_r)
    _mrSetTransformValues(_t[0], _t[1], _t[2], rx, ry, rz)
    const joints = newState.currentDesign?.cluster_joints?.filter(j => j.cluster_id === newState.activeClusterId) ?? []
    _mrSetPivotOptions(joints, newState.activeClusterId)
    _mrSetSelectedPivot('centroid')
    _mrSyncClusterDropdown(newState.activeClusterId)
    clusterGizmo.setConstraint('centroid', null)
  })

  // Selection→tool bridge: selecting a cluster (3D cluster-filter click OR Movable
  // Clusters sidebar row — both surface as a `selectedObject` of type 'cluster') auto-opens
  // Move/Rotate on it; re-targets it to a different cluster; and auto-closes (auto-committing)
  // when the cluster is deselected. Parts-editor only; sticky for manually-opened tools.
  // Logic + guards live in translate_rotate_tool.js; this is thin wiring.
  store.subscribe((newState, prevState) => { _translateRotateTool.handleSelectionChange(newState, prevState) })

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

  // Unify sidebar + 3D cluster selection into ONE state. selection_manager sets a
  // cluster `selectedObject` (from either the 3D cluster-filter click or the
  // sidebar row via selectCluster) with the green glow + bead scale; here we mirror
  // it onto `activeClusterId` so the sidebar "Movable clusters" row highlights too.
  // Non-tool only — the Move/Rotate tool owns activeClusterId via the gizmo.
  store.subscribe((newState, prevState) => {
    if (newState.translateRotateActive) return
    if (newState.selectedObject === prevState.selectedObject) return
    const cid = newState.selectedObject?.type === 'cluster'
      ? newState.selectedObject.data?.cluster_id ?? null
      : null
    if (newState.activeClusterId !== cid) store.setState({ activeClusterId: cid })
  })

  // Move/Rotate tool: the blue clusterGlowLayer marks the gizmo's active cluster.
  // (Plain design-mode cluster SELECTION now glows green via selection_manager —
  // see the selectedObject→activeClusterId sync above — so this layer is reserved
  // for the tool to avoid a double halo.) Re-applies after geometry rebuilds.
  store.subscribe((newState, prevState) => {
    if (!newState.translateRotateActive) {
      if (prevState.translateRotateActive) clusterGlowLayer.clear()
      return
    }
    const activeId = newState.activeClusterId
    if (!activeId) {
      if (prevState.activeClusterId) clusterGlowLayer.clear()
      return
    }
    // Update when active cluster changes, geometry rebuilds, or the tool just turned on.
    if (activeId === prevState.activeClusterId &&
        newState.currentGeometry === prevState.currentGeometry &&
        prevState.translateRotateActive) return
    const cluster = newState.currentDesign?.cluster_transforms?.find(c => c.id === activeId)
    if (!cluster) { clusterGlowLayer.clear(); return }
    const entries = _clusterBackboneEntries(cluster, newState.currentDesign)
    clusterGlowLayer.setEntries(entries)
  })

  const { runScript } = createScriptRunner({
    slicePlane, bluntEnds, camera, controls,
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
      showToast(`Script failed: ${err.message}`, { severity: 'error' })
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
  // Extracted to ui/strand_length_histogram.js (factory + pure computeStrandLengthBins).
  initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand: _centerOnStrand })


  // ── Import menu (File → Import + library-panel import callbacks) ───────────────
  _importMenu = initImportMenu({
    store, api, libraryPanel,
    resetForNewDesign: _resetForNewDesign,
    showWelcome: _showWelcome,
    hideWelcome: _hideWelcome,
    renderRecentMenu: _renderRecentMenu,
    setWorkspacePath: _setWorkspacePath,
    setFileName: _setFileName,
    setSyncStatus: _syncBadge.setSyncStatus,
    saveAs: _fileIo.saveAs,
    setFileHandle: (v) => { _fileHandle = v },
  })

  // ── Attach Protein to Overhang ─────────────────────────────────────────────────
  document.getElementById('menu-file-attach-protein')?.addEventListener('click', () => {
    openProteinAttachModal({ store, api, onChanged: _refreshProteins })
  })

  // ── Export menu (File → Export submenu) ──────────────────────────────────────
  initExportMenu({ store, api })

  // ── Representation option sliders → ui/repr_option_sliders.js ─────────────────
  // Owns the four tuning sliders + the per-repr row-visibility (`updateForRepr`,
  // aliased so _setRepresentation's call site stays verbatim). The alias-const
  // resolves before any deferred caller fires (_setRepresentation only runs from
  // post-boot handlers / the lifecycle spine), so no lazy-let is needed.
  const _reprOptionSlidersCtrl = initReprOptionSliders({
    store,
    designRenderer,
    getJointRenderer: () => jointRenderer,
    getLodMode: () => _lodMode,
    setAtomisticSlidersVisible: _setAtomisticSlidersVisible,
    setSurfacePanelVisible: _setSurfacePanelVisible,
  })
  const _reprOptionSliders = _reprOptionSlidersCtrl.updateForRepr

  // ── Coloring array in Representation Options → ui/coloring_options_panel.js ────
  // The full coloring grid in the sidebar: enabled modes clickable, unsupported
  // ones grayed. Driven on repr change via the switcher's availability hub
  // (updateColoringOptions, called from _updateColoringMenuAvailability) and
  // self-syncs its active highlight off store.coloringMode. Inits BEFORE the
  // switcher so the initial 'full' availability call can reach it.
  const _coloringOptionsPanel = initColoringOptionsPanel({
    store,
    onSelect: _setColoringMode,
  })

  // ── Unified representation switcher → ui/representation_switcher.js ────────────
  // Owns the seven-representation radio, the Coloring-menu availability matrix,
  // the F1…F7 hotkeys, and `_setRepresentation`. Inits AFTER `_reprOptionSliders`
  // (its tail drives the sliders). The three aliased fns are referenced by
  // deferred callers ABOVE this point (reset @_resetForNewDesign, hull-auto
  // subscriber, assembly-load defaults, assembly-rebuild settle) — TDZ-safe
  // because none fire during boot before this init (proven: `_setRepresentation`
  // already internally calls the `_reprOptionSliders` const declared just above,
  // so a boot-time call would already have thrown). `_currentRepr`/`_lodMode`/
  // `_lastDetailLevel` stay main `let`s (read by the render-loop LOD tick +
  // hull-auto) and are reached via the get/set shims below.
  const _reprSwitcher = initRepresentationSwitcher({
    store,
    api,
    atomisticRenderer,
    designRenderer,
    flexibleArcs,
    overhangLinkArcs,
    unfoldView,
    getJointRenderer: () => jointRenderer,
    getSurfaceMode: () => _atomSurface.getSurfaceMode(),
    applySurfaceMode: _applySurfaceMode,
    applyAtomisticMode: _applyAtomisticMode,
    setCGVisible: _setCGVisible,
    setColoringMode: _setColoringMode,
    reprOptionSliders: _reprOptionSliders,
    updateColoringOptions: _coloringOptionsPanel.updateForRepr,
    getLastDetailLevel: () => _lastDetailLevel,
    setLastDetailLevel: (v) => { _lastDetailLevel = v },
    setLodMode: (v) => { _lodMode = v },
    setCurrentRepr: (v) => { _currentRepr = v },
  })
  const _setRepresentation    = _reprSwitcher.setRepresentation
  const _updateReprRadio      = _reprSwitcher.updateReprRadio
  const _syncAssemblyReprMenu = _reprSwitcher.syncAssemblyReprMenu

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

  // ── Reference geometry show/hide (translucent backdrop strands) ───────────────
  // The cadnano-editor window has its own independent toggle (separate store).
  document.getElementById('menu-view-reference')?.addEventListener('click', () => {
    const show = store.getState().showReferenceGeometry !== false  // default shown
    store.setState({ showReferenceGeometry: !show })
    _setMenuToggle('menu-view-reference', !show)  // pill ON when reference is shown
  })
  store.subscribe((newState, prevState) => {
    if (newState.showReferenceGeometry !== prevState.showReferenceGeometry) {
      _setMenuToggle('menu-view-reference', newState.showReferenceGeometry !== false)
    }
  })

  document.getElementById('menu-view-overhang-names')?.addEventListener('click', () => {
    const { showOverhangNames } = store.getState()
    store.setState({ showOverhangNames: !showOverhangNames })
    _setMenuToggle('menu-view-overhang-names', !showOverhangNames)
  })

  // End-to-End Crossovers: show/hide the long periodic-boundary seam connectors
  // (default hidden). The unfold_view + assembly_renderer subscribe directly.
  document.getElementById('menu-view-periodic-seam-arcs')?.addEventListener('click', () => {
    const show = store.getState().showPeriodicSeamArcs === true
    store.setState({ showPeriodicSeamArcs: !show })
    _setMenuToggle('menu-view-periodic-seam-arcs', !show)
  })
  store.subscribe((newState, prevState) => {
    if (newState.showPeriodicSeamArcs !== prevState.showPeriodicSeamArcs) {
      _setMenuToggle('menu-view-periodic-seam-arcs', newState.showPeriodicSeamArcs === true)
    }
  })

  // ── Highlight Undefined Bases toggle → scene/undefined_highlight.js ──────────
  // Owns the on/off flag, the View-menu button, and the design-change re-highlight
  // subscriber. The shared flag is reached from the View-tool-buttons vt-btn (#41)
  // and the scaffold-assign modal (#56) via lazy dep arrows wired at their factory
  // inits above (isOn/setOn/refresh) — TDZ-safe since those fire only on user action.
  // Subscriber registers HERE (original spot) to preserve store-subscription order.
  const _undefinedHighlight = initUndefinedHighlight({
    store, designRenderer, setMenuToggle: _setMenuToggle,
  })

  // ── Fluorescence + FRET Checker ──────────────────────────────────────────────
  const fretChecker = initFretChecker({ designRenderer, store, setMenuToggle: _setMenuToggle })

  document.getElementById('menu-view-joints')?.addEventListener('click', () => {
    const on = !jointRenderer?.isVisible()
    jointRenderer?.setVisible(on)
    _setMenuToggle('menu-view-joints', on)
  })

  // ── Help / Hotkeys modal ─────────────────────────────────────────────────────
  const helpModal = document.getElementById('help-modal')
  document.getElementById('menu-help-hotkeys')?.addEventListener('click', () => helpModal.classList.add('visible'))
  document.getElementById('menu-help-strand-anim')?.addEventListener('click',
    () => window.open('/strand-anim.html', 'nadoc-strand-anim'))
  document.getElementById('help-modal-close')?.addEventListener('click', () => helpModal.classList.remove('visible'))
  helpModal?.addEventListener('click', e => { if (e.target === helpModal) helpModal.classList.remove('visible') })

  document.getElementById('menu-help-fjc-sim')?.addEventListener('click', async () => {
    // Lazy-load the modal so the dev bundle stays slim until the user opens it.
    const { showLinkerConfigModal } = await import('./ui/linker_config_modal.js')
    showLinkerConfigModal({ readOnly: true })
  })

  document.getElementById('menu-help-about-file')?.addEventListener('click', async () => {
    const { showAboutFileModal } = await import('./ui/about_file_modal.js')
    showAboutFileModal({ api, path: _workspacePath })
  })

  // MD Engines: Help-menu install/status panel + sidebar install gates.
  const mdEngines = initMdEngines({ api })
  mdEngines.mountSidebarGates()
  mdEngines.refresh()
  document.getElementById('menu-help-md-engines')?.addEventListener('click', () => mdEngines.showStatusModal())

  initCreateSeam({ store, api })

  // ── Debug > Show LOD HUD ────────────────────────────────────────────────────
  // Toggles the on-canvas LOD overlay (per-source bucket counts + pixel-size
  // range + thresholds).  The HUD itself is created/dismissed by
  // `__NADOC_DBG__.toggleLodHud()` — exposed only when the shared assembly
  // renderer is active (`localStorage.NADOC_SHARED_RENDERER = 'true'`).
  document.getElementById('menu-debug-lod-hud')?.addEventListener('click', function () {
    if (!window.__NADOC_DBG__?.toggleLodHud) {
      showToast(
        'Shared renderer not active — set localStorage.NADOC_SHARED_RENDERER = "true" then reload.',
        { severity: 'warn' },
      )
      return
    }
    window.__NADOC_DBG__.toggleLodHud()
    const isOn = !!window.__NADOC_LOD_HUD__
    this.textContent = isOn ? 'Hide LOD HUD' : 'Show LOD HUD'
  })

  // ── Debug > Hull Cluster Debug ────────────────────────────────────────────────
  // Colors each hull-prism cluster distinctly, labels it with its dsDNA bp
  // size-% of the whole origami, and shows clusters below the size threshold
  // faintly — so the exclusion threshold can be tuned visually. Only meaningful
  // in the Hull Prism representation (View → Representation → Hull Prism).
  let _hullClusterDebugOn = false
  document.getElementById('menu-debug-hull-cluster')?.addEventListener('click', function () {
    _hullClusterDebugOn = !!jointRenderer?.setHullClusterDebug(!_hullClusterDebugOn)
    this.textContent = _hullClusterDebugOn ? 'Hide Hull Cluster Debug' : 'Show Hull Cluster Debug'
    if (_hullClusterDebugOn) {
      showToast('Hull Cluster Debug on — visible in the Hull Prism representation (View → Representation).',
        { severity: 'info' })
    }
  })

  // ── Debug > Render diagnostics (wireframe / double-side / opaque / inspect / camera) ──
  // Classifiers for "weird mesh" artifacts, applied to every material under the
  // design root (originals saved in material.userData._dbgOrig, restored when the
  // flag clears). Re-toggle after a full geometry rebuild (rep switch keeps meshes).
  //   Wireframe   → reveals geometry (open ends, stray caps, degenerate faces).
  //   Double-Side → if missing parts reappear, it was back-face culling.
  //   Opaque      → if it snaps right, it was transparent depth-sort (transparent@opacity1).
  let _dbgWire = false, _dbgDouble = false, _dbgOpaque = false
  function _applyRenderDebug() {
    const root = designRenderer.getHelixCtrl()?.root
    if (!root) { showToast('No design geometry to debug.', { severity: 'error' }); return }
    root.traverse(o => {
      const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : []
      for (const m of mats) {
        if (m.userData._dbgOrig === undefined)
          m.userData._dbgOrig = { wireframe: m.wireframe, side: m.side, transparent: m.transparent }
        const orig = m.userData._dbgOrig
        m.wireframe   = _dbgWire   ? true             : orig.wireframe
        m.side        = _dbgDouble ? THREE.DoubleSide : orig.side
        m.transparent = _dbgOpaque ? false            : orig.transparent
        m.needsUpdate = true
      }
    })
  }
  document.getElementById('menu-debug-wireframe')?.addEventListener('click', () => {
    _dbgWire = !_dbgWire; _setMenuToggle('menu-debug-wireframe', _dbgWire); _applyRenderDebug()
  })
  document.getElementById('menu-debug-doubleside')?.addEventListener('click', () => {
    _dbgDouble = !_dbgDouble; _setMenuToggle('menu-debug-doubleside', _dbgDouble); _applyRenderDebug()
  })
  document.getElementById('menu-debug-opaque')?.addEventListener('click', () => {
    _dbgOpaque = !_dbgOpaque; _setMenuToggle('menu-debug-opaque', _dbgOpaque); _applyRenderDebug()
  })
  document.getElementById('menu-debug-copy-camera')?.addEventListener('click', () => {
    const p = camera.position, t = controls.target
    const txt = `${p.x.toFixed(3)},${p.y.toFixed(3)},${p.z.toFixed(3)},${t.x.toFixed(3)},${t.y.toFixed(3)},${t.z.toFixed(3)}`
    navigator.clipboard?.writeText(txt).catch(() => {})
    showToast('Camera copied (pos.xyz,target.xyz): ' + txt, { duration: 7000 })
  })

  // Inspect Mesh: when on, a canvas click reports the hit mesh's material/geometry
  // props (toast + console.table) — removes ambiguity about what's being rendered.
  let _dbgInspect = false
  const _dbgRay = new THREE.Raycaster()
  const _dbgNdc = new THREE.Vector2()
  const _DBG_SIDE = { 0: 'FrontSide', 1: 'BackSide', 2: 'DoubleSide' }
  document.getElementById('menu-debug-inspect')?.addEventListener('click', () => {
    _dbgInspect = !_dbgInspect; _setMenuToggle('menu-debug-inspect', _dbgInspect)
    showToast(_dbgInspect ? 'Inspect Mesh ON — click a mesh to report it (console.table for full props).' : 'Inspect Mesh off')
  })
  canvas.addEventListener('click', (e) => {
    if (!_dbgInspect) return
    const root = designRenderer.getHelixCtrl()?.root
    if (!root) return
    const r = canvas.getBoundingClientRect()
    _dbgNdc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    _dbgRay.setFromCamera(_dbgNdc, camera)
    const hit = _dbgRay.intersectObject(root, true).find(h => h.object.visible)
    if (!hit) { showToast('Inspect: nothing under cursor'); return }
    const o = hit.object, m = Array.isArray(o.material) ? o.material[0] : o.material
    const info = {
      name: o.name || '(unnamed)', objType: o.type,
      instanced: !!o.isInstancedMesh, count: o.isInstancedMesh ? o.count : undefined,
      geometry: o.geometry?.type, indexed: !!o.geometry?.index, vertices: o.geometry?.attributes?.position?.count,
      material: m?.type, side: _DBG_SIDE[m?.side], transparent: m?.transparent, opacity: m?.opacity,
      depthWrite: m?.depthWrite, wireframe: m?.wireframe, frustumCulled: o.frustumCulled,
    }
    console.table(info)
    showToast(`${info.name} · ${info.geometry} · ${info.material} · ${info.side} · transp=${info.transparent} op=${info.opacity} · fc=${info.frustumCulled}`, { duration: 9000 })
  })

  // ── Debug > MrDNA Round-Trip Test ────────────────────────────────────────────
  document.getElementById('menu-debug-mrdna-roundtrip')?.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }

    const btn = document.getElementById('menu-debug-mrdna-roundtrip')
    const origText = btn.textContent
    btn.textContent = 'Running… (may take ~10 s)'
    btn.disabled = true

    try {
      const r = await fetch('/api/design/debug/mrdna-roundtrip', { headers: docHeaders() })
      if (!r.ok) {
        const msg = await r.text()
        showToast(`Round-trip test failed:\n${msg}`, { severity: 'error' })
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
      showToast(`Round-trip test error: ${err.message}`, { severity: 'error' })
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

  let _lastTickPerf = performance.now()
  ;(function tick() {
    const _nowPerf = performance.now()
    const _dt      = (_nowPerf - _lastTickPerf) / 1000
    _lastTickPerf  = _nowPerf

    // Per-frame integrator for continuous-spin revolute joints.
    if (store.getState().assemblyActive) {
      kinematicsTicker.tick(_dt)
    }

    updateDistLabel()
    sequenceOverlay.orientToCamera(camera)

    // Live FRET re-check — runs every frame so translate/rotate moves update glow instantly.
    fretChecker.refreshIfFret()

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
        unfoldView.refreshArcVisibility()
      }
    }

    requestAnimationFrame(tick)
  })()

  // ── Test helpers (dev only — used by Playwright e2e tests) ───────────────
  if (import.meta.env.DEV) {
    window.__nadocTest = {
      scene,
      /** Camera-pose count of the loaded design (build-primitives readiness check). */
      getDesignCameraPoseCount: () => (store.getState().currentDesign?.camera_poses?.length ?? 0),
      /** Render the loaded design through its saved poses → {gifBase64, posterDataUrl}.
       *  Used by the offline build-primitives pipeline; see scene/primitive_preview_capture.js. */
      capturePrimitivePreview: async (opts = {}) => {
        const { capturePosesGif } = await import('./scene/primitive_preview_capture.js')
        const poses = store.getState().currentDesign?.camera_poses ?? []
        return capturePosesGif({ renderer, scene, camera, controls, poses, ...opts })
      },
      getAtomisticRenderer: () => atomisticRenderer,
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
      /** Screen {x,y} centres of up to `maxN` visible, on-screen backbone beads.
       *  Reusable primitive for gesture e2e tests (e.g. measurement_tool.spec.js). */
      getBackboneBeadScreenPositions(maxN = 12) {
        const rect = canvas.getBoundingClientRect()
        let mesh = null
        scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.visible && o.count > 0) mesh = o })
        if (!mesh) return []
        const m = new THREE.Matrix4(), v = new THREE.Vector3()
        const out = []
        const n = Math.min(maxN, mesh.count)
        for (let i = 0; i < n; i++) {
          mesh.getMatrixAt(i, m)
          v.setFromMatrixPosition(m).applyMatrix4(mesh.matrixWorld)
          const ndc = v.clone().project(camera)
          if (ndc.z > 1 || Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) continue  // behind camera / off-screen
          out.push({
            x: rect.left + (ndc.x  *  0.5 + 0.5) * rect.width,
            y: rect.top  + (-ndc.y * 0.5 + 0.5) * rect.height,
          })
        }
        return out
      },
      /** Screen {x,y} + strand-end identity of every visible 5′/3′ terminus bead.
       *  Gesture e2e for the End-level multi-select → forced-ligation ('x') flow:
       *  lets a spec pick a valid opposite-polarity pair on different strands and
       *  click each end deterministically. */
      getEndBeadScreenPositions() {
        const rect = canvas.getBoundingClientRect()
        const out = []
        const v = new THREE.Vector3(), m = new THREE.Matrix4()
        for (const e of designRenderer.getBackboneEntries?.() ?? []) {
          const nuc = e.nuc
          if (!nuc?.strand_id) continue
          if (!nuc.is_five_prime && !nuc.is_three_prime) continue
          if (!e.instMesh?.visible) continue
          e.instMesh.getMatrixAt(e.id, m)
          v.setFromMatrixPosition(m).applyMatrix4(e.instMesh.matrixWorld)
          const ndc = v.clone().project(camera)
          if (ndc.z > 1 || Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) continue
          out.push({
            x: rect.left + (ndc.x  *  0.5 + 0.5) * rect.width,
            y: rect.top  + (-ndc.y * 0.5 + 0.5) * rect.height,
            strand_id: nuc.strand_id,
            helix_id:  nuc.helix_id,
            bp_index:  nuc.bp_index,
            direction: nuc.direction,
            is_five_prime:  !!nuc.is_five_prime,
            is_three_prime: !!nuc.is_three_prime,
          })
        }
        return out
      },
      /** Screen {x,y} + identity of each visible blunt-end ring (gesture e2e for
       *  blunt-end / primitive-on-face flows). */
      getDomainEndScreenPositions: () =>
        bluntEnds.getEndScreenInfo?.(camera, canvas.getBoundingClientRect()) ?? [],
      /** Slice-plane mode snapshot (visible / placement / continuation). */
      getSliceState: () => ({
        visible: slicePlane.isVisible(),
        placement: slicePlane.isPlacement(),
        armed: slicePlane.isArmed(),
        continuation: slicePlane.isContinuation(),
        deformed: slicePlane.isDeformed(),
      }),
      /** Count of Alt-picked measurement beads (the measurement tool's input). */
      getCtrlBeadCount: () => selectionManager.getCtrlBeads?.().length ?? 0,
      /** Current single-selection ({type,id,...}) or null. */
      getSelectedObject: () => store.getState().selectedObject ?? null,
      /** Multi-selection pools (cluster multi-select gesture e2e). */
      getMultiSelection: () => ({
        clusterIds: store.getState().multiSelectedClusterIds ?? [],
        strandIds:  store.getState().multiSelectedStrandIds ?? [],
      }),
      /** Drill-v2 engaged selection level ('default'|'cluster'|'strand'|'domain'|'end'|'xover'). */
      getSelectionLevel: () => selectionManager.getSelectionLevel?.() ?? 'default',

      // ── Robust gesture harness (MapGrab-style controller) ──────────────────
      // pickBeadAt runs the REAL raycast (same camera + bead meshes the selection
      // manager uses) against client (viewport) coords, returning the frontmost
      // bead hit or null. This is occlusion-correct — it answers "what would a
      // click here actually hit?" — unlike projecting a point and hoping.
      pickBeadAt(clientX, clientY) {
        const rect = canvas.getBoundingClientRect()
        const ndc = new THREE.Vector2(
          ((clientX - rect.left) / rect.width) * 2 - 1,
          -((clientY - rect.top) / rect.height) * 2 + 1,
        )
        const ray = new THREE.Raycaster()
        ray.setFromCamera(ndc, camera)
        const entries = designRenderer.getBackboneEntries?.() ?? []
        const meshes = [...new Set(entries.map(e => e.instMesh))].filter(m => m && m.visible)
        if (!meshes.length) return null
        const hits = ray.intersectObjects(meshes)
        if (!hits.length) return null
        const hit = hits[0]
        const entry = entries.find(e => e.instMesh === hit.object && e.id === hit.instanceId)
        if (!entry) return null
        return {
          instanceId: hit.instanceId,
          strand_id: entry.nuc?.strand_id, helix_id: entry.nuc?.helix_id,
          bp_index: entry.nuc?.bp_index, direction: entry.nuc?.direction,
        }
      },

      // ── Assembly gesture harness (mirrors the design-view hooks above) ─────
      // Used by e2e/helpers/scene_harness.js to validate the assembly canvas
      // pointer handlers (_onAssemblyPointerDown / _onAssemblyClick) — part
      // selection, group click-through, joint pick. Dev-only, never shipped.

      /** Occlusion-correct "which instance is front-most at this client point?" — the
       *  REAL pick (same NDC + camera the click handler uses). null if nothing hit.
       *  This is the identity oracle the gesture harness scans + clicks through. */
      pickAssemblyInstanceAt(clientX, clientY) {
        const ndc = clientToNdc(clientX, clientY, canvas.getBoundingClientRect())
        const hit = assemblyRenderer.pickInstance?.(ndc, camera)
        return hit ? { id: hit.id } : null
      },
      /** Selection-state oracles the retry loops assert against. */
      getActiveInstanceId: () => store.getState().activeInstanceId ?? null,
      getMultiSelectedInstanceIds: () => store.getState().multiSelectedInstanceIds ?? [],
      getActiveGroupId:    () => store.getState().activeGroupId ?? null,
      isAssemblyActive:    () => !!store.getState().assemblyActive,
      /** Arm the part-joint cluster drag (Priority 2b in _onAssemblyPointerDown):
       *  set the selected cluster so a subsequent pointer-down on the instance
       *  starts a cluster rotation. This is the gesture's selection PREREQUISITE
       *  (normally a cluster re-click / panel select); the ring DRAG itself stays
       *  the real gesture under test. */
      selectAssemblyClusterForTest(instanceId, clusterId) {
        _selectedAssemblyCluster = { instanceId, clusterId }
      },
      /** Pending (uncommitted) part-joint rotations recorded by _onAssemblyDragUp.
       *  The observable for the part-joint drag gesture: each entry's joint_value
       *  is the rotated angle. */
      getAssemblyPendingPartJoints() {
        return [..._assemblyPendingPartJoints.entries()].map(([key, v]) => ({
          key, jointValue: v?.body?.joint_value ?? null,
        }))
      },
      /** Pending (uncommitted) PRIMARY instance transforms recorded by the
       *  Move/Rotate tool — both the panel-input path (_mrCommitInputs →
       *  _queueAssemblyPrimaryCommit) and the gizmo onCommit callback feed the
       *  same `_assemblyPendingTransforms` map. The observable the move-tool
       *  gate asserts against: one entry per moved instance, with the matrix's
       *  translation column so a test can check the move actually landed.
       *  Distinct from getAssemblyPendingPartJoints (which is joint rotation). */
      getAssemblyPendingTransforms() {
        return [..._assemblyPendingTransforms.entries()].map(([instanceId, mat]) => ({
          instanceId,
          translation: mat ? [mat.elements[12], mat.elements[13], mat.elements[14]] : null,
        }))
      },
      /** Activate the assembly Move/Rotate tool on the currently-active instance
       *  (the real entry point — same fn the right-click "Move/Rotate" menu item
       *  and the toolbar button call). Requires an instance already selected.
       *  Returns the resulting translateRotateActive flag so the gate can assert
       *  the tool armed. Async — the gizmo attach awaits a pivot refresh. */
      async activateAssemblyMoveTool() {
        await _activateTranslateRotateTool()
        return !!store.getState().translateRotateActive
      },
      /** Activate the DESIGN-mode Move/Rotate tool on a specific cluster (the real
       *  entry point — same fn the Rotate button / cluster-row click call, with the
       *  cluster pre-targeted). Returns the pivot-select's option values so a gate
       *  can assert the duplex root options appear. Used by the duplex rotation-point
       *  e2e (pivot dropdown must hold a non-centroid selection across the round-trip). */
      async activateDesignMoveTool(clusterId) {
        store.setState({ activeClusterId: clusterId })
        await _activateTranslateRotateTool(clusterId)
        const sel = document.getElementById('mr-pivot-sel')
        return {
          active: !!store.getState().translateRotateActive,
          pivotOptions: sel ? [...sel.options].map(o => o.value) : [],
          pivotValue: sel?.value ?? null,
        }
      },
      /** Read the current Move/Rotate pivot-select {value, options}. The observable
       *  for the "dropdown holds a root pivot" gate. */
      getMoveRotatePivotState() {
        const sel = document.getElementById('mr-pivot-sel')
        return {
          value: sel?.value ?? null,
          options: sel ? [...sel.options].map(o => o.value) : [],
        }
      },
      /** Move/Rotate gizmo geometry for a cluster: the rotation pivot the gizmo uses,
       *  the world position where the gizmo HANDLES render, and the cluster's current
       *  bead centroid (rendered positions). Lets an e2e assert the gizmo sits at its
       *  pivot and that a +45° step rotates the beads about that pivot. */
      getClusterGizmoState(clusterId) {
        const design = store.getState().currentDesign
        const cluster = design?.cluster_transforms?.find(c => c.id === clusterId)
        const entries = cluster ? _clusterBackboneEntries(cluster, design) : []
        let cx = 0, cy = 0, cz = 0
        for (const e of entries) { cx += e.pos.x; cy += e.pos.y; cz += e.pos.z }
        const n = entries.length || 1
        return {
          pivot:      clusterGizmo.getPivot?.() ?? null,
          gizmoPos:   clusterGizmo.getGizmoWorldPosition?.() ?? null,
          beadCount:  entries.length,
          beadCentroid: [cx / n, cy / n, cz / n],
          beads:      entries.map(e => [e.pos.x, e.pos.y, e.pos.z]),
        }
      },
      /** Enter assembly mode on the doc's current server assembly. The 'a'
       *  toggle was removed (real entry is opening/creating a .nass); this
       *  mirrors that path's two steps — fetch into currentAssembly, then
       *  _enterAssemblyMode (which attaches the canvas pointer handlers). */
      async enterAssemblyMode() {
        await api.getAssembly()
        _enterAssemblyMode()
      },
      /** Exit assembly mode (flips assemblyActive → false, firing the
       *  subscriber's tear-down: gizmo detach, renderer dispose, multi-box
       *  dispose, listener removal). Mirrors the real close/new-doc path's
       *  call to _exitAssemblyMode; used by e2e to exercise the cleanup. */
      exitAssemblyMode() {
        _exitAssemblyMode()
      },
      /** Deterministically frame the camera on the assembly's RENDERED geometry
       *  (the actual instance meshes, not their transform origins — the rod body
       *  is offset from a part's local origin). The auto-fit relies on the
       *  renderer's bounding box, which is empty for these instances and fires
       *  late, leaving the parts off-screen / under a side panel. Returns false
       *  if no instance geometry is in the scene yet. */
      frameAssemblyForTest() {
        const bbox = new THREE.Box3()
        let any = false
        scene.traverse(o => {
          if (o.userData?.assemblyInstance) {
            o.updateWorldMatrix(true, true)
            const b = new THREE.Box3().setFromObject(o)
            if (!b.isEmpty() && isFinite(b.min.x) && isFinite(b.max.x)) { bbox.union(b); any = true }
          }
        })
        if (!any) return false
        const center = bbox.getCenter(new THREE.Vector3())
        const size = bbox.getSize(new THREE.Vector3())
        // View the broad face: place the camera dominantly along the SMALLEST
        // bbox axis (the parts can be thin ribbons; an edge-on view makes the
        // raycast graze past them and pick nothing).
        const dims = [size.x, size.y, size.z]
        const minAxis = dims.indexOf(Math.min(...dims))
        const dist = Math.max(Math.max(...dims) * 0.85, 25)
        const off = [0.25, 0.25, 0.25]; off[minAxis] = 1.0
        camera.position.set(center.x + off[0] * dist, center.y + off[1] * dist, center.z + off[2] * dist)
        camera.lookAt(center)
        camera.updateMatrixWorld(true)
        if (controls) { controls.target.copy(center); controls.update() }
        return true
      },
    }
    // Force-Crossover tool gesture hook (activate / pickEnd / state) — see
    // scene/force_crossover_tool.js. Lets e2e drive a forced ligation by strand id.
    window.__nadocForceXover = forceCrossoverTool.testApi
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

  nadocBroadcast.onMessage(async (data) => {
    const { type, strandIds, source, windowName, designName, instanceId, designId, docName, docAssembly } = data
    if (type === 'file-saved' && data.path) {
      // A sibling tab autosaved this file. Suppress the SSE echo only if it shares
      // OUR doc (else it's a genuine cross-tab edit that must reload — ISSUE-2).
      _lifecycleSync.registerSiblingSave(data.path, nadocBroadcast.isSameDoc(data))
      return
    }
    if (type === 'doc-presence-request') {
      _announceDocPresence()
    }
    if (type === 'doc-goodbye') {
      _otherTabDocs.delete(source)   // tab closed → drop it so the co-edit count stays honest
      _refreshCoediting()
    }
    if (type === 'doc-presence') {
      _otherTabDocs.set(source, { designId, docName, docAssembly, workspacePath: data.workspacePath ?? null, docId: data.docId ?? null })
      _refreshCoediting()   // a same-file sibling may have just appeared
      // Only a real clobber risk when the other tab shares THIS tab's backend
      // document. Under multi-document (Phase 2) every tab — including each part
      // editor — owns its own doc, so different-design tabs are NOT contending.
      // (Pre-Phase-2 this warned on any different design; that's now a false
      // positive that fired e.g. when opening a second part editor.)
      if (nadocBroadcast.isSameDoc(data)) _maybeWarnDocClobber(designId, docName, docAssembly)
    }
    if (type === 'design-changed') {
      // Doc-scoped: only react to mutations in OUR document. A different tab
      // editing a different document must not make us refetch (multi-document).
      if (!nadocBroadcast.isSameDoc(data)) return
      // Mark live same-doc editing so a following file-changed SSE (a sibling's
      // autosave echo) doesn't reload a stale file over the live edits.
      _lifecycleSync.markSameDocActivity()
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
      _lifecycleSync.setReloadingFromSSE(true)
      try {
        await api.getDesign()
        await api.getGeometry()
      } finally {
        _lifecycleSync.setReloadingFromSSE(false)
      }
    }
    if (type === 'selection-changed') {
      if (!nadocBroadcast.isSameDoc(data)) return   // doc-scoped
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
      _syncBadge.syncLog('info', 'BC-RX', `part-design-updated id=${instanceId}`)
      // Coalesced: a burst of edits (slider drag) emits a burst of these; collapse
      // them into one refresh instead of one heavy rebuild per broadcast.
      _assemblyRefresh.requestRefresh(instanceId, 'broadcast')
      // Part-edit tabs (?part-instance=<id>) show this instance's design as
      // their active design. Re-import from the backend so the topology in
      // this tab reflects the assembly window's mutation. Re-import also
      // emits 'design-changed', which refreshes any open cadnano editor.
      if (_partEditContext?.instanceId === instanceId) {
        try {
          // Re-fetch the updated source FROM the assembly's doc; re-import into
          // THIS tab's own doc (the importDesign emits a doc-scoped design-changed
          // that refreshes only this part's cadnano editor).
          const r = await fetch(`/api/assembly/instances/${instanceId}/design`, { headers: docHeadersFor(_partEditContext.assemblyDoc) })
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
      // Open with a unique target so this one gets a fresh tab; carry our doc id.
      const qs = getDocId() ? `?doc=${encodeURIComponent(getDocId())}` : ''
      window.open(`/cadnano-editor.html${qs}`, 'nadoc-editor-' + Date.now())
    })
    dropdown.appendChild(newBtn)

    dropdown.style.display = ''
  }

  // Request roll-call so any already-open editors re-announce themselves.
  nadocBroadcast.emit('editor-list-request')

  // ── Interim multi-document guard (Phase 1; removed when Phase 2 lands) ────────
  // The backend holds ONE document. If two plain design tabs edit DIFFERENT
  // designs against it, their edits clobber each other. Announce this tab's
  // document identity; warn once if another tab reports a different one.
  const _otherTabDocs = new Map()   // source tabId → { designId, docName, docAssembly }
  let _lastAnnouncedDesignId = null
  let _docClobberWarned = false

  function _announceDocPresence() {
    const s = store.getState()
    const id = s.currentDesign?.id ?? null
    if (!id) return
    nadocBroadcast.emit('doc-presence', {
      designId:      id,
      docName:       s.currentDesign?.metadata?.name ?? null,
      docAssembly:   !!s.assemblyActive,
      workspacePath: _workspacePath,   // lets siblings detect same-file co-editing (ISSUE-2 sub-phase B)
    })
  }

  // Feed the "saved" badge an honest co-editing count: how many OTHER tabs hold
  // our workspace file in a different backend doc (a save-clobber risk, not synced).
  function _refreshCoediting() {
    _syncBadge.setSiblingCoediting(
      countCoeditingSiblings(_workspacePath, getDocId(), [..._otherTabDocs.values()]),
    )
  }

  function _maybeWarnDocClobber(otherId, otherName, otherAssembly) {
    if (_docClobberWarned) return
    const s = store.getState()
    const myId = s.currentDesign?.id ?? null
    // Assemblies use a separate backend slot (/api/assembly) — no contention.
    if (s.assemblyActive || otherAssembly) return
    if (!myId || !otherId || myId === otherId) return
    _docClobberWarned = true
    showToast(
      `Another tab is editing "${otherName ?? 'a different design'}". This backend holds ` +
      `one document at a time — edits from the two tabs may overwrite each other.`,
      9000,
    )
  }

  // Announce our document whenever its identity changes (a new design loaded).
  store.subscribe((ns) => {
    const id = ns.currentDesign?.id ?? null
    if (id === _lastAnnouncedDesignId) return
    _lastAnnouncedDesignId = id
    _docClobberWarned = false   // new document → allow a fresh warning
    _announceDocPresence()
  })

  // Ask any already-open tabs to announce their document, and announce ours.
  nadocBroadcast.emit('doc-presence-request')
  _announceDocPresence()

  // ── Run the boot action for a New/Open-spawned tab (?new / ?open) ────────────
  // This tab owns a fresh ?doc=<id>, so the action targets its own document.
  // Strip the action params afterward (keep ?doc=) so a reload doesn't re-run it.
  if (_bootDocAction) {
    const { newKind, openPath, openType, openName } = _bootDocAction
    const docId = getDocId()
    if (docId) history.replaceState({}, '', `/?doc=${encodeURIComponent(docId)}`)
    else        history.replaceState({}, '', '/')
    if (newKind === 'part') {
      _newDesignModal.openModal()
    } else if (newKind === 'assembly') {
      document.getElementById('menu-file-new-assembly')?.click()
    } else if (openPath) {
      if (openType === 'assembly') await _fileOpen.openAssemblyFromServer(openPath)
      else                         await _fileOpen.openPartFromServer(openPath, openName || undefined)
    }
  }

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

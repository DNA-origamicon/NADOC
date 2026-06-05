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
import { buildNucLetterMap, buildStapleColorMap, BEAD_RADIUS } from './scene/helix_renderer.js'
import { initSelectionManager }      from './scene/selection_manager.js'
import { initWorkspace }             from './scene/workspace.js'
import { initSlicePlane }            from './scene/slice_plane.js'
import { bundleMidOffset }           from './scene/bundle_geometry.js'
import { quatToEulerDeg, eulerDegToQuat, extractJointAngleDeg, posEulerFromMatrix } from './scene/rotation_math.js'
import { initMeasurementTool }       from './scene/measurement_tool.js'
import { intersectCoverage, findHamiltonianPath } from './scene/scaffold_coverage.js'
import { initCreateSeam } from './scene/create_seam.js'
import { strandLengthNt } from './scene/strand_length.js'
import { buildSpecMap, buildDomainMapFromDesign, buildJunctionMapFromDomains, buildRootMap } from './scene/overhang_maps.js'
import { initGroupGizmo } from './scene/group_gizmo.js'
import { matrixFromInstance, sameInstanceTransform, assemblyTransformOnlyChange, constraintRelevantChanged } from './scene/assembly_diff.js'
import { surfaceSegments, isExtrudeOverhang, ovhgDomainIds, flexAnchorKey, connIdForBead, flexibleRunForBead } from './scene/design_queries.js'
import { formatScoreSummary, formatGraphSummary } from './scene/aksel_format.js'
import { computeGroupHiddenInstanceIds, collectGroupMemberInstanceIds } from './scene/assembly_groups_util.js'
import { initAssemblyPointer } from './scene/assembly_pointer.js'
import { hexFromInt, atomColorsFromLetters } from './scene/color_util.js'
import { initFretChecker } from './scene/fret_checker.js'
import { motionChipStyle } from './scene/motion_chip.js'
import { assemblyDuplicateOffset } from './scene/assembly_layout.js'
import { selectionBBox } from './scene/selection_bbox.js'
import { initAssemblyMultiBox } from './scene/assembly_multi_box.js'
import { clientToNdc } from './scene/ndc.js'
import { flexTetherConnections } from './scene/flex_tethers.js'
import { clusterBackboneEntries } from './scene/cluster_entries.js'
import { initEmptySpaceMenu } from './scene/empty_space_menu.js'
import { initAssemblyLasso } from './scene/assembly_lasso.js'
import { initOverhangHoverPicker } from './scene/overhang_hover_picker.js'
import { supportedColoringSet, nextColoringMode } from './scene/coloring_modes.js'
import { initScaffoldModal } from './ui/scaffold_modal.js'
import { initNewDesignModal } from './ui/new_design_modal.js'
import { filterAtomData } from './scene/atom_filter.js'
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
import { createScriptRunner }  from './ui/script_runner.js'
import { store, popGroupUndo } from './state/store.js'
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
import { initPolymerizePanel }     from './ui/polymerize_panel.js'
import { initBeltPathPanel }       from './ui/belt_path_panel.js'
import { initStrandAnimPanel }     from './ui/strand_anim_panel.js'
import { openProteinAttachModal }  from './ui/protein_attach_modal.js'
import { initProteinGizmo }        from './scene/protein_gizmo.js'
import { initUnfoldView }          from './scene/unfold_view.js'
import { initCadnanoView }         from './scene/cadnano_view.js'
import { initDeformView }          from './scene/deform_view.js'
import { initLoopSkipHighlight }   from './scene/loop_skip_highlight.js'
import { initOverhangLocations }   from './scene/overhang_locations.js'
import { initOverhangLinkArcs }    from './scene/overhang_link_arcs.js'
import { initFlexibleArcs }        from './scene/flexible_arcs.js'
import { initOverhangBindingLines } from './scene/overhang_binding_lines.js'
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
// Shared low-poly interactive geometries — used by reference to find atom/bond
// InstancedMeshes for the export-only high-detail swap (see _withHighDetailGeometry).
import { SPHERE_GEO as ATOM_SPHERE_GEO, CYLINDER_GEO as BOND_CYL_GEO } from './scene/atomistic_renderer/geometry_builder.js'
import { initSurfaceRenderer }     from './scene/surface_renderer.js'
import { repColumnsByRep, overhangsToSegments, editOverridesForSegments, createRepresentationMenuItem } from './scene/representation_overrides.js'
import { initSpreadsheet } from './ui/spreadsheet.js'
import { initExportMenu }          from './ui/export_menu.js'
import { initImportMenu }          from './ui/import_menu.js'
import { initAssemblyPanel }        from './ui/assembly_panel.js'
import { initAssemblyContextMenu }  from './ui/assembly_context_menu.js'
import { initLibraryPanel }         from './ui/library_panel.js'
import { pickLattice }              from './ui/lattice_picker.js'
import { openFileBrowser }          from './ui/file_browser.js'
import { initFileIo, initFileOpen, initFileSave } from './ui/file_io.js'
import { initSyncBadge }            from './ui/sync_badge.js'
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
import { getRigidBodyGroup, getKinematicChildren, isGroupAnchored, computeFixedDepths } from './scene/assembly_constraint_graph.js'
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
import { exportVideo, exportPhotoVideo }          from './scene/export_video.js'
import { initClusterGizmo, computeClusterPivotFromEntries, rebaseClusterTranslationForPivot } from './scene/cluster_gizmo.js'
import { initSubDomainGizmo } from './scene/sub_domain_gizmo.js'
import { initInstanceGizmo }       from './scene/instance_gizmo.js'
import { initOverhangGizmo } from './scene/overhang_gizmo.js'
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
import { createContextMenu }                   from './ui/primitives/context_menu.js'
import { initSidebarResize }                   from './ui/sidebar_resize.js'
import { initSceneInspector }                  from './scene/scene_inspector.js'
import { createModal }                         from './ui/primitives/modal.js'
import { createButton }                        from './ui/primitives/button.js'
import { initBackgroundModal }                 from './ui/background_modal.js'
import { nadocBroadcast } from './shared/broadcast.js'
import { getDocId, mintDocId, docHeaders, docHeadersFor, docKey } from './shared/doc_id.js'
import { initMdOverlay }             from './scene/md_overlay.js'
import { initMdSegmentationOverlay } from './scene/md_segmentation_overlay.js'
import { initPeriodicMdOverlay }    from './scene/periodic_md_overlay.js'
import { initPeriodicMdPanel }      from './ui/periodic_md_panel.js'
import { initMdPanel }    from './ui/md_panel.js'
import { createPhotoRenderer } from './scene/photo_renderer.js'
import { initPhotoPanel }      from './ui/photo_panel.js'
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

  // ── World-origin axes (toggleable via View > Toggle Origin Axes; off by
  // default so they don't read as a "part origin gizmo" sitting at 0,0,0). ───
  const originAxes = new THREE.AxesHelper(4)
  originAxes.visible = false
  scene.add(originAxes)

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

  // ── Selection-filter mode (auto-drill vs manual) ─────────────────────────────
  // The drill-lock state machine + the #select-filter button row are extracted to
  // ui/selection_filter.js. `isManualSelect`/`reflectDrillLevel` are injected into
  // initSelectionManager (below); `reflectLockOnButtons`/`resetToAutoBaseline` into
  // initKeyboardShortcuts. `attachFilterButtons()` registers the button handlers +
  // subscribers at the original ~4852 spot (subscription order preserved).
  // selectionManager doesn't exist yet → reached via a lazy getter (all callers
  // fire on user action, post-init).
  const selectionFilter = initSelectionFilter({
    store,
    getSelectionManager: () => selectionManager,
  })

  // ── Selection manager ───────────────────────────────────────────────────────
  const selectionManager = initSelectionManager(canvas, camera, designRenderer, {
    getProteinRenderer: () => proteinRenderer,
    // Per-region overlay renderers (mixed rep) — lazy getters resolve after they're
    // created below; used for atom/surface picking in atomistic/surface regions.
    getRegionVdwRenderer:       () => regionVdwRenderer,
    getRegionBallstickRenderer: () => regionBallstickRenderer,
    getRegionSurfaceRenderer:   () => regionSurfaceRenderer,
    isManualSelect: selectionFilter.isManualSelect,
    onDrillLevel: selectionFilter.reflectDrillLevel,
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
        if (action === 'relax_all') { await _relaxFlexible('all'); return }
        if (action === 'relax_one') {
          let connId = extra
          if (!connId && nuc) connId = connIdForBead(nuc, store.getState().currentDesign)
          if (!connId) { showToast('No flexible connection here', { severity: 'error' }); return }
          await _relaxFlexible('one', connId)
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
      _showOverhangOrientMenu(ovhgIds, clientX, clientY)
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
      // Right-click on empty 3D space → minimal "Extrude" menu. Suppressed
      // while the workspace plane-picker / slice plane is already up (it owns
      // its own interaction) and in assembly mode (separate context menu).
      if (store.getState().assemblyActive) return
      if (slicePlane.isVisible() || workspace.isVisible()) return
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
    isDisabled:    () => slicePlane?.isContinuation(),
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
        // Overlay relaxed positions via the shared mrDNA relaxed-position path.
        designRenderer.applyFemPositions(result.positions)
      }
    })
  })()

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

  // ── Overhang Binding Lines (dashed connectors for design.overhang_bindings) ─
  // Bound bindings → solid green; unbound (pre-bind) → translucent amber.
  // Right-click on a line exposes a Toggle Bind / Delete menu (capture-phase
  // contextmenu listener below).
  const overhangBindingLines = initOverhangBindingLines(scene)
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

  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign) return
    if (newState.assemblyActive) return   // per-part bindings only in design mode for now
    overhangBindingLines.rebuild(newState.currentDesign, newState.currentGeometry)
  })
  {
    const s = store.getState()
    if (!s.assemblyActive && s.currentDesign && s.currentGeometry) {
      overhangBindingLines.rebuild(s.currentDesign, s.currentGeometry)
    }
  }
  // Hide binding lines while in assembly mode (overhang_bindings live on the
  // per-part design, not on the assembly tree).
  store.subscribe((newState, prevState) => {
    if (newState.assemblyActive === prevState.assemblyActive) return
    overhangBindingLines.setVisible(!newState.assemblyActive)
  })

  // Right-click on a binding line → custom menu with Toggle Bind / Delete.
  // Capture-phase so we intercept before selection_manager's contextmenu
  // handler (which would otherwise interpret the click as "no hit, dismiss").
  // If we don't hit a binding line we don't preventDefault — the existing
  // handlers run as usual.
  let _bindingCtxEl = null
  function _hideBindingCtx() {
    if (_bindingCtxEl) { _bindingCtxEl.remove(); _bindingCtxEl = null }
  }
  function _showBindingCtx(bindingId, clientX, clientY) {
    _hideBindingCtx()
    const design = store.getState().currentDesign
    const binding = design?.overhang_bindings?.find(b => b.id === bindingId)
    if (!binding) return
    const el = document.createElement('div')
    el.style.cssText = [
      'position:fixed', `left:${clientX}px`, `top:${clientY}px`,
      'z-index:var(--z-context-menu)',
      'background:var(--color-bg-surface)', 'color:var(--color-text-primary)',
      'border:1px solid var(--color-border-default)',
      'border-radius:var(--radius-md)', 'box-shadow:var(--shadow-md)',
      'padding:4px 0', 'min-width:180px', 'font-size:var(--text-xs)',
      'font-family:var(--font-ui)',
    ].join(';')

    const hdr = document.createElement('div')
    hdr.textContent = binding.name || 'Binding'
    hdr.style.cssText = 'padding:5px 12px 4px;font-weight:600;color:var(--color-text-muted);user-select:none'
    el.appendChild(hdr)

    const hr = document.createElement('div')
    hr.style.cssText = 'border-top:1px solid var(--color-border-muted);margin:3px 0'
    el.appendChild(hr)

    function _mkItem(label, opts = {}) {
      const it = document.createElement('div')
      it.textContent = label
      const color = opts.danger ? 'var(--color-danger)' : 'var(--color-text-primary)'
      it.style.cssText = `padding:5px 12px;cursor:pointer;user-select:none;color:${color}`
      it.addEventListener('pointerenter', () => { it.style.background = 'var(--color-bg-raised)' })
      it.addEventListener('pointerleave', () => { it.style.background = '' })
      it.addEventListener('click', () => { _hideBindingCtx(); opts.onClick?.() })
      return it
    }

    el.appendChild(_mkItem(binding.bound ? 'Unbind' : 'Bind', {
      onClick: async () => {
        try { await api.patchOverhangBinding(bindingId, { bound: !binding.bound }) }
        catch (err) { showToast(err?.message || String(err), { severity: 'error' }) }
      },
    }))
    el.appendChild(_mkItem('Delete binding', {
      danger: true,
      onClick: async () => {
        const ok = await showConfirm({
          title: `Delete ${binding.name || 'binding'}`,
          message: 'Delete this overhang binding? The associated cluster pose lock will release.',
          danger: true,
          confirmLabel: 'Delete',
        })
        if (!ok) return
        try { await api.deleteOverhangBinding(bindingId) }
        catch (err) { showToast(err?.message || String(err), { severity: 'error' }) }
      },
    }))

    document.body.appendChild(el)
    _bindingCtxEl = el
    const rect = el.getBoundingClientRect()
    if (clientX + rect.width  > window.innerWidth)  el.style.left = `${clientX - rect.width}px`
    if (clientY + rect.height > window.innerHeight) el.style.top  = `${clientY - rect.height}px`

    const onOutside = (ev) => { if (!el.contains(ev.target)) _hideBindingCtx() }
    const onKey = (ev) => { if (ev.key === 'Escape') { ev.stopPropagation(); _hideBindingCtx() } }
    setTimeout(() => {
      document.addEventListener('pointerdown', onOutside, true)
      document.addEventListener('keydown', onKey, true)
    }, 0)
    // Clean up listeners when the menu is removed.
    const origHide = _hideBindingCtx
    _hideBindingCtx = () => {
      origHide()
      document.removeEventListener('pointerdown', onOutside, true)
      document.removeEventListener('keydown', onKey, true)
      _hideBindingCtx = origHide
    }
  }
  canvas.addEventListener('contextmenu', (e) => {
    if (store.getState().assemblyActive) return  // per-part bindings only
    if (!overhangBindingLines.isVisible()) return
    const rect = canvas.getBoundingClientRect()
    const ndc = {
      x:  ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      y: -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    }
    const rc = new THREE.Raycaster()
    rc.setFromCamera(ndc, camera)
    const hit = overhangBindingLines.hitTest(rc)
    if (!hit) return
    e.preventDefault()
    e.stopPropagation()
    _showBindingCtx(hit.bindingId, e.clientX, e.clientY)
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

  // ── Protein renderer (imported proteins; independent of the DNA atomistic
  // mode so proteins coexist with cylinders/beads/atomistic DNA). ─────────────
  const proteinRenderer = initAtomisticRenderer(scene)
  const _proteinCentroid = (id) =>
    proteinRenderer.centroidOf(a => a.helix_id === `__protein__${id}`)

  // ── Per-region overlay renderers (mixed representation) ─────────────────────
  // A focal domain/strand/cluster can be pinned to surface / vdw / ballstick; the
  // helix renderer auto-hides the CG beads/cylinders at those columns and these
  // overlays draw the region. Two atomistic instances because vdw and ballstick
  // are distinct geometry and each renderer holds a single mode.
  const regionVdwRenderer       = initAtomisticRenderer(scene)
  const regionBallstickRenderer = initAtomisticRenderer(scene)

  // Transform gizmo for the selected protein. Live preview during drag; on
  // drag-end it commits a gizmo_move (which syncs the design → the currentDesign
  // subscription below re-renders + re-anchors the gizmo). No onCommitted needed.
  const proteinGizmo = initProteinGizmo(store, controls, {
    onLiveStart: (id) => proteinRenderer.beginLiveTransform(a => a.helix_id === `__protein__${id}`),
    onLive:      (m)  => proteinRenderer.applyLiveTransform(m),
    onLiveEnd:   ()   => proteinRenderer.endLiveTransform(),
  })

  // Re-apply the selection visual: highlight + (re)anchor the gizmo at the
  // selected protein's current centroid, or detach when nothing/none-existent
  // is selected. Called after every render so the gizmo follows moves and
  // drops away when the protein is deleted/undone.
  function _syncProteinSelectionVisual() {
    const sel = store.getState().selectedObject
    const protId = sel?.type === 'protein' ? sel.id : null
    const c = protId ? _proteinCentroid(protId) : null
    if (protId && c) {
      proteinRenderer.highlight(sel)
      proteinGizmo.attach(protId, scene, camera, canvas, c)
    } else {
      if (proteinGizmo.isAttached()) proteinGizmo.detach()
      proteinRenderer.highlight(null)
    }
  }

  // Re-render proteins from the server — the design's attachments are the single
  // source of truth. Coalesced so overlapping triggers don't double-fetch.
  let _protRefreshInFlight = false
  let _protRefreshPending = false
  async function _refreshProteins() {
    if (_protRefreshInFlight) { _protRefreshPending = true; return }
    _protRefreshInFlight = true
    try {
      const resp = await fetch('/api/design/protein/atomistic', { headers: docHeaders() })
      if (!resp.ok) return
      const data = await resp.json()
      if (data?.atoms?.length) {
        proteinRenderer.setMode('vdw')
        proteinRenderer.update(data)
      } else {
        proteinRenderer.setMode('off')
        proteinRenderer.update({ atoms: [] })   // clear any existing meshes
      }
      _syncProteinSelectionVisual()
    } catch (e) {
      console.error('Protein atomistic fetch error:', e)
    } finally {
      _protRefreshInFlight = false
      if (_protRefreshPending) { _protRefreshPending = false; _refreshProteins() }
    }
  }

  // Single source of truth: any change to the design (import, move, delete,
  // undo, redo, attach/detach) re-renders proteins from its attachments.
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign === prevState.currentDesign) return
    const hasProteins = (newState.currentDesign?.protein_attachments?.length ?? 0) > 0
    // Refresh when proteins exist now, or when the renderer is showing some
    // (so a removal — undo/delete — clears them).
    if (hasProteins || proteinRenderer.getMode() !== 'off') _refreshProteins()
  })

  // Selection change → update the gizmo/highlight (without a server round-trip).
  store.subscribe((newState, prevState) => {
    if (newState.selectedObject !== prevState.selectedObject) _syncProteinSelectionVisual()
  })

  if (window.__NADOC_DBG__) {
    window.__NADOC_DBG__.proteinRenderer = proteinRenderer
    window.__NADOC_DBG__.proteinGizmo = proteinGizmo
    window.__NADOC_DBG__.refreshProteins = _refreshProteins
  }

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
  const regionSurfaceRenderer = initSurfaceRenderer(scene)   // per-region SURFACE overlay
  if (window.__NADOC_DBG__) {
    window.__NADOC_DBG__.regionVdwRenderer       = regionVdwRenderer
    window.__NADOC_DBG__.regionBallstickRenderer = regionBallstickRenderer
    window.__NADOC_DBG__.regionSurfaceRenderer   = regionSurfaceRenderer
  }
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
        const resp = await fetch(url, { headers: docHeaders() })
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
      const resp = await fetch(_atomisticUrl(), { headers: docHeaders() })
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
    // scaffold gets cadnano blue
    for (const s of currentDesign?.strands ?? []) {
      if (s.strand_type === 'scaffold' && !(s.id in effective)) {
        effective[s.id] = 0x0070bb
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
  // The store/geometry read lives here; the pure mapping is atomColorsFromLetters.
  function _getAtomBaseColors() {
    const { currentDesign, currentGeometry } = store.getState()
    if (!currentDesign || !currentGeometry) return new Map()
    return atomColorsFromLetters(buildNucLetterMap(currentDesign, currentGeometry))
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
    // Arc lines track design visibility; the coarse cylinders/sticks LOD no longer
    // hides the whole group — instead each arc is collapsed per-region by the
    // mixed-representation rep gate (unfold_view._arcRepHidden), so a region pinned
    // to full still shows its crossovers under a global cylinder LOD.
    unfoldView?.setArcsVisible(visible)
    unfoldView?.refreshArcVisibility()
    overhangLinkArcs?.setVisible?.(visible)
  }

  function _atomisticUrl() {
    return '/api/design/atomistic'
  }

  // Lazily fetch + cache the all-atom model. Shared by the global atomistic mode
  // and the per-region atomistic overlays.
  async function _ensureAtomData() {
    if (_atomDataCache) return _atomDataCache
    const resp = await fetch(_atomisticUrl(), { headers: docHeaders() })
    if (!resp.ok) { console.error('Atomistic fetch failed:', resp.status); return null }
    _atomDataCache = await resp.json()
    return _atomDataCache
  }

  async function _applyAtomisticMode(mode) {
    atomisticRenderer.setMode(mode)
    // Hide CG model when any atomistic mode is active; restore when off
    _setCGVisible(mode === 'off')
    _setAtomisticSlidersVisible(mode !== 'off')
    if (mode !== 'off' && !_atomDataCache) {
      showPersistentToast('Loading atomistic model…')
      try {
        const data = await _ensureAtomData()
        if (data) {
          atomisticRenderer.update(data)
          _refreshAtomColors()
          const { selectedObject, multiSelectedStrandIds } = store.getState()
          atomisticRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
        }
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

  // ── Per-region overlay coordinators (mixed representation) ──────────────────
  // Drive the surface / vdw / ballstick overlays from the design's representation
  // overrides. The helix renderer auto-hides CG at those columns; these draw them.

  // Filter the cached all-atom model to a set of columns ("helix:bp"). Keeps each
  // atom's original `serial` so ballstick bonds (serial pairs) resolve without
  // renumbering — bonds are filtered to pairs whose both endpoints survive.

  async function _applyRegionAtomisticOverlays(design) {
    const { vdw, ballstick } = repColumnsByRep(design)
    if (!vdw.size && !ballstick.size) {
      regionVdwRenderer.dispose()
      regionBallstickRenderer.dispose()
      return
    }
    const data = await _ensureAtomData()
    if (!data) return
    // Always dispose-then-update — update() does not pre-clear element meshes.
    regionVdwRenderer.dispose()
    if (vdw.size) { regionVdwRenderer.update(filterAtomData(_atomDataCache, vdw, false)); regionVdwRenderer.setMode('vdw') }
    regionBallstickRenderer.dispose()
    if (ballstick.size) { regionBallstickRenderer.update(filterAtomData(_atomDataCache, ballstick, true)); regionBallstickRenderer.setMode('ballstick') }
    const { selectedObject, multiSelectedStrandIds } = store.getState()
    regionVdwRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
    regionBallstickRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
  }

  // Surface overlay — debounced + signature-cached (surface compute is slow).
  let _regionSurfaceSig   = null
  let _regionSurfaceTimer = null
  async function _recomputeRegionSurface(design) {
    const segs = surfaceSegments(design)
    if (!segs.length) { regionSurfaceRenderer.dispose(); return }
    showPersistentToast('Computing region surface…')
    try {
      const colorMode = store.getState().surfaceColorMode
      const mesh = await api.getRegionSurface(segs, { colorMode })
      regionSurfaceRenderer.update(mesh, colorMode, 'dna-surface-region')
      regionSurfaceRenderer.applyStrandColors(_getAtomStrandColors())
      regionSurfaceRenderer.setOpacity(store.getState().surfaceOpacity)
    } catch (e) {
      console.error('Region surface error:', e)
    } finally {
      dismissToast()
    }
  }
  function _applyRegionSurfaceOverlay(design, force = false) {
    const sig = surfaceSegments(design)
      .map(s => `${s.helix_id}:${s.bp_start}-${s.bp_end}`).sort().join('|')
    if (!force && sig === _regionSurfaceSig) return
    _regionSurfaceSig = sig
    if (_regionSurfaceTimer) clearTimeout(_regionSurfaceTimer)
    _regionSurfaceTimer = setTimeout(() => _recomputeRegionSurface(design), 400)
  }

  // Override change OR geometry/design rebuild → re-apply overlays. (Registered
  // AFTER the atomistic cache-invalidation sub so `_atomDataCache` is null'd first
  // on a design change, forcing a re-fetch.) Surface recompute is forced when the
  // geometry moved; otherwise the signature-cache skips unchanged columns.
  store.subscribe((n, p) => {
    const designChanged = n.currentDesign   !== p.currentDesign
    const geoChanged    = n.currentGeometry !== p.currentGeometry ||
                          n.currentHelixAxes !== p.currentHelixAxes
    if (!designChanged && !geoChanged) return
    _applyRegionAtomisticOverlays(n.currentDesign)
    _applyRegionSurfaceOverlay(n.currentDesign, geoChanged)
  })

  // Selection change → atomistic highlight + surface strand recolor (no recompute).
  store.subscribe((n, p) => {
    if (n.selectedObject === p.selectedObject &&
        n.multiSelectedStrandIds === p.multiSelectedStrandIds) return
    const sel = n.selectedObject, multi = n.multiSelectedStrandIds ?? []
    if (regionVdwRenderer.getMode() !== 'off')       regionVdwRenderer.highlight(sel, multi)
    if (regionBallstickRenderer.getMode() !== 'off') regionBallstickRenderer.highlight(sel, multi)
    if (regionSurfaceRenderer.getMode() === 'on')    regionSurfaceRenderer.applyStrandColors(_getAtomStrandColors())
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
      sliceHighlighter.update(offsetNm, effectivePlane)
    },
    onPreviewToggle: (enabled) => {
      // "Show preview" checkbox in the slice extrude popup → persist + sync overhang ghost.
      _extrudePreviewEnabled = enabled
      localStorage.setItem('NADOC_EXTRUDE_PREVIEW', String(enabled))
      _refreshOverhangGhost()
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
      sliceHighlighter.clear()
      _setMenuToggle('menu-view-slice', false)
    }
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  })

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
  let _scafSplitTarget = null  // { strandId, helixId, bpPosition, direction }

  function _showScaffoldSplitCtx(x, y, coneEntry) {
    const { helix_id, bp_index, direction } = coneEntry.fromNuc
    _scafSplitTarget = { strandId: coneEntry.strandId, helixId: helix_id, bpPosition: bp_index, direction }
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
    _clearScaffoldChecks()
    // Nicking the scaffold here splits it into two scaffold strands at the 3′
    // side of the clicked nucleotide (same make_nick path as the staple nick menu).
    const ok = await api.addNick({ helixId: target.helixId, bpIndex: target.bpPosition, direction: target.direction })
    if (!ok) showToast('Nick failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
  })

  document.getElementById('scaffold-assign-seq-btn')?.addEventListener('click', () => {
    const target = _scafSplitTarget
    _hideScaffoldSplitCtx()
    if (!target) return
    _scaffoldModal.openModal(target.strandId)
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
      menu.appendChild(_mItem('Generate OH binding strand', async () => {
        try { await api.generateBinderForOverhang(ovhgIds[0]) } catch { /* lastError */ }
      }))
    }
    // Representation override for the overhang region(s).
    menu.appendChild(_mSep())
    menu.appendChild(createRepresentationMenuItem({
      dismiss: _dismissOvhgMenu,
      apply: (rep) => {
        const design = store.getState().currentDesign
        const segs = overhangsToSegments(design, ovhgIds)
        const next = editOverridesForSegments(design?.representation_overrides ?? [], segs, rep)
        api.saveRepresentationOverrides(next)
      },
    }))

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
    const { plane, helixId, hasDeformations } = info
    // Anchor the continuation on the helix's axis endpoint, not the between-index
    // disk slot.  axis_end sits one rise PAST the last bp (so far end: diskBp=bp+1),
    // but axis_start sits AT the first bp (so near end must use bp, not bp-1).
    //   near (openSide -1) → bp        far (openSide +1) → bp+1 (= diskBp)
    // Default the ±dir to "away from the body" (openSide): minus for near, plus for far.
    const continuationBp = info.bp + Math.max(0, info.openSide)
    store.setState({ currentPlane: plane })
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
    const { deformVisuActive } = store.getState()
    if (hasDeformations && deformVisuActive) {
      const frame = await api.getDeformedFrame(continuationBp, helixId)
      if (frame) {
        slicePlane.showDeformed(frame, { plane, continuation: true, refHelixId: helixId, defaultDirSign: info.openSide })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
        return
      }
    }
    slicePlane.showAtEnd(helixId, continuationBp, true, { defaultDirSign: info.openSide })
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
  }

  document.getElementById('blunt-extrude-btn')?.addEventListener('click', _bluntExtrude)
  document.getElementById('blunt-bend-btn')?.addEventListener('click', () => {
    const info = _domainEndInfo
    _hideBluntPanel()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
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
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
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
    const { plane, helixId, hasDeformations } = info
    // See _bluntExtrude: anchor on the axis endpoint (near→bp, far→bp+1) and default
    // the ±dir to "away from the body" (openSide).
    const continuationBp = info.bp + Math.max(0, info.openSide)
    store.setState({ currentPlane: plane })
    expandedSpacing.forceOff()   // expanded spacing off while slice plane is active
    const { deformVisuActive } = store.getState()
    if (hasDeformations && deformVisuActive) {
      const frame = await api.getDeformedFrame(continuationBp, helixId)
      if (frame) {
        slicePlane.showDeformed(frame, { plane, continuation: true, refHelixId: helixId, defaultDirSign: info.openSide })
        document.getElementById('mode-indicator').textContent =
          'DEFORMED CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
        return
      }
    }
    slicePlane.showAtEnd(helixId, continuationBp, true, { defaultDirSign: info.openSide })
    document.getElementById('mode-indicator').textContent =
      'CONTINUATION — amber = extend existing strand · right-click cells → Extrude · Esc to close'
  })
  document.getElementById('blunt-bend-btn-ctx')?.addEventListener('click', () => {
    const info = _domainEndCtxInfo
    _hideBluntCtx()
    if (!info) return
    if (!deformView.isActive() && store.getState().currentDesign?.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
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
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' })
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

  // After (re)opening a saved part, decide what the user sees: a part that was
  // created but never extruded (no helices), then saved + closed, reopens
  // straight into the new-bundle plane-picker so the user can resume extruding —
  // same UX as a brand-new part. A populated part just hides the workspace grid.
  function _revealWorkspaceForEmptyPart() {
    const d = store.getState().currentDesign
    if (d && !store.getState().assemblyActive && (d.helices?.length ?? 0) === 0) {
      workspace.show(d.lattice_type ?? 'HONEYCOMB')
    } else {
      workspace.hide()
    }
  }

  // ── Empty-space context menu (start a new bundle / extrude) ─────────────────
  // Right-clicking empty 3D space (no strand/bead/arc/overhang under the cursor)
  // pops a minimal menu whose only item, "Extrude", launches the workspace
  // plane-picker — the same flow as File > New Part.
  async function _startEmptySpaceExtrude() {
    const { currentDesign, assemblyActive } = store.getState()
    if (assemblyActive) return
    const lattice = currentDesign?.lattice_type ?? 'HONEYCOMB'
    // The new-bundle flow (POST /design/bundle) resets to an empty workspace
    // before building, so completing it discards the current design. Guard
    // against silently wiping a populated part.
    if ((currentDesign?.helices?.length ?? 0) > 0) {
      const ok = await showConfirm({
        title: 'Start a new bundle?',
        message: 'Extruding from empty space starts a fresh bundle and replaces the current part. Continue?',
        confirmLabel: 'New bundle',
        danger: true,
      })
      if (!ok) return
    }
    workspace.show(lattice)
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
      if (hasInstances && !_exportRepActive) {
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
  // init (~8773, after `_exportRepActive`). All call sites invoke on user action
  // (menu click / Ctrl+S) post-init, so wrapped as lazy arrows at those sites.
  let _fileSave           = null
  // Doc-scoped so each tab's filename/path metadata is independent (and the
  // cadnano editor opened with the same ?doc= reads the matching values).
  const _FNAME_KEY = docKey('nadoc:design-filename')
  function _setFileName(name) {
    _fileName = name
    if (name) localStorage.setItem(_FNAME_KEY, name)
    else      localStorage.removeItem(_FNAME_KEY)
  }

  // Workspace paths — set when a file is opened from or saved to the workspace.
  // Auto-save subscribers use these to know which file to overwrite.
  const _WS_PATH_KEY  = docKey('nadoc:workspace-path')
  const _ASM_PATH_KEY = docKey('nadoc:assembly-workspace-path')
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
    // A part-editor tab has no assembly in its own doc (the assembly lives in the
    // assembly tab's doc); skip so we don't write an empty/foreign assembly cache.
    if (!_partEditContext) api.persistAssembly()   // no-op if no assembly is loaded
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
    _photoModeExit()
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
    crossSectionMinimap.clearSlice()
    crossSectionMinimap.hide()
    sliceHighlighter.clear()
    bluntEnds.clear()
    _hideBluntPanel()
    _setMenuToggle('menu-view-slice', false)
    viewLegends.reset()
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
    'sel-row-bluntEnds', 'sel-row-crossoverLocations',
    'selection-filter-section', 'properties-section',
    'blunt-panel', 'deform-panel', 'strand-hist-section',
    'groups-panel', 'overhang-panel',
    'oxdna-section', 'md-panel',
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
    '#view-tools [data-key="xloc"]',
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
    _photoModeExit()
    _setDesignGeometryVisible(false)
    // The workspace plane-picker (XY/XZ/YZ grid at world origin) is a
    // new-design-only affordance; hide it whenever we enter assembly mode so
    // its meshes don't leak into the assembly view (visible faded grid +
    // invisible-but-pickable hit planes both sat at world origin).
    workspace.hide()
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
    store, api, workspace,
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
  // (~8773, after `_exportRepActive`). Lazy arrows defer the deref to click time.
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
      // _applyResponseDelta below). Do NOT re-apply here — that would
      // double-apply the rotation (cluster ends up at PRE − θ instead
      // of PRE) per the 2026-05-14 undo-after-relax regression.
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
        showToast('CG Relax failed: ' + message, { severity: 'error' })
      },
    })

    function _applyShape(positions) {
      if (!positions) { designRenderer.clearFemOverlay(); return }
      designRenderer.applyFemPositions(positions)
    }

    _btnRun?.addEventListener('click', () => {
      if (!store.getState().currentDesign?.helices?.length) {
        showToast('No design loaded.', { severity: 'error' }); return
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
      if (!currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
      const mode = modal.querySelector('input[name="as-mode"]:checked')?.value || 'seamed'
      modal.classList.remove('visible')
      if (mode === 'seamless') {
        _showProgress('Seamless Scaffold', 'Routing seamless scaffold strand…')
        const ok = await api.autoScaffoldSeamless()
        _hideProgress()
        if (!ok) {
          showToast('Seamless scaffold failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      } else if (mode === 'matched') {
        _showProgress('Matched Ends', 'Routing scaffold with matched ends for end-to-end polymerization…')
        const ok = await api.autoScaffoldMatched()
        _hideProgress()
        if (!ok) {
          showToast('Matched-ends scaffold failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      } else if (mode === 'advanced-seamed') {
        _showProgress('Advanced Seam Routing', 'Routing scaffold with experimental seam planner…')
        const ok = await api.autoScaffoldAdvancedSeamed()
        _hideProgress()
        if (!ok) {
          showToast('Advanced seam routing failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      } else if (mode === 'advanced-seamless') {
        _showProgress('Advanced Seamless Routing', 'Routing scaffold with experimental seamless planner…')
        const ok = await api.autoScaffoldAdvancedSeamless()
        _hideProgress()
        if (!ok) {
          showToast('Advanced seamless routing failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      } else {
        _showProgress('Autoscaffold (Seamed)', 'Routing scaffold strand with seam crossovers…')
        const ok = await api.autoScaffoldSeamed()
        _hideProgress()
        if (!ok) {
          showToast('Seamed autoscaffold failed: ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
        } else {
          _setRoutingCheck('scaffoldEnds', true)
        }
      }
    }

    document.getElementById('menu-routing-scaffold-ends')?.addEventListener('click', () => {
      if (!store.getState().currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
      modal.classList.add('visible')
    })
    btnRun?.addEventListener('click', _runAutoscaffold)
    btnCancel?.addEventListener('click', () => modal.classList.remove('visible'))
    modal?.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('visible') })
  })()

  document.getElementById('menu-routing-auto-crossover')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    const result = await api.addAutoCrossover()
    if (!result) {
      showToast('Auto Crossover failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
    } else {
      showToast('Auto crossovers placed.')
    }
  })

  document.getElementById('menu-routing-full-autostaple')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    _showProgress('Full autostaple', 'Assigning sequences and routing staples…')
    const result = await api.addFullAutostaple({ scaffold_name: 'M13mp18', k_paths: 3 })
    _hideProgress()
    if (!result) {
      showToast('Full autostaple failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
      return
    }
    const full = result.full_autostaple ?? {}
    const removed = full.removed_circularizing_crossover_count ?? 0
    showToast(`Full autostaple complete: ${full.aksel_break?.new_staple_count ?? 0} staples, ${removed} circularizing crossovers removed.`)
  })

  ;(() => {
    let _abModalCtrl = null
    let _abBody      = null
    let _abReport    = null

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

    function _readAkselOptions() {
      const minNt = Number.parseInt(_abBody?.querySelector('#ab-min-nt')?.value ?? '21', 10)
      const maxNt = Number.parseInt(_abBody?.querySelector('#ab-max-nt')?.value ?? '60', 10)
      const kPaths = Number.parseInt(_abBody?.querySelector('#ab-k-paths')?.value ?? '3', 10)
      const pathIndex = Number.parseInt(_abBody?.querySelector('#ab-path-index')?.value ?? '0', 10)
      return {
        min_staple_nt: Number.isFinite(minNt) ? minNt : 21,
        max_staple_nt: Number.isFinite(maxNt) ? maxNt : 60,
        k_paths: Number.isFinite(kPaths) ? kPaths : 3,
        path_index: Number.isFinite(pathIndex) ? pathIndex : 0,
      }
    }

    function _setAkselReport(lines, severity = 'normal') {
      if (!_abReport) return
      _abReport.style.display = 'block'
      _abReport.style.color = severity === 'error'
        ? 'var(--color-danger, #ff6b6b)'
        : 'var(--color-text-muted)'
      _abReport.textContent = lines.filter(Boolean).join('\n')
    }

    async function _scoreAksel3d() {
      const opts = _readAkselOptions()
      _setAkselReport(['Scoring current staples…'])
      const report = await api.scoreStaples(opts)
      if (!report) {
        _setAkselReport(['Score failed: ' + (store.getState().lastError?.message ?? 'unknown error')], 'error')
        return
      }
      _setAkselReport(['Current route', ...formatScoreSummary(report)])
    }

    async function _previewAksel3d() {
      const opts = _readAkselOptions()
      _setAkselReport(['Building precursor graph…'])
      _showProgress('Aksel preview', 'Scoring candidate breaks…')
      const report = await api.buildStaplePrecursorGraphs(opts)
      _hideProgress()
      if (!report) {
        _setAkselReport(['Preview failed: ' + (store.getState().lastError?.message ?? 'unknown error')], 'error')
        return
      }
      _setAkselReport(['Precursor graph', ...formatGraphSummary(report)])
    }

    async function _runAutoBreak3d() {
      _abModalCtrl?.close()
      const algo = _abBody?.querySelector('input[name="ab-algo"]:checked')?.value || 'basic'
      const isAksel = algo === 'aksel' || algo === 'advanced'
      _showProgress('Autobreak', isAksel ? 'Running Aksel optimizer…' : 'Running nick planner…')
      if (isAksel) _startIndeterminate()
      const result = isAksel
        ? await api.addAutoRouteAksel(_readAkselOptions())
        : await api.addAutoBreak({ algorithm: algo })
      if (isAksel) _stopIndeterminate()
      _hideProgress()
      if (!result) {
        showToast('Autobreak failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
      } else {
        const akselRoute = result.aksel_route
        const aksel = akselRoute?.aksel_break ?? result.aksel_break
        if (aksel) {
          const placed = akselRoute?.auto_crossover?.placed
          const prefix = placed == null ? 'Aksel autobreak' : `Aksel route (${placed} crossovers)`
          showToast(`${prefix} complete: ${aksel.new_staple_count ?? 0} staples, ${aksel.length_violation_count ?? 0} length violations.`)
        } else {
          showToast('Autobreak complete.')
        }
      }
    }

    function _buildOnce() {
      if (_abModalCtrl) return
      _abBody = document.getElementById('autobreak-modal-body')
      if (!_abBody) return
      _abBody.removeAttribute('hidden')
      _abReport = _abBody.querySelector('#ab-aksel-report')
      const cancelBtn = createButton({ label: 'Cancel', variant: 'default', onClick: () => _abModalCtrl.close() })
      const scoreBtn  = createButton({ label: 'Score', variant: 'default', onClick: _scoreAksel3d })
      const graphBtn  = createButton({ label: 'Preview', variant: 'default', onClick: _previewAksel3d })
      const runBtn    = createButton({ label: 'Run Autobreak', variant: 'primary', onClick: _runAutoBreak3d })
      _abModalCtrl = createModal({
        title: 'Autobreak — choose algorithm',
        size: 'md',
        body: _abBody,
        actions: [cancelBtn, scoreBtn, graphBtn, runBtn],
      })
    }

    document.getElementById('menu-routing-autobreak')?.addEventListener('click', () => {
      if (!store.getState().currentDesign?.helices?.length) {
        showToast('No design loaded.', { severity: 'error' }); return
      }
      _buildOnce()
      _abModalCtrl?.open()
    })
  })()

  // ── Sequencing ────────────────────────────────────────────────────────────

  // Assign Scaffold Sequence modal (menu + scaffold right-click) → ui/scaffold_modal.js.
  // _undefinedHighlightOn / _refreshUndefinedHighlight are declared later in main();
  // injected as lazy getters since the apply path only runs on user action (post-boot).
  const _scaffoldModal = initScaffoldModal({
    store, api,
    showProgress: _showProgress,
    hideProgress: _hideProgress,
    getUndefinedHighlightOn: () => _undefinedHighlightOn,
    refreshUndefinedHighlight: () => _refreshUndefinedHighlight(),
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

  initOverhangsManagerPopup({ store })
  document.getElementById('menu-tools-overhangs-manager')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    openOverhangsManager()   // popup pulls preselect from store on its own
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
    // Side-panel atom-color buttons mirror the (atomistic-relevant) modes.
    const cpkBtn    = document.getElementById('atom-color-cpk')
    const strandBtn = document.getElementById('atom-color-strand')
    cpkBtn   ?.classList.toggle('active', mode === 'cpk')
    strandBtn?.classList.toggle('active', mode === 'strand')
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
      workspace.reset()
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
    store, crossoverLocations, overhangLocations, designRenderer,
    cadnanoView, unfoldView,
    rebuildOverhangLocations: _rebuildOverhangLocations,
    getOverhangHoverPicker: () => overhangHoverPicker,
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
  // shared _undefinedHighlightOn mutable (declared in the Highlight Undefined
  // Bases region below) is reached via get/set shims.
  initViewToolButtons({
    store, scene, designRenderer, expandedSpacing,
    setMenuToggle: _setMenuToggle,
    refreshUndefinedHighlight: _refreshUndefinedHighlight,
    getUndefinedHighlightOn: () => _undefinedHighlightOn,
    setUndefinedHighlightOn: (v) => { _undefinedHighlightOn = v },
    toggleDeformView: () => _toggleDeformView(),
    toggleUnfold: () => _toggleUnfold(),
    toggleCadnano: () => _toggleCadnano(),
  })

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
      workspace.reset()
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
    workspace, deformView, crossSectionMinimap, sliceHighlighter,
    isUnfoldActive:           _isUnfoldActive,
    isDeformActive,
    isManualSelect:           selectionFilter.isManualSelect,
    captureCurrentCamera,
    frameSelectionOrAll:      _frameSelectionOrAll,
    setMenuToggle:            _setMenuToggle,
    reflectLockOnButtons:     selectionFilter.reflectLockOnButtons,
    resetToAutoBaseline:      selectionFilter.resetToAutoBaseline,
    toggleUnfold:             _toggleUnfold,
    toggleCadnano:            _toggleCadnano,
    savePartToAssembly:       (opts) => _fileIo.savePartToAssembly(opts),
    saveAssemblyAsGuarded:    () => _fileSave.saveAssemblyAsGuarded(),
    setAssemblyWorkspacePath: _setAssemblyWorkspacePath,
    showWelcome:              _showWelcome,
    ooClose:                  _ooClose,
    cancelTranslateRotateTool: _cancelTranslateRotateTool,
    watchDeformState:         _watchDeformState,
    deformEscape,
    popGroupUndo,
    isTranslateRotateActive:  () => _translateRotateActive,
    getPartEditContext:       () => _partEditContext,
    getAssemblyWorkspacePath: () => _assemblyWorkspacePath,
    getOoActiveIds:           () => _ooActiveIds,
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
      const domIds = ovhgDomainIds(id, currentDesign)
      if (domIds) allDomainIds.push(...domIds)
      if (isExtrudeOverhang(id, currentDesign)) {
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
      const domIds = ovhgDomainIds(id, currentDesign)
      const isExtrude = isExtrudeOverhang(id, currentDesign)
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
  const overhangGizmo = initOverhangGizmo(scene, camera, canvas, controls)
  overhangGizmo.setCallbacks({
    onDragStart: (helixIds) => {
      const { currentDesign } = store.getState()
      const helixCtrl = designRenderer.getHelixCtrl()
      const allDomainIds = _ooActiveIds.flatMap(id => ovhgDomainIds(id, currentDesign) ?? [])
      helixCtrl?.captureClusterBase(helixIds, allDomainIds.length ? allDomainIds : null)
      const extrudeHelixIds = _ooActiveIds
        .filter(id => isExtrudeOverhang(id, currentDesign))
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
        const domIds = ovhgDomainIds(id, currentDesign)
        const isExtrude = isExtrudeOverhang(id, currentDesign)
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
    const { pos, euler } = posEulerFromMatrix(matrix4)
    _mrSetTransformValues(pos[0], pos[1], pos[2], euler[0], euler[1], euler[2])
  }

  function _mrSetJointAngle(deg) {
    if (_mrJaInp && document.activeElement !== _mrJaInp) _mrJaInp.value = deg.toFixed(1)
  }

  // Flexible-segment gate cache (refreshed when the move/rotate tool opens /
  // switches cluster). Drives the "ssDNA constrained" dropdown option.
  let _flexGates = {}
  let _flexConnections = []
  async function _refreshFlexGates() {
    try {
      const info = await api.getFlexibleConnections()
      _flexGates = info?.gates ?? {}
      _flexConnections = info?.connections ?? []
    } catch { _flexGates = {}; _flexConnections = [] }
  }

  function _mrSetPivotOptions(joints, clusterId = null) {
    if (!_mrPivotSel) return
    while (_mrPivotSel.options.length > 1) _mrPivotSel.remove(1)
    for (const j of (joints ?? [])) {
      const opt = document.createElement('option')
      opt.value = j.id
      opt.textContent = `Joint: ${j.name}`
      _mrPivotSel.appendChild(opt)
    }
    // "ssDNA constrained" — only when every inter-cluster connection from this
    // cluster passes through a flexible segment (free-until-taut drag).
    if (clusterId && _flexGates[clusterId]?.gate) {
      const opt = document.createElement('option')
      opt.value = 'ssdna'
      opt.textContent = 'ssDNA constrained'
      _mrPivotSel.appendChild(opt)
    }
  }

  /** Resolve a flexible anchor (FlexibleAnchor) → 'helix:bp:DIR' key. */
  /** Build the gizmo ssDNA-constraint payload for a cluster: per-tether moving/
   *  fixed anchor keys + a live world-position resolver from backboneEntries. */
  function _buildSsdnaPayload(clusterId) {
    const design = store.getState().currentDesign
    const connections = flexTetherConnections(_flexConnections, clusterId, design)
    const resolveWorldPos = (key) => {
      const [h, bp, dir] = key.split(':')
      const bpN = Number(bp)
      for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
        const n = e.nuc
        if (n && n.helix_id === h && n.bp_index === bpN && n.direction === dir) return e.pos
      }
      return null
    }
    return { connections, resolveWorldPos }
  }

  /** Bead count of a cluster (its "size") — used to pick the smaller cluster to move. */
  function _clusterBeadCount(clusterId, design) {
    const ct = design?.cluster_transforms?.find(c => c.id === clusterId)
    if (!ct) return 0
    const hids = new Set(ct.helix_ids ?? [])
    let n = 0
    for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
      if (hids.has(e.nuc?.helix_id)) n++
    }
    return n
  }

  /** Per-tether {movingKey, fixedKey, contour} for the given moving cluster over a
   *  specific subset of connections, plus a live world-position resolver. */
  function _buildRelaxPayload(movingId, conns, design) {
    const connections = flexTetherConnections(conns, movingId, design)
    const resolveWorldPos = (key) => {
      const [h, bp, dir] = key.split(':')
      const bpN = Number(bp)
      for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
        const n = e.nuc
        if (n && n.helix_id === h && n.bp_index === bpN && n.direction === dir) return e.pos
      }
      return null
    }
    return { connections, resolveWorldPos }
  }

  // Relax overstretched flexible ssDNA segments: move the smaller cluster of each
  // flexible-connected pair so no tether exceeds its contour length (= taut at the
  // ssDNA per-base rise). A pair joined by a single flexible region translates only;
  // multiple regions translate + rotate (emergent from the PBD solve). scope='one'
  // relaxes just the clicked connection's pair; 'all' sweeps every pair to settle.
  const _SS_RELAX_TOL = 0.05  // nm — overstretch beyond contour that counts as "needs relax"
  async function _relaxFlexible(scope, connId = null) {
    if (store.getState().assemblyActive) return
    if (_translateRotateActive) { showToast('Finish the current move first', { severity: 'error' }); return }
    const allConns = store.getState().currentDesign?.flexible_connections ?? []
    if (!allConns.length) { showToast('No flexible segments to relax'); return }

    const pairKey = (a, b) => [a, b].sort().join(' ')
    let pairs
    if (scope === 'one') {
      const conn = allConns.find(c => c.id === connId)
      if (!conn) { showToast('Flexible connection not found', { severity: 'error' }); return }
      pairs = [pairKey(conn.cluster_a_id, conn.cluster_b_id)]
    } else {
      pairs = [...new Set(allConns.map(c => pairKey(c.cluster_a_id, c.cluster_b_id)))]
    }

    // Solve headlessly: accumulate one net pending transform per moved cluster
    // (the gizmo's pending map overwrites per cluster, so sweeps never double-count).
    clusterGizmo.discardPendingTransforms?.()
    const maxSweeps = scope === 'all' ? 8 : 2
    let residualRemains = false
    for (let sweep = 0; sweep < maxSweeps; sweep++) {
      let progressed = false
      for (const pk of pairs) {
        const design = store.getState().currentDesign
        const conns = (design?.flexible_connections ?? [])
          .filter(c => pairKey(c.cluster_a_id, c.cluster_b_id) === pk)
        if (!conns.length) continue
        const [ca, cb] = pk.split(' ')
        const movingId = (_clusterBeadCount(ca, design) <= _clusterBeadCount(cb, design)) ? ca : cb
        const translateOnly = conns.length === 1
        const payload = _buildRelaxPayload(movingId, conns, design)
        if (!payload.connections.length) continue
        // Skip if nothing in this pair is overstretched.
        const overstretched = payload.connections.some(c => {
          const pM = payload.resolveWorldPos(c.movingKey), pF = payload.resolveWorldPos(c.fixedKey)
          return pM && pF && pM.distanceTo(pF) > c.contour + _SS_RELAX_TOL
        })
        if (!overstretched) continue

        const res = clusterGizmo.relaxClusterHeadless(movingId, { ...payload, translateOnly })
        if (res.moved) progressed = true
        if (res.residual > _SS_RELAX_TOL) residualRemains = true
      }
      if (!progressed) break
    }

    const pending = clusterGizmo.getAllPendingTransforms?.() ?? []
    if (!pending.length) {
      clusterGizmo.discardPendingTransforms?.()
      clusterGizmo.detach()
      showToast('Flexible segments already relaxed')
      return
    }

    // Commit all moved clusters atomically — ONE feature-log entry (revertable +
    // deletable), ONE undo step, for both 'relax one' and 'relax all'.
    _showProgress('Relaxing', 'Settling flexible segments…', { indeterminate: true })
    try {
      const label = scope === 'all' ? 'Relax all flexible segments' : 'Relax flexible segment'
      await api.relaxFlexibleSegments(
        pending.map(p => ({ cluster_id: p.clusterId, pivot: p.pivot, translation: p.translation, rotation: p.rotation })),
        label,
      )
    } catch (err) {
      showToast(err?.message || String(err), { severity: 'error' })
      return
    } finally {
      clusterGizmo.discardPendingTransforms?.()
      clusterGizmo.detach()
      _hideProgress()
    }

    if (residualRemains) showToast('Relaxed — some tethers still overstretched; try Relax all again', { severity: 'warning' })
    else showToast('Relaxed flexible segments')
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
      const q = eulerDegToQuat(rx, ry, rz)
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
    clusterGizmo.setTransform([tx, ty, tz], eulerDegToQuat(rx, ry, rz))
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
    } else if (val === 'ssdna') {
      _mrShowJointMode(false)
      const clusterId = store.getState().activeClusterId
      clusterGizmo.setConstraint('ssdna', _buildSsdnaPayload(clusterId))
      showToast('ssDNA constrained: drag the arm — tethers won’t overstretch')
    } else {
      const joint = store.getState().currentDesign?.cluster_joints?.find(j => j.id === val)
      if (joint) { _mrShowJointMode(true); clusterGizmo.setConstraint('joint', joint) }
    }
  })


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

  // Cluster dropdown change — switch gizmo to chosen cluster
  _mrClusterSel?.addEventListener('change', async () => {
    const clusterId = _mrClusterSel.value
    if (!clusterId || !_translateRotateActive) return
    if (clusterId === store.getState().activeClusterId) return
    await _refreshClusterPivotForAttach(clusterId)
    clusterGizmo.attach(clusterId, scene, camera, canvas)
    // Repopulate pivot options (joints + ssDNA-constrained gate) for this cluster.
    await _refreshFlexGates()
    const joints = store.getState().currentDesign?.cluster_joints?.filter(j => j.cluster_id === clusterId) ?? []
    _mrSetPivotOptions(joints, clusterId)
    _mrSetSelectedPivot('centroid')
    clusterGizmo.setConstraint('centroid', null)
  })

  const instanceGizmo = initInstanceGizmo(store, controls)
  const assemblyJointRenderer = initAssemblyJointRenderer(scene, camera, canvas, store, api, controls)

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
    getMrAssemblyCtx:                () => _mrAssemblyCtx,
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

  function _canvasNdc(e) {
    return clientToNdc(e.clientX, e.clientY, canvas.getBoundingClientRect())
  }

  function _clusterBackboneEntries(cluster, design, backboneEntries = null) {
    backboneEntries ??= designRenderer.getBackboneEntries?.() ?? []
    return clusterBackboneEntries(cluster, design, backboneEntries)
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
    onMoveRotate: _activateTranslateRotateTool,
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
        showToast('Select an instance first by clicking it in the viewport or its row in the Assembly panel.', { severity: 'error' })
        return
      }
      const _instForGizmo = store.getState().currentAssembly?.instances?.find(i => i.id === activeInstanceId)
      if (_instForGizmo?.fixed) {
        showToast('This part is marked as Fixed and cannot be moved. Uncheck Fixed in the right-click menu to enable movement.', { severity: 'error' })
        return
      }
      const ctx = _createAssemblyTransformContext(activeInstanceId)
      if (!ctx) return
      _mrAssemblyCtx = ctx
      _translateRotateActive = true
      store.setState({ translateRotateActive: true })
      document.getElementById('mode-indicator').textContent = 'MOVE — Tab: move/rotate · click elsewhere: commit · Esc: cancel'
      _attachGroupGizmo(activeInstanceId, ctx)
      _mrSetClusterOptions([{ id: activeInstanceId, name: _instForGizmo?.name ?? 'Selected part' }], activeInstanceId)
      if (_mrClusterSel) _mrClusterSel.disabled = true
      if (_mrPivotSel) _mrPivotSel.disabled = true
      _mrSetPivotOptions([])
      _mrSetSelectedPivot('centroid')
      _mrSetTransformValuesFromMatrix(ctx.primaryStart)
      if (_mrPanel) _mrPanel.style.display = ''
      // No confirm checkmark in assembly mode — committing happens by
      // clicking anywhere other than the selected instance (see
      // _onAssemblyClick), or via Esc to cancel.  The checkmark is still
      // used by the design-mode cluster gizmo path below.
      _confirmBtn.style.display = 'none'
      return
    }

    // ── Design mode: attach cluster gizmo ───────────────────────────────────
    const clusters = currentDesign?.cluster_transforms ?? []
    if (!clusters.length) {
      showToast('No movable clusters exist. Create a cluster first by multi-selecting strands, then using the Movable Clusters panel.', { severity: 'error' })
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
    await _refreshFlexGates()
    const initJoints = store.getState().currentDesign?.cluster_joints?.filter(j => j.cluster_id === first.id) ?? []
    _mrSetPivotOptions(initJoints, first.id)
    _mrSetSelectedPivot('centroid')
    const [irx, iry, irz] = quatToEulerDeg(first.rotation)
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
        // Flexible ssDNA arcs are anchor-derived. The cluster delta moved the
        // beads imperatively (Plan B skips geometry), and the currentDesign
        // subscriber's rebuild already ran against the PRE-delta positions.
        // Rebuild now from the post-delta anchors so undo/redo of a relax (or
        // revert→undo) shows the arcs re-applied, not in the pre-undo shape.
        flexibleArcs?.rebuild?.(cd)
        overhangLinkArcs?.rebuild?.(cd, cg)
        if (overhangLocations?.isVisible?.()) overhangLocations.rebuild(cd, cg)
        // rebuild(geometry, design) — arg order is reversed vs the others.
        if (overhangNameOverlay?.isVisible?.()) overhangNameOverlay.rebuild(cg, cd)
        if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
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
      flexibleArcs?.rebuild?.(cd)   // anchor-derived — refresh on any position delta
      overhangLinkArcs?.rebuild?.(cd, cg)
      if (overhangLocations?.isVisible?.()) overhangLocations.rebuild(cd, cg)
      // rebuild(geometry, design) — arg order is reversed vs the others.
      if (overhangNameOverlay?.isVisible?.()) overhangNameOverlay.rebuild(cg, cd)
      if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
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
                // rebuild(geometry, design) — arg order is reversed vs the others.
                if (overhangNameOverlay?.isVisible?.()) overhangNameOverlay.rebuild(cg, cd)
                if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
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
                // rebuild(geometry, design) — arg order is reversed vs the others.
                if (overhangNameOverlay?.isVisible?.()) overhangNameOverlay.rebuild(cg, cd)
                if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
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
          for (const inst of newState.currentAssembly.instances) {
            const prev = _prevById.get(inst.id)
            if (prev && sameInstanceTransform(prev, inst)) continue
            assemblyRenderer.setLiveTransform(inst.id, matrixFromInstance(inst))
          }
          assemblyJointRenderer.rebuild(newState.currentAssembly)
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
  // created below once its deps are available). The pending-transform Maps stay
  // here — they're touched file-wide (dev hooks, exit-cleanup, keyboard-commit).
  const _assemblyPendingTransforms = new Map()
  const _assemblyPendingPartJoints = new Map()

  function _effectiveInstanceMatrix(inst) {
    return _assemblyPendingTransforms.get(inst.id)?.clone() ?? matrixFromInstance(inst)
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
    return delta
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
      return startTransforms.get(id) ?? (inst ? matrixFromInstance(inst) : null)
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
      const cur = store.getState().multiSelectedInstanceIds ?? []
      const next = cur.includes(hit.id) ? cur.filter(id => id !== hit.id) : [...cur, hit.id]
      store.setState({ multiSelectedInstanceIds: next, activeInstanceId: null, activeGroupId: null })
    },
  })

  // ── PartGroup helpers (id walks; mirror backend/core/assembly_groups.py) ────


  // ── Motion-constraint analyzer ─────────────────────────────────────────────
  // Inspect the joint graph from a moving body (instance or group) to the
  // "anchored network" (instances with `fixed=true` + everything rigidly
  // transitive). Returns the available DOF so the gizmo can expose only the
  // joint's allowed motion instead of a misleading 6-DOF widget.
  //
  // Classification:
  //   { dof: 'free' }                                              — no anchored mates
  //   { dof: 'anchored', anchorId, reason }                         — 0 DOF
  //   { dof: 'revolute',  origin, axis, jointId, name, limits }     — 1 DOF rotation
  //   { dof: 'prismatic', origin, axis, jointId, name, limits }     — 1 DOF translation
  //   { dof: 'spherical', origin, jointId, name }                   — 3 DOF rotation
  //   { dof: 'over-constrained', count, reason }                    — conservatively 0
  function _analyzeMotionConstraints(target) {
    const assembly = store.getState().currentAssembly
    if (!assembly || !target?.id) return { dof: 'free' }
    const movingIds = new Set(
      target.kind === 'group'
        ? collectGroupMemberInstanceIds(assembly, target.id)
        : [target.id],
    )
    if (movingIds.size === 0) return { dof: 'free' }

    // Anchored = fixed=true seeds + rigid-joint transitive closure. Spherical
    // doesn't propagate position-fixedness; it pins the joint origin but
    // lets the other body rotate around it freely.
    const anchored = new Set()
    for (const inst of (assembly.instances ?? [])) {
      if (inst.fixed) anchored.add(inst.id)
    }
    let changed = true
    while (changed) {
      changed = false
      for (const j of (assembly.joints ?? [])) {
        if (j.joint_type !== 'rigid') continue
        const a = j.instance_a_id, b = j.instance_b_id
        if (!a || !b) continue
        if (anchored.has(a) && !anchored.has(b)) { anchored.add(b); changed = true }
        if (anchored.has(b) && !anchored.has(a)) { anchored.add(a); changed = true }
      }
    }

    // If any member of the moving body is itself anchored → can't move.
    for (const id of movingIds) {
      if (anchored.has(id)) return { dof: 'anchored', anchorId: id, reason: 'Part is rigidly anchored.' }
    }

    // External mates: joints whose ONE endpoint is in movingIds and the OTHER
    // is in anchored (or world via instance_a_id === null).
    const externals = []
    for (const j of (assembly.joints ?? [])) {
      const a = j.instance_a_id, b = j.instance_b_id
      const aIn = !!(a && movingIds.has(a))
      const bIn = !!(b && movingIds.has(b))
      if (aIn === bIn) continue
      const otherId = aIn ? b : a
      const externalAnchored = (otherId == null) || anchored.has(otherId)
      if (!externalAnchored) continue
      externals.push(j)
    }
    if (externals.length === 0) return { dof: 'free' }
    if (externals.length > 1) {
      return {
        dof: 'over-constrained',
        count: externals.length,
        reason: `${externals.length} mates to anchored parts — use joint sliders instead.`,
      }
    }

    const j = externals[0]
    const origin = new THREE.Vector3(...(j.axis_origin ?? [0, 0, 0]))
    const axis   = new THREE.Vector3(...(j.axis_direction ?? [0, 0, 1])).normalize()
    const limits = {
      min: j.min_limit ?? null,
      max: j.max_limit ?? null,
      current: j.current_value ?? 0,
    }
    if (j.joint_type === 'rigid') {
      return { dof: 'anchored', anchorId: j.instance_a_id ?? j.instance_b_id,
               reason: 'Rigidly mated to an anchored part.' }
    }
    if (j.joint_type === 'revolute')  return { dof: 'revolute',  origin, axis, jointId: j.id, name: j.name, limits }
    if (j.joint_type === 'prismatic') return { dof: 'prismatic', origin, axis, jointId: j.id, name: j.name, limits }
    if (j.joint_type === 'spherical') return { dof: 'spherical', origin, jointId: j.id, name: j.name }
    return { dof: 'free' }
  }

  // ── Motion-constraint status chip ──────────────────────────────────────────
  // Lightweight overlay so the user sees WHY their gizmo looks the way it does
  // (or why no gizmo appeared). One persistent element above the canvas; the
  // text + colour swap based on the analyzer's verdict.
  const _motionChip = document.createElement('div')
  _motionChip.id = 'assembly-motion-chip'
  _motionChip.style.cssText = [
    'position:absolute;top:8px;left:50%;transform:translateX(-50%);z-index:30',
    'padding:4px 10px;border-radius:12px;border:1px solid #30363d',
    'font-size:11px;font-weight:500;pointer-events:none;user-select:none',
    'background:#161b22;color:#8b949e;display:none',
    'box-shadow:0 2px 6px rgba(0,0,0,0.4)',
  ].join(';')
  document.body.appendChild(_motionChip)

  function _setMotionChip(text, severity = 'info') {
    if (!text) { _motionChip.style.display = 'none'; return }
    _motionChip.textContent = text
    _motionChip.style.display = ''
    const c = motionChipStyle(severity)
    _motionChip.style.color = c.fg
    _motionChip.style.borderColor = c.bd
    _motionChip.style.background = c.bg
  }

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
    setAssemblyRightDownAt:      (v) => { _assemblyRightDownAt = v },
    getTranslateRotateActive:    () => _translateRotateActive,
    getSelectedAssemblyCluster:  () => _selectedAssemblyCluster,
    setSelectedAssemblyCluster:  (v) => { _selectedAssemblyCluster = v },
    getAssemblySelectedPartJoint:() => _assemblySelectedPartJoint,
    setAssemblySelectedPartJoint:(v) => { _assemblySelectedPartJoint = v },
  })
  const _onAssemblyClick = _assemblyPointer.onAssemblyClick
  const _onAssemblyPointerDown = _assemblyPointer.onAssemblyPointerDown

  // Right-click menu for an assembly cross-part linker. Mirrors the per-design
  // linker menu's "Relax linker": the assembly relax rigid-places the free part
  // into a coaxial native-length duplex. Relax availability is gated by the
  // backend status (ds-only; needs a movable part).
  async function _showAssemblyLinkerMenu(connId, x, y) {
    const conn = store.getState().currentAssembly?.overhang_connections?.find(c => c.id === connId)
    const name = conn?.name ?? 'linker'
    let status = null
    try { status = await api.getAssemblyOverhangConnectionRelaxStatus(connId) } catch { /* treat as available */ }
    const available = status?.available !== false
    createContextMenu({
      x, y,
      items: [
        { type: 'header', label: `Linker · ${name}` },
        {
          label: 'Relax linker',
          disabled: !available,
          onClick: async () => {
            try {
              await api.relaxAssemblyOverhangConnection(connId)
              showToast('Relaxed linker — free part moved into a coaxial native-length duplex.')
            } catch (err) {
              showToast(`Relax failed: ${err?.message ?? err}`, { severity: 'error' })
            }
          },
        },
        ...(available ? [] : [{ type: 'header', label: status?.reason ?? 'Relax unavailable' }]),
      ],
    })
  }

  async function _onAssemblyContextMenu(e) {
    e.preventDefault()
    e.stopPropagation()
    // Right-drag pans the camera (OrbitControls); the browser still emits a
    // contextmenu on release.  If the pointer moved since right-button-down it
    // was a pan, not a click — suppress selection + menu (default is already
    // prevented above, so no browser menu appears either).
    const rightDown = _assemblyRightDownAt
    _assemblyRightDownAt = null
    if (rightDown) {
      const rdx = e.clientX - rightDown.x, rdy = e.clientY - rightDown.y
      if (rdx * rdx + rdy * rdy > 25) return   // pan-drag, not a right-click
    }
    // If the right-click hit an overhang arrow, selection_manager's
    // contextmenu listener already routes it to the overhang length dialog.
    // Skip the part context menu so it doesn't appear on top.
    if (overhangLocations?.isVisible?.()) {
      const rc = new THREE.Raycaster()
      rc.setFromCamera(_canvasNdc(e), camera)
      if (overhangLocations.hitTest(rc)) return
    }
    // Right-click on any part of a linker (complement/bridge beads or connector
    // arc) → a Relax menu, mirroring the per-design linker right-click.
    const linkerConnId = assemblyRenderer.pickLinker?.(_canvasNdc(e), camera)
    if (linkerConnId) { _showAssemblyLinkerMenu(linkerConnId, e.clientX, e.clientY); return }

    // Right-click on a belt path → "Attach part to belt" (uses the clicked point
    // as the belt location; then pick the part's connector).
    const beltHit = assemblyJointRenderer.pickBeltAt(e)
    if (beltHit) {
      createContextMenu({ x: e.clientX, y: e.clientY, items: [
        { type: 'header', label: 'Belt path' },
        { label: 'Attach part to belt', onClick: () => _attachPartToBelt(beltHit.beltId) },
      ] })
      return
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
  })

  // ── Photo mode ───────────────────────────────────────────────────────────────
  photoRenderer = createPhotoRenderer(sceneCtx)
  let _photoPanelCtrl = null

  // ── Export representation (final-render LOD) ───────────────────────────────
  // The assembly's `export_representation` is applied to ALL instances only for
  // the duration of a photo-mode PNG/video render, then the working reps are
  // restored. Lets the user edit/preview at a fast LOD but export at high
  // detail. `_exportRepActive` guards saves so the temporary upgrade never hits
  // disk (restore in `finally` + the load-time auto-downgrade are the net).
  let _exportRepActive = false

  // Save/Save-As dispatch factory (ui/file_io.js initFileSave, extraction #60).
  // Placed here — not at the menu listeners (~3924) — because its deps span the
  // file: `_fileIo`/`_syncBadge`/`_lifecycleSync` (~7200-7240) AND `_exportRepActive`
  // (just above). Initializing after the last dep means every value is concrete at
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
    getExportRepActive:        () => _exportRepActive,
    setAssemblyWorkspacePath:  _setAssemblyWorkspacePath,
    selfSavedPaths:            _lifecycleSync.selfSavedPaths,
  })

  /** Batch-patch all instances and resolve when the renderer finishes the
   *  rebuild the store subscriber kicks off. `onRebuildComplete` only appends
   *  (no off-API), so guard a one-shot; a timeout surfaces a stuck rebuild. */
  function _applyRepAndAwaitRebuild(patches) {
    return new Promise((resolve, reject) => {
      let done = false
      const timer = setTimeout(() => {
        if (!done) { done = true; reject(new Error('export rebuild timed out')) }
      }, 120_000)
      assemblyRenderer.onRebuildComplete(() => {
        if (done) return
        done = true; clearTimeout(timer); resolve()
      })
      api.batchPatchInstances(patches).catch(err => {
        if (!done) { done = true; clearTimeout(timer); reject(err) }
      })
    })
  }

  /** Run `fn` (the actual export render) with every instance temporarily set to
   *  the assembly's export representation, restoring the originals afterward.
   *  ALSO suppresses the distance LOD demotion for the whole export so every
   *  part renders at its rep's detail bucket (no far-away hull) → uniform
   *  high-detail figures regardless of zoom.  The rep upgrade is a no-op when
   *  not in assembly mode, no instances, 'working', or already matching; the
   *  LOD suppression still applies whenever we're in an assembly. */
  // High-segment geometry built once on first export, reused thereafter.  The
  // interactive scene keeps its fast low-poly meshes; only the export render uses
  // these.  Atoms/bonds are unit-sized (scaled per-instance); beads/fluorophores
  // bake their radius (instances only translate), so the radius must match the
  // low-poly source (GEO_SPHERE = BEAD_RADIUS, GEO_FLUORO_SPHERE = 0.25).
  let _hdGeoCache = null
  function _highDetailGeometries() {
    if (_hdGeoCache) return _hdGeoCache
    const W = 32, H = 24, RADIAL = 24   // sphere width/height segs; cylinder radial segs
    _hdGeoCache = {
      atom:   new THREE.SphereGeometry(1, W, H),
      bond:   new THREE.CylinderGeometry(1, 1, 1, RADIAL, 1),
      bead:   new THREE.SphereGeometry(BEAD_RADIUS, W, H),
      fluoro: new THREE.SphereGeometry(0.25, W, H),
    }
    return _hdGeoCache
  }

  // Export-only: swap the low-poly interactive sphere/cylinder geometry on
  // atom/bond/bead/fluorophore InstancedMeshes for smooth high-segment versions,
  // run the export, then restore.  Atoms/bonds are matched by shared-geometry
  // reference; CG beads/fluorophores by mesh name (and only when they're still
  // real spheres — skip the opt-in impostor quads).  Swapping `mesh.geometry`
  // leaves instanceMatrix/instanceColor untouched, so positions + colors hold.
  async function _withHighDetailGeometry(fn) {
    const hd = _highDetailGeometries()
    const restore = []   // [mesh, originalGeometry]
    scene.traverse(obj => {
      if (!obj.isInstancedMesh) return
      let hi = null
      if      (obj.geometry === ATOM_SPHERE_GEO) hi = hd.atom
      else if (obj.geometry === BOND_CYL_GEO)    hi = hd.bond
      else if (obj.name === 'backboneSpheres'       && obj.geometry?.type === 'SphereGeometry') hi = hd.bead
      else if (obj.name === 'extensionFluorophores' && obj.geometry?.type === 'SphereGeometry') hi = hd.fluoro
      if (hi && obj.geometry !== hi) { restore.push([obj, obj.geometry]); obj.geometry = hi }
    })
    try { await fn() }
    finally { for (const [mesh, geo] of restore) mesh.geometry = geo }
  }

  async function _withExportRepresentation(fn) {
    // Always export at full geometric detail (smooth atoms/beads/bonds), restored
    // after.  Wraps the actual render so both the rep-upgrade and no-upgrade paths
    // get it; harmless when no atom/bead meshes are present.
    const run = () => _withHighDetailGeometry(fn)
    const st  = store.getState()
    const asm = st.currentAssembly
    const exportRep = asm?.export_representation ?? 'full'
    const insts = asm?.instances ?? []
    const inAssembly = !!st.assemblyActive && insts.length > 0
    if (inAssembly) assemblyRenderer.setSuppressLodDemotion?.(true)

    const needUpgrade = inAssembly && exportRep !== 'working'
      && !insts.every(i => i.representation === exportRep)
    if (!needUpgrade) {
      try { await run() }
      finally { if (inAssembly) assemblyRenderer.setSuppressLodDemotion?.(false) }
      return
    }

    const snapshot = insts.map(i => ({ id: i.id, representation: i.representation }))
    _exportRepActive = true
    try {
      await _applyRepAndAwaitRebuild(insts.map(i => ({ id: i.id, representation: exportRep })))
      photoRenderer.resyncMaterials()
      await run()
    } finally {
      try {
        await _applyRepAndAwaitRebuild(snapshot)
        photoRenderer.resyncMaterials()
      } catch (err) {
        console.error('[export-rep] restore failed:', err)
      }
      assemblyRenderer.setSuppressLodDemotion?.(false)
      _exportRepActive = false
    }
  }

  function _photoModeEnter() {
    const leftPanel = document.getElementById('left-panel')

    // Show photo pane directly — bypasses both the locked-hidden guard and the
    // setActiveTab collapsed-toggle behaviour (clicking an active tab collapses;
    // entering photo mode should always expand).
    document.querySelectorAll('#left-panel .tab-content').forEach(el => {
      el.hidden = el.id !== 'tab-content-photo'
    })
    if (leftPanel) {
      leftPanel.classList.remove('hidden')
      // Update tab button active states so the Photo button looks selected.
      document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === 'photo')
      })
    }

    if (!_photoPanelCtrl) {
      _photoPanelCtrl = initPhotoPanel(photoRenderer, sceneCtx, {
        onEnter: _photoModeEnter,
        onExit:  _photoModeExit,
        store,
        player: animPlayer,
        exportPhotoVideo,
        withExportRepresentation: _withExportRepresentation,
        setExportRepresentation: (rep) => api.setAssemblyExportRepresentation(rep),
      })
    }
    photoRenderer.activate({})
    // Apply the persisted active profile (if any) AFTER activate so material
    // setters take effect immediately rather than queueing.
    _photoPanelCtrl?.applyActiveProfile?.()
    _photoPanelCtrl?.syncToState()

    // Suppress annotation overlays that don't belong in publication renders.
    // Design-mode renderer (no-op in assembly mode):
    designRenderer.setAxisArrowsVisible(false)
    bluntEnds?.setVisible(false)
    // Assembly-mode counterparts: per-instance helix axis arrows + helix-id
    // labels + overhang-name sprites + active-instance BoxHelper, plus the
    // orange joint indicators and (mate-mode-only) blunt-end disks drawn by
    // assemblyJointRenderer. setPhotoMode also flags the renderer so any
    // rebuild WHILE photo mode is active (e.g. polymerize mid-photo) keeps
    // the new instances clean too.
    assemblyRenderer.setPhotoMode(true)
    assemblyJointRenderer.setVisible(false)
    // Partial UI lockdown for clean publication renders:
    // hide the view cube + nav HUD; leave selection/orbit/zoom enabled so the
    // user can still frame parts. Active gizmos remain visible (they self-hide
    // when their owning panel exits transform mode).
    viewCube.hide()
    const modeIndicator = document.getElementById('mode-indicator')
    if (modeIndicator) modeIndicator.style.display = 'none'
    store.setState({ photoActive: true })
  }

  function _photoModeExit() {
    // Idempotent: safe to call from any teardown path (file close/open/new,
    // assembly enter) even when photo mode isn't active — just no-op.
    if (!photoRenderer.isActive()) return
    photoRenderer.deactivate()

    // Restore annotation overlays to their pre-photo-mode state.
    designRenderer.setAxisArrowsVisible(true)
    const tf = store.getState().toolFilters
    bluntEnds?.setVisible(tf?.bluntEnds ?? true)
    assemblyRenderer.setPhotoMode(false)
    assemblyJointRenderer.setVisible(true)
    // Restore the partial-lockdown UI.
    viewCube.show()
    const modeIndicator = document.getElementById('mode-indicator')
    if (modeIndicator) modeIndicator.style.display = ''
    store.setState({ photoActive: false })

    const leftPanel = document.getElementById('left-panel')
    if (leftPanel?.classList.contains('locked-hidden')) {
      // No design loaded — hide photo pane and the panel itself.
      document.getElementById('tab-content-photo').hidden = true
      leftPanel.classList.add('hidden')
    } else {
      // Design loaded — restore normal tab state via the sidebar controller.
      window.__leftSidebar?.setActiveTab('feature-log')
    }
  }

  document.getElementById('photo-tab-btn')?.addEventListener('click', () => {
    if (!photoRenderer.isActive()) _photoModeEnter()
  })

  registerShortcut({
    key: 'p', ctrl: false, shift: false,
    description: 'Toggle photo mode',
    handler() {
      if (photoRenderer.isActive()) _photoModeExit()
      else _photoModeEnter()
    },
  })

  // Expose photo debug helpers on the existing debug object.
  if (window._nadocDebug) {
    window._nadocDebug.photoMaterials = function() {
      const s = photoRenderer.getSettings()
      console.group('[photo] active settings')
      console.log('active:', photoRenderer.isActive())
      console.log('lighting:', s.lighting)
      console.log('background:', s.bgType, s.bgColor)
      console.log('material presets:', { full: s.full, surface: s.surface, cylinders: s.cylinders, atomistic: s.atomistic })
      console.log('ssao:', s.ssao, '| bloom:', s.bloom, s.bloomStrength)
      console.log('pathTracing:', s.pathTracing, '| samples:', photoRenderer.getSampleCount())
      console.groupEnd()
      return s
    }
    window._nadocDebug.ptSamples = function() {
      const n = photoRenderer.getSampleCount()
      const building = photoRenderer.isPathTracingBuilding?.()
      const enabled  = photoRenderer.isPathTracingEnabled?.()
      console.log('[photo] path tracer — enabled:', enabled, '| building BVH:', building, '| samples:', n)
      return n
    }
    window._nadocDebug.ssaoParams = function() {
      const s = photoRenderer.getSettings()
      console.log('[photo] SSAO enabled:', s.ssao, '— kernelRadius≈0.3 nm, kernelSize=32, minDist=0.002, maxDist=0.12')
    }
    window._nadocDebug.bloomParams = function() {
      const s = photoRenderer.getSettings()
      console.log('[photo] bloom enabled:', s.bloom, '| strength:', s.bloomStrength)
    }
    window._nadocDebug.renderTargetSize = function() {
      const el = renderer.domElement
      console.log('[photo] main canvas:', el.width, '×', el.height, '| devicePixelRatio:', window.devicePixelRatio)
    }
  }

  // Populate transform fields and pivot options when the active cluster changes.
  store.subscribe((newState, prevState) => {
    if (newState.activeClusterId === prevState.activeClusterId) return
    if (!newState.activeClusterId || !newState.translateRotateActive) return
    const cluster = newState.currentDesign?.cluster_transforms?.find(c => c.id === newState.activeClusterId)
    if (!cluster) return
    const [rx, ry, rz] = quatToEulerDeg(cluster.rotation)
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
    store, api, workspace, libraryPanel,
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

  // ── Unified representation radio ──────────────────────────────────────────────
  // All seven representations are mutually exclusive.  Exactly one is active at
  // a time; switching to any one deactivates all others.
  //
  // Ordered least → most compute-intensive.  This is also the order shown in the
  // View → Representation menu and the order the F1…F7 hotkeys bind to (the
  // F-key registration loop below iterates this array, so the two stay in sync).
  //
  //  'hull-prism' — per-part grey boxes, aggressive culling (F1, cheapest)
  //  'cylinders'  — domain cylinders (LOD 2)            (F2)
  //  'beads'      — CG beads only    (LOD 1)            (F3)
  //  'full'       — CG beads + slabs (LOD 0)            (F4)
  //  'surface'    — molecular surface mesh              (F5)
  //  'vdw'        — atomistic VDW space-fill            (F6)
  //  'ballstick'  — atomistic ball-and-stick            (F7, heaviest)

  const _ALL_REPRS = [
    { id: 'menu-view-hull-prism',         repr: 'hull-prism' },
    { id: 'menu-view-detail-cylinders',   repr: 'cylinders' },
    { id: 'menu-view-detail-beads',       repr: 'beads'     },
    { id: 'menu-view-detail-full',        repr: 'full'      },
    { id: 'menu-view-surface',            repr: 'surface'    },
    { id: 'menu-view-atomistic-vdw',      repr: 'vdw'       },
    { id: 'menu-view-atomistic-ballstick',repr: 'ballstick' },
  ]

  // Friendly labels for the F-key shortcut descriptions (command palette / help).
  const _REPR_LABELS = {
    'hull-prism': 'Hull Prism',
    cylinders:    'Cylinders',
    beads:        'Beads',
    full:         'Full',
    surface:      'Surface',
    vdw:          'VDW / Space-fill',
    ballstick:    'Ball & Stick',
  }

  // Keep a forward-compat alias so any remaining call sites still work.
  function _updateAtomisticRadio() {}  // no-op — superseded by _updateReprRadio

  function _updateReprRadio(activeRepr) {
    for (const { id, repr } of _ALL_REPRS) {
      document.getElementById(id)?.classList.toggle('is-checked', repr === activeRepr)
    }
    _updateColoringMenuAvailability(activeRepr)
  }

  // Sync the View → Representation menu state with the current assembly's
  // per-part representations.  Three states:
  //   • All parts agree on a single representation → normal radio check
  //     on that representation, no mixed-state dot.
  //   • Parts disagree → no representation is checked AND the green dot
  //     next to "Representation" lights up so the user knows the menu
  //     selection is ambiguous.
  //   • No assembly / no instances → hide the dot and leave the menu
  //     state to design-mode handling.
  function _syncAssemblyReprMenu(assembly) {
    const dotEl = document.getElementById('menu-view-repr-mixed-dot')
    const instances = assembly?.instances ?? []
    if (instances.length === 0) {
      if (dotEl) dotEl.style.display = 'none'
      return
    }
    const reps = new Set()
    for (const inst of instances) reps.add(inst.representation ?? 'full')
    if (reps.size === 1) {
      const only = [...reps][0]
      _updateReprRadio(only)
      if (dotEl) dotEl.style.display = 'none'
    } else {
      // Mixed: clear every is-checked so no representation looks selected.
      for (const { id } of _ALL_REPRS) {
        document.getElementById(id)?.classList.remove('is-checked')
      }
      if (dotEl) dotEl.style.display = ''
    }
  }

  // Per-representation support matrix for the View → Coloring submenu.
  // Cylinders span multiple bps so 'base' is meaningless there; CPK is only
  // meaningful on atomistic; Hull Prism has no per-strand colour at all.
  // Surface vertices are keyed by strand_id only (no per-bp letter), so 'base'
  // is unsupported there; 'cluster' rides on the strand→cluster colour map.
  // Friendly labels for coloring modes — used for the toast shown when an
  // F-key cycles coloring (the menu is closed, so the toast is the feedback).
  const _COLORING_LABELS = {
    strand:          'Strand color',
    base:            'Base color',
    cluster:         'Cluster color',
    'overhang-only': 'Overhang highlight',
    cpk:             'Atomic (CPK)',
    source:          'By part / source',
  }

  // Cycle to the next coloring mode supported by `repr` (supportedColoringSet +
  // nextColoringMode live in scene/coloring_modes.js). Invoked when an F-key is
  // pressed again while its representation is already active. No-op for reprs
  // with <2 options (Hull Prism has none).
  function _cycleColoringForRepr(repr) {
    const modes = [...supportedColoringSet(repr, store.getState().assemblyActive)]
    const next = nextColoringMode(modes, store.getState().coloringMode || 'strand')
    if (!next) return
    _setColoringMode(next)
    showToast(`Coloring: ${_COLORING_LABELS[next] ?? next}`)
  }

  function _updateColoringMenuAvailability(activeRepr) {
    const isAtom = activeRepr === 'vdw' || activeRepr === 'ballstick'
    const supported = supportedColoringSet(activeRepr, store.getState().assemblyActive)
    const map = {
      strand:         'menu-view-coloring-strand',
      base:           'menu-view-coloring-base',
      cluster:        'menu-view-coloring-cluster',
      'overhang-only':'menu-view-coloring-overhang-only',
      cpk:            'menu-view-coloring-cpk',
      source:         'menu-view-coloring-source',
    }
    for (const [mode, id] of Object.entries(map)) {
      const el = document.getElementById(id)
      if (!el) continue
      el.disabled = !supported.has(mode)
    }
    // If the active mode is no longer supported, fall back to an enabled one so
    // the menu's checkmark always reflects an available item. Atomistic prefers
    // CPK; otherwise strand. Hull Prism supports nothing — leave it untouched.
    const current = store.getState().coloringMode || 'strand'
    if (!supported.has(current)) {
      if (isAtom && supported.has('cpk')) _setColoringMode('cpk')
      else if (supported.has('strand'))  _setColoringMode('strand')
    }
  }

  function _reprOptionSliders(repr) {
    document.getElementById('repr-bead-radius-row')?.style.setProperty(
      'display', (repr === 'full' || repr === 'beads') ? '' : 'none')
    document.getElementById('repr-cyl-radius-row')?.style.setProperty(
      'display', repr === 'cylinders' ? '' : 'none')
    document.getElementById('repr-hull-margin-row')?.style.setProperty(
      'display', repr === 'hull-prism' ? '' : 'none')
    document.getElementById('repr-hull-curve-row')?.style.setProperty(
      'display', repr === 'hull-prism' ? '' : 'none')
    if (repr === 'hull-prism') {
      // Sync the slider to the per-lattice default (7 square / 8 honeycomb).
      const lat = store.getState().currentDesign?.lattice_type
      const tick = lat === 'HONEYCOMB' ? 8 : 7
      const sl = document.getElementById('sl-hull-margin')
      const sv = document.getElementById('sv-hull-margin')
      if (sl) sl.value = String(tick)
      if (sv) sv.textContent = String(tick)
    }
    _setAtomisticSlidersVisible(repr === 'vdw' || repr === 'ballstick')
    _setSurfacePanelVisible(repr === 'surface')
  }

  async function _setRepresentation(repr) {
    _currentRepr = repr
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
        unfoldView?.refreshArcVisibility()
      }
    } else if (repr === 'vdw' || repr === 'ballstick') {
      await _applyAtomisticMode(repr)
      store.setState({ atomisticMode: repr })
    } else if (repr === 'surface') {
      await _applySurfaceMode('on')
      store.setState({ surfaceMode: 'on' })
    } else if (repr === 'hull-prism') {
      _setCGVisible(false)
      // Per-lattice default scan margin: 7 bp square / 8 bp honeycomb. Set
      // before activating the hull so the first build uses it (no rebuild yet —
      // hull repr isn't active until setHullRepr below).
      const lat = store.getState().currentDesign?.lattice_type
      jointRenderer?.setHullScanTick(lat === 'HONEYCOMB' ? 8 : 7)
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

        if (repr === 'vdw' || repr === 'ballstick' || repr === 'surface') {
          const ok = await showConfirm({
            title: repr === 'surface' ? 'Apply surface to assembly' : 'Apply atomistic to assembly',
            message: (repr === 'surface'
              ? 'A molecular surface will be computed for every part'
              : 'Atomistic rendering will be computed for every part')
              + ' in the assembly and can be slow for large designs.\n\nApply anyway?',
            confirmLabel: 'Apply',
          })
          if (!ok) return
        }

        _updateReprRadio(repr)
        _updateColoringMenuAvailability(repr)   // atomistic-in-assembly → cpk/strand/cluster/source
        // Batch into a single PATCH so the renderer rebuilds once instead
        // of once per instance. With 20 heavy origamis at 'cylinders' →
        // 'full', the previous Promise.all-of-individual-PATCHes path took
        // ~1.5 min as the renderer rebuilt each instance from a fresh
        // network round-trip. The batched endpoint applies the rep change
        // atomically and the renderer does an in-place LOD swap per entry
        // (no fetch, no labels/arcs/xovers rebuild — see
        // assembly_renderer._inPlaceHelixLodRebuild).
        await api.batchPatchInstances(
          instances.map(inst => ({ id: inst.id, representation: repr })),
        )
        return
      }

      // ── Design mode: existing single-design behaviour ────────────────────────
      if (!currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
      // Choosing a global representation (View → Representation menu or an F-key) is
      // a master reset: it clears any per-region representation overrides so the new
      // global wins everywhere. Internal _setRepresentation calls (reset-to-full,
      // hull-prism auto-switch on edit) bypass this handler and leave overrides intact.
      if (currentDesign.representation_overrides?.length) {
        await api.clearRepresentationOverrides()
      }
      await _setRepresentation(repr)
    })
  }

  // ── Function-key bindings: F1…F7 → representations ────────────────────────────
  // Bound in the same least→most compute-intensive order as _ALL_REPRS / the
  // View → Representation menu.  First press switches to the representation;
  // pressing the SAME key again (while that representation is already active)
  // cycles through its available coloring modes (_COLORING_SUPPORT[repr]).
  // The switch delegates to the menu button's click handler so the
  // assembly-mode, confirm-dialog and disabled logic above is shared (same
  // delegate-to-.click() pattern as the 1–6 routing hotkeys).
  // preventDefault() suppresses the browser's default F-key actions (e.g. F1 help).
  _ALL_REPRS.forEach(({ id, repr }, i) => {
    registerShortcut({
      key: `F${i + 1}`, ctrl: false, shift: false, alt: false,
      description: `Representation: ${_REPR_LABELS[repr] ?? repr} (repeat-press cycles coloring)`,
      blockedInInput: true, noRepeat: true,
      handler(e) {
        e.preventDefault()
        const btn = document.getElementById(id)
        if (!btn || btn.disabled) return
        // is-checked means this representation is already the active GLOBAL one →
        // repeat press cycles its coloring. EXCEPT when per-region representation
        // overrides are active: the displayed structure then diverges from the
        // nominal global rep, so the press should reset to the clean global rep
        // (btn.click() clears overrides) rather than cycle coloring.
        const _hasRepOverrides =
          (store.getState().currentDesign?.representation_overrides?.length ?? 0) > 0
        if (btn.classList.contains('is-checked') && !_hasRepOverrides) _cycleColoringForRepr(repr)
        else                                                           btn.click()
      },
    })
  })

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

  // Hull-prism cross-section margin (bp) — granularity of the extrusion scan.
  const _slHullMargin = document.getElementById('sl-hull-margin')
  const _svHullMargin = document.getElementById('sv-hull-margin')
  _slHullMargin?.addEventListener('input', () => {
    const bp = parseInt(_slHullMargin.value, 10)
    if (_svHullMargin) _svHullMargin.textContent = String(bp)
    jointRenderer?.setHullScanTick(bp)
  })

  // Curved-hull facet detail (nm deviation tolerance): lower = smoother/more facets.
  const _slHullCurve = document.getElementById('sl-hull-curve')
  const _svHullCurve = document.getElementById('sv-hull-curve')
  _slHullCurve?.addEventListener('input', () => {
    const nm = parseFloat(_slHullCurve.value)
    if (_svHullCurve) _svHullCurve.textContent = nm.toFixed(2)
    jointRenderer?.setHullCurveDetail(nm)
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
      /** Count of Alt-picked measurement beads (the measurement tool's input). */
      getCtrlBeadCount: () => selectionManager.getCtrlBeads?.().length ?? 0,
      /** Current single-selection ({type,id,...}) or null. */
      getSelectedObject: () => store.getState().selectedObject ?? null,

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
      // A sibling tab (e.g. the cadnano editor) just autosaved this file. Treat
      // it like our own save so the SSE file-changed echo is skipped — otherwise
      // we'd reload the sibling's autosave (a stale snapshot) back into the
      // shared backend doc and clobber in-progress edits. 5s window covers SSE
      // latency; matches the self-save expiry.
      _lifecycleSync.selfSavedPaths.add(data.path)
      setTimeout(() => _lifecycleSync.selfSavedPaths.delete(data.path), 5000)
      return
    }
    if (type === 'doc-presence-request') {
      _announceDocPresence()
    }
    if (type === 'doc-presence') {
      _otherTabDocs.set(source, { designId, docName, docAssembly })
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
      designId:    id,
      docName:     s.currentDesign?.metadata?.name ?? null,
      docAssembly: !!s.assemblyActive,
    })
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

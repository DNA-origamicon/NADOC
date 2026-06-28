/**
 * Keyboard-shortcut registration for the design editor.
 *
 * Extracted verbatim from main.js's `// ── Keyboard shortcuts` region. The
 * dispatch infrastructure (registry + matcher) lives in input/shortcuts.js;
 * this module owns the *registrations* — the key→action wiring for the design
 * editor — so they're out of the main() closure and unit-testable by
 * dispatching synthetic keydowns through the real registry.
 *
 * It's a dispatcher into nearly everything, so deps come in as one injected
 * object of callbacks/modules rather than dozens of positional args. Handlers
 * are moved verbatim; live-mutable closure state (part-edit context, the
 * overhang-orientation edit set, the translate/rotate active flag, the
 * assembly workspace path) is read through getters so the values stay live.
 *
 * Registration order matters only for ambiguous key matches (first match wins);
 * the original main.js order is preserved here (file/edit → view/tool toggles →
 * Delete/Escape) even though all the keys are distinct.
 *
 * @param {Object} deps
 * @param {Object} deps.store / deps.api
 * @param {Object} deps.slicePlane / deps.expandedSpacing / deps.debugOverlay
 * @param {Object} deps.measurementTool / deps.selectionManager
 * @param {Object} deps.extrudePanel / deps.deformView
 * @param {Object} deps.crossSectionMinimap / deps.sliceHighlighter
 * @param {Function} deps.isUnfoldActive / deps.isDeformActive
 * @param {Function} deps.captureCurrentCamera / deps.frameSelectionOrAll
 * @param {Function} deps.setMenuToggle
 * @param {Function} deps.toggleUnfold / deps.toggleCadnano
 * @param {Function} deps.savePartToAssembly / deps.saveAssemblyAsGuarded / deps.setAssemblyWorkspacePath
 * @param {Function} deps.showWelcome / deps.ooClose / deps.cancelTranslateRotateTool
 * @param {Function} deps.watchDeformState / deps.deformEscape / deps.popGroupUndo
 * @param {Function} deps.isTranslateRotateActive   - () => bool (live getter)
 * @param {Function} deps.getPartEditContext        - () => ctx|null (live getter)
 * @param {Function} deps.getAssemblyWorkspacePath  - () => path|null (live getter)
 * @param {Function} deps.getOoActiveIds            - () => string[] (live getter)
 */
import { registerShortcut, dispatchKeyEvent } from '../input/shortcuts.js'
import { showToast } from './toast.js'
import { nextTabLevel } from '../scene/selection_level.js'
import { nearestWorkspaceAxis, signedAlong } from '../scene/axis_snap.js'

export function initKeyboardShortcuts(deps) {
  const {
    store, api,
    slicePlane, expandedSpacing, debugOverlay, measurementTool, selectionManager,
    extrudePanel, deformView, crossSectionMinimap, sliceHighlighter, primitiveLibrary,
    viewCube, camera, controls,
    isUnfoldActive, isDeformActive,
    captureCurrentCamera, frameSelectionOrAll,
    setMenuToggle,
    toggleUnfold, toggleCadnano,
    savePartToAssembly, saveAssemblyAsGuarded, setAssemblyWorkspacePath,
    showWelcome, ooClose, cancelTranslateRotateTool,
    watchDeformState, deformEscape, popGroupUndo,
    isTranslateRotateActive, getPartEditContext, getAssemblyWorkspacePath, getOoActiveIds,
  } = deps

  // ── File / edit (Ctrl-modifier) ──────────────────────────────────────────

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
      if (getPartEditContext()) {
        savePartToAssembly()
      } else if (store.getState().assemblyActive) {
        const modeEl = document.getElementById('mode-indicator')
        const wsPath = getAssemblyWorkspacePath()
        ;(wsPath ? api.saveAssemblyAs(wsPath) : api.saveAssemblyToWorkspace()).then(r => {
          if (r) {
            if (r.path) setAssemblyWorkspacePath(r.path)
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
    description: 'Save as…',
    handler(e) {
      e.preventDefault()
      // Ctrl+Shift+S dispatches by mode same as the menu Save As item.
      if (store.getState().assemblyActive) {
        saveAssemblyAsGuarded()
      } else {
        document.getElementById('menu-file-save-as')?.click()
      }
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
        // Delta applied inside api.undo() via _responseDeltaHandler.
        const { currentDesign } = store.getState()
        if (!currentDesign?.helices?.length) {
          slicePlane.hide()
          extrudePanel?.hide()
          showWelcome()
        }
        if (!currentDesign?.deformations?.length && !deformView.isActive()) {
          await deformView.activate()
          setMenuToggle('menu-view-deform', true)
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
      }
      // Delta applied inside api.redo() via _responseDeltaHandler.
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
      }
      // Delta applied inside api.redo() via _responseDeltaHandler.
    },
  })

  // 's' is reserved for WASD pan-down — spreadsheet toggle removed.
  // Use the sidebar tab or command palette instead.

  // ── View / tool toggles + number hotkeys ─────────────────────────────────

  registerShortcut({
    key: 'u', ctrl: false,
    description: 'Toggle 2D unfold view',
    blockedInInput: true,
    handler() { toggleUnfold() },
  })

  registerShortcut({
    key: 'k', ctrl: false,
    description: 'Toggle cadnano mode',
    blockedInInput: true,
    handler() { toggleCadnano() },
  })

  // Tab — cycle the unified selectionLevel: cluster → strand → domain → end →
  // xover → none(default) → cluster. `default` = no button engaged = the drill
  // ladder. The filter row reflects it via the emitted level.
  // Skipped when the move/rotate gizmo is active (cluster_gizmo.js owns Tab there).
  registerShortcut({
    key: 'Tab', ctrl: false,
    description: 'Cycle selection level (cluster → strand → domain → end → xover → drill)',
    blockedInInput: true,
    blockedWhen: () => isTranslateRotateActive(),
    handler(e) {
      e.preventDefault()
      const cur  = selectionManager.getSelectionLevel?.() ?? 'default'
      const next = nextTabLevel(cur)
      selectionManager.setSelectionLevel?.(next)
      showToast(next === 'default' ? 'Selection level: drill (default)' : `Selection level: ${next}`)
    },
  })

  registerShortcut({
    key: 'q', ctrl: false,
    description: 'Toggle expanded helix spacing',
    blockedInInput: true,
    handler() {
      if (isUnfoldActive() || slicePlane.isVisible()) {
        showToast('Expanded spacing not available while unfold or slice plane is active')
        return
      }
      const { currentDesign } = store.getState()
      if (!currentDesign?.helices?.length) return
      expandedSpacing.toggle()
    },
  })

  // 'd' is reserved for WASD pan-right — deform-view toggle removed.
  // Use the View menu or assign a different key.

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
        console.log('  op %s  %s  planes [%d → %d]  affected=%s  clusters=%s',
          op.id.slice(0, 8), op.type, op.plane_a_bp, op.plane_b_bp,
          op.affected_helix_ids.join(',') || '(all)',
          (op.cluster_ids ?? []).map(c => c.slice(0, 8)).join(',') || 'none',
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

  // Number hotkeys — workflow shortcuts (routing → sequencing in order).
  // Auto Crossover / Autobreak are intentionally hotkey-less; the one-click
  // Full Autostaple (which subsumes them) owns '2'.
  for (const [key, menuId, desc] of [
    ['1', 'menu-routing-scaffold-ends',    'Autoscaffold'],
    ['2', 'menu-routing-full-autostaple',  'Full Autostaple'],
    ['4', 'menu-seq-update-routing',       'Add Loops/Skips'],
    ['5', 'menu-seq-assign-scaffold',      'Scaffold sequence'],
    ['6', 'menu-seq-assign-staples',       'Staple sequence'],
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
      setMenuToggle('menu-view-debug', active)
      store.setState({ debugOverlayActive: active })
    },
  })

  registerShortcut({
    key: 'f', ctrl: false,
    description: 'Frame selection (or fit all if no selection)',
    blockedInInput: true,
    handler() { frameSelectionOrAll() },
  })

  // 'n' — snap camera onto an orthographic-ish view. In the Extrude tool (slice
  // plane up), snap to the lattice grid's normal so you're looking at it
  // face-on; otherwise snap to whichever signed world axis the camera is already
  // nearest. Both reuse the view-cube's bounding-box-aware snap animation.
  registerShortcut({
    key: 'n', ctrl: false,
    description: 'Snap camera to nearest workspace axis (or lattice grid normal in Extrude)',
    blockedInInput: true,
    handler() {
      if (!viewCube) return
      const fromDir = camera.position.clone().sub(controls.target)
      if (extrudePanel?.isActive() && slicePlane.isVisible()) {
        const normal = signedAlong(slicePlane.getPlaneNormalWorld(), fromDir)
        viewCube.snapToNormal(normal, slicePlane.getPlaneUpWorld())
      } else {
        const { normal, up } = nearestWorkspaceAxis(fromDir)
        viewCube.snapToNormal(normal, up)
      }
    },
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
      if (measurementTool.isActive()) { measurementTool.clear(); return }
      const cb = selectionManager.getCtrlBeads()
      if (cb.length === 2) {
        const posA = selectionManager.getCtrlBeadPos(0)
        const posB = selectionManager.getCtrlBeadPos(1)
        measurementTool.show(posA, posB)
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
    key: 'o', ctrl: false, alt: false, shift: false,
    description: 'Toggle overhang location markers',
    blockedInInput: true, noRepeat: true,
    handler(e) {
      e.preventDefault()
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, overhangLocations: !tf.overhangLocations } })
    },
  })

  // ── Delete / Escape ──────────────────────────────────────────────────────

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
        ooClose()
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
      if (getOoActiveIds().length > 0) {
        ooClose()
        return
      }
      if (measurementTool.isActive()) { measurementTool.clear() }
      if (selectionManager.getCtrlBeads().length > 0) {
        selectionManager.clearCtrlBeads()
        return
      }
      if (isTranslateRotateActive()) {
        cancelTranslateRotateTool()
        return
      }
      if (isDeformActive()) {
        deformEscape()
        watchDeformState()
        if (!isDeformActive()) {
          document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
        }
      } else if (slicePlane.isVisible() || slicePlane.isArmed?.()) {
        // Tears down the read-only slice plane AND the Extrude tool (the panel's
        // hide() also calls slicePlane.hide() + resets the indicator/dropdown).
        // Primitive placement also rides the slice plane → reset its panel controls.
        // isArmed covers the suppressed-grid case (armed on an existing structure, no
        // grid shown yet — still needs Esc to cancel).
        if (slicePlane.isArmed?.()) primitiveLibrary?.exitPlacement?.()
        extrudePanel?.hide()
        slicePlane.hide()
        crossSectionMinimap.clearSlice()
        crossSectionMinimap.hide()
        sliceHighlighter.clear()
        setMenuToggle('menu-view-slice', false)
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      } else if ((selectionManager.getSelectionLevel?.() ?? 'default') !== 'default') {
        // Escape returns the selectionLevel to default (strand-first click).
        selectionManager.setSelectionLevel('default')
        showToast('Selection level: default')
      }
    },
  })

  document.addEventListener('keydown', dispatchKeyEvent)
}

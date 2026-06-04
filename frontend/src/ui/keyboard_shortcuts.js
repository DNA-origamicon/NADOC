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
 * @param {Object} deps
 * @param {Object} deps.store                       - app store (getState/setState)
 * @param {Object} deps.api                          - api client
 * @param {Object} deps.slicePlane
 * @param {Object} deps.expandedSpacing
 * @param {Object} deps.debugOverlay
 * @param {Object} deps.measurementTool
 * @param {Object} deps.selectionManager
 * @param {Function} deps.isUnfoldActive            - () => bool
 * @param {Function} deps.captureCurrentCamera      - () => camState
 * @param {Function} deps.setMenuToggle             - (id, on) => void
 * @param {Function} deps.frameSelectionOrAll       - () => void
 * @param {Function} deps.toggleUnfold              - () => void
 * @param {Function} deps.toggleCadnano             - () => void
 * @param {Function} deps.resetToAutoBaseline       - () => void
 * @param {Function} deps.reflectLockOnButtons      - (level) => void
 * @param {Function} deps.isTranslateRotateActive   - () => bool (live getter)
 */
import { registerShortcut } from '../input/shortcuts.js'
import { showToast } from './toast.js'

// Tab cycle-lock drill levels (region-local consts, moved with the Tab handler).
const _TAB_LOCKS  = [null, 'cluster', 'strand', 'domain', 'bead', 'xover']
const _LOCK_LABEL = { cluster: 'cluster', strand: 'strand', domain: 'domain', bead: 'ends', xover: 'crossover' }

export function initKeyboardShortcuts(deps) {
  const {
    store, api,
    slicePlane, expandedSpacing, debugOverlay, measurementTool, selectionManager,
    isUnfoldActive, captureCurrentCamera, setMenuToggle, frameSelectionOrAll,
    toggleUnfold, toggleCadnano, resetToAutoBaseline, reflectLockOnButtons,
    isTranslateRotateActive,
  } = deps

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

  // Tab — cycle-lock the selection DRILL LEVEL: auto-drill → cluster → strand →
  // domain → ends(bead) → crossover → auto-drill. The lock pins the auto-drill to
  // a fixed level (every click selects at that level, no descent on repeat clicks),
  // reflected as a pinned highlight on the matching filter button. Escape (or
  // cycling past crossover) returns to auto-drill.
  // Skipped when the move/rotate gizmo is active (cluster_gizmo.js owns Tab there).
  registerShortcut({
    key: 'Tab', ctrl: false,
    description: 'Cycle selection lock (cluster → strand → domain → ends → crossover)',
    blockedInInput: true,
    blockedWhen: () => isTranslateRotateActive(),
    handler(e) {
      e.preventDefault()
      const cur  = selectionManager.getDrillLock?.() ?? null
      const next = _TAB_LOCKS[(_TAB_LOCKS.indexOf(cur) + 1) % _TAB_LOCKS.length]
      resetToAutoBaseline()                  // clear manual pins + restore baseline selectability
      selectionManager.setDrillLock?.(next)  // null = back to normal auto-drill
      reflectLockOnButtons(next)
      showToast(next ? `Selection locked: ${_LOCK_LABEL[next]}` : 'Selection: auto-drill')
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
}

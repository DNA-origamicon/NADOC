// Unified representation switcher — the core of the View → Representation menu.
//
// Owns the seven mutually-exclusive representations (hull-prism / cylinders /
// beads / full / surface / vdw / ballstick), the radio menu state, the View →
// Coloring submenu availability matrix, and the F1…F7 hotkey bindings. Exactly
// one representation is active at a time; switching deactivates the others.
//
// Extracted verbatim from main.js as the switcher-CORE lift of the
// representation-switcher campaign (frontier #2), after #82 (coloring_modes.js
// pure decisions) and #83 (ui/repr_option_sliders.js). The four tuning sliders
// live in repr_option_sliders.js and are driven from `setRepresentation`'s tail
// via the injected `reprOptionSliders` (its `updateForRepr`). The atomistic /
// surface controllers (`applyAtomisticMode` / `applySurfaceMode` / `setCGVisible`)
// and the coloring-mode setter (`setColoringMode`) remain in main.js and are
// injected.

import { supportedColoringSet, nextColoringMode, reprMenuState, coloringFallbackMode } from '../scene/coloring_modes.js'
import { showToast } from './toast.js'
import { showConfirm } from './primitives/confirm.js'
import { registerShortcut } from '../input/shortcuts.js'

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

/**
 * Initialise the representation switcher: wires the menu click handlers, the
 * F1…F7 hotkeys, and the initial Coloring-menu availability; returns the small
 * API the rest of main.js calls into.
 *
 * @param {object} deps
 * @returns {{setRepresentation, updateReprRadio, syncAssemblyReprMenu}}
 */
export function initRepresentationSwitcher({
  store,
  api,
  atomisticRenderer,
  designRenderer,
  overhangLinkArcs,
  unfoldView,
  getJointRenderer,
  getSurfaceMode,
  applySurfaceMode,
  applyAtomisticMode,
  setCGVisible,
  setColoringMode,
  reprOptionSliders,
  getLastDetailLevel,
  setLastDetailLevel,
  setLodMode,
  setCurrentRepr,
}) {
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
    const st = reprMenuState(assembly?.instances ?? [])
    if (st.kind === 'none') {
      if (dotEl) dotEl.style.display = 'none'
      return
    }
    if (st.kind === 'single') {
      _updateReprRadio(st.repr)
      if (dotEl) dotEl.style.display = 'none'
    } else {
      // Mixed: clear every is-checked so no representation looks selected.
      for (const { id } of _ALL_REPRS) {
        document.getElementById(id)?.classList.remove('is-checked')
      }
      if (dotEl) dotEl.style.display = ''
    }
  }

  // Cycle to the next coloring mode supported by `repr` (supportedColoringSet +
  // nextColoringMode live in scene/coloring_modes.js). Invoked when an F-key is
  // pressed again while its representation is already active. No-op for reprs
  // with <2 options (Hull Prism has none).
  function _cycleColoringForRepr(repr) {
    const modes = [...supportedColoringSet(repr, store.getState().assemblyActive)]
    const next = nextColoringMode(modes, store.getState().coloringMode || 'strand')
    if (!next) return
    setColoringMode(next)
    showToast(`Coloring: ${_COLORING_LABELS[next] ?? next}`)
  }

  function _updateColoringMenuAvailability(activeRepr) {
    const assemblyActive = store.getState().assemblyActive
    const supported = supportedColoringSet(activeRepr, assemblyActive)
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
    // the menu's checkmark always reflects an available item.
    const fallback = coloringFallbackMode(
      activeRepr, store.getState().coloringMode || 'strand', assemblyActive)
    if (fallback) setColoringMode(fallback)
  }

  async function _setRepresentation(repr) {
    setCurrentRepr(repr)
    // ── Deactivate any currently active exclusive mode ────────────────────────
    if (repr !== 'vdw' && repr !== 'ballstick' && atomisticRenderer.getMode() !== 'off') {
      atomisticRenderer.setMode('off')
      store.setState({ atomisticMode: 'off' })
    }
    if (repr !== 'surface' && getSurfaceMode() !== 'off') {
      applySurfaceMode('off')
      store.setState({ surfaceMode: 'off' })
    }
    if (repr !== 'hull-prism') {
      getJointRenderer()?.setHullRepr(false)
    }

    // ── Activate the new representation ──────────────────────────────────────
    if (repr === 'full' || repr === 'beads' || repr === 'cylinders') {
      setCGVisible(true)
      const lvl = { full: 0, beads: 1, cylinders: 2 }[repr]
      overhangLinkArcs?.setRepresentation?.(repr)
      if (lvl !== getLastDetailLevel()) {
        setLastDetailLevel(lvl)
        setLodMode(repr)
        designRenderer.setDetailLevel(lvl)
        unfoldView?.refreshArcVisibility()
      }
    } else if (repr === 'vdw' || repr === 'ballstick') {
      await applyAtomisticMode(repr)
      store.setState({ atomisticMode: repr })
    } else if (repr === 'surface') {
      await applySurfaceMode('on')
      store.setState({ surfaceMode: 'on' })
    } else if (repr === 'hull-prism') {
      setCGVisible(false)
      // Per-lattice default scan margin: 7 bp square / 8 bp honeycomb. Set
      // before activating the hull so the first build uses it (no rebuild yet —
      // hull repr isn't active until setHullRepr below).
      const lat = store.getState().currentDesign?.lattice_type
      getJointRenderer()?.setHullScanTick(lat === 'HONEYCOMB' ? 8 : 7)
      getJointRenderer()?.setHullRepr(true)
    }

    _updateReprRadio(repr)
    reprOptionSliders(repr)
    window.dispatchEvent(new CustomEvent('nadoc:representation-change', {
      detail: { representation: repr },
    }))
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

  return {
    setRepresentation:    _setRepresentation,
    updateReprRadio:      _updateReprRadio,
    syncAssemblyReprMenu: _syncAssemblyReprMenu,
  }
}

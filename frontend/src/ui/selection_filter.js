// Selection-filter mode (auto-drill vs manual) + the #select-filter .sf-btn row.
//
// Extracted verbatim from main.js (banners `// ── Selection-filter mode` ~727
// and `// ── Selection Filter toggles` ~4852). Two textually-distant blocks that
// form ONE subsystem:
//   - the drill-lock state machine (`_manualFilters` Set + the 4 reflect/reset
//     functions), which `selectionManager` and `keyboard_shortcuts` consume as
//     injected callbacks; and
//   - the `#select-filter` button-click handlers + 2 store subscribers that pin
//     filters and compute `selectableTypes`.
//
// Empty `_manualFilters` ⇒ auto-drill: repeated bead clicks descend cluster →
// strand → domain → bead/xover and the matching filter button auto-lights. Once
// the user clicks a filter button it is "pinned" (red border) and traditional
// `selectableTypes` gating applies; Tab or un-pinning the last button restores
// auto-drill. dataKey strings (e.g. 'clust', 'line') match the .sf-btn[data-key].
//
// `selectionManager` is created AFTER this factory in main()'s init order (the
// factory's `isManualSelect`/`reflectDrillLevel` are passed INTO its init), so it
// is reached through a lazy `getSelectionManager` getter — safe because every
// caller (button click / Tab key / drill) fires on user action, post-init.
// `attachFilterButtons()` registers the button handlers + subscribers and is
// called at the original ~4852 spot to preserve store-subscription order.

import { isDrillV2, BTN_LEVEL, LEVEL_BTN as LEVEL_BTN_V2, toggleLevel } from '../scene/selection_level.js'

const LEVEL_BTN = { cluster: 'clust', strand: 'strand', domain: 'line', bead: 'ends', xover: 'xover' }

// The five dataKeys that act as selectionLevel buttons in drill-v2.
const V2_LEVEL_KEYS = new Set(Object.keys(BTN_LEVEL))   // clust/strand/line/ends/xover

const SEL_KEY_MAP = [
  ['scaffold',      'scaf'   ],
  ['staples',       'stap'   ],
  ['clusters',      'clust'  ],
  ['strands',       'strand' ],
  ['domains',       'line'   ],
  ['ends',          'ends'   ],
  ['crossoverArcs', 'xover'  ],
  ['loops',         'loop'   ],
  ['skips',         'skip'   ],
  ['overhangs',     'ovhangs'],
]

/**
 * Pure: given the current `selectableTypes`, the clicked filter's store key, the
 * full set of filter keys, and the saved pre-loop/skip snapshot, compute the next
 * `selectableTypes` and the next `preLoopSkip` snapshot.
 *
 * loops/skips/overhangs are an EXCLUSIVE group: turning one on clears everything
 * else (snapshotting the prior state the first time), turning it off restores the
 * snapshot (or just clears that one if no snapshot). Every other key plain-toggles.
 *
 * @returns {{selectableTypes: object, preLoopSkip: object|null}}
 */
export function computeFilterToggle({ selectableTypes, storeKey, allKeys, preLoopSkip }) {
  const st = selectableTypes
  const isLoopSkipGroup = storeKey === 'loops' || storeKey === 'skips' || storeKey === 'overhangs'
  if (isLoopSkipGroup) {
    if (!st[storeKey]) {
      const nextPre = (!st.loops && !st.skips && !st.overhangs) ? { ...st } : preLoopSkip
      const cleared = {}
      for (const k of allKeys) cleared[k] = false
      return { selectableTypes: { ...cleared, [storeKey]: true }, preLoopSkip: nextPre }
    }
    if (preLoopSkip) {
      return { selectableTypes: { ...preLoopSkip }, preLoopSkip: null }
    }
    return { selectableTypes: { ...st, [storeKey]: false }, preLoopSkip }
  }
  return { selectableTypes: { ...st, [storeKey]: !st[storeKey] }, preLoopSkip }
}

export function initSelectionFilter({ store, getSelectionManager, drillV2 = isDrillV2() }) {
  const _manualFilters = new Set()
  let _preLoopSkipSelectables = null
  const _v2 = !!drillV2

  function isManualSelect() { return _manualFilters.size > 0 }

  // Light the filter button matching the current drill level (display only —
  // does NOT touch selectableTypes or _manualFilters). No-op in manual mode.
  function reflectDrillLevel(level) {
    // Drill-v2: the level buttons ARE the selectionLevel selector — paint the
    // engaged level with both .active and the .sf-pinned border (one coherent
    // surface, no overloaded red). 'default' lights the strand button.
    if (_v2) {
      const target = LEVEL_BTN_V2[level ?? 'default'] ?? 'strand'
      for (const dk of Object.values(LEVEL_BTN_V2)) {
        const b = document.querySelector(`#select-filter .sf-btn[data-key="${dk}"]`)
        if (b) { b.classList.toggle('active', dk === target); b.classList.toggle('sf-pinned', dk === target) }
      }
      return
    }
    if (isManualSelect()) return
    const target = level ? (LEVEL_BTN[level] ?? null) : null
    for (const dk of Object.values(LEVEL_BTN)) {
      const b = document.querySelector(`#select-filter .sf-btn[data-key="${dk}"]`)
      if (b) b.classList.toggle('active', dk === target)
    }
  }

  // Red "pinned" border on the level button matching the active Tab drill-lock
  // (level = 'cluster'|'strand'|'domain'|'bead'|'xover', or null to clear all).
  function reflectLockOnButtons(level) {
    const pinnedKey = level ? LEVEL_BTN[level] : null
    for (const dk of Object.values(LEVEL_BTN)) {
      const b = document.querySelector(`#select-filter .sf-btn[data-key="${dk}"]`)
      if (b) b.classList.toggle('sf-pinned', dk === pinnedKey)
    }
  }

  // Clear all manual pins and restore the neutral auto-drill baseline (scaffold/
  // staples/strands on, everything else off). Also fixes button .active classes
  // so they don't show stale manual state.
  function resetToAutoBaseline() {
    _manualFilters.clear()
    document.querySelectorAll('#select-filter .sf-btn.sf-pinned').forEach(b => b.classList.remove('sf-pinned'))
    store.setState({
      selectableTypes: {
        scaffold: true, staples: true,
        clusters: false, strands: true, domains: false, ends: false, crossoverArcs: false,
        loops: false, skips: false, extensions: false, overhangs: false,
      },
    })
    const baseActive = { scaf: true, stap: true, strand: true, clust: false, line: false, ends: false, xover: false, skip: false, loop: false, ovhangs: false }
    for (const [dk, on] of Object.entries(baseActive)) {
      const b = document.querySelector(`#select-filter .sf-btn[data-key="${dk}"]`)
      if (b) b.classList.toggle('active', on)
    }
    getSelectionManager()?.resetDrill?.()
  }

  // Register the #select-filter button click handlers + 2 store subscribers.
  // Called at the original ~4852 spot in main() so subscription order is preserved.
  function attachFilterButtons() {
    const _allSelKeys = SEL_KEY_MAP.map(([k]) => k)
    const _selectFilter = document.getElementById('select-filter')

    for (const [storeKey, dataKey] of SEL_KEY_MAP) {
      const btn = document.querySelector(`#select-filter .sf-btn[data-key="${dataKey}"]`)
      if (!btn) continue

      btn.addEventListener('click', () => {
        const { deformToolActive, translateRotateActive } = store.getState()
        if (deformToolActive || translateRotateActive) return

        // Drill-v2: the cluster/strand/domain/ends/xover buttons set the unified
        // selectionLevel (toggle off → default). They no longer pin selectableTypes;
        // the type-visibility gates (scaffold/staples/loops/skips/overhangs) keep
        // their plain-toggle behaviour below. reflectDrillLevel paints the row.
        if (_v2 && V2_LEVEL_KEYS.has(dataKey)) {
          const sm  = getSelectionManager()
          const cur = sm?.getSelectionLevel?.() ?? 'default'
          sm?.setSelectionLevel?.(toggleLevel(cur, BTN_LEVEL[dataKey]))
          return
        }

        // Manual filter pins and the Tab drill-lock are mutually exclusive — a
        // manual click cancels any active drill-lock first.
        const selectionManager = getSelectionManager()
        if (selectionManager?.getDrillLock?.()) {
          selectionManager.setDrillLock(null)
          reflectLockOnButtons(null)
        }

        // Clicking a filter button enters/adjusts manual mode: pin it (red border)
        // and apply traditional gating. Un-pinning the last button restores auto-drill.
        const wasPinned = _manualFilters.has(dataKey)
        if (wasPinned) _manualFilters.delete(dataKey)
        else           _manualFilters.add(dataKey)
        btn.classList.toggle('sf-pinned', !wasPinned)

        const st = store.getState().selectableTypes
        const next = computeFilterToggle({
          selectableTypes: st, storeKey, allKeys: _allSelKeys, preLoopSkip: _preLoopSkipSelectables,
        })
        _preLoopSkipSelectables = next.preLoopSkip
        store.setState({ selectableTypes: next.selectableTypes })

        // Stop the auto-drill cursor from fighting the manual selection.
        selectionManager?.resetDrill?.()
        // No manual pins left → return to auto-drill with a clean baseline.
        if (_manualFilters.size === 0) resetToAutoBaseline()
      })

      store.subscribe(() => {
        // In auto-drill mode the buttons are driven by reflectDrillLevel; only
        // sync .active from selectableTypes while a manual pin is active.
        if (!isManualSelect()) return
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

  return { isManualSelect, reflectDrillLevel, reflectLockOnButtons, resetToAutoBaseline, attachFilterButtons }
}

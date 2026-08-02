// The #select-filter .sf-btn row.
//
// Two roles share the row:
//   - the cluster/strand/domain/ends/xover buttons are the unified `selectionLevel`
//     selector (they drive `selectionManager.setSelectionLevel`); and
//   - the scaffold/staples/loops/skips/overhangs buttons are type-visibility gates
//     that plain-toggle `selectableTypes` ("what's pickable").
//
// `selectionManager` is created AFTER this factory in main()'s init order (the
// factory's `reflectDrillLevel` is passed INTO its init as `onDrillLevel`), so it
// is reached through a lazy `getSelectionManager` getter — safe because every
// caller fires on user action, post-init. `attachFilterButtons()` registers the
// button handlers + subscribers and is called at the original ~4852 spot to
// preserve store-subscription order.

import { BTN_LEVEL, LEVEL_BTN as LEVEL_BTN_V2, toggleLevel } from '../scene/selection_level.js'

// The five dataKeys that act as selectionLevel buttons.
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

// Level buttons with NO `selectableTypes` counterpart. `base` is a pure selection level
// (it gates nothing — it changes what a click resolves to), so it has no store key and
// therefore no SEL_KEY_MAP row. Without this list `attachFilterButtons` would skip it
// entirely and the button would get no click listener, while `reflectDrillLevel` (which
// iterates LEVEL_BTN) would still light it from Tab — a button that looks live and does
// nothing. `null` storeKey means "level-only": never touch selectableTypes.
const LEVEL_ONLY_BTNS = [
  [null, 'base'],
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

export function initSelectionFilter({ store, getSelectionManager }) {
  let _preLoopSkipSelectables = null

  // Light the filter button matching the engaged selectionLevel — the level
  // buttons ARE the selector. Paint ONLY the engaged level with .active (no red
  // border). `default` (no engaged level) lights NO button → the drill ladder.
  function reflectDrillLevel(level) {
    const target = LEVEL_BTN_V2[level] ?? null
    for (const dk of Object.values(LEVEL_BTN_V2)) {
      const b = document.querySelector(`#select-filter .sf-btn[data-key="${dk}"]`)
      if (b) b.classList.toggle('active', dk === target)
    }
  }

  // Register the #select-filter button click handlers + 2 store subscribers.
  // Called at the original ~4852 spot in main() so subscription order is preserved.
  function attachFilterButtons() {
    // _allSelKeys stays derived from SEL_KEY_MAP alone — it is the selectableTypes key
    // list computeFilterToggle clears, and a level-only button has no key to put in it.
    const _allSelKeys = SEL_KEY_MAP.map(([k]) => k)
    const _selectFilter = document.getElementById('select-filter')

    for (const [storeKey, dataKey] of [...SEL_KEY_MAP, ...LEVEL_ONLY_BTNS]) {
      const btn = document.querySelector(`#select-filter .sf-btn[data-key="${dataKey}"]`)
      if (!btn) continue

      btn.addEventListener('click', () => {
        const { deformToolActive, translateRotateActive } = store.getState()
        if (deformToolActive || translateRotateActive) return

        // The cluster/strand/domain/ends/xover buttons set the unified
        // selectionLevel (toggle off → default). They do NOT touch selectableTypes.
        if (V2_LEVEL_KEYS.has(dataKey)) {
          const sm  = getSelectionManager()
          const cur = sm?.getSelectionLevel?.() ?? 'default'
          sm?.setSelectionLevel?.(toggleLevel(cur, BTN_LEVEL[dataKey]))
          return
        }

        // Type-visibility gates (scaffold/staples/loops/skips/overhangs) plain-toggle
        // selectableTypes — loops/skips/overhangs are an exclusive group, handled by
        // computeFilterToggle. The subscriber below reflects .active.
        const st = store.getState().selectableTypes
        const next = computeFilterToggle({
          selectableTypes: st, storeKey, allKeys: _allSelKeys, preLoopSkip: _preLoopSkipSelectables,
        })
        _preLoopSkipSelectables = next.preLoopSkip
        store.setState({ selectableTypes: next.selectableTypes })
      })

      store.subscribe(() => {
        // Level buttons are painted by reflectDrillLevel; only the type-visibility
        // gates reflect selectableTypes here.
        if (V2_LEVEL_KEYS.has(dataKey)) return
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

  return { reflectDrillLevel, attachFilterButtons }
}

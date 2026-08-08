// The #select-filter .sf-btn buttons — now a COLLAPSED picker, not an inline row.
//
// Two roles share the button set:
//   - the cluster/strand/domain/ends/xover/base buttons are the unified `selectionLevel`
//     selector (they drive `selectionManager.setSelectionLevel`); and
//   - the scaffold/staples/loops/skips/overhangs buttons are type-visibility gates
//     that plain-toggle `selectableTypes` ("what's pickable").
//
// The buttons live in the `#select-filter-menu` drop-down; the strip shows only
// `#select-filter-trigger`, whose icon+label report whatever is currently in force
// (`collapsedSelectable`). Clicking a LEVEL closes the menu (one-shot choice);
// toggling a gate leaves it open (you usually flip more than one).
//
// Tab (keyboard_shortcuts.js) calls `flashLevelChange(prev, next)`: the menu pops
// open read-only, a marker bar slides from the old level's row to the new one, and
// it closes ~250 ms later. Repeated Tabs restart the timer, so fast cycling reads as
// one continuous scroll down the list — which is why the level rows are laid out in
// TAB_CYCLE order (strand → dom → ends → xover → base → default), with the
// out-of-cycle `clust` after them.
//
// `selectionManager` is created AFTER this factory in main()'s init order (the
// factory's `reflectDrillLevel` is passed INTO its init as `onDrillLevel`), so it
// is reached through a lazy `getSelectionManager` getter — safe because every
// caller fires on user action, post-init. `attachFilterButtons()` registers the
// button handlers + subscribers and is called at the original ~4852 spot to
// preserve store-subscription order.

import { BTN_LEVEL, LEVEL_BTN as LEVEL_BTN_V2, normalizeLevel, toggleLevel } from '../scene/selection_level.js'

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
  [null, 'default'],
]

// Short label shown on each button and on the collapsed trigger. Keyed by dataKey
// because that is what the markup carries; two of them differ from the store key
// (`line`→dom, `ovhangs`→ovhg).
const KEY_LABEL = {
  strand: 'strand', line: 'dom', ends: 'ends', xover: 'xover', base: 'base',
  clust: 'clust', default: 'default', scaf: 'scaf', stap: 'stap',
  skip: 'skip', loop: 'loop', ovhangs: 'ovhg',
}

// The exclusive gate group, in the order it outranks the level on the trigger.
// Only one can be on at a time (computeFilterToggle clears the rest), so the order
// only matters for a hand-set store.
const EXCLUSIVE_GATES = [['overhangs', 'ovhangs'], ['loops', 'loop'], ['skips', 'skip']]

/**
 * Pure: what the collapsed "Selectable: …" trigger should say.
 *
 * An engaged skip/loop/ovhg gate OUTRANKS the level, because those already take
 * precedence over the level for both plain clicks and the lasso — the trigger
 * reports what you will actually hit, not what is merely armed.
 *
 * `note` is the scaffold/staple restriction, shown only when no exclusive gate is
 * up (turning one on clears scaf+stap, so "none" there would be misleading noise).
 *
 * @param {{selectionLevel?:string, selectableTypes?:object}} o
 * @returns {{key:string, label:string, note:string}} `key` is the dataKey whose
 *   icon + colour the trigger borrows.
 */
export function collapsedSelectable({ selectionLevel = 'default', selectableTypes = {} } = {}) {
  for (const [storeKey, dataKey] of EXCLUSIVE_GATES) {
    if (selectableTypes[storeKey]) return { key: dataKey, label: KEY_LABEL[dataKey], note: '' }
  }
  const key  = LEVEL_BTN_V2[normalizeLevel(selectionLevel)] ?? 'default'
  const scaf = !!selectableTypes.scaffold
  const stap = !!selectableTypes.staples
  const note = (scaf && stap) ? ''
    : scaf ? 'scaf only'
    : stap ? 'stap only'
    : 'none'
  return { key, label: KEY_LABEL[key], note }
}

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
  let _level     = 'default'   // last level reflected — the trigger reads it
  let _menuOpen  = false       // user opened it (a Tab flash does NOT set this)
  let _flashTid  = null

  const $menu    = () => document.getElementById('select-filter-menu')
  const $trigger = () => document.getElementById('select-filter-trigger')
  const $row     = dk => document.querySelector(`#select-filter .sf-btn[data-key="${dk}"]`)

  // ── The collapsed trigger ───────────────────────────────────────────────────

  // Repaint the trigger from the current level + selectableTypes. The icon is CLONED
  // from the matching row so each SVG exists exactly once in the markup.
  function refreshTrigger() {
    const trg = $trigger()
    if (!trg) return
    const { key, label, note } = collapsedSelectable({
      selectionLevel: _level, selectableTypes: store.getState().selectableTypes ?? {},
    })
    trg.dataset.key = key
    const icon = trg.querySelector('.sf-trigger-icon')
    const src  = $row(key)?.querySelector('svg')
    if (icon && src) icon.replaceChildren(src.cloneNode(true))
    const txt = trg.querySelector('.sf-trigger-text')
    if (txt) txt.textContent = label
    const nt = trg.querySelector('.sf-trigger-note')
    if (nt) nt.textContent = note
  }

  // ── Open / close ────────────────────────────────────────────────────────────

  function openMenu({ flash = false } = {}) {
    const menu = $menu()
    if (!menu) return
    menu.hidden = false
    menu.classList.toggle('sf-flash', flash)
    if (!flash) _menuOpen = true
    $trigger()?.classList.toggle('open', !flash)
  }

  function closeMenu() {
    const menu = $menu()
    if (menu) { menu.hidden = true; menu.classList.remove('sf-flash') }
    _menuOpen = false
    $trigger()?.classList.remove('open')
    if (_flashTid) { clearTimeout(_flashTid); _flashTid = null }
  }

  /**
   * Tab feedback: pop the menu open read-only, slide the marker from the outgoing
   * level's row to the incoming one, then close. Called from the Tab shortcut —
   * NOT from `reflectDrillLevel`, which also fires on every canvas click.
   *
   * A repeat Tab restarts the timer instead of closing, so holding Tab reads as one
   * continuous scroll. If the user has the menu open by hand, the marker still
   * slides but the menu is left open.
   */
  function flashLevelChange(prevLevel, nextLevel) {
    const menu = $menu()
    const marker = menu?.querySelector('.sf-menu-marker')
    if (!menu || !marker) return
    const wasPinned = _menuOpen
    if (!wasPinned) openMenu({ flash: true })

    const from = $row(LEVEL_BTN_V2[normalizeLevel(prevLevel)] ?? 'default')
    const to   = $row(LEVEL_BTN_V2[normalizeLevel(nextLevel)] ?? 'default')
    if (to) {
      const start = from ?? to
      marker.style.transition = 'none'
      marker.style.top    = `${start.offsetTop}px`
      marker.style.height = `${start.offsetHeight}px`
      void marker.offsetHeight   // flush the jump before arming the transition
      marker.style.transition = 'top 150ms cubic-bezier(0.4,0,0.2,1)'
      marker.style.top = `${to.offsetTop}px`
    }

    if (_flashTid) clearTimeout(_flashTid)
    if (wasPinned) { _flashTid = null; return }
    _flashTid = setTimeout(() => { _flashTid = null; closeMenu() }, 250)
  }

  // Light the filter button matching the engaged selectionLevel — the level
  // buttons ARE the selector. Paint ONLY the engaged level with .active (no red
  // border). `default` lights the explicit "default" row → the drill ladder.
  function reflectDrillLevel(level) {
    _level = normalizeLevel(level)
    const target = LEVEL_BTN_V2[_level] ?? 'default'
    for (const dk of [...Object.values(LEVEL_BTN_V2), 'default']) {
      const b = $row(dk)
      if (b) b.classList.toggle('active', dk === target)
    }
    refreshTrigger()
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

        // "default" is the no-level row (the drill ladder). It has no BTN_LEVEL
        // entry — `default` is the absence of an engaged level — so it is set
        // directly rather than through toggleLevel.
        if (dataKey === 'default') {
          getSelectionManager()?.setSelectionLevel?.('default')
          closeMenu()
          return
        }

        // The cluster/strand/domain/ends/xover buttons set the unified
        // selectionLevel (toggle off → default). They do NOT touch selectableTypes.
        // Picking a level is a one-shot choice → close. Gates stay open below.
        if (V2_LEVEL_KEYS.has(dataKey)) {
          const sm  = getSelectionManager()
          const cur = sm?.getSelectionLevel?.() ?? 'default'
          sm?.setSelectionLevel?.(toggleLevel(cur, BTN_LEVEL[dataKey]))
          closeMenu()
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
        // gates reflect selectableTypes here. `storeKey` is null for level-only rows.
        if (V2_LEVEL_KEYS.has(dataKey) || !storeKey) return
        btn.classList.toggle('active', !!store.getState().selectableTypes[storeKey])
      })
    }

    // The gates live behind the trigger now, so their state has to reach it.
    store.subscribe((newState, prevState) => {
      if (newState.selectableTypes !== prevState.selectableTypes) refreshTrigger()
    })

    // Trigger opens/closes; outside-click and Escape close. Escape is NOT swallowed —
    // keyboard_shortcuts.js also uses it to drop back to the default level.
    $trigger()?.addEventListener('click', () => {
      const { deformToolActive, translateRotateActive } = store.getState()
      if (deformToolActive || translateRotateActive) return
      _menuOpen ? closeMenu() : openMenu()
    })
    document.addEventListener('pointerdown', e => {
      if (!_menuOpen) return
      if (!_selectFilter?.contains(e.target)) closeMenu()
    })
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && _menuOpen) closeMenu()
    })

    refreshTrigger()

    // Lock the selectable filter while a tool is active
    store.subscribe((newState, prevState) => {
      if (newState.deformToolActive === prevState.deformToolActive &&
          newState.translateRotateActive === prevState.translateRotateActive) return
      const locked = !!(newState.deformToolActive || newState.translateRotateActive)
      _selectFilter?.classList.toggle('filter-inactive', locked)
      if (locked) closeMenu()
    })
  }

  return { reflectDrillLevel, attachFilterButtons, flashLevelChange }
}

/** Sole writer for canonical selection state. */

import { conjugateStrandRefs } from './element_clipboard.js'

import { createSelectionState, reduceSelection, reconcileSelection } from './selection_model.js'

export function createSelectionController({ store, context = 'design' }) {
  if (!store?.getState || !store?.setState) throw new TypeError('selection controller requires a store')

  const commit = selection => {
    const related = selection.context === 'design' ? conjugateStrandRefs(store.getState().currentDesign, selection.items) : []
    const canonical = createSelectionState({ ...selection, items: [...selection.items, ...related], primary: selection.primary })
    store.setState({ selection: canonical })
    return canonical
  }
  const dispatch = intent => {
    const current = createSelectionState(store.getState().selection)
    // Derived conjugates travel with their owner, including toggle/re-click removal.
    const related = new Set(conjugateStrandRefs(store.getState().currentDesign, current.items).map(r => r.id))
    const logical = createSelectionState({ ...current, items: current.items.filter(r => r.kind !== 'strand' || !related.has(r.id)) })
    const changesContext = intent?.type === 'reload' || intent?.type === 'changeContext'
    // This controller owns design refs. In assembly context the canonical slice is an
    // empty isolation sentinel; hidden design gestures and cross-window messages must
    // not repopulate it behind the assembly selection subsystem.
    if (!changesContext && current.context !== context) return current
    return commit(reduceSelection(logical, intent))
  }

  return {
    dispatch,
    replace: refs => dispatch({ type: 'replace', refs }),
    select: ref => dispatch({ type: 'select', ref }),
    toggle: ref => dispatch({ type: 'toggle', ref }),
    extend: refs => dispatch({ type: 'extend', refs }),
    clear: () => dispatch({ type: 'clear' }),
    setLevel: level => dispatch({ type: 'setLevel', level }),
    reload: context => dispatch({ type: 'reload', context }),
    reconcile: isLive => {
      const current = createSelectionState(store.getState().selection)
      return current.context === context ? commit(reconcileSelection(current, isLive)) : current
    },
    getState: () => createSelectionState(store.getState().selection),
  }
}

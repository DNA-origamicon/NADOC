/** Sole writer for canonical selection state. */

import { createSelectionState, reduceSelection, reconcileSelection } from './selection_model.js'

export function createSelectionController({ store, context = 'design' }) {
  if (!store?.getState || !store?.setState) throw new TypeError('selection controller requires a store')

  const commit = selection => {
    const canonical = createSelectionState(selection)
    store.setState({ selection: canonical })
    return canonical
  }
  const dispatch = intent => {
    const current = createSelectionState(store.getState().selection)
    const changesContext = intent?.type === 'reload' || intent?.type === 'changeContext'
    // This controller owns design refs. In assembly context the canonical slice is an
    // empty isolation sentinel; hidden design gestures and cross-window messages must
    // not repopulate it behind the assembly selection subsystem.
    if (!changesContext && current.context !== context) return current
    return commit(reduceSelection(current, intent))
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

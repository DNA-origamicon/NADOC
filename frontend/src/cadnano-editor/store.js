/**
 * Editor-local reactive store.
 *
 * Mirrors the pattern of ../state/store.js but is scoped only to the
 * cadnano editor page.  Does NOT share state with the main 3D window.
 *
 * Usage:
 *   import { editorStore } from './store.js'
 *   editorStore.subscribe((next, prev) => { ... })
 *   editorStore.setState({ selectedTool: 'pencil' })
 *   const { design } = editorStore.getState()
 */

const _initialState = {
  /** Full Design object from GET /api/design, or null. */
  design: null,

  /** Active tool in the pathview. */
  selectedTool: 'select',   // 'select' | 'pencil' | 'erase'

  /**
   * Strand being hovered in the pathview, or null.
   * Shape: { strandId: string, ntCount: number, strandType: string }
   */
  hoveredStrand: null,

  /** True while an API request is in flight. */
  loading: false,

  /** Last API error, or null. */
  lastError: null,
}

let _state = { ..._initialState }
const _listeners = new Set()

export const editorStore = {
  getState() {
    return _state
  },

  setState(partial) {
    const prev = _state
    _state = { ..._state, ...partial }
    for (const fn of _listeners) {
      try { fn(_state, prev) } catch (e) { console.error('[editorStore]', e) }
    }
  },

  subscribe(fn) {
    _listeners.add(fn)
    return () => _listeners.delete(fn)
  },
}

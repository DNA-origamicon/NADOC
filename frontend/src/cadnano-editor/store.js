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
  selectedTool: 'select',   // 'select' | 'pencil' | 'nick' | 'paint' | 'skip' | 'loop'

  /** Index into CADNANO_PALETTE for the paint tool (0–11). */
  paintColorIdx: 0,

  /**
   * Custom paint color (overrides paintColorIdx when non-null).
   * '#RRGGBB' hex string, or null to use the palette slot.
   */
  paintCustomColor: null,

  /**
   * Strand being hovered in the pathview, or null.
   * Shape: { strandId: string, ntCount: number, strandType: string }
   */
  hoveredStrand: null,

  /**
   * Which element types respond to the Select tool.
   *   strand — whole-strand selection (click selects entire strand)
   *   scaf   — scaffold strand bodies / ends
   *   stap   — staple strand bodies / ends
   *   ends   — 5′/3′ end-cap cells (square + triangle)
   *   xover  — crossover indicator sprites
   *   line   — strand body cells (non-end-cap positions)
   *   loop   — loop markers (delta > 0)
   *   skip   — skip markers (delta < 0)
   */
  selectFilter: { strand: true, scaf: true, stap: true, ends: true, xover: true, line: true, loop: true, skip: true },

  /** View-tool toggles — visual overlays that don't affect selection. */
  viewTools: { lengthHeatmap: false, sequences: false, undefinedBases: false, overhangNames: false, grid: true },

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

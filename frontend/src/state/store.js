/**
 * Client-side design state store.
 *
 * Single source of truth on the frontend.  All API client functions update
 * this store; all UI components subscribe to it.
 *
 * Usage:
 *   import { store } from './store.js'
 *   store.subscribe((newState, prevState) => { ... })
 *   store.setState({ selectedObject: { type: 'helix', id: 'h1' } })
 *   const { currentDesign } = store.getState()
 */

const _initialState = {
  /** The full Design object from the API, or null if not loaded. */
  currentDesign: null,

  /** Flat array of NucleotidePosition dicts from /api/design/geometry, or null. */
  currentGeometry: null,

  /** The current ValidationReport from the API, or null. */
  validationReport: null,

  /**
   * Currently selected object in the 3D scene, or null.
   * Shape: { type: 'nucleotide' | 'helix' | 'strand', id: string, data: any }
   */
  selectedObject: null,

  /**
   * When crossover placement mode is active, this holds the pending state.
   * Shape: { helixAId: string, helixBId: string, markers: CrossoverCandidate[] } | null
   */
  crossoverPlacement: null,

  /** Last API error, or null.  Shape: { status: number, message: string } */
  lastError: null,

  /**
   * Per-strand custom colour overrides.  Plain object: strand_id → hex number.
   * Persists across scene rebuilds.  Set via designRenderer.setStrandColor().
   */
  strandColors: {},

  /**
   * The lattice plane used for the most recent extrude.  Set by main.js after
   * a successful createBundle call.  Used to initialise the slice plane.
   * Shape: 'XY' | 'XZ' | 'YZ' | null
   */
  currentPlane: null,
}

function createStore(initial) {
  let _state = { ...initial }
  const _listeners = new Set()

  return {
    getState() {
      return _state
    },

    setState(partial) {
      const prev = _state
      _state = { ..._state, ...partial }
      for (const fn of _listeners) {
        fn(_state, prev)
      }
    },

    /** Subscribe to state changes.  Returns an unsubscribe function. */
    subscribe(fn) {
      _listeners.add(fn)
      return () => _listeners.delete(fn)
    },
  }
}

export const store = createStore(_initialState)

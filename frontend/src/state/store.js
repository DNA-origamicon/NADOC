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

  /**
   * Map of helix_id → { start: [x,y,z], end: [x,y,z] } for deformed axis arrows.
   * Null when no geometry has been loaded.  Updated by getGeometry().
   */
  currentHelixAxes: null,

  /**
   * True while the bend/twist deformation tool is active.
   * Set by deformation_editor.js; read by main.js to disable element selection.
   */
  deformToolActive: false,

  /** The current ValidationReport from the API, or null. */
  validationReport: null,

  /**
   * Strand IDs of circular staple strands (no free 5′/3′ ends).
   * Populated from validation.loop_strand_ids on every design response.
   * These strands are rendered red in the scene.
   */
  loopStrandIds: [],

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
   * Named strand groups.  Each group holds a name, an optional CSS hex color
   * string, and an array of strand IDs.  Group color overrides strandColors.
   * Shape: Array<{ id: string, name: string, color: string|null, strandIds: string[] }>
   */
  strandGroups: [],

  /**
   * Frontend undo stack for group mutations.  Each entry is a snapshot of
   * strandGroups before a change.  Max 50 entries.
   */
  strandGroupsHistory: [],

  /**
   * Strand IDs selected by the Ctrl+drag rectangle lasso tool.
   * Empty array when no multi-selection is active.
   */
  multiSelectedStrandIds: [],

  /**
   * The lattice plane used for the most recent extrude.  Set by main.js after
   * a successful createBundle call.  Used to initialise the slice plane.
   * Shape: 'XY' | 'XZ' | 'YZ' | null
   */
  currentPlane: null,

  /**
   * Selection filter — controls which element types respond to clicks.
   * Each key maps to a boolean (true = selectable).
   */
  selectableTypes: {
    scaffold:  true,
    staples:   true,
    bluntEnds: true,
    crossovers: true,
  },

  /**
   * Whether the physics (XPBD) layer is currently active.
   * When true, a yellow physics overlay is rendered alongside geometric positions.
   */
  physicsMode: false,

  /**
   * Relaxed backbone positions from the XPBD WebSocket stream.
   * Map of "helix_id:bp_index:direction" → [x, y, z] (nm), or null.
   * Null means no physics data is available (design mode).
   */
  physicsPositions: null,

  /**
   * Whether the 2D unfold view is currently active.
   * When true, helices are translated to a linear horizontal stack.
   */
  unfoldActive: false,

  /**
   * Helix IDs in the order they should appear in the 2D unfold stack
   * (top to bottom, label 1 at top).  Set from workspace cell selection order.
   */
  unfoldHelixOrder: null,

  /**
   * Spacing between helix rows in the 2D unfolded view (nm).
   * Default matches caDNAno's path panel row spacing.
   */
  unfoldSpacing: 2.5,

  /**
   * Whether helix axis number labels are visible.
   * Toggled via View > Toggle Helix Labels.  Default: visible.
   */
  showHelixLabels: true,

  /**
   * Whether the deformed-geometry visualization is currently active.
   * When true, helices are lerped from straight to deformed positions.
   * Toggled via View > Toggle Deformed View.
   */
  deformVisuActive: true,

  /**
   * Straight (un-deformed) nucleotide geometry — same shape as currentGeometry
   * but with deformations=[] applied.  Used as the t=0 anchor for deform lerp.
   * Null until getStraightGeometry() is called.
   */
  straightGeometry: null,

  /**
   * Straight helix axes — same shape as currentHelixAxes but un-deformed.
   * Null until getStraightGeometry() is called.
   */
  straightHelixAxes: null,

  /**
   * When true, all staple strands are hidden in the 3D scene.
   * Toggled via View > Hide Staples.
   */
  staplesHidden: false,

  /**
   * Strand ID of the currently isolated staple strand, or null.
   * When set, all other non-scaffold strands are ghosted (dimmed).
   * Set via right-click context menu "Isolate" / "Un-isolate".
   */
  isolatedStrandId: null,

  /**
   * When true, base-letter sprites are shown at each nucleotide position.
   * Unassigned bases are shown in red; assigned bases use ATGC colours.
   * Toggled via View > Sequences.
   */
  showSequences: false,

  /**
   * True when the debug overlay (View > Debug / backtick) is active.
   * Mirrored here so other modules can subscribe to it.
   */
  debugOverlayActive: false,

  /**
   * Current atomistic display mode.  'off' = no atomistic overlay;
   * 'vdw' = space-filling Van der Waals spheres;
   * 'ballstick' = ball-and-stick with bond cylinders.
   */
  atomisticMode: 'off',
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

/** Save current strandGroups to the undo history before mutating. */
export function pushGroupUndo() {
  const { strandGroups, strandGroupsHistory } = store.getState()
  store.setState({ strandGroupsHistory: [...strandGroupsHistory.slice(-49), strandGroups] })
}

/**
 * Pop the most recent strandGroups snapshot and restore it.
 * Returns true if something was undone, false if the history was empty.
 */
export function popGroupUndo() {
  const { strandGroupsHistory } = store.getState()
  if (!strandGroupsHistory.length) return false
  const prev = strandGroupsHistory[strandGroupsHistory.length - 1]
  store.setState({
    strandGroups:        prev,
    strandGroupsHistory: strandGroupsHistory.slice(0, -1),
  })
  return true
}

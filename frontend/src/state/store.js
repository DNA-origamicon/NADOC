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

  /**
   * True when the active design was imported from a caDNAno file and has not yet
   * had automerge applied.  Used to show a routing-change warning
   * before that operation overwrites the imported staple routing.
   * Cleared automatically once the user confirms the operation.
   */
  isCadnanoImport: false,

  /** Flat array of NucleotidePosition dicts from /api/design/geometry, or null. */
  currentGeometry: null,

  /**
   * Set after a partial geometry merge (Fix B).  Holds the changed_helix_ids
   * from the last response so design_renderer can try an in-place fast path.
   * Null after any full-geometry replace.
   */
  lastPartialChangedHelixIds: null,

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

  /** ID of the cluster whose gizmo is currently active, or null. */
  activeClusterId: null,

  /** True while the Translate/Rotate tool is active. */
  translateRotateActive: false,

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
   * Domains selected by the Ctrl+drag rectangle lasso tool (when the
   * 'domains' selection filter is active).
   * Each entry: { strandId: string, domainIndex: number }.
   * Empty array when no domain multi-selection is active.
   */
  multiSelectedDomainIds: [],

  /**
   * Overhang IDs selected by the lasso tool (when the 'overhangs' selection
   * filter is active).  Empty array when no overhang multi-selection is active.
   */
  multiSelectedOverhangIds: [],

  /**
   * The lattice plane used for the most recent extrude.  Set by main.js after
   * a successful createBundle call.  Used to initialise the slice plane.
   * Shape: 'XY' | 'XZ' | 'YZ' | null
   */
  currentPlane: null,

  /**
   * Tool filter — controls visibility/activation of overlay tools.
   * bluntEnds: show blunt-end markers + enable click interaction.
   */
  toolFilters: {
    bluntEnds:          true,
    overhangLocations:  false,
    extensionLocations: true,   // show/hide strand extension beads and fluorophores
  },

  /**
   * Selection filter — controls which element types respond to clicks/lasso.
   * scaffold/staples: global strand-type filter (applies to strands, ends, arcs).
   * strands/ends: category on/off switches.
   * loops/skips: independent — not filtered by scaffold/staples (always paired).
   */
  selectableTypes: {
    scaffold:      true,   // global: include scaffold elements (strands/ends/arcs)
    staples:       true,   // global: include staple elements (strands/ends/arcs)

    strands:       true,   // category: whole-strand selection
    domains:       false,  // category: domain-level selection (sub-strand granularity)
    ends:          false,  // category: end bead selection enabled
    crossoverArcs: false,  // category: crossover arc/line selection

    loops:         false,  // independent: loop marker selection
    skips:         false,  // independent: skip marker selection
    extensions:    false,  // independent: extension bead click/lasso selection
    overhangs:     false,  // independent: overhang domain selection (lasso + click)
  },

  /** Relaxed backbone positions from mrdna CG simulation, or null.
   *  Map of "helix_id:bp_index:direction" → [x, y, z] (nm). */
  cgRelaxPositions: null,

  /** Stats from the last mrdna CG relaxation, or null. */
  cgRelaxStats: null,

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
   * When true, cadnano mode is active: beads are displayed as two flat tracks
   * per helix row (scaffold / staple), orthographic camera is used, and
   * the BP ruler + row-band overlays are visible.
   */
  cadnanoActive: false,

  /**
   * Whether helix axis number labels are visible.
   * Toggled via View > Toggle Helix Labels.  Default: hidden.
   */
  showHelixLabels: false,

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

  /** When true, overhang name labels are shown in the 3D scene. */
  showOverhangNames: false,

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

  /**
   * Current surface display mode.  'off' = no surface; 'on' = surface active.
   * Probe radius controls the smoothness (see surfaceOpacity, surfaceColorMode).
   */
  surfaceMode: 'off',

  /** Surface colour mode: 'strand' = strand-palette per-vertex, 'uniform' = flat grey. */
  surfaceColorMode: 'strand',

  /** Surface opacity (0–1). */
  surfaceOpacity: 0.85,

  /**
   * Global coloring mode applied to all representations except Hull Prism
   * (and Cylinders falls back to strand for 'base' since cylinders span bps).
   * 'strand'  — palette/group/custom per strand (default)
   * 'base'    — A/T/G/C per nucleotide; unknown bases stay at strand colour
   * 'cluster' — palette per cluster; nucs not in any cluster stay at strand colour
   * 'cpk'     — atomistic CPK (per-element).  Bead/slab/cone/cylinder views
   *             fall back to strand colour since CPK has no meaning there.
   */
  coloringMode: 'strand',

  // ── Domain Designer (Phase 3 overhang revamp) ─────────────────────────────────

  /**
   * Domain Designer — popup-local selection state.
   *
   * Selection here is intentionally NOT mirrored to the main-scene
   * `selectedObject` / `multiSelectedOverhangIds`; clicks inside the popup must
   * not move the 3D scene cursor, and main-scene selection does not react to
   * popup state while the modal is open. See plan §D.
   *
   * Belongs to the `selection` slice so the modal coalesces re-renders with
   * other selection changes.
   */
  domainDesigner: {
    /** Currently-focused OverhangSpec.id in the Domain Designer pane. */
    selectedOverhangId: null,
    /** Currently-focused SubDomain.id within `selectedOverhangId`. */
    selectedSubDomainId: null,
    /** helix_ids whose details-rows are expanded in the left listing. */
    expandedHelices: new Set(),
    /** 'preview' | 'pathview' | 'annotations' — last clicked pane (focus hint). */
    activePane: 'preview',
    /** True while the Overhangs Manager modal is open AND the Domain Designer
     *  tab is active. While true, design_renderer.js suppresses main-scene
     *  rebuilds; on the True→False transition the suppressed update flushes
     *  as a single rebuild against the most-recent design + geometry. */
    modalActive: false,
  },

  // ── Assembly layer ────────────────────────────────────────────────────────────

  /**
   * The active Assembly object from the API, or null if no assembly is loaded.
   */
  currentAssembly: null,

  /**
   * True when Assembly Mode is active — the assembly layer is shown in the scene.
   */
  assemblyActive: false,

  /**
   * ID of the currently selected PartInstance in the assembly, or null.
   */
  activeInstanceId: null,
}

/**
 * Slice definitions — each slice is the set of store keys it owns.
 *
 * Modules that react exclusively to one concern can subscribe to a named slice
 * (store.subscribeSlice) instead of the global store.subscribe, so their
 * callback is only invoked when a key in that slice changes.
 *
 * Keys not listed here still work normally via the global store.subscribe.
 */
const _SLICES = {
  /** mrdna CG-relax overlay */
  physics:   new Set(['cgRelaxPositions', 'cgRelaxStats']),

  /** Visual display toggles: unfold, deform, surface, atomistic, labels */
  viz:       new Set(['unfoldActive', 'unfoldHelixOrder', 'unfoldSpacing', 'cadnanoActive',
                      'deformVisuActive', 'straightGeometry', 'straightHelixAxes',
                      'showHelixLabels', 'atomisticMode', 'surfaceMode',
                      'surfaceColorMode', 'surfaceOpacity', 'coloringMode',
                      'staplesHidden', 'isolatedStrandId', 'showSequences']),

  /** Selection, multi-select, active tools, crossover placement */
  selection: new Set(['selectedObject', 'multiSelectedStrandIds', 'multiSelectedDomainIds',
                      'multiSelectedOverhangIds',
                      'selectableTypes', 'crossoverPlacement', 'deformToolActive',
                      'activeClusterId', 'translateRotateActive', 'debugOverlayActive',
                      'domainDesigner']),

  /** Design topology + derived geometry */
  design:    new Set(['currentDesign', 'currentGeometry', 'currentHelixAxes', 'currentPlane',
                      'loopStrandIds', 'isCadnanoImport', 'validationReport',
                      'lastPartialChangedHelixIds']),

  /** Strand colour overrides and groups */
  style:     new Set(['strandColors', 'strandGroups', 'strandGroupsHistory']),

  /** Tool panel toggles and error state */
  ui:        new Set(['toolFilters', 'lastError']),

  /** Assembly layer: active assembly, mode flag, selected instance */
  assembly:  new Set(['currentAssembly', 'assemblyActive', 'activeInstanceId']),
}

function createStore(initial) {
  let _state = { ...initial }
  const _listeners = new Set()

  // One listener Set per slice name
  const _sliceListeners = Object.fromEntries(
    Object.keys(_SLICES).map(name => [name, new Set()])
  )

  return {
    getState() {
      return _state
    },

    setState(partial) {
      const prev = _state
      _state = { ..._state, ...partial }

      // Notify global listeners first (preserves existing subscription order)
      for (const fn of _listeners) fn(_state, prev)

      // Notify slice listeners — only for slices that contain a changed key
      const changedKeys = Object.keys(partial)
      for (const [sliceName, keys] of Object.entries(_SLICES)) {
        if (changedKeys.some(k => keys.has(k))) {
          for (const fn of _sliceListeners[sliceName]) fn(_state, prev)
        }
      }
    },

    /** Subscribe to ALL state changes.  Returns an unsubscribe function. */
    subscribe(fn) {
      _listeners.add(fn)
      return () => _listeners.delete(fn)
    },

    /**
     * Subscribe to changes in a named feature slice only.
     * The callback is invoked with (newState, prevState) — same signature as
     * store.subscribe — but only when at least one key in the slice changes.
     *
     * Available slices: 'physics' | 'viz' | 'selection' | 'design' | 'style' | 'ui'
     *
     * @param {string}   sliceName
     * @param {Function} fn  (newState, prevState) => void
     * @returns {Function}   unsubscribe function
     */
    subscribeSlice(sliceName, fn) {
      if (!_sliceListeners[sliceName]) {
        throw new Error(`store.subscribeSlice: unknown slice "${sliceName}". ` +
                        `Available: ${Object.keys(_SLICES).join(', ')}`)
      }
      _sliceListeners[sliceName].add(fn)
      return () => _sliceListeners[sliceName].delete(fn)
    },
  }
}

export const store = createStore(_initialState)

// ── Domain Designer action helpers (Phase 3 overhang revamp) ──────────────────

/**
 * Patch `store.domainDesigner` selection fields.
 *
 * Partial fields supported: `{ overhangId, subDomainId, activePane }`.
 * `null` clears the field; `undefined` leaves it unchanged.
 *
 * Switching overhang clears the sub-domain selection unless one is provided.
 */
export function setDomainDesignerSelection({ overhangId, subDomainId, activePane } = {}) {
  const prev = store.getState().domainDesigner
  const next = { ...prev }
  if (overhangId !== undefined) {
    next.selectedOverhangId = overhangId
    // Auto-clear sub-domain when overhang changes unless caller specified one
    if (subDomainId === undefined && overhangId !== prev.selectedOverhangId) {
      next.selectedSubDomainId = null
    }
  }
  if (subDomainId !== undefined) next.selectedSubDomainId = subDomainId
  if (activePane  !== undefined) next.activePane          = activePane
  store.setState({ domainDesigner: next })
}

/** Mark the Domain Designer modal as open / closed.
 *  When this flips True→False, design_renderer flushes its deferred rebuild. */
export function setDomainDesignerModalActive(active) {
  const prev = store.getState().domainDesigner
  if (prev.modalActive === !!active) return
  store.setState({ domainDesigner: { ...prev, modalActive: !!active } })
}


/** Toggle a helix's expanded state in the Domain Designer left listing. */
export function toggleDomainDesignerHelix(helixId) {
  const prev = store.getState().domainDesigner
  const expanded = new Set(prev.expandedHelices)
  if (expanded.has(helixId)) expanded.delete(helixId)
  else                       expanded.add(helixId)
  store.setState({ domainDesigner: { ...prev, expandedHelices: expanded } })
}

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

// Atomistic + molecular-surface display controllers (extracted from main.js #86).
//
// Owns everything that drives the all-atom (Phase AA) renderer, the VdW/SES
// surface renderer, AND the per-region mixed-representation overlays
// (vdw/ballstick/surface pinned to a focal domain). These three share one
// atom-data fetch cache, one strand→colour mapping, and one CG-visibility
// toggle, so they form a single cohesive subsystem rather than three modules.
//
// `atomisticRenderer` + `surfaceRenderer` stay constructed in main.js (the
// animation player + MD panel + representation switcher also reference them) and
// are injected; the three region-overlay renderers are owned here. All store
// subscribers register at init time — placed in main.js at the original spot so
// registration order (atom cache-invalidate BEFORE region-overlay re-apply) is
// preserved.
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { initSurfaceRenderer } from './surface_renderer.js'
import { repColumnsByRep } from './representation_overrides.js'
import { filterAtomData } from './atom_filter.js'
import { surfaceSegments } from './design_queries.js'
import { buildNucLetterMap, buildStapleColorMap } from './helix_renderer.js'
import {
  atomColorsFromLetters,
  computeAtomStrandColors,
  computeAtomStrandAlphas,
  computeAtomNucAlphas,
  computeAtomNucColors,
} from './color_util.js'
import { clusterDisplaySignature } from './cluster_entries.js'
import { showPersistentToast, dismissToast, showToast } from '../ui/toast.js'
import { docHeaders } from '../shared/doc_id.js'
import { parseSurfaceBin } from './surface_bin.js'

// Stable signature for a design's per-region surface columns — used to skip a
// (slow) surface recompute when the pinned columns are unchanged.
export function regionSurfaceSignature(design) {
  return surfaceSegments(design)
    .map(s => `${s.helix_id}:${s.bp_start}-${s.bp_end}`).sort().join('|')
}

export function initAtomSurfaceDisplay({
  scene, store, api, designRenderer, atomisticRenderer, surfaceRenderer,
  unfoldView, overhangLinkArcs,
  // (kind: 'atomistic' | 'surface') → true when a simulation overlay is active AND can
  // actually rebuild THAT kind from the job's atoms + relaxed frame (oxDNA or NAMD:
  // relaxed / rmsf / trajectory).  When so, switching to atomistic/surface skips the
  // DESIGN heavy build (the "native flash") and keeps the relaxed CG up until the overlay
  // swaps in.  It MUST be asked per kind: the live NAMD display drives atomistic and never
  // surface, and a NAMD flexibility map drives neither — deferring to an overlay that
  // cannot deliver leaves a blank surface / empty atoms on screen forever.
  getSimOverlayWillDriveHeavy = () => false,
  // Called when a surface option (probe radius / colour mode) changes WHILE a sim overlay
  // owns the surface — the overlay must re-generate its mesh with the new params (the
  // design-surface path doesn't apply).  Reads the live params via getSurfaceParams().
  onSurfaceParamsChanged = () => {},
}) {
  // ── Per-region overlay renderers (mixed representation) ─────────────────────
  // A focal domain/strand/cluster can be pinned to surface / vdw / ballstick; the
  // helix renderer auto-hides the CG beads/cylinders at those columns and these
  // overlays draw the region. Two atomistic instances because vdw and ballstick
  // are distinct geometry and each renderer holds a single mode.
  const regionVdwRenderer       = initAtomisticRenderer(scene)
  const regionBallstickRenderer = initAtomisticRenderer(scene)
  const regionSurfaceRenderer = initSurfaceRenderer(scene)   // per-region SURFACE overlay
  // Guards the cluster-display repaint against gizmo-drag thrash (see the colour
  // subscriber below).
  let _clusterDisplaySig = ''
  if (window.__NADOC_DBG__) {
    window.__NADOC_DBG__.regionVdwRenderer       = regionVdwRenderer
    window.__NADOC_DBG__.regionBallstickRenderer = regionBallstickRenderer
    window.__NADOC_DBG__.regionSurfaceRenderer   = regionSurfaceRenderer
  }

  let _surfaceDataCache   = null   // cached API response; null = needs re-fetch
  let _surfaceProbeRadius = 0.28   // current probe radius for SES (nm)
  let _surfaceDetail      = 'coarse'  // 'coarse' = fast CG-bead envelope | 'fine' = full all-atom
  let _surfaceMode        = 'off'  // mirrors store.surfaceMode
  let _atomDataCache  = null
  let _regionSurfaceSig   = null
  let _regionSurfaceTimer = null

  // Atomistic-only option rows (shown only while atomistic mode is active).
  // Coloring for atomistic now lives in the unified Representation-Options
  // coloring array (ui/coloring_options_panel.js), so only the radius slider
  // remains here.
  const _atomisticSliderRowIds = [
    'repr-atom-radius-row',
  ]

  function _setSurfacePanelVisible(visible) {
    const el = document.getElementById('surface-options-panel')
    if (el) el.style.display = visible ? '' : 'none'
  }

  async function _applySurfaceMode(mode) {
    _surfaceMode = mode
    if (mode === 'off') {
      surfaceRenderer.dispose()
      _surfaceDataCache = null
      // Only restore CG if atomistic overlay is also off
      if (atomisticRenderer.getMode() === 'off') _setCGVisible(true)
      _setSurfacePanelVisible(false)
      return
    }
    // A sim overlay (relaxed/rmsf/trajectory) will rebuild the surface from the job's
    // atoms + relaxed frame — so DON'T compute+show the DESIGN surface first (the "native
    // flash").  Keep the relaxed CG up until the overlay's mesh lands (it hides CG on
    // apply via onHeavyApplied).
    const _deferToOverlay = !!getSimOverlayWillDriveHeavy('surface')
    _setCGVisible(_deferToOverlay)
    if (atomisticRenderer.getMode() !== 'off') {
      atomisticRenderer.setMode('off')
      store.setState({ atomisticMode: 'off' })
    }
    _setSurfacePanelVisible(true)
    if (_deferToOverlay) {
      // Activate the surface renderer NOW with an empty mesh (mode 'on' + a mesh for the
      // overlay's applyPositionLerp to populate).  Without this the design-surface update()
      // is skipped, so the renderer stays mode 'off' with no mesh and the overlay's
      // _pushSurface bails → the surface never renders.  Mirrors how the atomistic defer
      // sets atomisticRenderer.setMode() up front.
      surfaceRenderer.update({ vertices: [], faces: [] },
                             store.getState().surfaceColorMode ?? 'strand')
      return
    }
    if (!_surfaceDataCache) {
      showPersistentToast('Computing surface…')
      try {
        const { surfaceColorMode } = store.getState()
        const params = { color_mode: surfaceColorMode, probe_radius: _surfaceProbeRadius,
                         detail: _surfaceDetail }
        // Binary-first: ~2× smaller AND no million-number JSON.parse (which blocks the main
        // thread on a big design). The blob carries the strand-index table so client-side
        // recolour still works. Fall back to the JSON route if the binary path yields nothing.
        let data = null
        if (typeof api.getDesignSurfaceBin === 'function') {
          const buf = await api.getDesignSurfaceBin(params)
          if (buf) data = parseSurfaceBin(buf)
        }
        if (!data) {
          const url = `/api/design/surface?color_mode=${surfaceColorMode}&probe_radius=${_surfaceProbeRadius}&detail=${_surfaceDetail}`
          const resp = await fetch(url, { headers: docHeaders() })
          if (!resp.ok) {
            dismissToast()
            console.error('Surface fetch failed:', resp.status)
            return
          }
          data = await resp.json()
        }
        _surfaceDataCache = data
        console.debug(`Surface computed: ${_surfaceDataCache.stats?.n_verts ?? _surfaceDataCache.vertices?.length / 3} verts`)
      } catch (e) {
        dismissToast()
        console.error('Surface fetch error:', e)
        return
      }
      dismissToast()
    }
    const { surfaceColorMode, surfaceOpacity } = store.getState()
    // ChimeraX-quality builds a SEPARATE surface per strand (real geometric gaps between
    // strands), so every vertex is unambiguously one strand and per-vertex colours are
    // already solid — the crisp-zone face-flatten (for the fused mesh) isn't needed here.
    surfaceRenderer.setCrispZones?.(false)
    surfaceRenderer.update(_surfaceDataCache, surfaceColorMode)
    surfaceRenderer.applyStrandColors(_getAtomStrandColors())
    surfaceRenderer.setOpacity(surfaceOpacity)
  }

  // Invalidate surface cache on design/geometry change
  store.subscribe((newState, prevState) => {
    const designChanged   = newState.currentDesign   !== prevState.currentDesign
    const geometryChanged = newState.currentGeometry !== prevState.currentGeometry ||
                            newState.currentHelixAxes !== prevState.currentHelixAxes
    if (designChanged || geometryChanged) {
      _surfaceDataCache = null
      if (_surfaceMode !== 'off') _applySurfaceMode(_surfaceMode)
    }
  })

  // Live surface option updates
  store.subscribe((newState, prevState) => {
    if (newState.surfaceColorMode !== prevState.surfaceColorMode) {
      if (_surfaceMode !== 'off') {
        if (getSimOverlayWillDriveHeavy('surface') && newState.surfaceColorMode !== 'uniform') {
          // Overlay owns the surface and needs strand vertex colours it may not have →
          // set the renderer's colour mode so the regenerated mesh's colours are applied,
          // then re-generate the overlay mesh (with the new color_mode). Uniform is in-place.
          surfaceRenderer.setColorMode(newState.surfaceColorMode)
          onSurfaceParamsChanged()
        } else if (newState.surfaceColorMode === 'uniform' || _surfaceDataCache?.vertex_colors) {
          // Switch colour in-place — no re-fetch needed
          surfaceRenderer.setColorMode(newState.surfaceColorMode)
        } else {
          // Need vertex colours but cache lacks them — re-fetch with new color_mode
          _surfaceDataCache = null
          _applySurfaceMode(_surfaceMode)
        }
      }
    }
    if (newState.surfaceOpacity !== prevState.surfaceOpacity) {
      surfaceRenderer.setOpacity(newState.surfaceOpacity)
    }
  })

  // Surface opacity slider
  const _slSurfaceOpacity = document.getElementById('sl-surface-opacity')
  const _svSurfaceOpacity = document.getElementById('sv-surface-opacity')
  _slSurfaceOpacity?.addEventListener('input', () => {
    const val = parseFloat(_slSurfaceOpacity.value)
    if (_svSurfaceOpacity) _svSurfaceOpacity.textContent = val.toFixed(2)
    store.setState({ surfaceOpacity: val })
  })

  // Surface probe radius slider (SES only)
  const _slSurfaceProbe = document.getElementById('sl-surface-probe')
  const _svSurfaceProbe = document.getElementById('sv-surface-probe')
  _slSurfaceProbe?.addEventListener('input', () => {
    _surfaceProbeRadius = parseFloat(_slSurfaceProbe.value)
    if (_svSurfaceProbe) _svSurfaceProbe.textContent = _surfaceProbeRadius.toFixed(2)
    _regenSurfaceForParamChange()
  })

  // High-detail toggle: off = fast coarse CG-bead envelope (default), on = exact all-atom.
  const _cbHighDetail = document.getElementById('cb-surface-highdetail')
  _cbHighDetail?.addEventListener('change', () => {
    // Ignored while ChimeraX quality owns the detail level (checkbox is disabled then).
    if (_cbChimerax?.checked) return
    _surfaceDetail = _cbHighDetail.checked ? 'fine' : 'coarse'
    _regenSurfaceForParamChange()
  })

  // EXPERIMENTAL "ChimeraX quality" toggle: high-fidelity SES at a fine 0.5 Å grid +
  // 1.4 Å water probe + true VdW radii (detail='chimerax'). Overrides High detail while on.
  const _cbChimerax = document.getElementById('cb-surface-chimerax')
  _cbChimerax?.addEventListener('change', () => {
    if (_cbChimerax.checked) {
      _surfaceDetail = 'chimerax'
      if (_cbHighDetail) _cbHighDetail.disabled = true
    } else {
      _surfaceDetail = _cbHighDetail?.checked ? 'fine' : 'coarse'
      if (_cbHighDetail) _cbHighDetail.disabled = false
    }
    _regenSurfaceForParamChange()
  })

  // Re-generate the active surface after a param change: if a sim overlay owns it,
  // re-run the overlay's surface fetch (with the new params) — _applySurfaceMode would
  // take the defer path and just blank it; otherwise re-fetch the design surface.
  function _regenSurfaceForParamChange() {
    if (_surfaceMode === 'off') return
    if (getSimOverlayWillDriveHeavy('surface')) onSurfaceParamsChanged()
    else { _surfaceDataCache = null; _applySurfaceMode('on') }
  }

  // Surface colour-mode toggle buttons
  document.getElementById('surface-color-strand')?.addEventListener('click', () => {
    document.getElementById('surface-color-strand')?.classList.add('active')
    document.getElementById('surface-color-uniform')?.classList.remove('active')
    store.setState({ surfaceColorMode: 'strand' })
  })
  document.getElementById('surface-color-uniform')?.addEventListener('click', () => {
    document.getElementById('surface-color-uniform')?.classList.add('active')
    document.getElementById('surface-color-strand')?.classList.remove('active')
    store.setState({ surfaceColorMode: 'uniform' })
  })

  // Atom radius scale slider
  const _slAtomVdwScale = document.getElementById('sl-atom-vdw-scale')
  const _svAtomVdwScale = document.getElementById('sv-atom-vdw-scale')
  _slAtomVdwScale?.addEventListener('input', () => {
    const scale = parseFloat(_slAtomVdwScale.value)
    if (_svAtomVdwScale) _svAtomVdwScale.textContent = scale.toFixed(2)
    atomisticRenderer.setVdwScale(scale)
  })

  async function _refetchAtomistic() {
    if (atomisticRenderer.getMode() === 'off') return
    try {
      const resp = await fetch(_atomisticUrl(), { headers: docHeaders() })
      if (!resp.ok) { console.error('Atomistic refetch failed:', resp.status); return }
      _atomDataCache = await resp.json()
      atomisticRenderer.update(_atomDataCache)
      _refreshAtomColors()
      const { selectedObject, multiSelectedStrandIds } = store.getState()
      atomisticRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
    } catch (e) {
      console.error('Atomistic refetch error:', e)
    }
  }

  // Atom colouring toggle
  // Backend-canonical staple palette (matches helix_renderer.STAPLE_PALETTE).
  // Pure colour-mapping core lives in scene/color_util.js (computeAtomStrandColors);
  // this wrapper reads the store snapshot + builds the staple palette for it.
  function _getAtomStrandColors() {
    const state = store.getState()
    const { currentDesign, currentGeometry } = state
    const staplePalette = (currentDesign && currentGeometry)
      ? buildStapleColorMap(currentGeometry, currentDesign) : null
    return computeAtomStrandColors(state, staplePalette)
  }

  // Build per-atom base-letter colour map (key: "strand_id:bp_index:direction").
  // The store/geometry read lives here; the pure mapping is atomColorsFromLetters.
  function _getAtomBaseColors() {
    const { currentDesign, currentGeometry } = store.getState()
    if (!currentDesign || !currentGeometry) return new Map()
    return atomColorsFromLetters(buildNucLetterMap(currentDesign, currentGeometry))
  }

  // Dispatch atomistic colouring based on the global coloringMode.
  // The strand map we send mirrors coloringMode ('strand' uses palette/groups,
  // 'cluster' uses cluster-mapped colours).  It is still needed under 'base' as the
  // fallback for atoms with no base-letter key of their own — crossover extra bases
  // and extension tails, which carry their anchor nucleotide's key.
  function _refreshAtomColors() {
    const { coloringMode } = store.getState()
    const strandMap = _getAtomStrandColors()
    if (coloringMode === 'base') {
      atomisticRenderer.setColorMode('base', strandMap, _getAtomBaseColors())
    } else if (coloringMode === 'cpk') {
      atomisticRenderer.setColorMode('cpk', strandMap)
    } else {
      // 'strand' or 'cluster' → strand-color path; map already reflects mode.
      atomisticRenderer.setColorMode('strand', strandMap)
    }
  }

  /**
   * Push per-cluster colour + opacity at both renderers, per NUCLEOTIDE.
   *
   * Both resolve on the app-wide `helix:bp:direction` key. A strand id is too coarse: a
   * strand can pass through several clusters and the scaffold passes through nearly all
   * of them, so a strand-keyed lookup paints the whole scaffold with whichever cluster
   * owns its first domain (LESSONS D15).
   *
   * The surface gets the strand-keyed maps too, as a fallback — a payload without
   * `vertex_nuc_index_table` (one cached before the backend shipped it, or a producer with
   * no nucleotide identity) still fades, just at strand granularity. The renderer picks
   * the space per payload.
   */
  function refreshClusterDisplay(design = null) {
    const d     = design ?? store.getState().currentDesign
    const state = design ? { ...store.getState(), currentDesign: design } : store.getState()
    const nucAlphas = computeAtomNucAlphas(d)
    const nucColors = computeAtomNucColors(state)
    const surfaceMaps = {
      nucAlphas, nucColors,
      strandAlphas: computeAtomStrandAlphas(d),
      strandColors: state.coloringMode === 'cluster' ? computeAtomStrandColors(state, null) : null,
    }
    atomisticRenderer.setClusterDisplay(nucAlphas, nucColors)
    surfaceRenderer.applyClusterDisplay(surfaceMaps)
    // The mixed-representation region overlays are separate renderer instances and
    // draw the same strands, so they must fade in step or a region pinned to
    // vdw/surface would stay opaque inside a faded cluster.
    regionVdwRenderer.setClusterDisplay(nucAlphas, nucColors)
    regionBallstickRenderer.setClusterDisplay(nucAlphas, nucColors)
    regionSurfaceRenderer.applyClusterDisplay(surfaceMaps)
  }

  // Keep atom + surface strand colours in sync when groups/colors change.
  // Always refresh regardless of CPK/strand mode so extra-base coloring stays current.
  store.subscribe((newState, prevState) => {
    // Per-cluster opacity lives on design.cluster_transforms, which none of the keys
    // below track — a swatch drag changes neither coloringMode nor strandColors, so
    // without this guard the fade never reached either renderer. Signature-keyed
    // because cluster_transforms is replaced on every gizmo-drag patch (~60/s) while
    // only the pose moves.
    const sig = clusterDisplaySignature(newState.currentDesign)
    const clusterChanged = sig !== _clusterDisplaySig
    if (clusterChanged) _clusterDisplaySig = sig
    if (!clusterChanged
        && newState.strandColors === prevState.strandColors
        && newState.strandGroups === prevState.strandGroups
        && newState.coloringMode === prevState.coloringMode
        && newState.loopStrandIds === prevState.loopStrandIds) return
    if (clusterChanged || newState.coloringMode !== prevState.coloringMode) {
      refreshClusterDisplay(newState.currentDesign)
    }
    if (atomisticRenderer.getMode() !== 'off') _refreshAtomColors()
    if (_surfaceMode !== 'off') {
      surfaceRenderer.applyStrandColors(_getAtomStrandColors())
    }
  })

  function _setAtomisticSlidersVisible(visible) {
    for (const id of _atomisticSliderRowIds) {
      const el = document.getElementById(id)
      if (el) el.style.display = visible ? '' : 'none'
    }
  }

  function _setCGVisible(visible) {
    // Go through setDesignVisible, NOT root.visible directly: the renderer re-applies
    // `_designVisible` after every rebuild, so poking the root left the flag stale at
    // `true` and any later rebuild (e.g. setExtraNucleotides from the oxDNA capture
    // strands) resurrected the CG model on top of the atomistic rep.
    // Extra-base beads/slabs are children of root, so they follow automatically.
    if (typeof designRenderer.setDesignVisible === 'function') designRenderer.setDesignVisible(visible)
    else { const root = designRenderer.getHelixCtrl()?.root; if (root) root.visible = visible }
    // Arc lines track design visibility; the coarse cylinders/sticks LOD no longer
    // hides the whole group — instead each arc is collapsed per-region by the
    // mixed-representation rep gate (unfold_view._arcRepHidden), so a region pinned
    // to full still shows its crossovers under a global cylinder LOD.
    unfoldView?.setArcsVisible(visible)
    unfoldView?.refreshArcVisibility()
    overhangLinkArcs?.setVisible?.(visible)
  }

  // MD SEED view: when set (e.g. 'auto'), the atomistic reps show the t=0,
  // PRE-MINIMISATION coordinates the simulation actually starts from, for every
  // atom — exact phosphodiester linkers instead of the display build's cheap
  // interpolation, and the lattice pre-expanded to the measured relaxed spacing.
  // Driven by the "Adjust for Extra Bases" view toggle.
  let _seedLatticeNm = null

  function _atomisticUrl() {
    return _seedLatticeNm === null
      ? '/api/design/atomistic'
      : `/api/design/atomistic?seed_lattice_nm=${encodeURIComponent(_seedLatticeNm)}`
  }

  /**
   * Switch the atomistic reps between the ordinary display build and the MD seed.
   *
   * The two builds differ by ~3 A per atom on an insert-carrying design (lattice
   * expansion plus the exact linkers), and the linker atoms are exactly the ones a
   * junction clash is made of — so this is not a cosmetic difference.
   *
   * @param {number|string|null} latticeNm  null = ordinary display build;
   *        'auto' = seed at the measured relaxed spacing; a number = seed at that
   *        spacing. Mirrors `seed_lattice_nm` on POST /md/jobs.
   */
  async function setSeedLattice(latticeNm) {
    const next = latticeNm ?? null
    if (next === _seedLatticeNm) return
    _seedLatticeNm = next
    _atomDataCache = null           // different build → different atoms
    if (atomisticRenderer.getMode() === 'off') return
    showPersistentToast(next === null ? 'Loading atomistic model…'
                                      : 'Building MD seed coordinates…')
    try {
      await _refetchAtomistic()
    } finally {
      dismissToast()
    }
  }

  // Lazily fetch + cache the all-atom model. Shared by the global atomistic mode
  // and the per-region atomistic overlays.
  async function _ensureAtomData() {
    if (_atomDataCache) return _atomDataCache
    const resp = await fetch(_atomisticUrl(), { headers: docHeaders() })
    if (!resp.ok) { console.error('Atomistic fetch failed:', resp.status); return null }
    _atomDataCache = await resp.json()
    return _atomDataCache
  }

  async function _applyAtomisticMode(mode) {
    // A sim overlay (oxDNA relaxed/rmsf/trajectory) will rebuild the atomistic renderer
    // from the JOB's atoms + relaxed frame — so DON'T build+show the DESIGN atoms first
    // (the multi-second "native flash").  Keep the relaxed CG visible; the overlay hides
    // it when its atoms land (onHeavyApplied → setCGVisible(false)).  If the overlay
    // never lands (build fails), the relaxed CG stays up — a sane fallback.
    const _deferToOverlay = mode !== 'off' && !!getSimOverlayWillDriveHeavy('atomistic')
    atomisticRenderer.setMode(mode)
    // Hide CG model when any atomistic mode is active; restore when off — but keep it
    // up while deferring to the overlay.
    _setCGVisible(mode === 'off' || _deferToOverlay)
    _setAtomisticSlidersVisible(mode !== 'off')
    // Set the atomistic colour mode from the current global coloringMode NOW — it's
    // module-persistent, so the overlay's later atom rebuild re-applies it. Without
    // this the deferred path never sets it and the atoms fall back to the cpk default
    // (switching full→atomistic would drop strand/base/cluster colouring).
    if (mode !== 'off') _refreshAtomColors()
    if (_deferToOverlay) return
    if (mode !== 'off' && !_atomDataCache) {
      showPersistentToast('Loading atomistic model…')
      try {
        const data = await _ensureAtomData()
        if (data) {
          atomisticRenderer.update(data)
          _refreshAtomColors()
          const { selectedObject, multiSelectedStrandIds } = store.getState()
          atomisticRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
        }
      } catch (e) {
        console.error('Atomistic fetch error:', e)
      } finally {
        dismissToast()
      }
    }
  }

  // Loading toast for the DEFERRED full→atomistic path: it skips the design-atoms fetch
  // (+ its "Loading atomistic model…" toast) and lets the oxDNA/MD overlay rebuild the
  // atomistic geometry instead.  That build reports progress via the heavy-status event
  // (kind='atomistic' only fires when an overlay drives atomistic — i.e. the deferred
  // case), so mirror the toast off it.  `building:false` fires in the build's `finally`,
  // so the toast clears on completion AND on failure.
  // `kind: 'cg'` is the live MD panel's rep-SWITCH reload (md_panel._setSwitchBusy): the
  // socket is reloading in the other wire format and the scene is showing stale geometry
  // meanwhile.  It routes here rather than owning its own toast so there is exactly one
  // owner of the global persistent toast across all three sim-display controllers.
  const _BUSY_TEXT = {
    surface:   'Computing surface…',
    atomistic: 'Loading atomistic model…',
    cg:        'Loading MD frame…',
  }
  for (const _evt of ['nadoc:oxdna-heavy-status', 'nadoc:md-heavy-status']) {
    window.addEventListener(_evt, (e) => {
      const kind = e.detail?.kind
      if (!(kind in _BUSY_TEXT)) return
      // The overlay has no route for this (mode, kind) — a NAMD flexibility map in a
      // heavy rep, which md_viz_adapter leaves unmapped.  It used to fail silently and
      // leave the DESIGN's equilibrium structure on screen looking like a result.
      if (e.detail.unsupported) {
        dismissToast()
        showToast(
          `The flexibility map has no ${kind === 'surface' ? 'surface' : 'all-atom'} view for `
          + 'this engine — showing the design at equilibrium. Use a coarse-grained '
          + 'representation (F2-F4) to see the map.',
          { severity: 'warn' })
        return
      }
      if (e.detail.building) showPersistentToast(_BUSY_TEXT[kind])
      else dismissToast()
    })
  }

  // Invalidate atom cache on design change; re-hide CG root after any geometry rebuild.
  store.subscribe((newState, prevState) => {
    const designChanged   = newState.currentDesign   !== prevState.currentDesign
    const geometryChanged = newState.currentGeometry !== prevState.currentGeometry ||
                            newState.currentHelixAxes !== prevState.currentHelixAxes
    if (designChanged) _atomDataCache = null
    if ((designChanged || geometryChanged) && atomisticRenderer.getMode() !== 'off') {
      // The renderer just created a fresh root with visible=true — re-hide it.
      _setCGVisible(false)
      if (designChanged) _applyAtomisticMode(atomisticRenderer.getMode())
    }
  })

  // Keep highlight in sync with selection changes.
  store.subscribe((newState, prevState) => {
    if (newState.selectedObject         === prevState.selectedObject &&
        newState.multiSelectedStrandIds === prevState.multiSelectedStrandIds) return
    if (atomisticRenderer.getMode() === 'off') return
    atomisticRenderer.highlight(
      newState.selectedObject,
      newState.multiSelectedStrandIds ?? [],
    )
  })

  // ── Per-region overlay coordinators (mixed representation) ──────────────────
  // Drive the surface / vdw / ballstick overlays from the design's representation
  // overrides. The helix renderer auto-hides CG at those columns; these draw them.

  // Filter the cached all-atom model to a set of columns ("helix:bp"). Keeps each
  // atom's original `serial` so ballstick bonds (serial pairs) resolve without
  // renumbering — bonds are filtered to pairs whose both endpoints survive.

  async function _applyRegionAtomisticOverlays(design) {
    const { vdw, ballstick } = repColumnsByRep(design)
    if (!vdw.size && !ballstick.size) {
      regionVdwRenderer.dispose()
      regionBallstickRenderer.dispose()
      return
    }
    const data = await _ensureAtomData()
    if (!data) return
    // Always dispose-then-update — update() does not pre-clear element meshes.
    regionVdwRenderer.dispose()
    if (vdw.size) { regionVdwRenderer.update(filterAtomData(_atomDataCache, vdw, false)); regionVdwRenderer.setMode('vdw') }
    regionBallstickRenderer.dispose()
    if (ballstick.size) { regionBallstickRenderer.update(filterAtomData(_atomDataCache, ballstick, true)); regionBallstickRenderer.setMode('ballstick') }
    const { selectedObject, multiSelectedStrandIds } = store.getState()
    regionVdwRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
    regionBallstickRenderer.highlight(selectedObject, multiSelectedStrandIds ?? [])
  }

  // Surface overlay — debounced + signature-cached (surface compute is slow).
  async function _recomputeRegionSurface(design) {
    const segs = surfaceSegments(design)
    if (!segs.length) { regionSurfaceRenderer.dispose(); return }
    showPersistentToast('Computing region surface…')
    try {
      const colorMode = store.getState().surfaceColorMode
      const mesh = await api.getRegionSurface(segs, { colorMode })
      regionSurfaceRenderer.update(mesh, colorMode, 'dna-surface-region')
      regionSurfaceRenderer.applyStrandColors(_getAtomStrandColors())
      regionSurfaceRenderer.setOpacity(store.getState().surfaceOpacity)
    } catch (e) {
      console.error('Region surface error:', e)
    } finally {
      dismissToast()
    }
  }
  function _applyRegionSurfaceOverlay(design, force = false) {
    const sig = regionSurfaceSignature(design)
    if (!force && sig === _regionSurfaceSig) return
    _regionSurfaceSig = sig
    if (_regionSurfaceTimer) clearTimeout(_regionSurfaceTimer)
    _regionSurfaceTimer = setTimeout(() => _recomputeRegionSurface(design), 400)
  }

  // Override change OR geometry/design rebuild → re-apply overlays. (Registered
  // AFTER the atomistic cache-invalidation sub so `_atomDataCache` is null'd first
  // on a design change, forcing a re-fetch.) Surface recompute is forced when the
  // geometry moved; otherwise the signature-cache skips unchanged columns.
  store.subscribe((n, p) => {
    const designChanged = n.currentDesign   !== p.currentDesign
    const geoChanged    = n.currentGeometry !== p.currentGeometry ||
                          n.currentHelixAxes !== p.currentHelixAxes
    if (!designChanged && !geoChanged) return
    _applyRegionAtomisticOverlays(n.currentDesign)
    _applyRegionSurfaceOverlay(n.currentDesign, geoChanged)
  })

  // Selection change → atomistic highlight + surface strand recolor (no recompute).
  store.subscribe((n, p) => {
    if (n.selectedObject === p.selectedObject &&
        n.multiSelectedStrandIds === p.multiSelectedStrandIds) return
    const sel = n.selectedObject, multi = n.multiSelectedStrandIds ?? []
    if (regionVdwRenderer.getMode() !== 'off')       regionVdwRenderer.highlight(sel, multi)
    if (regionBallstickRenderer.getMode() !== 'off') regionBallstickRenderer.highlight(sel, multi)
    if (regionSurfaceRenderer.getMode() === 'on')    regionSurfaceRenderer.applyStrandColors(_getAtomStrandColors())
  })

  return {
    applySurfaceMode: _applySurfaceMode,
    applyAtomisticMode: _applyAtomisticMode,
    setCGVisible: _setCGVisible,
    setSurfacePanelVisible: _setSurfacePanelVisible,
    setAtomisticSlidersVisible: _setAtomisticSlidersVisible,
    refetchAtomistic: _refetchAtomistic,
    setSeedLattice,
    /** True while the atomistic reps are showing MD seed coordinates — the caller
     *  must NOT also apply lattice offsets to the atoms, which are already at the
     *  expanded positions. */
    isSeedLatticeActive: () => _seedLatticeNm !== null,
    refreshAtomColors: _refreshAtomColors,
    /** Per-cluster opacity for the atomistic + surface reps. The store subscriber
     *  drives the committed path; this is the entry point for the sidebar swatch's
     *  live preview, which patches a design locally and never touches the store. */
    refreshClusterDisplay,
    getAtomStrandColors: _getAtomStrandColors,
    getRegionVdwRenderer:       () => regionVdwRenderer,
    getRegionBallstickRenderer: () => regionBallstickRenderer,
    getRegionSurfaceRenderer:   () => regionSurfaceRenderer,
    getSurfaceMode: () => _surfaceMode,
    getSurfaceProbeRadius: () => _surfaceProbeRadius,
    // Live surface params for the sim-overlay surface fetch (so its mesh honours the
    // sidebar's probe radius + colour mode instead of the backend defaults).
    getSurfaceParams: () => ({ probe_radius: _surfaceProbeRadius, detail: _surfaceDetail,
                               color_mode: store.getState().surfaceColorMode ?? 'strand' }),
    invalidateAtomCache: () => { _atomDataCache = null },
    invalidateSurfaceCache: () => { _surfaceDataCache = null },
  }
}

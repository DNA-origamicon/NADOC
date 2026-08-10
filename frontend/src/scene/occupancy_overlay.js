/**
 * Occupancy clouds — superposed ghost copies of an oxDNA job's top-N configurations.
 *
 * The flexibility map moves the ONE model to a mean structure. This module draws the
 * other states around it: cluster rank 0 stays on the real model (driven by the caller
 * through `designRenderer.applyFemPositions`), and ranks 1..N-1 become translucent
 * copies owned here. So N states cost N-1 builds, and rank 0 keeps everything the real
 * model carries that a bare `buildHelixObjects` group does not — strand colours, hidden
 * staples, rep overrides, crossover arcs, extra-base beads, protein transforms. Ghosts
 * are deliberately-degraded stand-ins; they exist to show a SHAPE.
 *
 * Four things here are load-bearing and were each verified against the renderer source:
 *
 * 1. **Ghost tint goes through `buildHelixObjects`'s `customColors`, not
 *    `applyScalarColors`.** `customColors` ({strandId: hex}) feeds both the bead/cone/slab
 *    path and the domain-cylinder path, so the tint survives at cylinder LOD.
 *    `applyScalarColors` touches only spheres/slabs/cones AND is the scalar-map channel
 *    that `coloringInfo()` switches on for export — a categorical tint there would
 *    corrupt the ChimeraX/photo path.
 *
 * 2. **Opacity must clear `depthWrite`.** Materials are created per-build inside
 *    `buildHelixObjects`, so setting opacity on a ghost cannot bleed into the main model.
 *    But a transparent mesh that still writes depth is an INVISIBLE OCCLUDER punching
 *    voids into whatever is behind it — see `_fadeMat` in helix_renderer.js. A whole
 *    translucent structure copy is the worst case for that.
 *
 * 3. **A cylinder-LOD ghost is invisible until `setDetailLevel` is called.**
 *    `buildHelixObjects` starts every cylinder mesh at `visible = false` and initialises
 *    `_detailLevel` to 0 (full). Building at `lod='cylinders'` and never calling
 *    `setDetailLevel(CG_LOD.cylinders)` draws exactly nothing, silently.
 *
 * 4. **Shared geometries must survive disposal.** The template geometries in BOTH
 *    helix_renderer and crossover_connections are module-level singletons marked
 *    `userData.shared`, precisely so traverse-and-dispose call sites skip them. Disposing
 *    one would gut the main model's meshes the first time a ghost is torn down.
 *
 * 5. **Crossover extra bases are a separate mesh family.** They have no
 *    (helix, bp, direction) key, so `buildHelixObjects` emits nothing for them and
 *    `applyFemPositions` drops their `__xb__` updates. Each ghost therefore also builds
 *    `buildCrossoverConnections` and places the inserts itself. Extension tails need none
 *    of this — they carry real `("__ext_<id>", i, dir)` keys and ride the normal path.
 *
 * Ghosts are coarse-grained only. On a switch to a heavy representation
 * (atomistic/surface) they are cleared with a status message rather than left to
 * mis-render — this module registers that listener itself.
 *
 * Layer 3 (display-only). Nothing here touches topology.
 */
import * as THREE from 'three'

import {
  buildCrossoverConnections, partitionExtraBaseUpdates, setExtraBaseConnectors,
  setExtraBaseInstanceFromSim, setExtraBaseSlabConnectors, simBeadIndex,
  updateExtraBaseInstances,
} from './crossover_connections.js'
import { crossoverControlPoint as arcControlPoint } from './crossover_extra_placement.js'
import { CG_LOD, buildHelixObjects, buildStapleColorMap } from './helix_renderer.js'

/** Ghost palette, most-populated first. Rank 0 is the real model and takes none of these. */
export const OCCUPANCY_COLORS = [0xd29922, 0xa371f7, 0x3fb950, 0xf85149, 0x58a6ff]

export const OCC_MAX_ALPHA = 0.75
export const OCC_MIN_ALPHA = 0.22

/** Bytes of GPU/heap buffer per nucleotide for one full structure copy.
 *  Derived from the one measurement in the repo (9 instances x 61 kbp ~ 250 MB at full,
 *  ~30 MB at cylinders — see memory/project_polymerize_origami.md). */
export const GHOST_BYTES_PER_NT = { full: 230, beads: 150, cylinders: 28 }

/** Mirrors oxdna_display.js's ceilings so the two budgets cannot drift apart. */
export const BROWSER_HEAP_CEILING_BYTES = 1536 * 1024 * 1024
export const FREE_RAM_SAFE_FRACTION = 0.5

const _HEAVY_REPS = new Set(['vdw', 'ballstick', 'atomistic', 'surface'])

/** Colour for a ghost of the given rank (rank 0 is the real model → never asked for). */
export function clusterColors(n) {
  const out = []
  for (let i = 0; i < Math.max(0, n); i++) out.push(OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length])
  return out
}

/**
 * Opacity for a ghost, scaled by how populated its state is.
 * Monotone in `population` and clamped, so a 3 % state is still faintly visible and a
 * 49 % state never reads as solid.
 */
export function clusterOpacity(population, { min = OCC_MIN_ALPHA, max = OCC_MAX_ALPHA } = {}) {
  const p = Number.isFinite(population) ? Math.min(1, Math.max(0, population)) : 0
  return min + (max - min) * p
}

export function ghostBytesPerNucleotide(lod) {
  return GHOST_BYTES_PER_NT[lod] ?? GHOST_BYTES_PER_NT.full
}

/**
 * How many ghosts fit in memory — same `limitedBy` contract as
 * `prebuildMemoryPlan` in oxdna_display.js ('ram' | 'heap' | null).
 *
 * Deliberately NOT that function: it prices per-serial coordinate frames, a different
 * physical quantity, and reusing it here would give a silently wrong budget.
 */
export function ghostMemoryPlan({ nNucleotides, nGhosts, lod = 'full', availableBytes = null }) {
  const perGhost = Math.max(1, Math.round(nNucleotides * ghostBytesPerNucleotide(lod)))
  const want = perGhost * Math.max(0, nGhosts)

  const ramBudget = availableBytes != null ? availableBytes * FREE_RAM_SAFE_FRACTION : Infinity
  const budget = Math.min(BROWSER_HEAP_CEILING_BYTES, ramBudget)
  const fits = Math.max(0, Math.floor(budget / perGhost))
  const ghosts = Math.min(Math.max(0, nGhosts), fits)
  const capped = ghosts < Math.max(0, nGhosts)

  let limitedBy = null
  if (capped) limitedBy = ramBudget < BROWSER_HEAP_CEILING_BYTES ? 'ram' : 'heap'

  return { wantBytes: want, budgetBytes: budget === Infinity ? null : budget,
           bytesPerGhost: perGhost, ghosts, capped, limitedBy }
}

/** Uniform opacity over a ghost root, clearing depthWrite so it never occludes. */
function _setGroupOpacity(root, a) {
  const opaque = a >= 0.996
  root.traverse((o) => {
    if (!o.material) return
    const mats = Array.isArray(o.material) ? o.material : [o.material]
    for (const m of mats) {
      m.opacity = a
      m.transparent = !opaque
      m.depthWrite = opaque
    }
  })
}

/** Dispose a ghost root's own materials/geometries, leaving shared templates alone. */
function _disposeGhost(root) {
  root.traverse((o) => {
    if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
    if (o.material) {
      const mats = Array.isArray(o.material) ? o.material : [o.material]
      for (const m of mats) m.dispose()
    }
  })
}

/** `{strandId: hex}` painting every strand one colour. */
function _tintAll(design, hex) {
  const out = {}
  for (const s of design?.strands ?? []) out[s.id] = hex
  return out
}

/**
 * Flat wire frame + keys → the `applyFemPositions` update list.
 *
 * Same shape and stride as `framesToUpdates` in ui/oxdna_display.js — the backend emits
 * occupancy medoids through the same `_flatten_cg_frame` as the trajectory. It is
 * duplicated rather than imported because a scene/ module importing from ui/ inverts the
 * layering; the ten lines are cheaper than the cycle.
 *
 * `nx/ny/nz` (the base normal) must be carried: `applyFemPositions` orients cones and
 * slabs from it, so dropping it leaves a ghost's bases pointing the wrong way.
 */
export function occupancyFrameToUpdates(keys, frame) {
  if (!Array.isArray(keys) || !Array.isArray(frame)) return []
  const out = []
  for (let i = 0; i < keys.length; i++) {
    const b = i * 6
    if (b + 5 >= frame.length) break
    const [helix_id, bp_index, direction, copy] = keys[i]
    out.push({
      helix_id, bp_index, direction, copy: copy ?? 0,
      backbone_position: [frame[b], frame[b + 1], frame[b + 2]],
      nx: frame[b + 3], ny: frame[b + 4], nz: frame[b + 5],
    })
  }
  return out
}

export function initOccupancyOverlay({
  scene,
  getGeometry = () => null,
  getDesign = () => null,
  getHelixAxes = () => null,
  getRepr = () => 'full',
  setDesignVisible = null,
  onProgress = null,
  onStatus = null,
} = {}) {
  /** @type {Array<{group, ctrl, rank, color, visible, cluster}>} — index === rank */
  let _states = []
  let _visible = true
  let _token = 0
  let _lastResp = null
  let _owningScene = false
  // Why the last setClusters() produced no states. A silent no-op here is
  // indistinguishable from "the ensemble has one state", so the reason is recorded.
  let _lastSkip = null

  function _disposeState(st) {
    scene.remove(st.group)
    _disposeGhost(st.group)
  }

  function _clear() {
    for (const st of _states) _disposeState(st)
    _states = []
    _releaseScene()
  }

  /** Every state is a copy owned here, so the design's own model must step aside —
   *  the same hand-off mrdna_display / blade_display / md_panel do. */
  function _takeScene() {
    if (_owningScene) return
    _owningScene = true
    setDesignVisible?.(false)
  }

  function _releaseScene() {
    if (!_owningScene) return
    _owningScene = false
    setDesignVisible?.(true)
  }

  function _lodName() {
    const r = getRepr()
    return r === 'beads' || r === 'cylinders' ? r : 'full'
  }

  /**
   * Place a ghost's crossover extra bases.
   *
   * Extra bases have NO (helix, bp, direction) key, so `helix_renderer` cannot draw or
   * move them — `buildHelixObjects` emits no geometry for them at all and
   * `applyFemPositions` drops their updates on the floor. They live in their own
   * instanced meshes built by `buildCrossoverConnections`, and the simulated frame
   * carries their real positions under `__xb__` keys. This is the ghost's copy of what
   * `design_renderer.applyClusterCrossoverUpdate` does for the live model.
   *
   * Must run AFTER `applyFemPositions`: the no-sim-data fallback threads a Bezier between
   * the arc's two endpoint nucleotides, and those have to have moved first.
   */
  function _placeExtraBases(ctrl, xo, simXb) {
    const ctrlPt = new THREE.Vector3()
    for (const ad of xo.arcData ?? []) {
      const sim = simXb?.get(ad.xoId)
      if (sim) {
        for (let k = 0; k < ad.beadCount; k++) {
          const sBead = sim.get(k)
          if (!sBead) continue
          // Simulated k runs 5′→3′ from the strand's exit half; beads run A→B.
          const bi = simBeadIndex(k, ad.beadCount, ad.simReversed)
          setExtraBaseInstanceFromSim(xo.beadsMesh, xo.slabsMesh, ad.beadStartIdx + bi,
                                      sBead.pos, sBead.normal, ad.avgAx)
        }
        continue
      }
      // No simulated data for this arc (e.g. a scoped run, or a crossover the frame does
      // not cover) — fall back to the geometric Bezier from the ghost's LIVE endpoints,
      // so the inserts still sit on the moved structure rather than at the design pose.
      const a = ctrl.getNucLivePos?.(ad.nucA)
      const b = ctrl.getNucLivePos?.(ad.nucB)
      if (!a || !b) continue
      arcControlPoint(a, b, ad.nucA, ad.nucB, ctrlPt)
      updateExtraBaseInstances(xo.beadsMesh, xo.slabsMesh, ad.beadStartIdx, ad.beadCount,
                               a, ctrlPt, b, ad.avgAx,
                               ad.simReversed, ad.localFrameReversed,
                               ad.savedTransforms, ad.sequence)
    }
    xo.beadsMesh.instanceMatrix.needsUpdate = true
    xo.slabsMesh.instanceMatrix.needsUpdate = true
    if (xo.slabConnMesh) {
      for (const ad of xo.arcData ?? []) {
        setExtraBaseSlabConnectors(
          xo.beadsMesh, xo.slabsMesh, xo.slabConnMesh,
          ad.beadStartIdx, ad.beadCount, null,
        )
      }
      xo.slabConnMesh.instanceMatrix.needsUpdate = true
    }
    _threadConnectors(ctrl, xo)
  }

  /** Re-thread the backbone arrows through the beads' now-live matrices, so the inserts
   *  read as part of the strand instead of floating dots. */
  function _threadConnectors(ctrl, xo) {
    if (!xo.connMesh) return
    const mat = new THREE.Matrix4()
    for (const ad of xo.arcData ?? []) {
      const a = ctrl.getNucLivePos?.(ad.nucA)
      const b = ctrl.getNucLivePos?.(ad.nucB)
      if (!a || !b) continue
      const pts = [new THREE.Vector3().copy(a)]
      for (let k = 0; k < ad.beadCount; k++) {
        xo.beadsMesh.getMatrixAt(ad.beadStartIdx + k, mat)
        pts.push(new THREE.Vector3().setFromMatrixPosition(mat))
      }
      pts.push(new THREE.Vector3().copy(b))
      // null colour: the meshes were built with the ghost's flat tint already, and
      // re-colouring per arc here would fight it.
      setExtraBaseConnectors(xo.connMesh, ad.connStartIdx, pts, ad.beadCount + 1, null)
    }
    xo.connMesh.instanceMatrix.needsUpdate = true
  }

  function _buildState(cluster, rank, hex, lod, visible) {
    const design = getDesign()
    const geometry = getGeometry()
    if (!design || !geometry) {
      _lastSkip = `no ${!design ? 'design' : 'geometry'} available`
      return null
    }
    if (!cluster?.frame?.length) {
      _lastSkip = `state ${rank} carries no frame`
      return null
    }

    const group = new THREE.Group()
    group.name = `occupancyGhost${rank}`
    const tint = _tintAll(design, hex)
    const ctrl = buildHelixObjects(geometry, design, group, tint, [], getHelixAxes(), lod)

    // A cylinder/beads copy is built with those meshes hidden — without this it draws
    // nothing at all, silently.
    const level = CG_LOD[lod]
    if (level != null && level !== CG_LOD.full) ctrl.setDetailLevel?.(level)

    // Crossover extra bases are a separate mesh family that buildHelixObjects knows
    // nothing about; without this the inserts are simply absent from every ghost.
    // Extension tails need no such treatment — they carry real ("__ext_<id>", i, dir)
    // keys, so the builder draws them and applyFemPositions moves them like any base.
    // Returns null when the design has no crossover with extra bases — the common case.
    // A THROW is different: that is a real breakage, and swallowing it would leave the
    // inserts silently missing again, so it is recorded for stats().
    let xo = null
    try {
      xo = buildCrossoverConnections(design, geometry, buildStapleColorMap(geometry, design), tint)
    } catch (e) {
      xo = null
      _lastSkip = `extra bases unavailable: ${e?.message ?? e}`
    }
    if (xo?.group) {
      group.add(xo.group)
      // Cylinder LOD has no per-insert representation, matching the live model.
      if (level === CG_LOD.cylinders) {
        xo.beadsMesh.visible = xo.slabsMesh.visible = false
        if (xo.connMesh) xo.connMesh.visible = false
        if (xo.slabConnMesh) xo.slabConnMesh.visible = false
      }
    }

    const updates = occupancyFrameToUpdates(_lastResp.keys, cluster.frame)
    const { real, simXb } = partitionExtraBaseUpdates(updates)
    ctrl.applyFemPositions?.(real ?? updates)
    if (xo) _placeExtraBases(ctrl, xo, simXb)

    // AFTER the extra-base group is attached — this traverses the whole subtree, and a
    // group added later would keep opaque materials.
    _setGroupOpacity(group, clusterOpacity(cluster.population))
    group.renderOrder = 10 + rank
    group.visible = _visible && visible
    scene.add(group)
    return { group, ctrl, rank, color: hex, visible, cluster, hasExtraBases: !!xo }
  }

  const api = {
    /**
     * Draw EVERY state as its own flat-coloured copy. Yields between copies —
     * `buildHelixObjects` runs ~0.5-1 s on a large design, so building several back to
     * back would freeze the main thread for seconds.
     *
     * `colors` / `visible` let the caller restore the user's per-state choices across a
     * refetch; both are indexed by rank.
     */
    async setClusters(resp, { maxStates = Infinity, colors = null, visible = null } = {}) {
      const token = ++_token
      _clear()
      _lastSkip = null
      _lastResp = resp
      if (!resp?.clusters?.length || !resp?.keys?.length) {
        _lastSkip = 'response carried no clusters or no keys'
        return { states: 0, reason: _lastSkip }
      }

      const repr = getRepr()
      if (_HEAVY_REPS.has(repr)) {
        _lastSkip = `heavy representation (${repr})`
        onStatus?.({ level: 'warn', text: OCCUPANCY_HEAVY_REP_MESSAGE })
        return { states: 0, blocked: 'heavy-representation', reason: _lastSkip }
      }

      const wanted = resp.clusters.slice(0, Math.max(0, maxStates))
      const palette = clusterColors(wanted.length)
      _takeScene()

      let done = 0
      for (let i = 0; i < wanted.length; i++) {
        // Yield so the frame can render between copies, and bail if superseded.
        await new Promise((r) => (typeof requestAnimationFrame === 'function'
          ? requestAnimationFrame(() => r())
          : setTimeout(r, 0)))
        if (token !== _token) return { states: _states.length, cancelled: true }

        const st = _buildState(wanted[i], i, colors?.[i] ?? palette[i], lod_(),
                               visible?.[i] ?? true)
        if (st) _states.push(st)
        onProgress?.({ done: ++done, total: wanted.length })
      }
      if (!_states.length && wanted.length && !_lastSkip) _lastSkip = 'builder returned nothing'
      if (!_states.length) _releaseScene()
      return { states: _states.length, reason: _lastSkip }
    },

    /** Show/hide ONE state without rebuilding it. */
    setStateVisible(rank, on) {
      const st = _states[rank]
      if (!st) return false
      st.visible = !!on
      st.group.visible = _visible && st.visible
      return true
    },

    /**
     * Recolour ONE state. The tint is baked in at build time (it goes through
     * `buildHelixObjects`'s customColors so it survives at cylinder LOD), so this
     * rebuilds that single copy rather than trying to repaint instances.
     */
    setStateColor(rank, hex) {
      const st = _states[rank]
      if (!st) return false
      const { cluster, visible } = st
      _disposeState(st)
      const rebuilt = _buildState(cluster, rank, hex, lod_(), visible)
      if (!rebuilt) return false
      _states[rank] = rebuilt
      return true
    },

    setVisible(v) {
      _visible = !!v
      for (const st of _states) st.group.visible = _visible && st.visible
    },

    /** Per-rank colours currently in the scene — what the state list should show. */
    colors() {
      return _states.map((st) => st.color)
    },

    /** Default colour for each state, before the user overrides any. */
    defaultColors(nStates) {
      return clusterColors(Math.max(0, nStates))
    },

    memoryPlan(nStates, availableBytes = null) {
      const geometry = getGeometry()
      const n = geometry?.length ?? geometry?.nucleotides?.length ?? 0
      return ghostMemoryPlan({ nNucleotides: n, nGhosts: Math.max(0, nStates),
                               lod: _lodName(), availableBytes })
    },

    stats() {
      return { states: _states.length, ghosts: _states.length,
               lod: _lodName(), visible: _visible, owningScene: _owningScene,
               hidden: _states.filter((st) => !st.visible).length,
               skipped: _lastSkip,
               hasDesign: !!getDesign(), hasGeometry: !!getGeometry(), repr: getRepr() }
    },

    clear() {
      _token++
      _clear()
      _lastResp = null
    },

    dispose() {
      api.clear()
      if (typeof window !== 'undefined') {
        window.removeEventListener('nadoc:representation-change', _onRepr)
      }
    },
  }

  function lod_() { return _lodName() }

  function _onRepr(e) {
    const rep = e?.detail?.representation
    if (_HEAVY_REPS.has(rep)) {
      if (_states.length) onStatus?.({ level: 'warn', text: OCCUPANCY_HEAVY_REP_MESSAGE })
      _clear()
    } else if (_lastResp) {
      // Rebuild at the new LOD, preserving the user's per-state colours and toggles.
      const colors = _states.map((st) => st.color)
      const visible = _states.map((st) => st.visible)
      api.setClusters(_lastResp, { colors, visible })
    }
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('nadoc:representation-change', _onRepr)
  }

  return api
}

export const OCCUPANCY_HEAVY_REP_MESSAGE =
  'Occupancy ghosts are coarse-grained only — switch back to Full / Beads / Cylinders to see them.'

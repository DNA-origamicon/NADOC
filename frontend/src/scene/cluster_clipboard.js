/**
 * Cluster copy/paste (Ctrl+C / Ctrl+V) in the 3D part editor.
 *
 * Ctrl+C stashes the selected cluster(s) — transitively closed over parent/child —
 * as a lattice footprint. Ctrl+V arms a translucent ghost that follows the cursor on
 * the slice plane, snapping only to cells that preserve crossover phase; a click
 * commits it through `POST /design/cluster-paste`.
 *
 * The ghost is built from `store.currentHelixAxes`, which already carries the LIVE
 * posed + deformed axes of every helix. So a bent, rotated cluster ghosts as a bent,
 * rotated cluster with no pose math here — the copy will look like what's on screen.
 *
 * Hover raycasting, anchor snapping and occupied-cell conflict are delegated to
 * `slice_plane.js` via its `commitKind`/`onGhostUpdate`/`candidateCells` spec hatch;
 * all mesh work lives here. Display-layer only: this module never touches topology
 * (the backend route owns that).
 */

import * as THREE from 'three'

import {
  clusterClosure,
  describeCopy,
  footprintForClusters,
  pasteParityCandidates,
  unsupportedCopyReason,
} from './cluster_copy_logic.js'

const GHOST_RADIUS_NM = 1.0
const GHOST_TUBE_SEGMENTS = 24
const GHOST_RADIAL_SEGMENTS = 8
/** Scene-graph name for the paste ghost — the stable handle for tests/diagnostics. */
export const GHOST_NAME = 'clusterPasteGhost'

/**
 * @param {object} deps
 * @param {object} deps.store        the global store
 * @param {object} deps.api          api client (needs pasteClusters)
 * @param {THREE.Scene} deps.scene
 * @param {object} deps.slicePlane   initSlicePlane(...) api
 * @param {Function} deps.showToast
 */
export function initClusterClipboard({ store, api, scene, slicePlane, showToast }) {
  /** @type {{clusterIds: string[], addedIds: string[], footprint: object} | null} */
  let _clipboard = null
  /** @type {THREE.Group | null} */
  let _ghost = null
  let _committing = false

  const _ghostMat = new THREE.MeshBasicMaterial({
    color: 0x58a6ff, transparent: true, opacity: 0.35, depthWrite: false,
  })
  const _conflictMat = new THREE.MeshBasicMaterial({
    color: 0xff4d4f, transparent: true, opacity: 0.4, depthWrite: false,
  })

  // ── Selection ───────────────────────────────────────────────────────────────

  /** Cluster ids currently selected — the single selection and/or the multi pool. */
  function _selectedClusterIds() {
    const st = store.getState()
    const ids = new Set(st.multiSelectedClusterIds ?? [])
    if (st.selectedObject?.type === 'cluster' && st.selectedObject.id) {
      ids.add(st.selectedObject.id)
    }
    return [...ids]
  }

  // ── Ghost ───────────────────────────────────────────────────────────────────

  /** A translucent tube along a helix's live (posed + deformed) axis. */
  function _ghostMeshForHelix(ax) {
    if (!ax) return null
    const samples = ax.samples?.length >= 2 ? ax.samples : null
    const pts = samples
      ? samples.map(p => new THREE.Vector3(p[0], p[1], p[2]))
      : [ax.start, ax.end].filter(Boolean).map(p => new THREE.Vector3(p[0], p[1], p[2]))
    if (pts.length < 2) return null
    const curve = new THREE.CatmullRomCurve3(pts)
    const geom = new THREE.TubeGeometry(
      curve, samples ? GHOST_TUBE_SEGMENTS : 1, GHOST_RADIUS_NM, GHOST_RADIAL_SEGMENTS, false
    )
    return new THREE.Mesh(geom, _ghostMat)
  }

  function _buildGhost(helixIds) {
    const axes = store.getState().currentHelixAxes ?? {}
    const group = new THREE.Group()
    for (const hid of helixIds) {
      const mesh = _ghostMeshForHelix(axes[hid])
      if (mesh) group.add(mesh)
    }
    if (!group.children.length) return null
    group.name = GHOST_NAME   // renderOrder alone is ambiguous — several modules use 999
    group.renderOrder = 999
    return group
  }

  function _disposeGhost() {
    if (!_ghost) return
    scene.remove(_ghost)
    for (const m of _ghost.children) m.geometry?.dispose()
    _ghost = null
  }

  /** Slice-plane hands us the snapped hover offset + whether the cells collide. */
  function _onGhostUpdate(info) {
    if (!_ghost) return
    if (!info) { _ghost.visible = false; return }
    _ghost.visible = true
    _ghost.position.copy(info.worldOffset)
    const mat = info.conflict ? _conflictMat : _ghostMat
    for (const m of _ghost.children) m.material = mat
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  function copy() {
    const selected = _selectedClusterIds()
    if (!selected.length) {
      showToast('Select a cluster to copy.', { severity: 'info' })
      return false
    }
    const design = store.getState().currentDesign
    const { closureIds, addedIds } = clusterClosure(selected, design?.cluster_transforms ?? [])
    const footprint = footprintForClusters(closureIds, design)
    if (!footprint) {
      showToast('That cluster has no lattice-positioned helices to copy.', { severity: 'error' })
      return false
    }
    const refusal = unsupportedCopyReason(footprint.helixIds, design)
    if (refusal) {
      showToast(refusal, { severity: 'error', duration: 7000 })
      return false
    }
    _clipboard = { clusterIds: closureIds, addedIds, footprint }
    showToast(describeCopy(closureIds, addedIds, footprint.helixIds.length))
    return true
  }

  function paste() {
    if (!_clipboard) {
      showToast('Nothing copied yet — select a cluster and press Ctrl+C.', { severity: 'info' })
      return false
    }
    if (_ghost) cancel()

    const { cells, anchorCell, plane, latticeType, helixIds } = _clipboard.footprint
    _ghost = _buildGhost(helixIds)
    if (!_ghost) {
      showToast('Could not build a paste preview for that cluster.', { severity: 'error' })
      return false
    }
    _ghost.visible = false
    scene.add(_ghost)

    slicePlane.showPlacement(plane, {
      cells,
      anchorCell,
      latticeType,
      commitKind: 'cluster-paste',
      onGhostUpdate: _onGhostUpdate,
      // Even (row+col) parity on BOTH lattices — a paste grafts helices verbatim.
      candidateCells: pasteParityCandidates,
    })
    return true
  }

  /** Slice-plane click committed the placement at `gridDelta`. */
  async function onCommit({ gridDelta }) {
    if (!_clipboard || _committing) return
    const [deltaRow, deltaCol] = gridDelta
    _committing = true
    try {
      const res = await api.pasteClusters({
        clusterIds: _clipboard.clusterIds, deltaRow, deltaCol,
      })
      if (!res) {
        // `_request` records the failure in store.lastError but does NOT toast. Without
        // this, a rejected paste (an overhang on a copied helix, a collision, an
        // odd-parity offset) looked exactly like "the click did nothing".
        // Keep the ghost armed — most rejections are fixed by placing somewhere else.
        const err = store.getState().lastError
        showToast(err?.message ?? 'Paste failed.', { severity: 'error', duration: 7000 })
        return
      }
      const rep = res.pasteReport
      const n = rep?.closure_cluster_ids?.length ?? _clipboard.clusterIds.length
      let msg = `Pasted ${n} cluster${n === 1 ? '' : 's'}`
      if (rep?.truncated_strand_count) {
        msg += ` — ${rep.truncated_strand_count} strand${rep.truncated_strand_count === 1 ? '' : 's'} truncated at the boundary`
      }
      showToast(msg)
      cancel()
    } finally {
      _committing = false
    }
  }

  function cancel() {
    _disposeGhost()
    slicePlane.disarmPlacement()
  }

  function isActive() { return _ghost !== null }

  // A design change while a ghost is armed (undo, load, another edit) invalidates the
  // ghost's axes — drop it rather than leave a stale preview floating in the scene.
  store.subscribe((next, prev) => {
    if (_committing || !_ghost) return
    if (next.currentDesign !== prev.currentDesign) cancel()
  })

  return { copy, paste, onCommit, cancel, isActive }
}

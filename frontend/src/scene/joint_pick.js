/**
 * Active-cluster pick helpers extracted from main.js (translate/rotate tool).
 *
 * Three small stateful helpers that share the closure's `canvas`/`camera`/
 * `store`/`designRenderer`:
 *   • canvasNdc(e)               — pointer event → normalized device coords
 *   • clusterBackboneEntries(…)  — cluster → its backbone bead entries (defaults
 *                                  the entry list from the live design renderer)
 *   • pickActiveClusterEntry(e)  — raycast the ACTIVE cluster's instanced beads
 *                                  and return the front-most hit entry (or null)
 *
 * Factory (DI) so the raycast helper is exercisable with a mock store/camera.
 * Tested in joint_pick.test.js.
 */
import * as THREE from 'three'
import { clientToNdc } from './ndc.js'
import { clusterBackboneEntries as _clusterBackboneEntriesPure } from './cluster_entries.js'

export function initJointPick({ canvas, camera, store, designRenderer }) {
  function canvasNdc(e) {
    return clientToNdc(e.clientX, e.clientY, canvas.getBoundingClientRect())
  }

  function clusterBackboneEntries(cluster, design, backboneEntries = null) {
    backboneEntries ??= designRenderer.getBackboneEntries?.() ?? []
    return _clusterBackboneEntriesPure(cluster, design, backboneEntries)
  }

  const _clusterPickRaycaster = new THREE.Raycaster()
  const _clusterPickNdc = new THREE.Vector2()

  function pickActiveClusterEntry(e) {
    const { activeClusterId, currentDesign } = store.getState()
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === activeClusterId)
    if (!cluster) return null

    const entries = clusterBackboneEntries(cluster, currentDesign)
    if (!entries.length) return null

    const idsByMesh = new Map()
    for (const entry of entries) {
      if (!entry.instMesh) continue
      let ids = idsByMesh.get(entry.instMesh)
      if (!ids) {
        ids = new Set()
        idsByMesh.set(entry.instMesh, ids)
      }
      ids.add(entry.id)
    }
    const meshes = [...idsByMesh.keys()].filter(mesh => mesh?.visible !== false)
    if (!meshes.length) return null

    const ndc = canvasNdc(e)
    _clusterPickNdc.set(ndc.x, ndc.y)
    _clusterPickRaycaster.setFromCamera(_clusterPickNdc, camera)

    const hits = _clusterPickRaycaster.intersectObjects(meshes, false)
    for (const hit of hits) {
      if (idsByMesh.get(hit.object)?.has(hit.instanceId)) {
        return entries.find(entry => entry.instMesh === hit.object && entry.id === hit.instanceId) ?? null
      }
    }
    return null
  }

  return { canvasNdc, clusterBackboneEntries, pickActiveClusterEntry }
}

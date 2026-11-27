import * as THREE from 'three'
import { createCornerPreview } from './corner_preview.js'
import { ARC_SEGS } from './native_connection_lines.js'

/** Private Full buffers are built once. A cut only toggles complete residues/bonds. */
export function createBevelPreview(options) {
  let rows = [], arcs = [], lines = null, root = null
  const zero = new THREE.Matrix4().makeScale(0, 0, 0)
  const owner = createCornerPreview({ ...options, onFullBuilt(data) {
    root = data.root; root.name = 'bevel-full-preview'; rows = []; arcs = data.connections; lines = data.lines
    function add(mesh, id, endpoints) {
      if (!mesh || id == null) return
      const matrix = new THREE.Matrix4(); mesh.getMatrixAt(id, matrix)
      rows.push({ mesh, id, endpoints, matrix, visible: true })
    }
    for (const e of [...data.native.backboneEntries, ...data.native.slabEntries]) {
      add(e.instMesh, e.id, [e.nuc]); add(e.connectorMesh, e.connectorId, [e.nuc])
    }
    for (const e of data.native.coneEntries) add(e.instMesh, e.id, [e.fromNuc, e.toNuc])
    const extras = data.extras
    for (const arc of extras?.arcData ?? []) {
      const ends = [arc.nucA, arc.nucB]
      for (let i = 0; i < arc.beadCount; i++) {
        for (const mesh of [extras.beadsMesh, extras.slabsMesh, extras.slabConnMesh]) add(mesh, arc.beadStartIdx + i, ends)
      }
      for (let i = 0; i <= arc.beadCount; i++) add(extras.connMesh, arc.connStartIdx + i, ends)
    }
  } })
  return {
    full: owner.full,
    mask(keep, startedAt = performance.now()) {
      const start = performance.now(), changed = new Set()
      for (const row of rows) {
        const visible = row.endpoints.every(keep)
        if (visible === row.visible) continue
        row.mesh.setMatrixAt(row.id, visible ? row.matrix : zero)
        row.visible = visible; changed.add(row.mesh)
      }
      for (const mesh of changed) mesh.instanceMatrix.needsUpdate = true
      if (lines) {
        for (const arc of arcs) {
          const alpha = keep(arc.fromNuc) && keep(arc.toNuc) ? 1 : 0
          for (let i = 0; i <= ARC_SEGS; i++) lines.colors[(arc.vertIdx + i) * 4 + 3] = alpha
        }
        lines.geo.attributes.color.needsUpdate = true
      }
      if (root) { root.userData.maskMilliseconds = performance.now() - start; root.userData.previewMilliseconds = performance.now() - startedAt }
    },
    clear() { owner.clear(); rows = []; arcs = []; root = null; lines = null },
    dispose() { this.clear() },
  }
}

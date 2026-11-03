import * as THREE from 'three'
import { buildCrossoverConnections } from './crossover_connections.js'
import { clusterAlphaForNuc, clusterAlphaKeys } from './cluster_entries.js'
import { installInstanceAlpha, setInstanceAlpha } from './instance_alpha.js'
import { BASE_COLORS } from './helix_renderer/palette.js'

/** Extra residues live outside the helix LOD meshes. Each volume owns its copy. */
export function buildVolumeExtras(design, geometry, root, representation) {
  if (!['full', 'beads'].includes(representation)) return null
  const extras = buildCrossoverConnections(design, geometry, new Map(), {})
  if (!extras) return null
  root.add(extras.group)
  extras.slabsMesh.visible = extras.slabConnMesh.visible = representation === 'full'
  for (const mesh of [extras.beadsMesh, extras.slabsMesh, extras.connMesh, extras.slabConnMesh]) {
    installInstanceAlpha(mesh)
    // installInstanceAlpha clones shared templates; this clone belongs to the layer.
    mesh.geometry.userData.shared = false
  }
  return extras
}

export function paintVolumeExtras(extras, { columns, design, mode, strands, nucAlphas }) {
  if (!extras) return
  const alphas = clusterAlphaKeys(design), color = new THREE.Color()
  for (const arc of extras.arcData) {
    const endpoints = [arc.nucA, arc.nucB]
    const visible = endpoints.every(n => columns.get(`${n.helix_id}:${n.bp_index}`) === 'full' &&
      nucAlphas.get(`${n.helix_id}:${n.bp_index}:${n.direction}`) !== 0)
    const alpha = visible ? Math.min(...endpoints.map(n => clusterAlphaForNuc(alphas, n))) : 0
    const strandColor = strands.get(arc.nucA.strand_id) ?? arc.beadBaseColor
    for (let i = 0; i < arc.beadCount; i++) {
      const k = arc.simReversed ? arc.beadCount - 1 - i : i
      const hex = mode === 'base' ? BASE_COLORS[arc.sequence[k]?.toUpperCase()] ?? strandColor : strandColor
      for (const mesh of [extras.beadsMesh, extras.slabsMesh, extras.slabConnMesh]) {
        mesh.setColorAt(arc.beadStartIdx + i, color.setHex(hex))
        setInstanceAlpha(mesh, arc.beadStartIdx + i, alpha)
      }
    }
    for (let i = 0; i <= arc.beadCount; i++) {
      extras.connMesh.setColorAt(arc.connStartIdx + i, color.setHex(strandColor))
      setInstanceAlpha(extras.connMesh, arc.connStartIdx + i, alpha)
    }
  }
  for (const mesh of [extras.beadsMesh, extras.slabsMesh, extras.connMesh, extras.slabConnMesh]) {
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }
}

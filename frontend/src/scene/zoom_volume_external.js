import * as THREE from 'three'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { initProteinTraceRenderer } from './protein_trace_renderer.js'
import { initSurfaceRenderer } from './surface_renderer.js'
import { createNanoparticleMesh, createNanoparticleMaterial } from './nanoparticle_display.js'
import { atomBaseKey } from './base_ref.js'

/** External selections have no DNA backbone entries. Own their geometry separately. */
export async function buildZoomExternal({ root, design, refs, proteinData, representation, coloring, opacity, getSurface, signal }) {
  const renderers = [], meshes = [], bounds = new THREE.Box3()
  let count = 0
  const dispose = () => {
    for (const renderer of renderers) renderer.dispose()
    for (const mesh of meshes) { mesh.removeFromParent(); mesh.geometry.dispose(); mesh.material.dispose() }
  }
  try {
    const ids = new Set(refs == null ? (design.nanoparticles ?? []).map(p => p.id) : refs.filter(r => r.kind === 'nanoparticle').map(r => r.id))
    for (const particle of design.nanoparticles ?? []) if (ids.has(particle.id)) {
      const mesh = createNanoparticleMesh(particle, createNanoparticleMaterial(particle))
      mesh.material.opacity = opacity; mesh.material.transparent = opacity < 1
      root.add(mesh); meshes.push(mesh); mesh.geometry.computeBoundingBox(); bounds.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrix)); count++
    }
    const proteins = new Set(refs == null ? (design.protein_attachments ?? []).map(p => p.id) : refs.filter(r => r.kind === 'protein').map(r => r.id))
    if (proteins.size) {
      const data = await proteinData()
      if (signal.aborted) { dispose(); return null }
      const atoms = (data?.atoms ?? []).filter(a => proteins.has(a.helix_id?.slice(11)))
      const serials = new Set(atoms.map(a => a.serial))
      const subset = { ...data, atoms, bonds: (data?.bonds ?? []).filter(([a,b]) => serials.has(a) && serials.has(b)) }
      if (atoms.length) {
        count += proteins.size
        for (const atom of atoms) bounds.expandByPoint(new THREE.Vector3(atom.x, atom.y, atom.z))
        let renderer
        if (representation === 'surface') {
          const mesh = await getSurface([], { nucleotideKeys: [...new Set(atoms.map(atomBaseKey))], signal })
          if (signal.aborted) { dispose(); return null }
          renderer = initSurfaceRenderer(root); renderer.update(mesh, coloring, 'zoom-protein'); renderer.setOpacity(opacity)
        } else if (['full', 'beads', 'cylinders'].includes(representation)) {
          renderer = initProteinTraceRenderer(root); renderer.setMode(representation === 'cylinders' ? 'ovoid' : 'trace'); renderer.update(subset)
        } else {
          renderer = initAtomisticRenderer(root, { independentColors: true }); renderer.update(subset); renderer.setMode(representation); renderer.setColorMode(coloring)
        }
        renderers.push(renderer)
      }
    }
    root.traverse(o => { for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) { m.opacity = opacity; m.transparent = opacity < 1 } })
    return { count, bounds, dispose }
  } catch (error) { dispose(); throw error }
}

import * as THREE from 'three'

/** Preserve existing picking/selection entry points when a region has several layers. */
export function combineAtomRenderers(base, additional) {
  const all = () => [base, ...additional()].filter(Boolean)
  return new Proxy(base, { get(target, key) {
    if (key === 'getMode') return () => all().find(r => r.getMode() !== 'off')?.getMode() ?? 'off'
    if (key === 'raycastPick') return ray => all().map(r => r.raycastPick?.(ray)).filter(Boolean).sort((a,b) => a.distance - b.distance)[0] ?? null
    if (key === 'selectionAtomEntries') return (...args) => all().flatMap(r => r.selectionAtomEntries?.(...args) ?? [])
    if (key === 'residueInfo') return (...args) => all().map(r => r.residueInfo?.(...args)).find(Boolean) ?? null
    if (['visitAtoms', 'highlight', 'applyResidueMatrix'].includes(key)) return (...args) => { for (const r of all()) r[key]?.(...args) }
    return typeof target[key] === 'function' ? target[key].bind(target) : target[key]
  } })
}
export function combineSurfaceRenderers(base, additional) {
  const faces = new WeakMap(), proxyMesh = new THREE.Object3D()
  const all = () => [base, ...additional()].filter(Boolean)
  proxyMesh.raycast = (ray, hits) => {
    for (const renderer of all()) {
      const mesh = renderer.getMesh?.()
      if (!mesh?.visible) continue
      for (const hit of ray.intersectObject(mesh, false)) {
        if (hit.face) faces.set(hit.face, renderer)
        hits.push(hit)
      }
    }
  }
  return new Proxy(base, { get(target, key) {
    if (key === 'getMesh') return () => additional().length ? proxyMesh : base.getMesh()
    if (key === 'getMode') return () => all().some(r => r.getMode() !== 'off') ? 'on' : 'off'
    if (key === 'strandIdAt') return face => (faces.get(face) ?? base).strandIdAt(face)
    return typeof target[key] === 'function' ? target[key].bind(target) : target[key]
  } })
}

export function coarseVolumePicker(entry, keys, geometry) {
  const nucleotides = geometry.filter(n => keys.has(`${n.helix_id}:${n.bp_index}`) && n.backbone_position)
  return { getMode: () => entry.root.visible ? 'full' : 'off', raycastPick(ray) {
    const meshes = []
    entry.root.traverseVisible(o => { if (o.isMesh) meshes.push(o) })
    const hit = ray.intersectObjects(meshes, false).find(h => h.instanceId == null || (h.object.geometry.attributes.instanceAlpha?.getX(h.instanceId) ?? 1) > 0)
    if (!hit) return null
    let atom = null, distance = Infinity
    for (const n of nucleotides) {
      const d = new THREE.Vector3(...n.backbone_position).applyMatrix4(entry.root.matrixWorld).distanceToSquared(hit.point)
      if (d < distance) { distance = d; atom = n }
    }
    return atom ? { atom, distance: hit.distance } : null
  } }
}

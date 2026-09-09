/**
 * Lightweight C-alpha tube/trace representation for imported proteins.
 *
 * One smooth tube is built for each contiguous protein chain.  The renderer
 * retains the full atom payload for exact centroids and transforms, while only
 * C-alpha positions are sent to geometry.  This is the protein counterpart of
 * NADOC's simplified Full representation.
 */
import * as THREE from 'three'

const PROTEIN_PREFIX = '__protein__'
const TRACE_RADIUS_NM = 0.16
const OVOID_PADDING_NM = 0.18
const CHAIN_COLORS = [0x58a6ff, 0xf0883e, 0x7ee787, 0xd2a8ff, 0xff7b72, 0x79c0ff]

function attachmentId(atom) {
  const id = atom?.helix_id
  return typeof id === 'string' && id.startsWith(PROTEIN_PREFIX)
    ? id.slice(PROTEIN_PREFIX.length) : null
}

export function proteinTraceChains(atoms = []) {
  const chains = new Map()
  for (const atom of atoms) {
    const id = attachmentId(atom)
    if (!id || atom.name !== 'CA') continue
    const key = `${id}\u0000${atom.chain_id ?? ''}`
    if (!chains.has(key)) chains.set(key, { attachmentId: id, chainId: atom.chain_id ?? '', atoms: [] })
    chains.get(key).atoms.push(atom)
  }
  const out = []
  for (const chain of chains.values()) {
    let segment = []
    for (const atom of chain.atoms) {
      const point = new THREE.Vector3(atom.x, atom.y, atom.z)
      const previous = segment.at(-1)
      // Do not bridge missing/disconnected PDB fragments with a long tube.
      if (previous && point.distanceTo(previous.point) > 1.2) {
        if (segment.length) out.push({ ...chain, atoms: segment.map(item => item.atom) })
        segment = []
      }
      segment.push({ atom, point })
    }
    if (segment.length) out.push({ ...chain, atoms: segment.map(item => item.atom) })
  }
  return out
}

export function proteinOvoidSpec(atoms = []) {
  if (!atoms.length) return null
  const box = new THREE.Box3()
  for (const atom of atoms) box.expandByPoint(new THREE.Vector3(atom.x, atom.y, atom.z))
  if (box.isEmpty()) return null
  const center = box.getCenter(new THREE.Vector3())
  const radii = box.getSize(new THREE.Vector3()).multiplyScalar(0.5)
  radii.x = Math.max(TRACE_RADIUS_NM, radii.x + OVOID_PADDING_NM)
  radii.y = Math.max(TRACE_RADIUS_NM, radii.y + OVOID_PADDING_NM)
  radii.z = Math.max(TRACE_RADIUS_NM, radii.z + OVOID_PADDING_NM)
  return { center, radii }
}

export function proteinBoxSpec(atoms = []) {
  const ovoid = proteinOvoidSpec(atoms)
  if (!ovoid) return null
  return { center: ovoid.center, size: ovoid.radii.clone().multiplyScalar(2) }
}

export function initProteinTraceRenderer(scene) {
  const root = new THREE.Group()
  root.name = 'proteinTraceRoot'
  scene.add(root)
  let mode = 'off'
  let data = { atoms: [] }
  let attachmentGroups = new Map()
  let selectedId = null
  let liveIds = []
  let oxdnaTransforms = {}

  function clear() {
    for (const child of [...root.children]) {
      child.traverse(obj => {
        obj.geometry?.dispose?.()
        obj.material?.dispose?.()
      })
      root.remove(child)
    }
    attachmentGroups = new Map()
  }

  function materialFor(index) {
    return new THREE.MeshPhongMaterial({
      color: CHAIN_COLORS[index % CHAIN_COLORS.length],
      shininess: 24,
    })
  }

  function rebuild() {
    clear()
    if (mode !== 'trace' && mode !== 'ovoid' && mode !== 'box') return
    const atomsByAttachment = new Map()
    for (const atom of data?.atoms ?? []) {
      const id = attachmentId(atom)
      if (!id) continue
      if (!atomsByAttachment.has(id)) atomsByAttachment.set(id, [])
      atomsByAttachment.get(id).push(atom)
    }
    for (const [id, atoms] of atomsByAttachment) {
      const group = new THREE.Group()
      group.name = 'proteinTrace'
      group.userData = { attachmentId: id, atoms }
      root.add(group)
      attachmentGroups.set(id, group)
    }
    if (mode === 'ovoid' || mode === 'box') {
      let ovoidIndex = 0
      for (const group of attachmentGroups.values()) {
        const spec = mode === 'box'
          ? proteinBoxSpec(group.userData.atoms)
          : proteinOvoidSpec(group.userData.atoms)
        if (!spec) continue
        const geometry = mode === 'box'
          ? new THREE.BoxGeometry(spec.size.x, spec.size.y, spec.size.z)
          : new THREE.SphereGeometry(1, 20, 14)
        if (mode === 'ovoid') geometry.scale(spec.radii.x, spec.radii.y, spec.radii.z)
        geometry.translate(spec.center.x, spec.center.y, spec.center.z)
        const mesh = new THREE.Mesh(geometry, materialFor(ovoidIndex++))
        mesh.name = mode === 'box' ? 'proteinBox' : 'proteinOvoid'
        mesh.castShadow = true
        mesh.receiveShadow = true
        mesh.userData.atom = group.userData.atoms[0]
        group.add(mesh)
      }
      applyOxdnaTransforms(oxdnaTransforms)
      highlight(selectedId ? { data: { attachment_id: selectedId } } : null)
      return
    }
    let chainIndex = 0
    for (const chain of proteinTraceChains(data?.atoms ?? [])) {
      const group = attachmentGroups.get(chain.attachmentId)
      if (!group || !chain.atoms.length) continue
      const points = chain.atoms.map(atom => new THREE.Vector3(atom.x, atom.y, atom.z))
      let geometry
      if (points.length === 1) {
        geometry = new THREE.SphereGeometry(TRACE_RADIUS_NM, 12, 8)
        geometry.translate(points[0].x, points[0].y, points[0].z)
      } else {
        const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal')
        geometry = new THREE.TubeGeometry(curve, Math.max(8, (points.length - 1) * 6), TRACE_RADIUS_NM, 8, false)
      }
      const mesh = new THREE.Mesh(geometry, materialFor(chainIndex++))
      mesh.name = 'proteinTrace'
      mesh.castShadow = true
      mesh.receiveShadow = true
      mesh.userData.atom = chain.atoms[Math.floor(chain.atoms.length / 2)]
      group.add(mesh)
    }
    applyOxdnaTransforms(oxdnaTransforms)
    highlight(selectedId ? { data: { attachment_id: selectedId } } : null)
  }

  function highlight(selection) {
    selectedId = selection?.data?.attachment_id ?? null
    for (const [id, group] of attachmentGroups) {
      group.traverse(obj => {
        if (!obj.isMesh) return
        if (obj.userData.baseColor == null) obj.userData.baseColor = obj.material.color.getHex()
        obj.material.color.setHex(id === selectedId ? 0xffffff : obj.userData.baseColor)
      })
    }
  }

  function applyOxdnaTransforms(transforms) {
    oxdnaTransforms = transforms || {}
    for (const [id, group] of attachmentGroups) {
      const values = oxdnaTransforms[id]
      group.matrixAutoUpdate = false
      group.matrix.identity()
      if (Array.isArray(values) && values.length === 16) group.matrix.set(...values)
      group.matrixWorldNeedsUpdate = true
    }
  }

  return {
    update(next) { data = next || { atoms: [] }; rebuild() },
    setMode(next) { if (mode === next) return; mode = next; rebuild() },
    getMode: () => mode,
    highlight,
    centroidOf(predicate = null) {
      const sum = new THREE.Vector3()
      const point = new THREE.Vector3()
      let count = 0
      root.updateMatrixWorld(true)
      for (const group of attachmentGroups.values()) {
        for (const atom of group.userData.atoms) {
          if (predicate && !predicate(atom)) continue
          point.set(atom.x, atom.y, atom.z).applyMatrix4(group.matrixWorld)
          sum.add(point); count++
        }
      }
      return count ? sum.multiplyScalar(1 / count) : null
    },
    raycastPick(raycaster) {
      const meshes = []
      root.traverse(obj => { if (obj.isMesh) meshes.push(obj) })
      const hit = raycaster.intersectObjects(meshes, false)[0]
      return hit ? { atom: hit.object.userData.atom, distance: hit.distance } : null
    },
    beginLiveTransform(predicate) {
      liveIds = []
      for (const [id, group] of attachmentGroups) {
        if (group.userData.atoms.some(predicate)) liveIds.push(id)
      }
    },
    applyLiveTransform(matrix) {
      for (const id of liveIds) {
        const group = attachmentGroups.get(id)
        if (!group) continue
        group.matrixAutoUpdate = false
        group.matrix.copy(matrix)
        group.matrixWorldNeedsUpdate = true
      }
    },
    endLiveTransform() { liveIds = [] },
    applyOxdnaTransforms,
    clearOxdnaTransforms() { applyOxdnaTransforms(null) },
    dispose() { clear(); scene.remove(root) },
  }
}

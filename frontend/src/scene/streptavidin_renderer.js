import * as THREE from 'three'

/** Actual 1STP C-alpha traces, instanced in nanoparticle-local coordinates. */
export function addStreptavidinCoating(mesh, coating) {
  if (!coating?.poses?.length) return
  const group = new THREE.Group(); group.name = 'streptavidin-coating'
  group.userData.tetramerCount = coating.poses.length
  const chains = new Map()
  for (const atom of coating.protein.atoms) {
    if (atom.name !== 'CA') continue
    if (!chains.has(atom.chain_id)) chains.set(atom.chain_id, [])
    chains.get(atom.chain_id).push(new THREE.Vector3(atom.x, atom.y, atom.z))
  }
  const colors = [0x58a6ff, 0xf0883e, 0x7ee787, 0xd2a8ff]
  let index = 0
  for (const points of chains.values()) {
    const geometry = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), points.length * 2, .10, 4, false)
    const material = new THREE.MeshPhongMaterial({ color: colors[index++ % colors.length] })
    const instances = new THREE.InstancedMesh(geometry, material, coating.poses.length)
    for (let i = 0; i < coating.poses.length; i++) {
      instances.setMatrixAt(i, new THREE.Matrix4().fromArray(coating.poses[i].values).transpose())
    }
    instances.instanceMatrix.needsUpdate = true
    instances.raycast = () => {} // selection/manipulation remains on the parent particle
    group.add(instances)
  }
  mesh.add(group)
}

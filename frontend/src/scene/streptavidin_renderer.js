import * as THREE from 'three'
import biotinPockets from '../../../backend/data/proteins/biotin_pockets.json'

/** Pocket-centered Full markers use the same crystallographic ring as atomistic. */
export function addBiotinMarkers(mesh, particle, representation = 'full', geometry = []) {
  if (!particle.coating) return
  const inverseParticle = new THREE.Matrix4().fromArray(particle.pose?.values ?? particle.pose ?? new THREE.Matrix4().toArray()).transpose().invert()
  const ends = new Map()
  for (const nucleotide of geometry) {
    if (nucleotide.direction !== 'FORWARD' || !nucleotide.backbone_position) continue
    const previous = ends.get(nucleotide.helix_id)
    if (!previous || nucleotide.bp_index < previous.bp_index) ends.set(nucleotide.helix_id, nucleotide)
  }
  const group = new THREE.Group(); group.name = 'biotin-pockets'
  group.visible = representation === 'full'
  for (const record of particle.biotin_dna ?? []) {
    const pose = particle.coating.poses[record.tetramer_index ?? 0]
    const pocket = biotinPockets.pockets[record.chain]
    if (!pose || !pocket) continue
    const marker = new THREE.Mesh(new THREE.SphereGeometry(.30, 20, 14),
      new THREE.MeshPhongMaterial({ color: 0xffde59 }))
    marker.position.fromArray(pocket.center)
    marker.applyMatrix4(new THREE.Matrix4().fromArray(pose.values).transpose())
    marker.name = 'bound-biotin'
    marker.userData = { strandId: record.strand_id, tetramerIndex: record.tetramer_index ?? 0, pocket: record.chain }
    marker.updateMatrix(); marker.userData.restMatrix = marker.matrix.clone()
    marker.raycast = () => {}
    const end = ends.get(record.helix_id)
    if (end) {
      // A coarse connection symbol: one spacer bead and two cylinders joining
      // the bound-biotin sphere to the actual native 5′ backbone bead.
      marker.userData.dnaEnd = new THREE.Vector3(...end.backbone_position).applyMatrix4(inverseParticle)
      const linker = new THREE.Group(); linker.name = 'biotin-linker'
      const material = new THREE.MeshPhongMaterial({ color: 0xffde59 })
      const bead = new THREE.Mesh(new THREE.SphereGeometry(.16, 12, 8), material)
      bead.name = 'biotin-linker-bead'; linker.add(bead)
      for (let i = 0; i < 2; i++) {
        const bond = new THREE.Mesh(new THREE.CylinderGeometry(.065, .065, 1, 10), material)
        bond.name = 'biotin-linker-cylinder'; linker.add(bond)
      }
      linker.traverse(obj => { obj.raycast = () => {} })
      marker.add(linker)
      updateBiotinLinker(marker)
    }
    group.add(marker)
  }
  mesh.add(group)
}

function updateBiotinLinker(marker) {
  const linker = marker.getObjectByName('biotin-linker')
  if (!linker) return
  // Recompute in the moving marker's frame so a protein delta moves only the
  // pocket end; the other end remains attached to the DNA in particle space.
  const end = marker.userData.dnaEnd.clone().applyMatrix4(marker.matrix.clone().invert())
  const midpoint = end.clone().multiplyScalar(.5)
  linker.children[0].position.copy(midpoint)
  const points = [new THREE.Vector3(), midpoint, end]
  for (let i = 0; i < 2; i++) {
    const cylinder = linker.children[i + 1]
    const direction = points[i + 1].clone().sub(points[i])
    const length = direction.length()
    cylinder.visible = length > 1e-8
    cylinder.position.copy(points[i]).add(points[i + 1]).multiplyScalar(.5)
    cylinder.scale.set(1, length, 1)
    if (length > 1e-8) cylinder.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.divideScalar(length))
  }
}

/** Apply each tetramer's world-space simulation delta independently. */
export function applyCoatingTransforms(mesh, particle, transforms = {}) {
  mesh.updateWorldMatrix(true, false)
  const delta = i => {
    const value = transforms[`${particle.id}:strep:${i}`]
    return value ? mesh.matrixWorld.clone().invert()
      .multiply(new THREE.Matrix4().set(...value)).multiply(mesh.matrixWorld) : new THREE.Matrix4()
  }
  mesh.userData.strepAtoms?.applyTransforms(particle.coating.poses.map((_, i) => delta(i)))
  for (const child of mesh.getObjectByName('streptavidin-coating')?.children ?? []) {
    if (!child.isInstancedMesh) continue
    particle.coating.poses.forEach((pose, i) => child.setMatrixAt(i,
      delta(i).multiply(new THREE.Matrix4().fromArray(pose.values).transpose())))
    child.instanceMatrix.needsUpdate = true
    child.computeBoundingSphere()
  }
  for (const marker of mesh.getObjectByName('biotin-pockets')?.children ?? []) {
    marker.matrixAutoUpdate = false
    marker.matrix.copy(delta(marker.userData.tetramerIndex)).multiply(marker.userData.restMatrix)
    marker.matrixWorldNeedsUpdate = true
    updateBiotinLinker(marker)
  }
}

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

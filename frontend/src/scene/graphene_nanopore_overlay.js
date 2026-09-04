import * as THREE from 'three'

/** Display-only preview of the graphene build descriptor used by an oxDNA-seeded NAMD job. */
export function initGrapheneNanoporeOverlay(scene) {
  let mesh = null
  function clear() {
    if (!mesh) return
    scene.remove(mesh)
    mesh.geometry.dispose(); mesh.material.dispose(); mesh = null
  }
  function update({ enabled, surface, poreDiameterNm = 2.1, layers = 1,
                    layerSpacingNm = 0.335, bounds } = {}) {
    clear()
    if (!enabled || !surface || surface.positionNm == null) return
    const n = new THREE.Vector3(...(surface.dir || [0, 1, 0])).normalize()
    const ctr = bounds
      ? new THREE.Vector3(...bounds.min).add(new THREE.Vector3(...bounds.max)).multiplyScalar(0.5)
      : new THREE.Vector3()
    const planeProjection = surface.faceRelative && bounds
      ? Math.min(...boundsCorners(bounds).map(p => p.dot(n))) - Number(surface.positionNm)
      : Number(surface.positionNm)
    ctr.addScaledVector(n, planeProjection - ctr.dot(n))
    const span = bounds
      ? Math.max(...bounds.max.map((v, i) => Number(v) - Number(bounds.min[i]))) + 4
      : 12
    const half = Math.max(5, span / 2)
    const shape = new THREE.Shape()
    shape.moveTo(-half, -half); shape.lineTo(half, -half); shape.lineTo(half, half)
    shape.lineTo(-half, half); shape.closePath()
    const hole = new THREE.Path()
    hole.absarc(0, 0, Math.max(0.05, Number(poreDiameterNm) / 2), 0, Math.PI * 2, true)
    shape.holes.push(hole)
    const geometry = Number(layers) > 1
      ? new THREE.ExtrudeGeometry(shape, { depth: (Number(layers) - 1) * Number(layerSpacingNm),
          bevelEnabled: false, curveSegments: 48 })
      : new THREE.ShapeGeometry(shape, 48)
    mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ color: 0x4b5563, metalness: 0.45, roughness: 0.48,
        transparent: true, opacity: 0.72, side: THREE.DoubleSide }))
    mesh.name = 'Graphene nanopore preview'
    mesh.userData.grapheneNanopore = true
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n)
    mesh.position.copy(ctr)
    mesh.renderOrder = 12
    scene.add(mesh)
  }
  return { update, clear, dispose: clear, mesh: () => mesh }
}

function boundsCorners(bounds) {
  const corners = []
  for (const x of [bounds.min[0], bounds.max[0]])
    for (const y of [bounds.min[1], bounds.max[1]])
      for (const z of [bounds.min[2], bounds.max[2]])
        corners.push(new THREE.Vector3(Number(x), Number(y), Number(z)))
  return corners
}

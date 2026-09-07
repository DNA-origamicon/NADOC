import * as THREE from 'three'
import { graphenePreviewSites, initGrapheneRepresentation } from './graphene_representation.js'

/** Display-only preview of the graphene build descriptor used by an oxDNA-seeded NAMD job. */
export function initGrapheneNanoporeOverlay(scene) {
  let mesh = null
  let simulationActive = false
  let display = { visible: true, representation: 'plane' }
  let spec = null
  let atoms = null
  function clear() {
    if (!mesh) return
    scene.remove(mesh)
    if (atoms) { atoms.dispose(); atoms = null }
    else { mesh.geometry.dispose(); mesh.material.dispose() }
    mesh = null
  }
  function update({ enabled, surface, poreDiameterNm = 2.1, layers = 1,
                    layerSpacingNm = 0.335, bounds } = {}) {
    clear()
    spec = { enabled, surface, poreDiameterNm, layers, layerSpacingNm, bounds }
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
    if (Number(layers) > 1) geometry.translate(0, 0, -(Number(layers) - 1) * Number(layerSpacingNm))
    mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ color: 0x4b5563, metalness: 0.45, roughness: 0.48,
        transparent: true, opacity: 0.72, side: THREE.DoubleSide }))
    if (display.representation !== 'plane') {
      mesh.geometry.dispose(); mesh.material.dispose()
      atoms = initGrapheneRepresentation(scene)
      atoms.setDisplay(display)
      atoms.setFrame(graphenePreviewSites(half, Number(poreDiameterNm) / 2, Number(layers), Number(layerSpacingNm)))
      mesh = atoms.mesh()
      if (!mesh) { atoms.dispose(); atoms = null; return }
    }
    mesh.visible = display.visible && !simulationActive
    mesh.name = 'Graphene nanopore preview'
    mesh.userData.grapheneNanopore = true
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n)
    mesh.position.copy(ctr)
    mesh.renderOrder = 12
    scene.add(mesh)
  }
  function setSimulationActive(active) {
    simulationActive = !!active
    if (mesh) mesh.visible = display.visible && !simulationActive
  }
  function setDisplay(settings) {
    const changed = settings.representation != null && display.representation !== settings.representation
    display = { ...display, ...settings }
    if (changed && spec) update(spec)
    if (mesh) mesh.visible = display.visible && !simulationActive
  }
  function reset() { clear(); spec = null }
  return { update, clear: reset, setSimulationActive, setDisplay, dispose: reset, mesh: () => mesh }
}

function boundsCorners(bounds) {
  const corners = []
  for (const x of [bounds.min[0], bounds.max[0]])
    for (const y of [bounds.min[1], bounds.max[1]])
      for (const z of [bounds.min[2], bounds.max[2]])
        corners.push(new THREE.Vector3(Number(x), Number(y), Number(z)))
  return corners
}

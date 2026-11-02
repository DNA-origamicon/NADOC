import * as THREE from 'three'

/** Cyan wireframe diamonds remain distinct from red clash halos at the same base. */
export function createPiercingMarkers(scene) {
  const geometry = new THREE.OctahedronGeometry(.55)
  const material = new THREE.MeshBasicMaterial({ color: 0x38d9ef, wireframe: true,
    transparent: true, opacity: .9, depthTest: false, depthWrite: false })
  let entries = [], mesh
  const matrix = new THREE.Matrix4()
  function allocate(size) {
    if (mesh) { scene.remove(mesh); mesh.dispose() }
    mesh = new THREE.InstancedMesh(geometry, material, size)
    mesh.name = 'piercingMarkers'; mesh.frustumCulled = false; mesh.renderOrder = 5
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
    mesh.count = 0
    scene.add(mesh)
  }
  allocate(1)
  function refresh() {
    if (!entries.length) return
    for (let i = 0; i < entries.length; i++) {
      const p = entries[i].getPosition?.() ?? entries[i].pos
      mesh.setMatrixAt(i, matrix.makeTranslation(p.x, p.y, p.z))
    }
    mesh.instanceMatrix.needsUpdate = true
  }
  return {
    setEntries(next) {
      entries = next
      if (entries.length > mesh.instanceMatrix.count) allocate(entries.length)
      mesh.count = entries.length
      refresh()
    },
    clear() { entries = []; mesh.count = 0 },
    refresh,
    count() { return mesh.count },
    dispose() { scene.remove(mesh); mesh.dispose(); geometry.dispose(); material.dispose(); entries = [] },
  }
}

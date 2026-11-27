// Instanced graphics stress fixture, not an authored molecule or document.
// Exercises the same baked instance attributes used by detailed representations.
export function addTraceGraphics(THREE, scene, count = 512) {
  const geometry = new THREE.SphereGeometry(.07, 12, 8)
  const material = new THREE.MeshStandardMaterial({color: 0xaaaaaa, roughness: .4})
  const mesh = new THREE.InstancedMesh(geometry, material, count)
  const matrix = new THREE.Matrix4()
  for (let i = 0; i < mesh.count; i++) {
    matrix.makeTranslation((i % 16 - 7.5) * .19, (Math.floor(i / 16) % 16 - 7.5) * .19, -2 - Math.floor(i / 256) * .2)
    mesh.setMatrixAt(i, matrix)
    mesh.setColorAt(i, new THREE.Color().setRGB(.3 + (i % 3) * .1, .4, .3))
  }
  scene.add(mesh)
  return () => {scene.remove(mesh); geometry.dispose(); material.dispose()}
}

// Persistent formed-product marker. This is intentionally separate from the
// KIMMDY/cpd_weld propensity overlay: it reads Design.photoproduct_junctions and
// uses a fixed amber double rail to mean explicit product intent.

export function initPhotoproductOverlay({ scene, THREE, store, getBasePosition }) {
  const root = new THREE.Group()
  root.name = 'formedPhotoproductOverlay'
  root.renderOrder = 9
  scene.add(root)
  const rails = []
  const material = new THREE.MeshBasicMaterial({
    color: 0xffa51f, transparent: true, opacity: 0.95, depthTest: true,
  })
  const geometry = new THREE.CylinderGeometry(0.045, 0.045, 1, 10)
  const yAxis = new THREE.Vector3(0, 1, 0)
  const midpoint = new THREE.Vector3()
  const direction = new THREE.Vector3()
  const side = new THREE.Vector3()

  function clear() {
    while (root.children.length) root.remove(root.children[0])
    rails.length = 0
  }

  function rebuild() {
    clear()
    for (const lesion of store.getState().currentDesign?.photoproduct_junctions ?? []) {
      if (!lesion.base_key_1 || !lesion.base_key_2) continue
      const pair = new THREE.Group()
      pair.name = `formedPhotoproduct:${lesion.id}`
      pair.userData = { kind: 'photoproduct', id: lesion.id }
      const a = new THREE.Mesh(geometry, material)
      const b = new THREE.Mesh(geometry, material)
      a.onBeforeRender = b.onBeforeRender = refresh
      a.userData = b.userData = pair.userData
      pair.add(a, b)
      root.add(pair)
      rails.push({ lesion, a, b })
    }
    refresh()
  }

  function refresh() {
    for (const item of rails) {
      const p1 = getBasePosition(item.lesion.base_key_1)
      const p2 = getBasePosition(item.lesion.base_key_2)
      item.a.visible = item.b.visible = Boolean(p1 && p2)
      if (!p1 || !p2) continue
      direction.copy(p2).sub(p1)
      const length = direction.length()
      if (length < 1e-8) {
        item.a.visible = item.b.visible = false
        continue
      }
      direction.multiplyScalar(1 / length)
      side.crossVectors(direction, Math.abs(direction.z) < 0.9
        ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0)).normalize().multiplyScalar(0.075)
      midpoint.copy(p1).add(p2).multiplyScalar(0.5)
      for (const [mesh, sign] of [[item.a, -1], [item.b, 1]]) {
        mesh.position.copy(midpoint).addScaledVector(side, sign)
        mesh.scale.set(1, length, 1)
        mesh.quaternion.setFromUnitVectors(yAxis, direction)
      }
    }
  }

  root.onBeforeRender = refresh
  const unsubscribe = store.subscribe((next, prev) => {
    if (next.currentDesign !== prev.currentDesign) rebuild()
  })
  rebuild()
  return {
    root,
    refresh,
    dispose() {
      unsubscribe?.()
      clear()
      geometry.dispose()
      material.dispose()
      scene.remove(root)
    },
  }
}

import * as THREE from 'three'

/** Painter's order for separately rendered transparent scenes: farthest first. */
export function overlayRenderOrder(layers, count, camera) {
  camera.updateMatrixWorld?.(true)
  const world = new THREE.Vector3()
  return layers.slice(0, count).map((layer, index) => {
    const scene = layer.renderScene
    scene?.updateMatrixWorld?.(true)
    if (scene) scene.getWorldPosition(world)
    else world.set(0, 0, 0)
    const cameraZ = world.clone().applyMatrix4(camera.matrixWorldInverse).z
    return { index, cameraZ }
  }).sort((a, b) => a.cameraZ - b.cameraZ || a.index - b.index)
    .map(entry => entry.index)
}

/** Keep each representation's lighting and depth buffer isolated while orbiting. */
export function renderSharedOverlay(renderer, scenes, camera) {
  const autoClear = renderer.autoClear
  try {
    const order = overlayRenderOrder(scenes.map(renderScene => ({ renderScene })), scenes.length, camera)
    order.forEach((index, draw) => {
      renderer.autoClear = draw === 0
      if (draw) renderer.clearDepth()
      renderer.render(scenes[index], camera)
    })
  } finally { renderer.autoClear = autoClear }
}

export function validateSharedOverlay(data) {
  const ids = data.view?.overlay
  if (ids == null) return
  if (data.version < 5 || !Array.isArray(ids) || ids.length < 1 || ids.length > 4 ||
      new Set(ids).size !== ids.length || data.root?.type !== 'Scene' || data.root.children?.length !== ids.length ||
      ids.some((id, i) => typeof id !== 'string' || data.root.children[i].uuid !== id || data.root.children[i].type !== 'Scene')) {
    throw new Error('Invalid shared overlay')
  }
}

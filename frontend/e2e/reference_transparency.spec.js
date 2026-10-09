import { test, expect } from '@playwright/test'

// Read actual GPU pixels with an enclosing STL and instanced DNA. A remote
// instance shifts the DNA bounding center, making the transparent draw order
// change as the camera orbits while the enclosed bead stays in the same place.
test('enclosing STL preserves per-pixel depth across camera angles and opacity changes', async ({ page }) => {
  await page.goto('/?debug&doc=e2e-reference-depth')
  await page.waitForFunction(() => window.__referenceModels)
  const samples = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { STLExporter } = await import('/node_modules/three/examples/jsm/exporters/STLExporter.js')
    const { parseReferenceSTL } = await import('/src/scene/reference_models.js')
    const { setReferenceOpacity } = await import('/src/scene/reference_material.js')
    const renderer = new THREE.WebGLRenderer({ antialias: false })
    renderer.setSize(128, 128); renderer.setClearColor(0x000000)
    renderer.outputColorSpace = THREE.LinearSRGBColorSpace
    const target = new THREE.WebGLRenderTarget(128, 128)
    renderer.setRenderTarget(target)
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, 1, .1, 100)
    const stl = new STLExporter().parse(new THREE.Mesh(new THREE.BoxGeometry(4, 4, 4)), { binary: true })
    const shell = new THREE.Mesh(parseReferenceSTL(stl.buffer), new THREE.MeshBasicMaterial({ color: 0x0000ff, side: THREE.DoubleSide }))
    scene.add(shell)
    const dna = new THREE.InstancedMesh(new THREE.SphereGeometry(.8, 32, 24),
      new THREE.MeshBasicMaterial({ color: 0xff0000, transparent: true, depthWrite: true }), 2)
    dna.position.set(6, 0, 0)
    dna.setMatrixAt(0, new THREE.Matrix4().makeTranslation(-6, 0, 0))
    dna.setMatrixAt(1, new THREE.Matrix4().makeTranslation(6, 0, 0))
    scene.add(dna)
    const foreground = new THREE.Mesh(new THREE.SphereGeometry(.4, 24, 16), new THREE.MeshBasicMaterial({ color: 0x00ff00 }))
    scene.add(foreground); foreground.visible = false
    function sample() {
      renderer.render(scene, camera)
      const pixels = new Uint8Array(12 * 12 * 4)
      renderer.readRenderTargetPixels(target, 58, 58, 12, 12, pixels)
      const rgb = [0, 0, 0]
      for (let i = 0; i < pixels.length; i += 4) for (let c = 0; c < 3; c++) rgb[c] += pixels[i + c] / 255 / (12 * 12)
      return rgb
    }
    const control = []
    shell.material.opacity = .5; shell.material.transparent = true; shell.material.depthWrite = false
    for (const angle of [0, Math.PI]) {
      camera.position.set(Math.cos(angle) * 9, 1, Math.sin(angle) * 9); camera.lookAt(0, 0, 0)
      control.push(sample())
    }
    const result = []
    for (const opacity of [.25, .5, .75, 1, 0, .5]) {
      setReferenceOpacity(shell.material, opacity)
      for (const angle of [0, .45, 1.1, 2.1, Math.PI, 4.2, 5.4]) {
        camera.position.set(Math.cos(angle) * 9, 1, Math.sin(angle) * 9); camera.lookAt(0, 0, 0)
        foreground.visible = false
        const inside = sample()
        foreground.position.copy(camera.position).normalize().multiplyScalar(3.5)
        foreground.visible = true
        const outside = sample()
        result.push({ opacity, angle, inside, outside })
      }
    }
    for (const mesh of [shell, dna, foreground]) { mesh.geometry.dispose(); mesh.material.dispose() }
    target.dispose(); renderer.dispose()
    return { result, control }
  })
  expect(samples.control.some(rgb => rgb[2] < .1)).toBe(true)
  for (const sample of samples.result) {
    const label = JSON.stringify(sample)
    expect(sample.inside[2], label).toBeGreaterThan(sample.opacity - .13)
    expect(sample.inside[2], label).toBeLessThan(sample.opacity + .13)
    expect(sample.inside[0], label).toBeGreaterThan(1 - sample.opacity - .13)
    expect(sample.outside[1], label).toBeGreaterThan(.95)
  }
})

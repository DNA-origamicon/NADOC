import { test, expect } from '@playwright/test'

// Exercise the actual WebGL pre-pass with the same materials used for blunt-end
// picking disks, independently of the design/trajectory fixture and camera.
test('invisible blunt-end disks and overlays do not generate silhouette pixels', async ({ page }) => {
  await page.route('**/silhouette-regression', route => route.fulfill({
    contentType: 'text/html', body: '<html><body style="margin:0"></body></html>',
  }))
  await page.goto('/silhouette-regression')
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { FigurePass } = await import('/src/scene/photo_renderer/figure_pass.js')
    const { EffectComposer } = await import('/node_modules/three/examples/jsm/postprocessing/EffectComposer.js')
    const { RenderPass } = await import('/node_modules/three/examples/jsm/postprocessing/RenderPass.js')
    const renderer = new THREE.WebGLRenderer({ preserveDrawingBuffer: true })
    renderer.setSize(320, 240)
    document.body.appendChild(renderer.domElement)
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('white')
    const camera = new THREE.PerspectiveCamera(45, 320 / 240, 0.1, 100)
    camera.position.z = 10
    const dna = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 16), new THREE.MeshBasicMaterial({ color: 'orange' }))
    dna.position.x = -1.5
    scene.add(dna)
    const disk = new THREE.Mesh(new THREE.CircleGeometry(1, 32), new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false,
    }))
    disk.position.x = 1.5
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ visible: false }))
    plane.position.y = 2
    scene.add(disk, plane)
    const composer = new EffectComposer(renderer)
    composer.addPass(new RenderPass(scene, camera))
    const figure = new FigurePass(scene, camera)
    figure.setParams({ outline: true, silhouette: 'chimerax' })
    figure.setSceneDepth(2)
    composer.addPass(figure)
    const pixels = () => {
      composer.render()
      const gl = renderer.getContext()
      const data = new Uint8Array(320 * 240 * 4)
      gl.readPixels(0, 0, 320, 240, gl.RGBA, gl.UNSIGNED_BYTE, data)
      return data
    }
    const withHelpers = pixels()
    disk.visible = plane.visible = false
    const withoutHelpers = pixels()
    figure.setParams({ outline: false })
    const withoutOutline = pixels()
    const dark = data => {
      let n = 0
      for (let i = 0; i < data.length; i += 4) if (Math.max(data[i], data[i + 1], data[i + 2]) < 70) n++
      return n
    }
    figure.setParams({ outline: true })
    disk.visible = plane.visible = true
    composer.render()
    return {
      helperDifferences: withHelpers.reduce((n, value, i) => n + (value !== withoutHelpers[i]), 0),
      outlined: dark(withHelpers), plain: dark(withoutOutline),
      restored: disk.visible && plane.visible,
    }
  })
  expect(result.helperDifferences).toBe(0)
  expect(result.outlined).toBeGreaterThan(result.plain + 100)
  expect(result.restored).toBe(true)
})

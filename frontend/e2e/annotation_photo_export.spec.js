import { writeFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'

test('annotation glow and callouts survive photomode PNG export', async ({ page }) => {
  test.setTimeout(120_000)
  await page.route('**/annotation-photo-regression', route => route.fulfill({
    contentType: 'text/html', body: '<html><body style="margin:0"><div id="host" style="position:relative;width:640px;height:480px"></div></body></html>',
  }))
  await page.goto('/annotation-photo-regression')
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { createAnnotationController } = await import('/src/scene/annotation_controller.js')
    const { initAnnotationOverlay } = await import('/src/scene/annotation_overlay.js')
    const { createPhotoMode } = await import('/src/scene/photo_mode.js')
    const host = document.getElementById('host')
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(50, 640 / 480, 0.1, 100)
    camera.position.z = 8
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(640, 480)
    host.append(renderer.domElement)
    const controller = createAnnotationController()
    controller.syncFromDesign({ id: 'export-test', annotations: [] })
    const entries = Array.from({ length: 9 }, (_, i) => ({
      nuc: { strand_id: 's1', helix_id: 'h0', bp_index: i, direction: 'FORWARD' },
      pos: new THREE.Vector3((i % 3 - 1) * 0.5, (Math.floor(i / 3) - 1) * 0.5, 0),
    }))
    for (const entry of entries) {
      const bead = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), new THREE.MeshPhongMaterial({ color: '#777777' }))
      bead.position.copy(entry.pos)
      scene.add(bead)
    }
    const design = { cluster_transforms: [{ id: 'arm', helix_ids: ['h0'] }] }
    const overlay = initAnnotationOverlay({ container: host, scene, controller, getCamera: () => camera,
      getEntries: () => entries, getDesign: () => design, getViewport: () => ({ width: 640, height: 480 }) })
    const a = controller.add({ text: 'Exported annotation\nDNA target', icon: 'warning', color: '#ff0000',
      highlight: true, glowColor: '#00ff00', glowIntensity: 1.5, manual: true, screenPos: { x: 0.15, y: 0.2 },
      refs: [{ kind: 'cluster', id: 'arm' }] })
    overlay.update()
    const mode = createPhotoMode({ scene, camera, renderer, setRenderFn() {}, resetRenderFn() {},
      setResizeCallback() {}, clearResizeCallback() {} })
    mode.activate()
    mode.setOutline(true)
    async function capture(width = 1280, height = 960) {
      const blob = await mode.renderToBlob(width, height)
      const bitmap = await createImageBitmap(blob)
      const canvas = document.createElement('canvas')
      canvas.width = bitmap.width; canvas.height = bitmap.height
      const ctx = canvas.getContext('2d')
      ctx.drawImage(bitmap, 0, 0)
      bitmap.close()
      const { data } = ctx.getImageData(0, 0, width, height)
      let red = 0, green = 0, yellow = 0
      for (let i = 0; i < data.length; i += 4) {
        const [r, g, b] = data.subarray(i, i + 3)
        if (r > 140 && g < 100 && b < 100) red++
        if (g > r + 30 && g > b + 30) green++
        if (r > 120 && g > 80 && b < 70) yellow++
      }
      return { red, green, yellow, url: canvas.toDataURL() }
    }
    const enabled = await capture()
    controller.update(a.id, { glowIntensity: 0 })
    const zero = await capture()
    controller.update(a.id, { highlight: false, glowIntensity: 1.5 })
    const highlightOff = await capture()
    controller.update(a.id, { highlight: true })
    const reenabled = await capture()
    controller.update(a.id, { glowIntensity: 1.5 })
    const portrait = await capture(600, 900)
    controller.setEnabled(false)
    const hidden = await capture()
    controller.setEnabled(true)
    controller.update(a.id, { visible: false })
    const entryHidden = await capture()
    const restoredAspect = camera.aspect
    // Retain the rendered PNG in the test page for visual inspection.
    host.style.display = 'none'
    const image = document.createElement('img')
    image.src = enabled.url; image.style.width = '640px'; document.body.append(image)
    window.annotationExportImage = enabled.url
    mode.deactivate?.()
    overlay.dispose(); controller.dispose(); renderer.dispose()
    return { highlightOff: { ...highlightOff, url: undefined }, reenabled: { ...reenabled, url: undefined },
      sameAsZero: highlightOff.url === zero.url, enabled: { ...enabled, url: undefined }, zero: { ...zero, url: undefined },
      portrait: { ...portrait, url: undefined }, hidden: { ...hidden, url: undefined },
      entryHidden: { ...entryHidden, url: undefined }, restoredAspect }
  })
  if (process.env.NADOC_E2E_SHOT) {
    const url = await page.evaluate(() => window.annotationExportImage)
    writeFileSync(process.env.NADOC_E2E_SHOT, Buffer.from(url.split(',')[1], 'base64'))
  }
  expect(result.enabled.red).toBeGreaterThan(500)
  expect(result.enabled.yellow).toBeGreaterThan(100)
  expect(result.enabled.green).toBeGreaterThan(result.zero.green + 20)
  expect(result.sameAsZero).toBe(true)
  expect(result.highlightOff.green).toBe(0)
  expect(result.highlightOff.red).toBeGreaterThan(500)
  expect(result.reenabled.green).toBe(result.enabled.green)
  expect(result.portrait.red).toBeGreaterThan(200)
  expect(result.hidden.red).toBe(0)
  expect(result.hidden.green).toBe(0)
  expect(result.entryHidden.red).toBe(0)
  expect(result.restoredAspect).toBeCloseTo(640 / 480)
})

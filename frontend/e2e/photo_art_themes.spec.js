import { test, expect } from '@playwright/test'

// No workspace documents, uploads or downloads: generic graphics primitives only.
// Browser state dies with the context. The optional contact sheet is retained evidence
// explicitly under .development-artifacts, never a molecular structure file.
test('art controls render themes, respond to representation changes, and grade exported frames', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  await page.route('**/photo-art-check', r => r.fulfill({ contentType: 'text/html', body: '<html><body></body></html>' }))
  await page.goto('/photo-art-check')
  await page.evaluate(async () => {
    const html = new DOMParser().parseFromString(await (await fetch('/')).text(), 'text/html')
    for (const style of html.querySelectorAll('style, link[rel="stylesheet"]')) {
      if (style.href?.includes('google')) continue
      document.head.append(style.cloneNode(true))
    }
    const panel = html.getElementById('photo-settings')
    panel.disabled = false
    panel.style.cssText = 'width:340px;position:absolute;right:0;top:0;bottom:0;overflow:auto'
    document.body.append(panel)
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { createPhotoMode } = await import('/src/scene/photo_mode.js')
    const { initPhotoPanel } = await import('/src/ui/photo_panel.js')
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 4/3, .1, 100)
    camera.position.set(0, 1, 9); camera.lookAt(0, 0, 0)
    const group = new THREE.Group(); scene.add(group)
    for (let i = 0; i < 3; i++) {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(.8, 40, 32), new THREE.MeshPhongMaterial({ color: [0x16a8ed, 0xf46d8c, 0xf1b444][i] }))
      mesh.position.set((i - 1) * 1.4, (i % 2) * .6, 0); mesh.name = 'backboneSpheres'; group.add(mesh)
    }
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
    renderer.setSize(640, 480); document.body.append(renderer.domElement)
    let render
    const mode = createPhotoMode({ scene, camera, renderer, controls: { target: new THREE.Vector3(), update() {} }, setRenderFn: fn => { render = fn }, resetRenderFn() {}, setResizeCallback() {}, clearResizeCallback() {} })
    const ui = initPhotoPanel(mode)
    mode.activate(); ui.onEnter()
    const draw = () => { render?.(); window.__artRAF = requestAnimationFrame(draw) }; draw()
    window.__art = { mode, ui, group, scene, camera, renderer }
  })
  await expect(page.locator('#photo-advanced')).not.toHaveAttribute('open', '')
  await expect(page.locator('#photo-material')).toHaveValue('flat')
  expect(await page.evaluate(() => ({ available: window.__art.mode.getMaterialAvailability(), disabled: document.querySelector('#photo-material option[value="glass"]').disabled }))).toEqual({ available: { representations: ['full'], unsupported: 0 }, disabled: true })
  await page.selectOption('#photo-art-theme', 'electric')
  await expect(page.locator('#photo-material')).toHaveValue('glossy')
  expect(await page.evaluate(() => window.__art.mode.getSettings().saturation)).toBe(1.3)
  await page.selectOption('#photo-art-theme', 'scientific-light')
  expect(await page.evaluate(() => window.__art.mode.getSettings().outline)).toBe(true)
  await page.evaluate(() => { for (const mesh of window.__art.group.children) mesh.name = 'dna-surface' })
  await expect(page.locator('#photo-material option[value="glass"]')).toBeEnabled()
  const result = await page.evaluate(async () => {
    const { mode, ui, renderer } = window.__art
    const select = document.getElementById('photo-art-theme')
    const sheet = document.createElement('canvas'); sheet.width = 960; sheet.height = 540
    const ctx = sheet.getContext('2d')
    let i = 0
    for (const name of ['bright-studio', 'electric', 'metal-studio', 'soft-studio', 'scientific-light', 'scientific-dark']) {
      select.value = name; select.dispatchEvent(new Event('change'))
      const bitmap = await createImageBitmap(await mode.renderToBlob(320, 240))
      const x = i % 3 * 320, y = Math.floor(i / 3) * 270
      ctx.drawImage(bitmap, x, y); bitmap.close()
      ctx.fillStyle = '#151a21'; ctx.fillRect(x, y + 240, 320, 30)
      ctx.fillStyle = 'white'; ctx.font = '16px sans-serif'; ctx.fillText(name, x + 10, y + 260); i++
    }
    select.value = 'bright-studio'; select.dispatchEvent(new Event('change'))
    mode.setBackground('transparent', '#ffffff')
    const session = mode.beginFrameSession(320, 240)
    const sample = async () => {
      const bitmap = await createImageBitmap(await session.renderFrame())
      const c = document.createElement('canvas'); c.width = 320; c.height = 240
      const context = c.getContext('2d'); context.drawImage(bitmap, 0, 0); bitmap.close()
      const data = context.getImageData(0, 0, 320, 240).data
      let chroma = 0, opaque = 0
      for (let p = 0; p < data.length; p += 4) if (data[p + 3] > 250) { chroma += Math.abs(data[p] - data[p + 1]) + Math.abs(data[p + 1] - data[p + 2]); opaque++ }
      return { chroma: chroma / opaque, opaque, cornerAlpha: data[3] }
    }
    const color = await sample(); mode.setColorGrade({ saturation: 0 }); const gray = await sample()
    session.dispose(); cancelAnimationFrame(window.__artRAF); ui.dispose(); mode.deactivate(); renderer.dispose()
    return { color, gray, sheet: sheet.toDataURL() }
  })
  expect(result.color.opaque).toBeGreaterThan(1000)
  expect(result.color.chroma).toBeGreaterThan(10)
  expect(result.gray.chroma).toBeLessThan(2)
  expect(result.gray.cornerAlpha).toBe(0)
  expect(errors).toEqual([])
  if (process.env.NADOC_ART_EVIDENCE) {
    const { writeFile } = await import('node:fs/promises')
    await writeFile(process.env.NADOC_ART_EVIDENCE, Buffer.from(result.sheet.split(',')[1], 'base64'))
  }
})

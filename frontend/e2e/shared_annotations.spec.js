import { test, expect } from '@playwright/test'

test('presenter annotations appear, follow guest cameras, update, and disappear when disabled', async ({ page }) => {
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  await page.goto('/viewer.html?test=1')
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { createAnnotationController } = await import('/src/scene/annotation_controller.js')
    const { initAnnotationOverlay, captureSceneAnnotations } = await import('/src/scene/annotation_overlay.js')
    const { prepareScene } = await import('/src/viewer/prepared_scene.js')
    const scene = new THREE.Scene()
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(3, 16, 12), new THREE.MeshBasicMaterial()))
    const camera = new THREE.PerspectiveCamera(55, 1, .1, 1000)
    camera.position.set(0, 0, 20); camera.lookAt(0, 0, 0)
    const host = document.createElement('div'); host.style.display = 'none'; document.body.append(host)
    const controller = createAnnotationController({ setTimer: () => 0, clearTimer() {} })
    controller.syncFromDesign({ id: 'test-annotation', annotations: [] })
    const overlay = initAnnotationOverlay({ container: host, scene, controller, getCamera: () => camera,
      getEntries: () => [{ pos: new THREE.Vector3(2, 1, 0), nuc: { strand_id: 's1' } }], getViewport: () => ({ width: 800, height: 600 }) })
    const entry = controller.add({ text: 'Shared target', icon: 'check', calloutType: 'rounded', color: '#58a6ff', refs: [{ kind: 'strand', id: 's1' }] })
    controller.add({ text: 'Hidden note', visible: false })
    const publish = async () => {
      const bytes = prepareScene({ scene, camera: { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }, view: { annotations: captureSceneAnnotations(scene) } })
      if (!await window.__preparedViewer.loadFile(new File([bytes], 'annotation.nadocview'))) throw new Error(document.getElementById('status').textContent)
    }
    window.annotationTest = { controller, entry, publish, dispose() { overlay.dispose(); controller.dispose(); host.remove() } }
    await publish()
  })
  const callout = page.locator('main .nadoc-anno')
  await expect(callout).toHaveCount(1)
  await expect(callout).toContainText('Shared target')
  await expect(callout.locator('svg')).toBeVisible()
  await expect(page.locator('main .nadoc-anno__grip')).toHaveCount(0)
  const clearsStructure = () => page.evaluate(() => {
    const box = document.querySelector('main .nadoc-anno').getBoundingClientRect()
    const viewport = document.querySelector('main').getBoundingClientRect()
    const x = viewport.x + viewport.width / 2, y = viewport.y + viewport.height / 2
    return box.right < x - 50 || box.left > x + 50 || box.bottom < y - 50 || box.top > y + 50
  })
  await expect.poll(clearsStructure).toBe(true)
  const dot = page.locator('main .nadoc-anno-leaders circle')
  await expect(dot).toHaveAttribute('cx', /\d/)
  const before = await dot.getAttribute('cx')
  await page.evaluate(() => { const v = window.__preparedViewer; v.runtime.camera.position.x = -10; v.runtime.camera.lookAt(0, 0, 0); v.runtime.controls.update() })
  await expect.poll(() => dot.getAttribute('cx')).not.toBe(before)
  await page.evaluate(async () => { const t = window.annotationTest; t.controller.update(t.entry.id, { text: 'Edited target', manual: true, screenPos: { x: .2, y: .2 } }); await t.publish() })
  await expect(callout).toContainText('Edited target')
  await expect.poll(clearsStructure).toBe(true)
  await page.evaluate(async () => { window.annotationTest.controller.setEnabled(false); await window.annotationTest.publish() })
  await expect(callout).toHaveCount(0)
  await page.evaluate(async () => { window.annotationTest.controller.setEnabled(true); await window.annotationTest.publish() })
  await expect(callout).toHaveCount(1)
  await expect(callout).toContainText('Edited target')
  await page.evaluate(() => { window.__preparedViewer.clear(); window.annotationTest.dispose() })
  await expect(page.locator('main .nadoc-anno-layer')).toHaveCount(0)
  expect(errors).toEqual([])
})

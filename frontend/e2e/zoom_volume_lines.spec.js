import { test, expect } from '@playwright/test'
import { existsSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'

// Source stays read only; all loading uses a test-owned copy cleaned by global teardown.
const fixture = process.env.NADOC_ZOOM_LINES_FIXTURE
const doc = '__e2e__zoom-volume-lines'
test('protein zoom connectors touch the projected volume at Voltron pose 3', async ({ page }) => {
  test.skip(!fixture || !existsSync(fixture), 'Set NADOC_ZOOM_LINES_FIXTURE to local VoltronCoreArmV2.nadoc')
  test.setTimeout(240000)
  const owned = resolve('../workspace', `${doc}.nadoc`)
  expect(existsSync(owned)).toBe(false)
  execFileSync('python', ['-c', 'import json,sys; d=json.load(open(sys.argv[1])); d["id"]=sys.argv[3]; d["metadata"]["name"]=sys.argv[3]; json.dump(d,open(sys.argv[2],"w"))', fixture, owned, doc])
  await page.setViewportSize({ width: 1600, height: 1000 })
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await page.goto(`/?debug=1&doc=${doc}`)
  await page.waitForFunction(() => window.__NADOC_DBG__)
  await page.evaluate(async path => {
    const api = await import('/src/api/client.js'); await api.loadDesign(path); await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive', 'hidden')
    await window.__NADOC_DBG__.refreshProteins()
    const state = window.__nadocTest.store.getState()
    const pose = state.currentDesign.camera_poses.find(p => p.name === 'Pose 3')
    await window.__NADOC_DBG__.animateCameraTo({ ...pose, duration: 1 })
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store: window.__nadocTest.store }).replace([{ kind: 'protein', id: state.currentDesign.protein_attachments[0].id }])
    document.querySelector('.right-tab-btn[data-tab="visualization"]').click()
  }, owned)
  await page.locator('#zoom-volume-set').click()
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().ready), { timeout: 60000 }).toBe(true)
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().triangles)).toBeGreaterThan(0)
  const capture = process.env.NADOC_ZOOM_LINES_CAPTURE
  if (capture) { mkdirSync(capture, { recursive: true }); await page.screenshot({ path: `${capture}/pose3-protein.png` }) }
  const errorsPx = await page.evaluate(() => {
    const { camera, scene, THREE } = window.__NADOC_DBG__
    const box = scene.getObjectByName('zoom-volume-selection-box'), rect = document.getElementById('canvas').getBoundingClientRect()
    const points = [], positions = box.geometry.getAttribute('position')
    for (let i = 0; i < positions.count; i++) {
      const p = new THREE.Vector3().fromBufferAttribute(positions, i).applyMatrix4(box.matrixWorld).project(camera)
      points.push({ x: rect.left + (p.x + 1) * rect.width / 2, y: rect.top + (1 - p.y) * rect.height / 2 })
    }
    const host = document.getElementById('zoom-volume-inset'), inset = host.getBoundingClientRect()
    return [...host.nextElementSibling.querySelectorAll('line')].map(line => {
      const x = +line.getAttribute('x1'), y = +line.getAttribute('y1'), ix = +line.getAttribute('x2'), iy = +line.getAttribute('y2')
      return { volume: Math.min(...points.map(p => Math.hypot(p.x-x,p.y-y))), inset: Math.min(...[inset.left,inset.right].flatMap(cx => [inset.top,inset.bottom].map(cy => Math.hypot(cx-ix,cy-iy)))) }
    })
  })
  expect(errorsPx).toHaveLength(2)
  for (const error of errorsPx) { expect(error.volume).toBeLessThan(1); expect(error.inset).toBeLessThan(1) }
  expect(errors).toEqual([])
})

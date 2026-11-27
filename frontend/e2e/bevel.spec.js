import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'
import { beadCandidates, trackConsoleErrors } from './helpers/scene_harness.js'

// Isolated launcher owns workspace, revisions, browser profiles and caches;
// its finally removes the whole temporary root on success or failure.
for (const curved of [true, false]) test(`Bevel ${curved ? 'curved' : 'straight'} bundle preview, edit, undo and replay`, async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const doc = `__e2e__bevel-${curved}`
  const errors = trackConsoleErrors(page)
  page.on('response', async response => {
    if (response.status() >= 400) console.log('Bevel HTTP error', response.url(), response.status(), await response.text().catch(() => 'unavailable'))
  })
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill(doc)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(doc => window.__nadocTest.store.getState().currentDesign?.metadata?.name === doc, doc)
  await page.evaluate(async ({ doc, curved }) => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: [[0, 0], [0, 1]], lengthBp: 84, name: doc, latticeType: 'HONEYCOMB' })
    if (curved) {
      const design = window.__nadocTest.store.getState().currentDesign
      const result = await api._request('POST', '/design/deformation', {
        type: 'bend', plane_a_bp: 7, plane_b_bp: 70,
        cluster_ids: [design.cluster_transforms[0].id],
        params: { kind: 'bend', curvature_deg_per_bp: .3, direction_deg: 30 },
      })
      if (!result) throw new Error('Bend failed')
      await api._syncFromDesignResponse(result)
    }
    window.__nadocTest.applyCameraPoseForTest({ target: [1, 1, 14], position: [55, 18, 14] })
  }, { doc, curved })
  const before = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-bevel').click()
  const popup = page.locator('.tool-popup[data-tool-panel="bevel-panel"]')
  await expect(popup).toBeVisible()
  await expect(popup.locator('[role=status]')).toHaveText('Select a cluster in the viewer.', { timeout: 15000 })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().selection.level)).toBe('cluster')
  const header = await popup.locator('.tool-popup__header').boundingBox()
  await page.mouse.move(header.x + 50, header.y + 12)
  await page.mouse.down()
  await page.mouse.move(350, 110)
  await page.mouse.up()
  await page.screenshot({ path: testInfo.outputPath('selection.png') })
  await page.mouse.move(800, 700)
  const points = await beadCandidates(page)
  for (const point of points) {
    const visible = await page.evaluate(p => document.elementFromPoint(p.x, p.y)?.id === 'canvas', point)
    if (!visible) continue
    await page.mouse.click(point.x, point.y)
    if (await page.locator('#bevel-positionBp').isEnabled()) break
  }
  if (!(await page.locator('#bevel-positionBp').isEnabled())) console.log('Bevel pick diagnostics', await page.evaluate(() => ({ selection: window.__nadocTest.store.getState().selection, clusters: window.__nadocTest.store.getState().currentDesign.cluster_transforms, status: document.querySelector('#bevel-panel [role=status]').textContent })), errors)
  await expect(page.locator('#bevel-positionBp')).toBeEnabled()
  await page.locator('#bevel-angleDeg').fill('30')
  await expect(popup.locator('.def-btn.primary')).toBeEnabled({ timeout: 30_000 })
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(before)
  await popup.locator('.def-btn.primary').click()
  await expect(popup).not.toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1).op_kind)).toBe('bevel')
  await page.screenshot({ path: testInfo.outputPath('applied.png') })
  const after = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))
  expect(after).not.toBe(before)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(before)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(after)
  await page.locator('#fl-list button[title^="Edit"]').last().click()
  await expect(popup).toBeVisible()
  await page.locator('#bevel-trimEnd').selectOption('start')
  await page.locator('#bevel-angleDeg').fill('15')
  await expect(popup.locator('.def-btn.primary')).toBeEnabled({ timeout: 30_000 })
  await popup.locator('.def-btn.primary').click()
  await expect(popup).not.toBeVisible()
  const row = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1))
  expect(row.params).toMatchObject({ angle_deg: 15, trim_end: 'start' })
  const headers = { 'X-NADOC-Doc': doc }
  const start = await page.request.post('/api/design/features/verification/jobs', { headers })
  expect(start.status()).toBe(202)
  const { job_id: job } = await start.json()
  let result
  await expect.poll(async () => {
    result = await (await page.request.get(`/api/design/features/verification/jobs/${job}`, { headers })).json()
    return result.status
  }, { timeout: 15_000 }).toBe('complete')
  expect(result.result).toMatchObject({ status: 'verified', native_editable: true })
  expect(errors).toEqual([])
})


const cornerPath = fileURLToPath(new URL('../../workspace/corner_test.nadoc', import.meta.url))
test('Bevel live Full and face/rotation gestures along corner_test.nadoc', async ({ page }, testInfo) => {
  page.on('console', message => {
    if (message.text().startsWith('[API ') && /(?:bevel|undo|redo|features)/.test(message.text())) console.log(message.text())
  })
  test.skip(!existsSync(cornerPath), 'Local corner_test.nadoc is absent')
  test.setTimeout(240_000)
  const original = readFileSync(cornerPath, 'utf8'), doc = '__e2e__bevel-corner'
  const errors = trackConsoleErrors(page), calls = []
  page.on('console', message => { if (message.text().startsWith('Corner')) console.log(message.text()) })
  page.on('requestfailed', r => console.log('Corner request failed', r.url(), r.failure()))
  page.on('response', async r => { if (r.status() >= 400) console.log('Corner response', r.url(), r.status(), await r.text().catch(() => '')) })
  page.on('request', request => { if (request.url().includes('/design/bevel/')) calls.push(request.url()) })
  await page.addInitScript(() => Object.defineProperty(window, 'devicePixelRatio', { get: () => .5 }))
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill(doc)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  // CPU timing follows the Bend harness: pause continuous SwiftShader raster,
  // explicitly render checked views and keep real canvas raycasts for gestures.
  await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
  await page.evaluate(async ({ original, doc }) => {
    const api = await import('/src/api/client.js'), hold = api.holdFeatureEditSaves()
    await hold.ready
    try {
      if (!await api.importDesign(original)) throw new Error('Corner import failed')
      console.log('Corner source loaded')
      await api._syncFromDesignResponse(await api._request('PUT', '/design/metadata', { name: doc }), { skipGeometry: true })
    } finally { hold.release() }
    window.__nadocTest.setRepresentation('full')
    const THREE = await import('/node_modules/three/build/three.module.js'), box = new THREE.Box3()
    for (const n of window.__nadocTest.store.getState().currentGeometry) box.expandByPoint(new THREE.Vector3(...n.backbone_position))
    const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length()
    window.__nadocTest.applyCameraPoseForTest({ target: center.toArray(), position: center.clone().add(new THREE.Vector3(size * .7, size * 1.4, size * .8)).toArray() })
  }, { original, doc })
  // Finish the fixture's workspace save before starting the tool, as in the
  // Sweep workflow. Bevel must not race a save's revision acknowledgement.
  await expect(page.locator('#sync-status-text')).toContainText('saved', { timeout: 60000 })
  const before = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-bevel').click()
  const popup = page.locator('.tool-popup[data-tool-panel="bevel-panel"]')
  await expect(popup.locator('[role=status]')).toHaveText('Select a cluster in the viewer.', { timeout: 15000 })
  const header = await popup.locator('.tool-popup__header').boundingBox()
  await page.mouse.move(header.x + 50, header.y + 12); await page.mouse.down(); await page.mouse.move(70, 100); await page.mouse.up()
  await page.evaluate(() => {
    const api = window.__nadocTest, design = api.store.getState().currentDesign
    api.selectRefsForTest([{ kind: 'cluster', id: design.cluster_transforms[0].id }])
  })
  await expect(page.locator('#bevel-positionBp')).toBeEnabled()
  await page.locator('#bevel-positionBp').fill('140')
  await expect(popup.locator('.def-btn.primary')).toBeEnabled({ timeout: 60000 })
  console.log('Corner live Full prepared')
  await page.screenshot({ path: testInfo.outputPath('corner-preview.png') })
  await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
  const fullId = await page.evaluate(() => window.__nadocTest.scene.getObjectByName('bevel-full-preview').uuid)
  const times = []
  for (const station of [40, 60, 130, 150, 140]) {
    await page.locator('#bevel-positionBp').fill(String(station))
    await expect(popup.locator('.def-btn.primary')).toBeEnabled()
    await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
    times.push(await page.evaluate(() => {
      const root = window.__nadocTest.scene.getObjectByName('bevel-full-preview')
      return { id: root.uuid, point: window.__nadocTest.scene.getObjectByName('bevel-plane-controls').position.toArray(), ms: root.userData.previewMilliseconds, status: document.querySelector('#bevel-panel [role=status]').textContent }
    }))
  }
  expect(times.every(t => t.id === fullId)).toBe(true)
  expect(calls.filter(url => url.includes('/source'))).toHaveLength(1)
  expect(calls.filter(url => url.includes('/preview')).every(url => url.includes('prepare_only=true'))).toBe(true)
  console.log('Corner live preview timings', times)
  // Drag across the actual corner, not only along one straight arm.
  await page.locator('#bevel-positionBp').fill('60')
  await page.locator('#bevel-positionBp').blur()
  const across = await page.evaluate(async ({ from, to }) => {
    const THREE = await import('/node_modules/three/build/three.module.js'), t = window.__nadocTest
    const a = new THREE.Vector3(...from), b = new THREE.Vector3(...to), center = a.clone().add(b).multiplyScalar(.5)
    t.controls.target.copy(center); t.camera.position.copy(center).add(new THREE.Vector3(5, 95, 10))
    t.camera.up.set(0, 0, 1); t.controls.update(); t.camera.updateMatrixWorld(); t.renderViewerFrameForTest()
    const rect = document.getElementById('canvas').getBoundingClientRect()
    const screen = p => { const q = p.project(t.camera); return { x: rect.x + (q.x + 1) * rect.width / 2, y: rect.y + (1 - q.y) * rect.height / 2 } }
    return { from: screen(a), to: screen(b) }
  }, { from: times[1].point, to: times[4].point })
  await page.mouse.move(across.from.x, across.from.y); await page.mouse.down()
  await page.mouse.move(across.to.x, across.to.y, { steps: 24 }); await page.mouse.up()
  const afterCorner = Number(await page.locator('#bevel-positionBp').inputValue())
  console.log('Corner cross-junction face drag', { from: 60, to: afterCorner })
  expect(afterCorner).toBeGreaterThan(120)
  await page.locator('#bevel-positionBp').fill('140')
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js'), t = window.__nadocTest
    const center = t.scene.getObjectByName('bevel-plane-controls').position
    t.controls.target.copy(center); t.camera.position.copy(center).add(new THREE.Vector3(50, 60, 50))
    t.camera.up.set(0, 1, 0); t.controls.update(); t.camera.updateMatrixWorld(); t.renderViewerFrameForTest()
  })
  // Native raycast face drag; both endpoints are projected from the actual plane.
  const gesture = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js'), api = window.__nadocTest
    const plane = api.scene.getObjectByName('bevel-plane-controls'), camera = api.camera
    const rect = document.getElementById('canvas').getBoundingClientRect()
    const project = p => { const q = p.project(camera); return { x: rect.x + (q.x + 1) * rect.width / 2, y: rect.y + (1 - q.y) * rect.height / 2 } }
    plane.updateMatrixWorld(true)
    const normal = new THREE.Vector3(...plane.userData.normal)
    for (const x of [0, 3, -3, 6, -6]) for (const y of [0, 3, -3, 6, -6]) {
      const center = plane.localToWorld(new THREE.Vector3(x, y, 0))
      const from = project(center.clone()), to = project(center.addScaledVector(normal, 6))
      if (document.elementFromPoint(from.x, from.y)?.id === 'canvas' && document.elementFromPoint(to.x, to.y)?.id === 'canvas') return { from, to }
    }
    const p = project(plane.position.clone())
    throw new Error('The plane face is covered: ' + JSON.stringify({ p, hit: document.elementFromPoint(p.x, p.y)?.outerHTML?.slice(0, 400) }))
  })
  await page.locator('#bevel-positionBp').blur()
  console.log('Corner face gesture', gesture)
  await page.mouse.move(gesture.from.x, gesture.from.y); await page.mouse.down()
  console.log('Corner face drag captured', await page.evaluate(() => !window.__nadocTest.controlsEnabled()))
  await page.mouse.move(gesture.to.x, gesture.to.y, { steps: 12 }); await page.mouse.up()
  expect(Number(await page.locator('#bevel-positionBp').inputValue())).not.toBe(140)
  expect(await page.evaluate(() => window.__nadocTest.controlsEnabled())).toBe(true)
  await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
  await page.screenshot({ path: testInfo.outputPath('corner-face-drag.png') })
  await page.keyboard.press('Tab')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.getObjectByName('bevel-plane-controls').userData.mode)).toBe('rotate')
  // Pick a visible rotation ring vertex, outside any popup, using the actual gizmo.
  const ring = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js'), api = window.__nadocTest, helper = api.scene.getObjectByName('bevel-rotation-controls')
    const rect = document.getElementById('canvas').getBoundingClientRect(), candidates = []
    helper.updateMatrixWorld(true)
    helper.traverse(o => {
      if (!o.isMesh || !o.visible || !['X', 'Y'].includes(o.name) || o.parent !== helper.controls._gizmo.gizmo.rotate) return
      for (let p = o.parent; p; p = p.parent) if (!p.visible) return
      const positions = o.geometry.attributes.position
      for (let i = 0; i < positions.count; i += 3) {
        const q = new THREE.Vector3().fromBufferAttribute(positions, i).applyMatrix4(o.matrixWorld).project(api.camera)
        const x = rect.x + (q.x + 1) * rect.width / 2, y = rect.y + (1 - q.y) * rect.height / 2
        if (document.elementFromPoint(x, y)?.id === 'canvas') candidates.push({ x, y })
      }
    })
    return candidates
  })
  expect(ring.length).toBeGreaterThan(0)
  const angleBefore = await page.locator('#bevel-angleDeg').inputValue()
  for (const p of ring.slice(0, 20)) {
    await page.mouse.move(p.x, p.y); await page.mouse.down(); await page.mouse.move(p.x + 25, p.y + 20, { steps: 8 }); await page.mouse.up()
    if (await page.locator('#bevel-angleDeg').inputValue() !== angleBefore) break
  }
  expect(await page.locator('#bevel-angleDeg').inputValue()).not.toBe(angleBefore)
  await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
  await page.screenshot({ path: testInfo.outputPath('corner-rotation.png') })
  await page.keyboard.press('Tab')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.getObjectByName('bevel-plane-controls').userData.mode)).toBe('translate')
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(before)
  await page.locator('#bevel-positionBp').fill('150'); await page.locator('#bevel-angleDeg').fill('20')
  await expect(popup.locator('[role=status]')).toHaveText('Live Full preview. Ready to apply.')
  // Measure click -> recorded topology + geometry synchronized + popup closed.
  // Continuous SwiftShader raster is paused, as in the live-preview timings.
  const applyMs = await page.evaluate(async () => {
    const button = document.querySelector('#bevel-panel .def-btn.primary'), panel = button.closest('.tool-popup')
    const start = performance.now()
    button.click()
    while (getComputedStyle(panel).display !== 'none' && panel.getClientRects().length) {
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    return performance.now() - start
  })
  console.log('Corner cold Apply milliseconds (no prepared result)', applyMs)
  await expect(popup).not.toBeVisible({ timeout: 60000 })
  await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
  await page.screenshot({ path: testInfo.outputPath('corner-applied.png') })
  const operationTimes = { apply: applyMs }
  async function timeHistory(name, method) {
    operationTimes[name] = await page.evaluate(async method => {
      const api = await import('/src/api/client.js'), start = performance.now()
      const index = window.__nadocTest.store.getState().currentDesign.feature_log.length - 1
      await api[method](...(['deleteFeature', 'revertToBeforeFeature'].includes(method) ? [index] : []))
      return performance.now() - start
    }, method)
    console.log(`Corner ${name} milliseconds`, operationTimes[name])
  }
  await timeHistory('undo', 'undo')
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(before)
  await timeHistory('redo', 'redo')
  await expect(page.locator('#sync-status-text')).toContainText('saved', { timeout: 60000 })
  operationTimes.open_edit = await page.evaluate(async () => {
    const start = performance.now()
    Array.from(document.querySelectorAll('#fl-list button[title^="Edit"]')).at(-1).click()
    const button = document.querySelector('#bevel-panel .def-btn.primary')
    while (button.disabled) await new Promise(resolve => setTimeout(resolve, 0))
    return performance.now() - start
  })
  console.log('Corner open edit milliseconds', operationTimes.open_edit)
  await page.locator('#bevel-positionBp').fill('145')
  operationTimes.edit = await page.evaluate(async () => {
    const button = document.querySelector('#bevel-panel .def-btn.primary'), panel = button.closest('.tool-popup')
    const start = performance.now()
    button.click()
    while (getComputedStyle(panel).display !== 'none' && panel.getClientRects().length) {
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    return performance.now() - start
  })
  console.log('Corner cold edit milliseconds', operationTimes.edit)
  await timeHistory('delete', 'deleteFeature')
  await timeHistory('undo_delete', 'undo')
  await timeHistory('revert', 'revertToBeforeFeature')
  await timeHistory('undo_revert', 'undo')
  // Verification must inspect one stable revision, not a concurrent autosave
  // acknowledgement. The normal source-bound verifier correctly rejects races.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    window.__bevelVerificationHold = api.holdFeatureEditSaves()
    await window.__bevelVerificationHold.ready
  })
  const headers = { 'X-NADOC-Doc': doc }
  const response = await page.request.post('/api/design/features/verification/jobs', { headers })
  expect(response.status()).toBe(202)
  const { job_id: job } = await response.json()
  let result
  await expect.poll(async () => {
    result = await (await page.request.get(`/api/design/features/verification/jobs/${job}`, { headers })).json()
    return result.status
  }, { timeout: 60000 }).toBe('complete')
  console.log('Corner verification result', JSON.stringify(result.result))
  expect(result.result.status).toBe('verified')
  await page.evaluate(() => window.__bevelVerificationHold.release())
  expect(readFileSync(cornerPath, 'utf8')).toBe(original)
  expect(errors).toEqual([])
  for (const [operation, milliseconds] of Object.entries(operationTimes)) {
    expect(milliseconds, `${operation} must finish in under one second`).toBeLessThan(1000)
  }
})

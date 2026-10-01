import { createHash } from 'node:crypto'
import { test, expect } from '@playwright/test'
// All meeting/package data stays in memory. Global teardown removes the Vite
// bridge key; the cleanup reporter removes runner screenshots/traces.
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 })
test('mobile login, navigation, touch drawing and smooth presenter lock', async ({ page, context }) => {
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/viewer.html?test=1')
  const bytes = await page.evaluate(async () => {
    const T = await import('/node_modules/.vite/deps/three.js'), { prepareScene } = await import('/src/viewer/prepared_scene.js')
    const scene = new T.Scene()
    scene.add(new T.Mesh(new T.CylinderGeometry(1, 1, 5), new T.MeshBasicMaterial({ color: 0x4499cc })))
    return [...new Uint8Array(prepareScene({ scene, title: 'Mobile test', camera: { position: [10, 5, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'multiscale' } }))]
  })
  const revision = createHash('sha256').update(Buffer.from(bytes)).digest('hex')
  let sequence = 0, hostLocked = false, presenterCamera = null
  const drawings = []
  await page.route('**/meeting/**', route => {
    const action = new URL(route.request().url()).pathname.split('/').pop()
    if (action === 'join') {
      const body = route.request().postDataJSON()
      return route.fulfill({ status: body.resume ? 401 : body.password === 'test-password' ? 200 : 403, json: { name: 'Phone guest', role: 'guest', participantId: 'phone', revision, error: 'Incorrect password' } })
    }
    if (action === 'events') return route.fulfill({ contentType: 'text/event-stream', body: `event: state\ndata: ${JSON.stringify({ room: 'default', revision, sequence: ++sequence, presenting: hostLocked, viewLocked: hostLocked, camera: presenterCamera, participants: [], serverTime: Date.now() })}\n\n` })
    if (action === 'drawings') drawings.push(route.request().postDataJSON())
    if (action === 'scene') return route.fulfill({ body: Buffer.from(bytes), headers: { 'Content-Length': String(bytes.length) } })
    return route.fulfill({ json: {} })
  })
  // Route fixtures end their SSE body immediately. Keep the simulated meeting
  // connected between events; online dispatch below requests the next state.
  await page.addInitScript(() => {
    const NativeEventSource = window.EventSource
    window.EventSource = class extends NativeEventSource {
      addEventListener(type, listener, options) { if (type !== 'error') super.addEventListener(type, listener, options) }
    }
  })
  await page.goto('/viewer.html?test=1&meeting=1#invite=mobile-test&password=required')
  await expect(page.locator('#join')).toBeVisible()
  await expect(page.locator('.mobile-orientation')).toBeHidden()
  await page.locator('#guest-name').fill('Phone guest')
  await page.locator('#meeting-password').fill('wrong')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join-error')).toContainText('Incorrect password')
  await page.locator('#meeting-password').fill('test-password')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join')).not.toBeVisible()
  await expect(page.locator('.mobile-orientation')).toBeVisible()
  await expect(page.locator('.mobile-orientation')).toHaveAttribute('data-orientation', 'portrait')
  await expect(page.locator('.mobile-qr-tracking')).toHaveCount(0)
  const rotate = page.locator('header button.mobile-orientation')
  await expect(rotate).toBeEnabled()
  const rotateBox = await rotate.boundingBox(), headerBox = await page.locator('header').boundingBox()
  expect(rotateBox.y + rotateBox.height).toBeLessThanOrEqual(headerBox.y + headerBox.height)
  expect(rotateBox.height).toBeGreaterThanOrEqual(44)
  expect(await rotate.evaluate(el => getComputedStyle(el).border)).toBe(await page.locator('#reset').evaluate(el => getComputedStyle(el).border))
  await page.evaluate(() => {
    window.__rotationCalls = []
    document.documentElement.requestFullscreen = async () => { window.__rotationCalls.push('fullscreen') }
    screen.orientation.lock = async value => { window.__rotationCalls.push(value) }
  })
  await rotate.tap()
  expect(await page.evaluate(() => window.__rotationCalls)).toEqual(['fullscreen', 'landscape'])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.setViewportSize({ width: 844, height: 390 })
  await expect(page.locator('.mobile-orientation')).toBeVisible()
  await expect(page.locator('.mobile-orientation')).toHaveAttribute('data-orientation', 'landscape')
  await rotate.tap()
  expect(await page.evaluate(() => window.__rotationCalls.slice(-2))).toEqual(['fullscreen', 'portrait'])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const state = () => page.evaluate(() => ({ camera: window.__preparedViewer.captureCamera(), ratio: window.__preparedViewer.runtime.renderer.getPixelRatio() }))
  const before = await state(); expect(before.ratio).toBe(1); expect(before.camera.orbitMode).toBe('orbit')
  const box = await page.locator('#canvas').boundingBox(); expect(box.height).toBeGreaterThan(240)
  const client = await context.newCDPSession(page)
  const touch = (type, points) => client.send('Input.dispatchTouchEvent', { type, touchPoints: points.map(([x, y], id) => ({ x, y, id })) })
  const x = box.x + box.width / 2, y = box.y + box.height / 2
  await touch('touchStart', [[x, y]]); await touch('touchMove', [[x + 75, y + 25]]); await touch('touchEnd', [])
  expect((await state()).camera.position).not.toEqual(before.camera.position)
  const distance = () => page.evaluate(() => window.__preparedViewer.runtime.camera.position.distanceTo(window.__preparedViewer.runtime.controls.target))
  const oldDistance = await distance()
  await touch('touchStart', [[x - 35, y], [x + 35, y]]); await touch('touchMove', [[x - 70, y], [x + 70, y]]); await touch('touchEnd', [])
  expect(await distance()).toBeLessThan(oldDistance)
  const oldTarget = (await state()).camera.target
  await touch('touchStart', [[x - 35, y], [x + 35, y]]); await touch('touchMove', [[x, y + 25], [x + 70, y + 25]]); await touch('touchEnd', [])
  expect((await state()).camera.target).not.toEqual(oldTarget)
  await page.evaluate(pose => window.__preparedViewer.applyCamera({ ...pose, orbitMode: 'multiscale', near: .1, far: 2000 }), before.camera)
  expect((await state()).camera.orbitMode).toBe('orbit')
  await page.getByRole('button', { name: 'Center', exact: true }).click()
  await touch('touchStart', [[x, y]]); await touch('touchEnd', [])
  await expect(page.getByRole('button', { name: 'Center', exact: true })).toHaveAttribute('aria-pressed', 'false')
  expect((await state()).camera.target).not.toEqual(before.camera.target)
  await page.getByRole('button', { name: 'Help', exact: true }).click()
  await expect(page.locator('#status')).toContainText('Pinch to zoom')
  await page.getByRole('button', { name: 'Help', exact: true }).click()
  const draw = page.locator('[data-draw]')
  await draw.tap()
  await expect(draw).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('#reset')).toBeDisabled()
  const held = await state(), drawingBox = await page.locator('#canvas').boundingBox()
  const dx = drawingBox.x + drawingBox.width / 2, dy = drawingBox.y + drawingBox.height / 2
  await touch('touchStart', [[dx, dy]])
  await touch('touchMove', [[dx + 50, dy + 20]])
  await expect(page.locator('[data-meeting-drawing] polyline').first()).toBeVisible()
  await touch('touchEnd', [])
  await expect.poll(() => drawings.some(value => value.points?.length >= 2)).toBe(true)
  await touch('touchStart', [[dx - 35, dy], [dx + 35, dy]])
  await touch('touchMove', [[dx - 70, dy + 20], [dx + 70, dy + 20]])
  await touch('touchEnd', [])
  expect((await state()).camera).toEqual(held.camera)
  await draw.tap()
  await expect(page.locator('#reset')).toBeEnabled()
  await touch('touchStart', [[dx, dy]]); await touch('touchMove', [[dx + 50, dy + 20]]); await touch('touchEnd', [])
  expect((await state()).camera.position).not.toEqual(held.camera.position)
  await draw.tap()
  presenterCamera = { ...held.camera, position: [20, 10, -10] }
  // Observe actual frame-by-frame motion and control reconstruction, not just UI state.
  await page.evaluate(() => {
    const viewer = window.__preparedViewer, original = viewer.runtime.switchOrbitMode
    window.__lockMotion = []; window.__lockModeSwitches = 0
    viewer.runtime.switchOrbitMode = (...args) => { window.__lockModeSwitches++; return original(...args) }
    const sample = () => window.__lockMotion.push(viewer.captureCamera().position)
    viewer.runtime.addFrameCallback(sample)
    window.__stopLockProbe = () => { viewer.runtime.removeFrameCallback(sample); viewer.runtime.switchOrbitMode = original }
  })
  hostLocked = true
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(draw).toHaveAttribute('aria-pressed', 'false')
  await expect(draw).toBeDisabled()
  await expect(page.locator('[data-follow]')).toHaveText('Perspective locked')
  await page.waitForTimeout(1100)
  const motion = await page.evaluate(() => ({ positions: window.__lockMotion, switches: window.__lockModeSwitches }))
  expect(new Set(motion.positions.map(position => JSON.stringify(position))).size).toBeGreaterThan(3)
  expect(motion.switches).toBe(0)
  expect(await page.evaluate(() => window.__preparedViewer.runtime.controls.enabled)).toBe(false)
  await page.evaluate(() => window.__stopLockProbe())
  hostLocked = false
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(draw).toBeEnabled()
  await expect(page.locator('#reset')).toBeEnabled()
  expect(await page.evaluate(() => window.__preparedViewer.runtime.controls.enabled)).toBe(true)
  expect(errors).toEqual([])
})

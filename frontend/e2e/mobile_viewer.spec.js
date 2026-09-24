import { createHash } from 'node:crypto'
import { test, expect } from '@playwright/test'
// All meeting/package data stays in memory. Global teardown removes the Vite
// bridge key; the cleanup reporter removes runner screenshots/traces.
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 })
test('mobile login, landscape layout, pinch and presenter navigation', async ({ page, context }) => {
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/viewer.html?test=1')
  const bytes = await page.evaluate(async () => {
    const T = await import('/node_modules/.vite/deps/three.js'), { prepareScene } = await import('/src/viewer/prepared_scene.js')
    const scene = new T.Scene()
    scene.add(new T.Mesh(new T.CylinderGeometry(1, 1, 5), new T.MeshBasicMaterial({ color: 0x4499cc })))
    return [...new Uint8Array(prepareScene({ scene, title: 'Mobile test', camera: { position: [10, 5, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'multiscale' } }))]
  })
  const revision = createHash('sha256').update(Buffer.from(bytes)).digest('hex')
  await page.route('**/meeting/**', route => {
    const action = new URL(route.request().url()).pathname.split('/').pop()
    if (action === 'join') {
      const body = route.request().postDataJSON()
      return route.fulfill({ status: body.resume ? 401 : body.password === 'test-password' ? 200 : 403, json: { name: 'Phone guest', role: 'guest', participantId: 'phone', revision, error: 'Incorrect password' } })
    }
    if (action === 'events') return route.fulfill({ contentType: 'text/event-stream', body: `event: state\ndata: ${JSON.stringify({ room: 'default', revision, sequence: 1, presenting: false, participants: [], serverTime: Date.now() })}\n\n` })
    if (action === 'scene') return route.fulfill({ body: Buffer.from(bytes), headers: { 'Content-Length': String(bytes.length) } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/viewer.html?test=1#invite=mobile-test&password=required')
  await expect(page.locator('#join')).toBeVisible()
  await expect(page.locator('.mobile-landscape')).toBeHidden()
  await page.locator('#guest-name').fill('Phone guest')
  await page.locator('#meeting-password').fill('wrong')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join-error')).toContainText('Incorrect password')
  await page.locator('#meeting-password').fill('test-password')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join')).not.toBeVisible()
  await expect(page.locator('.mobile-landscape')).toBeVisible()
  await page.setViewportSize({ width: 844, height: 390 })
  await expect(page.locator('.mobile-landscape')).toBeHidden()
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
  expect(errors).toEqual([])
})

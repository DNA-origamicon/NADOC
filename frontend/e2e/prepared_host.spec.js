import { test, expect } from '@playwright/test'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import * as THREE from 'three'
import { build } from 'esbuild'
import { pathToFileURL } from 'node:url'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'

// Only persistence is this mkdtemp directory, removed by afterEach even on failure.
// No editor/backend or user workspace is used.
let root, host, base, prepareScene
const errors = []
test.beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), 'nadoc-share-e2e-'))
  const bundle = join(root, 'prepared-scene.mjs')
  await build({ entryPoints: [resolve('src/viewer/prepared_scene.js')], outfile: bundle, bundle: true, platform: 'node', format: 'esm', loader: { '.css': 'empty' }, plugins: [{ name: 'shared-three', setup(build) { build.onResolve({ filter: /^three$/ }, () => ({ path: resolve('node_modules/three/build/three.module.js'), external: true })) } }] })
  ;({ prepareScene } = await import(pathToFileURL(bundle).href))
  const scene = new THREE.Scene()
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial({ color: '#36aaff' })))
  const bytes = prepareScene({ scene, title: 'Private test design', camera: { position: [20, 15, 25], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' } })
  await writeFile(join(root, 'scene.nadocview'), Buffer.from(bytes))
  host = await createPreparedHost({ dist: resolve('dist'), packagePath: join(root, 'scene.nadocview') })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  base = `http://127.0.0.1:${host.server.address().port}`
})
test.afterEach(async () => { host?.stop(); if (root) await rm(root, { recursive: true, force: true }) })
test('invite opens a production browser viewer, prompts for name, and loads without editor endpoints', async ({ page }, testInfo) => {
  page.on('pageerror', error => errors.push(error.message))
  const apiRequests = []
  page.on('request', request => { if (request.url().includes('/api/')) apiRequests.push(request.url()) })
  expect((await page.request.get(base + '/meeting/scene')).status()).toBe(401)
  const url = new URL(`${base}/viewer.html#invite=${host.invite}`)
  if (testInfo.project.name === 'chromium-lan-http') url.hostname = 'nadoc-lan.test'
  await page.goto(url.href)
  if (testInfo.project.name === 'chromium-lan-http') {
    expect(await page.evaluate(() => ({ secure: isSecureContext, uuid: typeof crypto.randomUUID, subtle: typeof crypto.subtle })))
      .toEqual({ secure: false, uuid: 'undefined', subtle: 'undefined' })
  }
  await expect(page.locator('#join')).toBeVisible()
  await expect(page.locator('#reset')).toBeDisabled()
  await page.locator('#guest-name').fill('Laptop tester')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join')).not.toBeVisible()
  await expect(page.locator('#title')).toHaveText('Private test design')
  await expect(page.locator('#guest')).toContainText('Laptop tester')
  await expect(page.locator('#status')).toContainText('Static snapshot')
  // Let the closed modal leave the top layer and the first scene frame render.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const canvas = page.locator('#canvas'), box = await canvas.boundingBox()
  const before = await canvas.screenshot({ path: testInfo.outputPath('before.png') })
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down(); await page.mouse.move(box.x + box.width * .65, box.y + box.height * .55, { steps: 8 }); await page.mouse.up()
  await page.waitForTimeout(250)
  expect(errors).toEqual([])
  expect((await canvas.screenshot({ path: testInfo.outputPath('after.png') })).equals(before)).toBe(false)
  await page.locator('#reset').click()
  await page.keyboard.press('Control+p')
  await expect(page.locator('#performance')).toBeVisible()
  await page.locator('#performance summary').click()
  await page.locator('[data-perf-seconds]').fill('1')
  await page.locator('[data-perf-start]').click()
  await expect(page.locator('#performance')).not.toBeVisible()
  await page.waitForTimeout(1300)
  await page.keyboard.press('Control+p')
  await expect(page.locator('[data-perf-status]')).toContainText('Completed')
  const metrics = await page.locator('[data-perf-output]').inputValue()
  expect(metrics).toContain('[NADOC_VIEWER_PERF v1]')
  expect(JSON.parse(metrics.slice(metrics.indexOf('{'))).valid).toBe(true)
  await page.locator('#close-metrics').click()
  expect(apiRequests).toEqual([]); expect(errors).toEqual([])
  host.stop()
  await expect(page.locator('#guest')).toContainText('Session ended', { timeout: 15000 })
  await expect(page.locator('#presentation-ended')).toBeVisible() // explicit room end clears the shared view
})

test('QR guest joins by name and tracks a synthetic camera target in the production viewer', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'Camera access requires a secure context')
  const { createGuestQR } = await import('../src/viewer/meeting_target.js')
  const scene = new THREE.Scene()
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial()))
  host.setPublicBase(base)
  const share = host.createShare(Buffer.from(prepareScene({ scene, title: 'QR tracking test', camera: { position: [20, 15, 25], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' } })))
  const invitation = share.qrUrl + '&qrmm=150'
  const svg = createGuestQR(invitation)
  // A real MediaStream from canvas exercises video playback and the bundled QR
  // decoder. No files, devices, public gateway or workspace designs are created.
  await page.addInitScript(svg => {
    navigator.mediaDevices.getUserMedia = async () => {
      const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480
      const ctx = canvas.getContext('2d'), image = new Image()
      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
      image.src = url
      try { await image.decode() } finally { URL.revokeObjectURL(url) }
      window.__qrCameraStopped = false
      window.__qrCamera = { size: 400, visible: true }
      const draw = () => {
        ctx.fillStyle = 'white'; ctx.fillRect(0, 0, 640, 480)
        const { size, visible } = window.__qrCamera
        if (visible) ctx.drawImage(image, (640 - size) / 2, (480 - size) / 2, size, size)
      }
      draw()
      const stream = canvas.captureStream(15), interval = setInterval(draw, 60)
      const track = stream.getVideoTracks()[0], stop = track.stop.bind(track)
      track.stop = () => { clearInterval(interval); stop(); window.__qrCameraStopped = true }
      return stream
    }
  }, svg)
  const failures = []; page.on('pageerror', e => failures.push(e.message))
  await page.goto(invitation)
  await expect(page.locator('#meeting-password-row')).toBeHidden()
  await page.locator('#guest-name').fill('Phone guest')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join')).not.toBeVisible()
  const panel = page.locator('.mobile-qr-tracking')
  await panel.locator('summary').click()
  await expect(panel.locator('[data-size]')).toBeVisible()
  await expect(panel.locator('[data-size]')).toHaveValue('150')
  await panel.locator('[data-start]').click()
  await expect(panel.locator('[data-state]')).toContainText('Tracking ·', { timeout: 15000 })
  const initial = JSON.parse(await panel.getAttribute('data-position'))
  expect(initial[2]).toBeGreaterThan(0)
  await page.evaluate(() => { window.__qrCamera.size = 300 })
  await expect.poll(async () => JSON.parse(await panel.getAttribute('data-position') || '[0,0,0]')[2]).toBeGreaterThan(initial[2] * 1.2)
  await page.evaluate(() => { window.__qrCamera.visible = false })
  await expect(panel.locator('[data-state]')).toContainText('Position unavailable')
  await expect(panel).not.toHaveAttribute('data-position')
  await page.evaluate(() => { window.__qrCamera.visible = true })
  await expect(panel.locator('[data-state]')).toContainText('Tracking ·')
  await panel.locator('[data-stop]').click()
  await expect.poll(() => page.evaluate(() => window.__qrCameraStopped)).toBe(true)
  await expect(panel.locator('canvas')).toBeHidden()
  await panel.locator('[data-start]').click()
  await expect(panel.locator('[data-state]')).toContainText('Tracking ·')
  host.stop()
  await expect(panel).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => window.__qrCameraStopped)).toBe(true)
  expect(failures).toEqual([])
})

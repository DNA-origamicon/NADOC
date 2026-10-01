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
  await expect(page.locator('#join-title')).toBeFocused()
  const name = page.locator('#guest-name')
  await expect(name).toHaveAttribute('autocomplete', 'off')
  await expect(page.locator('#meeting-password')).toBeDisabled()
  await page.keyboard.press('Tab')
  await expect(name).toBeFocused()
  await name.fill('Laptop tester')
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

test('QR guest joins by name without a tracking panel or camera request', async ({ page }) => {
  const scene = new THREE.Scene()
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial()))
  host.setPublicBase(base)
  const share = host.createShare(Buffer.from(prepareScene({ scene, title: 'QR guest test', camera: { position: [20, 15, 25], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' } })))
  await page.addInitScript(() => {
    window.__cameraRequests = 0
    if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => {
      window.__cameraRequests++
      throw new Error('Guest entry should not request a camera')
    }
  })
  await page.goto(share.qrUrl + '&qrmm=150')
  await expect(page.locator('#meeting-password-row')).toBeHidden()
  await page.locator('#guest-name').fill('Phone guest')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join')).not.toBeVisible()
  await expect(page.locator('#title')).toHaveText('QR guest test')
  await expect(page.locator('.mobile-qr-tracking')).toHaveCount(0)
  expect(await page.evaluate(() => window.__cameraRequests)).toBe(0)
})


test.describe('Mobile guest entry', () => {
  test.use({ viewport: { width: 393, height: 851 }, isMobile: true, hasTouch: true })
  test('opens without focusing a field, then accepts touch typing and Enter to join', async ({ page }) => {
    const failures = []
    page.on('pageerror', error => failures.push(error.message))
    await page.goto(`${base}/viewer.html#invite=${host.invite}`)
    await expect(page.locator('#join-title')).toBeFocused()
    const name = page.locator('#guest-name')
    await expect(name).toHaveValue('')
    await expect(name).toBeEditable()
    await expect(name).toHaveAttribute('inputmode', 'text')
    await expect(name).toHaveAttribute('autocorrect', 'off')
    await expect(name).toHaveAttribute('autocapitalize', 'off')
    await expect(name).toHaveAttribute('spellcheck', 'false')
    for (const attribute of ['data-1p-ignore', 'data-lpignore', 'data-bwignore', 'data-form-type']) {
      expect(await name.getAttribute(attribute)).not.toBeNull()
    }
    await name.tap()
    await expect(name).toBeFocused()
    await page.keyboard.insertText('Zoë 李')
    await page.locator('#join-title').tap()
    await name.tap()
    await expect(name).toHaveValue('Zoë 李')
    await expect(page.locator('#join-submit')).toBeEnabled()
    await page.keyboard.press('Enter')
    await expect(page.locator('#join')).not.toBeVisible()
    await expect(page.locator('#guest')).toContainText('Zoë 李')
    await expect(page.locator('#title')).toHaveText('Private test design')
    expect(failures).toEqual([])
  })
})

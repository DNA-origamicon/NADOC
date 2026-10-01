import { test, expect } from '@playwright/test'
import { access, writeFile, unlink, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persisted inventory: __e2e__drawing-share .nadoc/project history (global teardown),
// test-port host credential (afterAll). Host scenes/links are memory-only.
// PNG downloads stay in browser temp storage; afterEach closes their owning contexts on failure.
// Three review PNGs are intentionally retained in .development-artifacts/guest-drawing/.
const root = path.resolve(import.meta.dirname, '../..')
const control = shareControlFile(path.join(root, 'frontend'), Number(process.env.NADOC_E2E_FRONTEND_PORT || 5175))
let host, ownsControl = false
const guests = []
test.afterEach(async () => { for (const guest of guests.splice(0)) await guest.close() })
test.beforeAll(async () => {
  try { await access(control); throw new Error('An existing test sharing credential must not be overwritten') } catch (e) { if (e.code !== 'ENOENT') throw e }
  host = await createPreparedHost({ dist: path.join(root, 'frontend/dist') })
  await new Promise(resolve => host.server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(control, JSON.stringify({ url, token: host.controlToken }), { flag: 'wx', mode: 0o600 }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(control).catch(() => {}) })

test('guest ink follows matching perspectives, expires and clears; screenshots exclude interface overlays', async ({ page, browser }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__drawing-share', name: 'drawing-share' })
  // The picking harness deliberately zooms to individual beads. Frame the whole
  // actual structure for this presentation test so orbiting cannot hide it.
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const api = window.__nadocTest, bounds = new THREE.Box3()
    api.scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count) bounds.union(new THREE.Box3().setFromObject(o)) })
    const center = bounds.getCenter(new THREE.Vector3()), radius = bounds.getSize(new THREE.Vector3()).length() / 2
    api.applyCameraPoseForTest({ position: center.clone().add(new THREE.Vector3(2 * radius, radius, 2 * radius)).toArray(), target: center.toArray(), up: [0, 1, 0], fov: 55 })
  })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.renderedPixelCensus().visible)).toBeGreaterThan(100)
  await page.locator('#menu-file-sharing').evaluate(el => el.click())
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({ timeout: 45000 })
  const url = await page.locator('#share-link-dialog [data-link]').inputValue()
  await page.locator('#share-link-dialog [data-close]').click()
  async function join(name, width) {
    const guest = await browser.newPage({ viewport: { width, height: 800 } }); guests.push(guest)
    await guest.goto(url); await guest.locator('#guest-name').fill(name); await guest.locator('#join-submit').click()
    await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 30000 })
    return guest
  }
  const a = await join('Drawer', 1100), b = await join('Follower', 900), c = await join('Independent', 1000)
  const guestErrors = [a, b, c].map(trackConsoleErrors)
  const evidence = path.join(root, '.development-artifacts/guest-drawing')
  await mkdir(evidence, { recursive: true })
  const marks = tab => tab.locator('[data-meeting-drawing] polyline')
  async function orbit(tab) {
    const r = await tab.locator('#canvas').boundingBox()
    await tab.mouse.move(r.x + r.width * .4, r.y + r.height * .5); await tab.mouse.down()
    await tab.mouse.move(r.x + r.width * .65, r.y + r.height * .6, { steps: 10 }); await tab.mouse.up()
  }
  await orbit(a)
  await a.locator('[data-share-view]').click()
  await b.getByRole('button', { name: "View Drawer's shared perspective" }).click()
  await page.getByRole('button', { name: "View Drawer's shared perspective" }).click()
  await b.waitForTimeout(1200) // Shared-view camera motion is 900 ms.
  await a.locator('[data-draw]').click()
  async function draw() {
    const r = await a.locator('#canvas').boundingBox()
    await a.mouse.move(r.x + r.width * .5, r.y + r.height * .4)
    await a.keyboard.down('Shift'); await a.mouse.down()
    await a.mouse.move(r.x + r.width * .6, r.y + r.height * .5, { steps: 12 }); await a.mouse.up(); await a.keyboard.up('Shift')
  }
  await a.bringToFront()
  const bounds = await a.locator('#canvas').boundingBox()
  const clip = { x: bounds.x + bounds.width * .45, y: bounds.y + bounds.height * .3, width: bounds.width * .25, height: bounds.height * .3 }
  const beforeInk = await a.screenshot({ clip })
  await draw()
  await a.screenshot({ path: path.join(evidence, 'drawing-visible.png') })
  const inkPixels = await a.screenshot({ clip })
  await expect(marks(a).first()).toBeVisible()
  await expect(marks(b).first()).toBeVisible()
  await expect(marks(page).first()).toBeVisible()
  expect(await marks(c).count()).toBe(0)
  expect(inkPixels.equals(beforeInk)).toBe(false)
  await expect(marks(a)).toHaveCount(0, { timeout: 4000 })
  await expect(marks(b)).toHaveCount(0)
  await expect(marks(page)).toHaveCount(0)
  expect((await a.screenshot({ clip })).equals(beforeInk)).toBe(true)
  await draw(); await expect(marks(b).first()).toBeVisible()
  await orbit(a)
  await expect(marks(a)).toHaveCount(0, { timeout: 1000 })
  await expect(marks(b)).toHaveCount(0, { timeout: 1500 })
  // The lock does not disable drawing or let Shift-drag change perspective.
  await page.locator('.presentation-view-lock').click()
  await expect(a.locator('[data-follow]')).toBeDisabled()
  await draw(); await expect(marks(b).first()).toBeVisible()
  await expect(a.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
  async function screenshot() {
    const pending = a.waitForEvent('download'); await a.locator('[data-screenshot]').click()
    const download = await pending; expect(download.suggestedFilename()).toBe('NADOC-view.png')
    const stream = await download.createReadStream(), chunks = []
    for await (const chunk of stream) chunks.push(chunk)
    await download.delete() // Browser temporary download is removed even on success.
    return Buffer.concat(chunks)
  }
  const first = await screenshot()
  await writeFile(path.join(evidence, 'download.png'), first)
  await a.screenshot({ path: path.join(evidence, 'guest-screen.png') })
  const dimensions = await a.locator('#canvas').evaluate(el => [el.width, el.height])
  expect([first.readUInt32BE(16), first.readUInt32BE(20)]).toEqual(dimensions)
  const colors = await a.evaluate(async data => {
    const img = await createImageBitmap(new Blob([Uint8Array.from(atob(data), c => c.charCodeAt(0))], { type: 'image/png' }))
    const canvas = document.createElement('canvas'); canvas.width = img.width; canvas.height = img.height
    const ctx = canvas.getContext('2d'); ctx.drawImage(img, 0, 0); img.close()
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data, colors = new Set()
    for (let i = 0; i < pixels.length; i += 4) colors.add(`${pixels[i]},${pixels[i + 1]},${pixels[i + 2]}`)
    return colors.size
  }, first.toString('base64'))
  expect(colors).toBeGreaterThan(20)
  await a.evaluate(() => { const ui = document.createElement('div'); ui.style.cssText = 'position:absolute;inset:0;background:magenta;z-index:100;pointer-events:none'; ui.textContent = 'UI MUST NOT APPEAR'; document.querySelector('main').append(ui) })
  expect((await screenshot()).equals(first)).toBe(true)
  expect(errors).toEqual([])
  for (const list of guestErrors) expect(list).toEqual([])
})

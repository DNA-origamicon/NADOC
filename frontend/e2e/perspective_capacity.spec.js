import { test, expect } from '@playwright/test'
import { access, writeFile, unlink } from 'node:fs/promises'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persisted inventory: __e2e__perspective-capacity .nadoc/project history (global teardown),
// test-port host credential/status sidecar (afterAll). Host scenes/links are memory-only.
// afterEach closes all guest contexts, including on failure.
// No downloads or review images are created by this test.
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
test.afterAll(async () => {
  host?.stop()
  if (ownsControl) for (const file of [control, control + '.status.json']) await unlink(file).catch(() => {})
})

test('four guests can join before the presenter shares, stops, locks and unlocks perspective', async ({ page, browser }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__perspective-capacity', name: 'perspective-capacity' })
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
  const detail = page.locator('#menu-view-surface-detail')
  const surfaceRequests = []
  await page.route('**/api/design/surface-bin?**', route => { surfaceRequests.push(route) })
  await expect(detail).toBeEnabled()
  // Delay transport rather than spending CPU on a real detailed surface.
  for (const action of ['cancel', 'switch']) {
    const before = surfaceRequests.length
    await detail.evaluate(el => el.click())
    await expect.poll(() => surfaceRequests.length).toBe(before + 1)
    await expect(page.locator('#op-progress-cancel')).toBeVisible()
    const cancelled = page.waitForRequest(r => r.method() === 'POST' && /surface-progress\/.+\/cancel$/.test(r.url()))
    if (action === 'cancel') await page.locator('#op-progress-cancel').click()
    else await page.keyboard.press('F4')
    await cancelled
    await expect(page.locator('#op-progress')).not.toHaveClass(/visible/)
    await expect(page.locator('#menu-view-detail-full')).toHaveClass(/is-checked/)
    await surfaceRequests.at(-1).abort().catch(() => {})
  }
  await page.unroute('**/api/design/surface-bin?**')
  await page.locator('#menu-file-sharing').evaluate(el => el.click())
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({ timeout: 45000 })
  const url = await page.locator('#share-link-dialog [data-link]').inputValue()
  await expect(detail).toBeDisabled()
  await expect(page.locator('.right-repr-btn[data-target="menu-view-surface-detail"]')).toBeDisabled()
  await expect(page.locator('#menu-view-surface')).toBeEnabled()
  await page.locator('#share-link-dialog [data-close]').click()
  async function join(name, width) {
    const guest = await browser.newPage({ viewport: { width, height: 800 } }); guests.push(guest)
    await guest.goto(url); await guest.locator('#guest-name').fill(name); await guest.locator('#join-submit').click()
    await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 30000 })
    return guest
  }
  const a = await join('Drawer', 1100), b = await join('Follower', 900), c = await join('Independent', 1000), d = await join('Fourth guest', 950)
  const guestErrors = [a, b, c, d].map(trackConsoleErrors)
  // A full guest room must allow sharing, stopping, and locking from stopped.
  const perspective = page.locator('.presentation-perspective'), lock = page.locator('.presentation-view-lock')
  await perspective.click()
  await expect(perspective).toHaveAttribute('aria-pressed', 'true')
  await perspective.click()
  await expect(perspective).toHaveAttribute('aria-pressed', 'false')
  await lock.click()
  await expect(lock).toHaveAttribute('aria-pressed', 'true')
  for (const guest of [a, b, c, d]) await expect(guest.locator('[data-follow]')).toBeDisabled()
  await lock.click()
  await expect(lock).toHaveAttribute('aria-pressed', 'false')
  for (const guest of [a, b, c, d]) await expect(guest.locator('[data-follow]')).toBeEnabled()
  await perspective.click()
  await expect(perspective).toHaveAttribute('aria-pressed', 'false')
  await expect(page.locator('.presentation-error')).toHaveText('')
  await page.locator('[data-end-presentation]').click()
  await expect(detail).toBeEnabled()
  expect(errors).toEqual([])
  for (const list of guestErrors) expect(list).toEqual([])
})

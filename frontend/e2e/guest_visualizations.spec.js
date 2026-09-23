import { test, expect } from '@playwright/test'
import { access, writeFile, unlink, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
import { decodeContainer } from '../src/viewer/package_container.js'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persisted: __e2e__ model/history (global teardown), :5174 credential (afterAll),
// documented screenshots below. All simulation HTTP responses are fixtures.
const root = path.resolve(import.meta.dirname, '..'), control = shareControlFile(root, 5174)
const evidence = path.resolve(root, '../docs/audits/guest_visualizations_20260923')
let host, ownsControl = false
test.beforeAll(async () => {
  try { await access(control); throw new Error('Test sharing credential already exists') } catch (error) { if (error.code !== 'ENOENT') throw error }
  host = await createPreparedHost({ dist: path.join(root, 'dist') })
  await new Promise(resolve => host.server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(control, JSON.stringify({ url, token: host.controlToken }), { flag: 'wx', mode: 0o600 }); ownsControl = true
  await mkdir(evidence, { recursive: true })
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(control).catch(() => {}) })

function ionPacket() {
  const coords = [], paths = [], tracks = []
  for (let i = 0; i < 6; i++) {
    const offset = coords.length
    for (let j = 0; j < 13; j++) coords.push(i - 2.5 + Math.sin(j / 3), Math.cos(j / 3 + i), j * 2 - 12)
    tracks.push({ offset, count: 13 }); paths.push({ track: i, species: i < 3 ? 'NA' : 'CL', ion_serial: i + 1, crossing_frame: 6, start_frame: 0, point_start: 0, point_count: 13, offset: [0, 0, 0] })
  }
  const metadata = Buffer.from(JSON.stringify({ paths, tracks, pore: { radius_nm: 4, normal: [0, 0, 1] }, crossings: 6, frames: 13 }))
  const start = 12 + Math.ceil(metadata.length / 4) * 4, result = Buffer.alloc(start + coords.length * 4)
  result.writeUInt32LE(0x4e495054, 0); result.writeUInt32LE(1, 4); result.writeUInt32LE(metadata.length, 8); metadata.copy(result, 12)
  coords.forEach((value, i) => result.writeFloatLE(value, start + i * 4)); return result
}
test('guest sees measured loading, nanopore paths and vector fields, then a terminal presentation-ended screen', async ({ page, context }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page), job = { job_id: '__e2e__guest_ions', engine: 'namd', status: 'completed', kind: 'relax', created_at: 1, prep_params: { graphene_nanopore: true }, segments: [] }
  let release; const ready = new Promise(resolve => { release = resolve })
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [job] }))
  await page.route('**/api/md/jobs', route => route.fulfill({ json: [job] }))
  await page.route('**/api/md/jobs/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === `/api/md/jobs/${job.job_id}`) return route.fulfill({ json: job })
    if (pathname.endsWith('/ion-paths-progress')) return route.fulfill({ json: { stages: [{ stage: 'coordinates', done: 1, total: 2 }] } })
    if (pathname.endsWith('/ion-paths')) { await ready; return route.fulfill({ body: ionPacket(), contentType: 'application/octet-stream' }) }
    return route.fulfill({ json: {} })
  })
  await loadScaffoldedPart(page, { doc: '__e2e__guest_visualizations', name: 'guest_visualizations' })
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [28, 20, 48], target: [0, 0, 10], up: [0, 1, 0], fov: 55 }))
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.locator('#simulate-jobs-list [data-job-id="__e2e__guest_ions"]').click()
  await page.locator('#menu-help-share-link').evaluate(button => button.click())
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled(); await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-status]')).toContainText('Invitation ready', { timeout: 30000 })
  const url = await page.locator('.sharing-url').inputValue(); await page.locator('#share-link-dialog [data-close]').click()
  const guest = await context.newPage(), packets = []
  guest.on('response', async response => { if (response.url().includes('/scene?revision=') && response.ok()) { const bytes = await response.body().catch(() => null); if (bytes) packets.push(decodeContainer(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength))) } })
  await guest.goto(url); await expect(guest.locator('#join-submit')).toBeEnabled()
  // The initial resume probe intentionally returns 401 for a first-time guest.
  const guestErrors = trackConsoleErrors(guest)
  await guest.locator('#guest-name').fill('Ion viewer'); await guest.locator('#join-submit').click()
  await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 30000 })
  await page.locator('[data-share-job="namd"]').click(); await expect(page.locator('[data-share-job="namd"]')).toHaveText('Stop sharing')
  await expect(page.locator('#md-ion-paths-toggle')).toBeEnabled()
  await page.locator('#md-ion-paths-toggle').check()
  await expect(guest.locator('#meeting-loading')).toBeVisible()
  await expect.poll(() => guest.locator('#meeting-loading progress').evaluate(bar => bar.value)).toBe(.07)
  await guest.screenshot({ path: path.join(evidence, 'loading.png') }); release()
  await expect(page.locator('#md-ion-paths-progress')).toHaveJSProperty('value', 100, { timeout: 30000 })
  await expect.poll(() => packets.at(-1)?.materials.some(m => m.wideLine), { timeout: 30000 }).toBe(true)
  await expect(guest.locator('#meeting-loading')).toBeHidden()
  const paths = await guest.locator('canvas').screenshot({ path: path.join(evidence, 'ion-paths.png') })
  await page.locator('#md-ion-paths-width').fill('6'); await page.locator('#md-ion-paths-width').dispatchEvent('input')
  await expect.poll(() => packets.at(-1)?.materials.find(m => m.wideLine)?.linewidth).toBe(6)
  await page.locator('#md-ion-vector-field-toggle').check()
  const names = node => [node.name, ...node.children.flatMap(names)]
  await expect.poll(() => packets.at(-1) && names(packets.at(-1).root).some(n => n.startsWith('ionVectorHeads-')), { timeout: 30000 }).toBe(true)
  await expect.poll(async () => paths.equals(await guest.locator('canvas').screenshot())).toBe(false)
  await guest.locator('canvas').screenshot({ path: path.join(evidence, 'vector-field.png') })
  await page.locator('[data-end-presentation]').click()
  await expect(guest.locator('#presentation-ended')).toBeVisible({ timeout: 10000 })
  await expect(guest.locator('#status')).toHaveText('Presentation ended')
  await expect(guest.locator('#reset')).toBeDisabled(); await expect(guest.locator('[data-presentation]')).toHaveCount(0)
  await guest.screenshot({ path: path.join(evidence, 'ended.png') })
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
})

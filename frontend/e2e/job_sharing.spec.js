import { test, expect } from '@playwright/test'
import { access, writeFile, unlink, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

// Only persisted artifacts: __e2e__ model/history (global teardown), :5174 share
// credential (afterAll). Jobs are HTTP fixtures; no simulation is created/run.
const root = path.resolve(import.meta.dirname, '..'), controlFile = shareControlFile(root, 5174)
const evidence = path.resolve(root, '../docs/audits/job_sharing_20260923')
let host, ownsControl = false
test.beforeAll(async () => {
  try { await access(controlFile); throw new Error('Test sharing credential already exists') } catch (error) { if (error.code !== 'ENOENT') throw error }
  host = await createPreparedHost({ dist: path.join(root, 'dist') })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }), { mode: 0o600, flag: 'wx' }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(controlFile).catch(() => {}) })
test.afterEach(async ({ page }) => { console.log('Job sharing status:', await page.locator('.sharing-job-status').textContent().catch(() => 'page closed')) })

test('one guest link follows explicit job sharing, freezes private selection, and returns to native', async ({ page, context }) => {
  test.setTimeout(180000)
  const jobs = ['a', 'b'].map((id, i) => ({ engine: i === 0 ? 'oxdna' : 'namd', job_id: `__e2e__share_${id}`, status: 'completed', kind: 'relax', parent_job_id: null, created_at: 100 + i, production_state: 'none', run_config: {} }))
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: jobs }))
  await page.route('**/api/oxdna/jobs', route => route.fulfill({ json: [jobs[0]] }))
  await page.route('**/api/md/jobs', route => route.fulfill({ json: [jobs[1]] }))
  await page.route('**/api/md/jobs/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/oxdna/jobs/**', route => route.fulfill({ json: {} }))
  const errors = [], actions = {}; page.on('pageerror', e => errors.push(e.message))
  page.on('response', async response => {
    if (response.url().includes('/broadcast/')) { const action = response.url().split('/').pop(); actions[action] = (actions[action] ?? 0) + 1 }
    if (response.url().includes('/broadcast/') && !response.ok()) console.log('Sharing transfer error:', response.status(), await response.text())
  })
  await loadScaffoldedPart(page, { doc: '__e2e__job_sharing', name: 'job_sharing' })
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [45, 25, 105], target: [0, 0, 34], up: [0, 1, 0], fov: 55 }))
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  const row = id => page.locator(`#simulate-jobs-list [data-job-id="__e2e__share_${id}"]`)
  await row('a').click()
  let button = page.locator('[data-share-job="oxdna"]')
  await expect(button).toBeHidden()
  await expect(page.locator('#presentation-controls')).toBeHidden()
  await page.locator('#menu-file-sharing').evaluate(el => el.click())
  await expect(page.locator('[data-create]')).toBeEnabled()
  await page.locator('[data-create]').click()
  await expect(page.locator('#share-link-dialog [data-copy-link]')).toBeVisible({ timeout: 30000 })
  await page.evaluate(() => { navigator.clipboard.writeText = async value => { window.__copiedShare = value } })
  await page.locator('[data-copy-link]').click()
  const url = await page.evaluate(() => window.__copiedShare)
  await expect(page.getByRole('link', { name: 'Open presenter', exact: true })).toHaveCount(0)
  await page.locator('#share-link-dialog [data-close]').click()
  const bar = page.locator('#canvas-area #presentation-controls'), glasses = bar.locator('.presentation-perspective')
  await expect(bar).toBeVisible(); await expect(bar).toContainText('Presenting')
  const area = await page.locator('#canvas-area').boundingBox(), bounds = await bar.boundingBox()
  expect(Math.abs(bounds.x + bounds.width / 2 - area.x - area.width / 2)).toBeLessThan(2)
  expect(bounds.y - area.y).toBeGreaterThanOrEqual(8); expect(bounds.y - area.y).toBeLessThan(20)
  await bar.screenshot({ path: path.join(evidence, 'presenting-controls.png') })
  const guest = await context.newPage(); guest.on('pageerror', e => errors.push(e.message))
  let joins = 0, frames = 0
  guest.on('request', r => { if (r.url().endsWith('/join')) joins++ })
  guest.on('response', r => { if (r.url().includes('/live-frame?') && r.ok()) frames++ })
  await guest.goto(url); await expect(guest.locator('#join-submit')).toBeEnabled()
  await guest.locator('#guest-name').fill('Presentation guest'); await guest.locator('#join-submit').click()
  await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 30000 })
  const pageCount = context.pages().length
  await expect(guest.locator('[data-follow]')).toBeDisabled()
  await glasses.click(); await expect(glasses).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('[data-follow]')).toBeEnabled()
  await guest.locator('[data-follow]').click(); await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('[data-follow]')).toHaveCSS('background-color', 'rgb(35, 134, 54)')
  await glasses.click(); await expect(glasses).toHaveAttribute('aria-pressed', 'false')
  await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('[data-follow]')).toBeEnabled()
  expect(context.pages()).toHaveLength(pageCount)
  const before = joins, cookies = (await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))
  await expect(button).toHaveCSS('background-color', 'rgb(35, 134, 54)')
  await button.click(); await expect(button).toHaveText('Stop sharing', { timeout: 30000 })
  await expect(button).toHaveCSS('background-color', 'rgb(182, 35, 36)')
  await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('[data-follow]')).toBeEnabled()
  await glasses.click(); await expect(glasses).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('[data-follow]')).toBeEnabled()
  await expect(row('a').locator('[data-job-sharing-dot]')).toHaveAttribute('title', 'currently sharing this job for presentation')
  await expect.poll(() => frames).toBeGreaterThan(0).catch(async error => {
    console.log('Stream diagnostic', actions, await guest.evaluate(async () => {
      const room = new URLSearchParams(location.hash.slice(1)).get('room')
      return (await (await fetch(`/meeting/${room}/status`)).json()).presentation
    }), errors)
    throw error
  })
  const move = async x => page.evaluate(x => {
    const mesh = window.__nadocTest.scene.getObjectByName('backboneSpheres')
    if (!mesh) throw new Error('Missing real design mesh')
    mesh.position.x = x
  }, x)
  const first = await guest.locator('canvas').screenshot(), received = frames
  await move(20); await expect.poll(() => frames).toBeGreaterThan(received)
  await expect.poll(async () => first.equals(await guest.locator('canvas').screenshot())).toBe(false)
  await mkdir(evidence, { recursive: true })
  await writeFile(path.join(evidence, 'guest-before.png'), first)
  await guest.locator('canvas').screenshot({ path: path.join(evidence, 'guest-stream.png') })
  await page.locator('#oxdna-jobs-viz-toggle').screenshot({ path: path.join(evidence, 'sharing-control.png') })
  await page.locator('#simulate-jobs-show-all-types').check()
  await row('b').click(); button = page.locator('[data-share-job="namd"]'); await expect(button).toHaveText('Share')
  await expect(page.locator('.sharing-job-status')).toContainText('private')
  await expect(row('a').locator('[data-job-sharing-dot]')).toHaveCount(1)
  await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('[data-follow]')).toBeEnabled()
  await expect(bar).toBeVisible()
  const paused = frames; await move(40); await page.waitForTimeout(600)
  expect(frames).toBe(paused)
  await button.click(); await expect(button).toHaveText('Stop sharing', { timeout: 30000 })
  await expect(row('a').locator('[data-job-sharing-dot]')).toHaveCount(0)
  await expect(row('b').locator('[data-job-sharing-dot]')).toHaveCount(1)
  await move(0)
  await button.click(); await expect(button).toHaveText('Share', { timeout: 30000 })
  await expect(page.locator('.sharing-job-status')).toContainText('native NADOC model')
  await expect(page.locator('[data-job-sharing-dot]')).toHaveCount(0)
  expect(guest.url()).toBe(url); expect(joins).toBe(before)
  expect((await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))).toEqual(cookies)
  await expect(bar).toBeVisible()
  await expect(guest.locator('[data-follow]')).toBeEnabled()
  await page.locator('#canvas-area').screenshot({ path: path.join(evidence, 'presenting-in-editor.png') })
  await bar.locator('[data-end-presentation]').click()
  await expect(bar).toBeHidden()
  await expect(button).toBeHidden()
  await expect.poll(async () => (await (await page.request.get('/__nadoc_share/status', { headers: { 'X-NADOC-Share': '1' } })).json()).shares?.length ?? 0).toBe(0)
  expect(errors).toEqual([])
  await guest.close()
})

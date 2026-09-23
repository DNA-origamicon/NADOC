import { test, expect } from '@playwright/test'
import { decodeContainer } from '../src/viewer/package_container.js'
import { writeFile, unlink, access } from 'node:fs/promises'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persisted artifacts: isolated :5174 control file (afterAll), __e2e__ parts and
// project histories (global teardown). No native host/elevation or user servers.
const root = path.resolve(import.meta.dirname, '..'), controlFile = shareControlFile(root, 5174)
let host, ownsControl = false
test.beforeAll(async () => {
  try { await access(controlFile); throw new Error('Isolated control file already exists; refusing to overwrite it') } catch (error) { if (error.code !== 'ENOENT') throw error }
  host = await createPreparedHost({ dist: path.join(root, 'dist') })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }), { mode: 0o600, flag: 'wx' }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(controlFile).catch(() => {}) })
test('Help updates one invitation across parts and retains guest sessions', async ({ page, context }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:5174' })
  async function sharePart(name) {
    await loadScaffoldedPart(page, { doc: `__e2e__share_${name}`, name: `share_${name}` })
    // Hover the actual Help menu, then use the visible entry.
    await page.locator('.menu-item').filter({ has: page.locator('#menu-help-share-link') }).hover()
    await page.locator('#menu-help-share-link').click()
    await expect(page.locator('#share-link-dialog')).toBeVisible()
    await expect(page.locator('#share-link-dialog [data-target]')).toBeEnabled()
    await page.locator('#share-link-dialog [data-create]').click()
    await expect(page.locator('#share-link-dialog [data-status]')).toHaveText(/Invitation ready|Shared view updated/, { timeout: 30000 })
    const section = page.locator('#share-link-dialog section').first()
    await expect(section.locator('strong')).toHaveText(`__e2e__share_${name}`)
    await section.getByRole('button', { name: 'Copy link', exact: true }).click()
    const url = await page.evaluate(() => navigator.clipboard.readText())
    expect(url).toBe(await section.locator('input').inputValue())
    const presenter = section.getByRole('link', { name: 'Open presenter', exact: true })
    await expect(presenter).toHaveCount(0)
    await expect(page.locator('#presentation-controls')).toBeVisible()
    return url
  }
  const first = await sharePart('alpha')
  await page.locator('#share-link-dialog [data-close]').click()
  const second = await sharePart('beta')
  expect(second).toBe(first)
  const guest = await context.newPage(), guestErrors = []
  guest.on('pageerror', error => guestErrors.push(error.message))
  async function openLink(url, name) {
    const resumed = guest.waitForResponse(response => response.url().endsWith('/join') && response.request().method() === 'POST')
    await guest.goto(url)
    await resumed
    await expect(guest.locator('#join-submit')).toBeEnabled()
    if (await guest.locator('#join').isVisible()) {
      await guest.locator('#guest-name').fill('Laptop tester')
      await guest.locator('#join-submit').click()
    }
    await expect(guest.locator('#title')).toHaveText(`__e2e__share_${name}`)
    await expect(guest.locator('#status')).toContainText('Static snapshot')
  }
  await openLink(second, 'beta')
  // Native snapshot updates and inline camera sharing use the same invitation, with no guest rejoin.
  const updates = [], updateErrors = [], downloads = []
  guest.on('response', response => {
    if (!response.url().includes('/scene?revision=') || !response.ok()) return
    downloads.push(response.body().then(bytes => updates.push(decodeContainer(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)))).catch(error => updateErrors.push(error.message)))
  })
  const cookieBefore = (await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))
  let joins = 0; guest.on('request', request => { if (request.url().endsWith('/join')) joins++ })
  await page.locator('#share-link-dialog [data-close]').click()
  const glasses = page.locator('#presentation-controls .presentation-perspective')
  await glasses.click(); await expect(glasses).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('[data-follow]')).toBeEnabled({ timeout: 15000 })
  async function updateView() {
    await page.locator('#menu-help-share-link').evaluate(button => button.click())
    await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
    await page.locator('#share-link-dialog [data-create]').click()
    await expect(page.locator('#share-link-dialog [data-status]')).toContainText('Shared view updated', { timeout: 30000 })
    await page.locator('#share-link-dialog [data-close]').click()
  }
  await page.evaluate(() => window.__nadocTest.store.setState({ coloringMode: 'base' }))
  await updateView()
  await expect.poll(() => updates.at(-1)?.view?.coloring, { timeout: 20000 }).toBe('base')
  await page.locator('#section-view-btn').evaluate(button => button.click())
  await updateView()
  await expect.poll(() => updates.at(-1)?.materials.some(m => m.sectionCap && m.sectionPlanes), { timeout: 20000 }).toBe(true)
  await expect(guest.locator('#status')).toContainText('Static snapshot')
  await page.evaluate(() => window.__nadocTest.configureMultiView({ count: 2, representations: ['beads', 'full'], colorings: ['strand', 'base'] }))
  await page.locator('.mv-viewport-panel[data-panel="2"]').click({ position: { x: 40, y: 70 } })
  await updateView()
  await expect.poll(() => updates.at(-1)?.view?.representation, { timeout: 25000 }).toBe('full')
  expect(updates.at(-1).view.coloring).toBe('base')
  expect(guest.url()).toBe(second); expect(joins).toBe(0)
  expect((await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))).toEqual(cookieBefore)
  await glasses.click(); await expect(glasses).toHaveAttribute('aria-pressed', 'false')
  const paused = updates.length
  await page.evaluate(() => window.__nadocTest.store.setState({ coloringMode: 'strand' }))
  await page.waitForTimeout(3500); expect(updates.length).toBe(paused)
  await Promise.all(downloads); expect(updateErrors).toEqual([])
  await page.locator('.menu-item').filter({ has: page.locator('#menu-help-share-link') }).hover()
  await page.locator('#menu-help-share-link').click()
  const betaRow = page.locator('#share-link-dialog section').filter({ hasText: '__e2e__share_beta' })
  await betaRow.getByRole('button', { name: 'End invitation', exact: true }).click()
  await expect(betaRow).toHaveCount(0)
  await guest.goto(second); await guest.reload()
  await expect(guest.locator('#join-error')).toContainText('This share has ended')
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
  await page.locator('#share-link-dialog [data-stop-host]').click()
  await expect(page.locator('#share-link-dialog [data-status]')).toHaveText('Hosting stopped. All links have ended.')
  await guest.close()
})

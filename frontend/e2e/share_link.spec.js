import { test, expect } from '@playwright/test'
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
  host = await createPreparedHost({ dist: path.join(root, 'dist'), persistent: true })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }), { mode: 0o600, flag: 'wx' }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(controlFile).catch(() => {}) })
test('File Sharing creates, copies, restores and stops one invitation', async ({ page, context }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:5174' })
  async function sharePart(name) {
    await loadScaffoldedPart(page, { doc: `__e2e__share_${name}`, name: `share_${name}` })
    // Hover the actual File menu, then use the visible entry.
    await expect(page.locator('#menu-workspace-hub + #menu-file-sharing')).toHaveText('Sharing…')
    await page.locator('.menu-item').filter({ has: page.locator('#menu-file-sharing') }).hover()
    await page.locator('#menu-file-sharing').click()
    await expect(page.locator('#share-link-dialog')).toBeVisible()
    await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
    await expect(page.locator('#share-link-dialog [data-stop-host]')).toBeDisabled()
    await page.locator('#share-link-dialog [data-create]').click()
    await expect(page.locator('#share-link-dialog [data-copy-link]')).toBeVisible({ timeout: 30000 })
    await expect(page.locator('#share-link-dialog [data-create]')).toBeDisabled()
    await page.locator('#share-link-dialog [data-copy-link]').click()
    const url = await page.evaluate(() => navigator.clipboard.readText())
    await expect(page.locator('#presentation-controls')).toBeVisible()
    return url
  }
  const first = await sharePart('alpha')
  await page.locator('#share-link-dialog [data-close]').click()
  await page.locator('#menu-file-sharing').evaluate(button => button.click())
  await expect(page.locator('[data-copy-link]')).toBeVisible()
  await expect(page.locator('[data-create]')).toBeDisabled()
  await page.locator('[data-copy-link]').click()
  const second = await page.evaluate(() => navigator.clipboard.readText())
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
  await openLink(second, 'alpha')
  await page.locator('#share-link-dialog [data-stop-host]').click()
  await expect(page.locator('#share-link-dialog [data-copy-link]')).toHaveCount(0)
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
  await expect(page.locator('#share-link-dialog [data-stop-host]')).toBeDisabled()
  await expect(guest.locator('#guest')).toContainText('Session ended')
  const idle = await (await page.request.get('/__nadoc_share/status')).json()
  expect(idle.running).toBe(true); expect(idle.shares).toEqual([])
  const warmed = performance.now()
  await page.getByRole('button', { name: 'Enable link', exact: true }).click()
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible()
  console.log(`Warm editor enable (small scaffolded part): ${Math.round(performance.now() - warmed)} ms`)
  const next = await page.locator('#share-link-dialog [data-link]').inputValue()
  await openLink(next, 'alpha')
  await page.locator('#share-link-dialog [data-close]').click()
  await page.locator('.menu-item').filter({ has: page.locator('#menu-file-close-session') }).hover()
  await page.locator('#menu-file-close-session').click()
  await expect(guest.locator('#presentation-ended')).toBeVisible()
  await expect.poll(async () => (await (await page.request.get('/__nadoc_share/status')).json()).shares.length).toBe(0)
  expect((await (await page.request.get('/__nadoc_share/status')).json()).running).toBe(true)
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
  await guest.close()
})

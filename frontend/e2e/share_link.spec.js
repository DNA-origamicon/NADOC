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
  host = await createPreparedHost({ dist: path.join(root, 'dist') })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }), { mode: 0o600 }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(controlFile).catch(() => {}) })
test('Help creates and copies part-specific links that open independently and revoke independently', async ({ page, context }) => {
  test.setTimeout(120000)
  const errors = trackConsoleErrors(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:5174' })
  async function sharePart(name) {
    await loadScaffoldedPart(page, { doc: `__e2e__share_${name}`, name: `share_${name}` })
    // Hover the actual Help menu, then use the visible entry.
    await page.locator('.menu-item').filter({ has: page.locator('#menu-help-share-link') }).hover()
    await page.locator('#menu-help-share-link').click()
    await expect(page.locator('#share-link-dialog')).toBeVisible()
    await page.locator('[data-create]').click()
    await expect(page.locator('[data-status]')).toHaveText('Invitation ready. Send it to your guests.', { timeout: 30000 })
    const section = page.locator('#share-link-dialog section').first()
    await expect(section.locator('strong')).toHaveText(`__e2e__share_${name}`)
    await section.getByRole('button', { name: 'Copy link', exact: true }).click()
    const url = await page.evaluate(() => navigator.clipboard.readText())
    expect(url).toBe(await section.locator('input').inputValue())
    return url
  }
  const first = await sharePart('alpha')
  await page.locator('[data-close]').click()
  const second = await sharePart('beta')
  expect(second).not.toBe(first)
  const guest = await context.newPage(), guestErrors = []
  guest.on('pageerror', error => guestErrors.push(error.message))
  async function openLink(url, name) {
    await guest.goto(url)
    await guest.locator('#guest-name').fill('Laptop tester')
    await guest.locator('#join-submit').click()
    await expect(guest.locator('#title')).toHaveText(`__e2e__share_${name}`)
    await expect(guest.locator('#status')).toContainText('Static snapshot')
  }
  await openLink(first, 'alpha'); await openLink(second, 'beta'); await openLink(first, 'alpha')
  const betaRow = page.locator('#share-link-dialog section').filter({ hasText: '__e2e__share_beta' })
  await betaRow.getByRole('button', { name: 'Stop sharing', exact: true }).click()
  await expect(betaRow).toHaveCount(0)
  await guest.goto(second); await guest.locator('#guest-name').fill('Laptop tester'); await guest.locator('#join-submit').click()
  await expect(guest.locator('#join-error')).toContainText('This share has ended')
  await openLink(first, 'alpha')
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
  await page.locator('[data-stop-host]').click()
  await expect(page.locator('[data-status]')).toHaveText('Hosting stopped. All links have ended.')
  await guest.close()
})

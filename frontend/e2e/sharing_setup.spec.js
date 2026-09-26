import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
// Only the __e2e__ copy/history may persist; global teardown removes them and the
// isolated Vite bridge. Provider calls are intercepted: no real public room.
// Runner screenshots/traces are removed by the cleanup reporter on failure too.
test('Enable link automatically waits for public access and publishes without a setup step', async ({ page }) => {
  let started = false, polls = 0, publications = 0, shared = null
  const pending = { state: 'dns_pending', message: 'Waiting for public DNS', checks: [] }
  const ready = { state: 'ready', message: 'Public DNS and HTTPS verified', checks: [] }
  await page.route('**/__nadoc_share/**', route => {
    const action = new URL(route.request().url()).pathname.split('/').pop()
    if (action === 'start') { started = true; return route.fulfill({ json: { shares: [], publicAccess: pending } }) }
    if (action === 'stop') { started = false; shared = null; return route.fulfill({ json: {} }) }
    if (action === 'create') {
      expect(polls).toBeGreaterThan(1); publications++
      shared = { id: 'a'.repeat(32), title: 'Setup test', url: 'https://example.invalid/viewer#invite=guest&password=required', password: 'test-password', expiresAt: Date.now() + 60000 }
      return route.fulfill({ json: shared })
    }
    return route.fulfill({ json: { running: started, shares: shared ? [shared] : [], ...(started ? { publicAccess: ++polls > 1 ? ready : pending } : {}) } })
  })
  const design = JSON.parse(readFileSync(new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)))
  design.id = '__e2e__auto-sharing'; design.metadata.name = '__e2e__auto-sharing'
  await page.goto('/?doc=__e2e__auto-sharing')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js'); await api.importDesign(JSON.stringify(design)); await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden'); document.getElementById('menu-file-sharing').click()
  }, design)
  const dialog = page.locator('#share-link-dialog')
  await expect(dialog.locator('[data-host-setup]')).toHaveCount(0)
  await expect(dialog.locator('[data-create]')).toBeEnabled()
  await expect(dialog.locator('[data-stop-host]')).toBeDisabled()
  await expect(dialog.locator('[data-copy-link]')).toHaveCount(0)
  await dialog.locator('[data-create]').click()
  await expect(dialog.locator('[data-status]')).toHaveText('Waiting for public DNS')
  expect(publications).toBe(0)
  await expect(dialog.locator('[data-copy-link]')).toBeVisible({ timeout: 20000 })
  await expect(dialog.locator('[data-create]')).toBeDisabled()
  await expect(dialog.locator('[data-stop-host]')).toBeEnabled()
  await expect(dialog.locator('[data-status]')).toBeEmpty()
  expect(publications).toBe(1)
  await page.evaluate(() => { window.__copiedShare = ''; navigator.clipboard.writeText = async value => { window.__copiedShare = value } })
  await dialog.locator('[data-copy-link]').click()
  expect(await page.evaluate(() => window.__copiedShare)).toBe('https://example.invalid/viewer#invite=guest&password=required')
  await expect(dialog.locator('[data-link]')).toHaveValue('https://example.invalid/viewer#invite=guest&password=required')
  await expect(dialog.locator('[data-password]')).toHaveValue('test-password')
  for (const key of ['link', 'password']) {
    const field = dialog.locator(`[data-${key}]`)
    const copy = dialog.getByRole('button', { name: `Copy ${key}`, exact: true })
    await expect(field).toBeVisible()
    await expect(field).toHaveAttribute('readonly', '')
    await expect(copy.locator('svg')).toBeVisible()
    const inputBox = await field.boundingBox(), copyBox = await copy.boundingBox()
    expect(copyBox.x).toBeGreaterThanOrEqual(inputBox.x + inputBox.width)
    await field.dblclick()
    expect(await field.evaluate(input => input.value.slice(input.selectionStart, input.selectionEnd))).toBe(await field.inputValue())
  }
  await dialog.locator('[data-copy-password]').click()
  expect(await page.evaluate(() => window.__copiedShare)).toBe('test-password')
  await expect(dialog.locator('[data-status]')).toHaveText('Password copied')
  await dialog.locator('[data-stop-host]').click()
  await expect(dialog.locator('[data-create]')).toBeEnabled()
  await expect(dialog.locator('[data-stop-host]')).toBeDisabled()
  await expect(dialog.locator('[data-copy-link]')).toHaveCount(0)
  await expect(dialog.locator('[data-copy-password]')).toHaveCount(0)
  await page.route('**/__nadoc_share/start', route => route.fulfill({ status: 503, json: { error: 'Host connection failed' } }))
  await dialog.locator('[data-create]').click()
  const errors = dialog.locator('[data-error]')
  await expect(errors).toBeVisible()
  await expect(errors).not.toHaveAttribute('open')
  await expect(errors.locator('pre')).not.toBeVisible()
  await errors.locator('summary').click()
  await expect(errors.locator('pre')).toHaveText('Host connection failed')
  await expect(errors.locator('pre')).toBeVisible()
})

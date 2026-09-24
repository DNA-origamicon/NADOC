import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
// Only the __e2e__ copy/history may persist; global teardown removes them and the
// isolated Vite bridge. Provider calls are intercepted: no real public room.
// Runner screenshots/traces are removed by the cleanup reporter on failure too.
test('Create link automatically waits for public access and publishes without a setup step', async ({ page }) => {
  let started = false, polls = 0, publications = 0
  const pending = { state: 'dns_pending', message: 'Waiting for public DNS', checks: [] }
  const ready = { state: 'ready', message: 'Public DNS and HTTPS verified', checks: [] }
  await page.route('**/__nadoc_share/**', route => {
    const action = new URL(route.request().url()).pathname.split('/').pop()
    if (action === 'start') { started = true; return route.fulfill({ json: { shares: [], publicAccess: pending } }) }
    if (action === 'create') {
      expect(polls).toBeGreaterThan(1); publications++
      return route.fulfill({ json: { id: 'a'.repeat(32), title: 'Setup test', url: 'https://example.invalid/viewer', password: 'test-password', expiresAt: Date.now() + 60000 } })
    }
    return route.fulfill({ json: { running: started, shares: [], ...(started ? { publicAccess: ++polls > 1 ? ready : pending } : {}) } })
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
  await dialog.locator('[data-create]').click()
  await expect(dialog.locator('[data-status]')).toContainText('Waiting for public DNS')
  expect(publications).toBe(0)
  await expect(dialog.locator('[data-status]')).toContainText('Invitation ready', { timeout: 20000 })
  expect(publications).toBe(1)
})

import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Read-only fixture, transient selections and in-memory annotation only. Autosave
// and save routes are disabled. The isolated backend disables session caching.
// Global teardown removes test bridge credentials; reporter removes traces/images.
test('spreadsheet ranges and toggles feed the 3D and annotation selection', async ({ page }) => {
  test.setTimeout(90000)
  const file = path.resolve(process.cwd(), '..', 'Examples/2hb_xover_atoms_test.nadoc')
  const hash = () => createHash('sha256').update(readFileSync(file)).digest('hex')
  const before = hash(), errors = trackConsoleErrors(page)
  try {
    await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
    await page.route('**/api/design/save**', route => route.fulfill({ status: 409, json: { detail: 'Read-only test' } }))
    await page.setViewportSize({ width: 1600, height: 1000 })
    await page.goto('/?doc=__e2e__spreadsheet-multiselect')
    await page.waitForFunction(() => !!window.__nadocTest)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.loadDesign(file)
      document.getElementById('welcome-screen').classList.add('hidden')
      document.getElementById('spreadsheet-panel').style.display = ''
      for (const id of ['right-panel', 'right-tab-strip']) document.getElementById(id).classList.remove('locked-inactive')
    }, file)
    await page.locator('#sheet-toggle').click()
    const rows = page.locator('#spreadsheet-tbody tr[data-strand-id]')
    await expect(rows).toHaveCount(3)
    const ids = await rows.evaluateAll(rows => rows.map(row => row.dataset.strandId))
    const selected = () => page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.filter(r => r.kind === 'strand').map(r => r.id).sort())
    const check = async expected => {
      await expect.poll(selected).toEqual([...expected].sort())
      await expect(page.locator('#spreadsheet-tbody .sheet-selected')).toHaveCount(expected.length)
    }
    await rows.nth(0).locator('[data-col="id"]').click()
    await rows.nth(2).locator('[data-col="id"]').click({ modifiers: ['Shift'] })
    await check(ids)
    await rows.nth(1).locator('[data-col="id"]').click({ modifiers: ['Control'] })
    await check([ids[0], ids[2]])
    await rows.nth(1).locator('[data-col="id"]').click({ modifiers: ['Control'] })
    await check(ids)
    await rows.nth(2).locator('[data-col="id"]').click()
    await rows.nth(1).locator('[data-col="id"]').click({ modifiers: ['Shift'] })
    await check(ids.slice(1))
    await page.locator('#right-tab-strip [data-tab="annotations"]').click()
    const panel = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
    await panel.locator('.anno-add').click()
    await panel.locator('[data-field="useSelection"]').click()
    await expect(panel.locator('.anno-target')).toContainText('2 strands')
    expect(errors).toEqual([])
  } finally { expect(hash()).toBe(before) }
})

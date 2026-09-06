import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

// Persistence inventory: none. Imports stay in the isolated backend's memory,
// session caching is disabled, and no workspace save path is assigned. Standard
// global teardown/reporter remove browser reports and any __e2e__ session artifacts.
test('Hinge editor undo cannot restore a previously loaded file', async ({ page }) => {
  const doc = '__e2e__undo_boundary'
  const headers = { 'X-NADOC-Doc': doc }
  const api = `${process.env.NADOC_E2E_API_BASE}/api`
  const fixture = JSON.parse(await readFile('../workspace/Hinge_test.nadoc', 'utf8'))
  Object.assign(fixture, { id: '__e2e__previous_hinge', loadouts: [], active_loadout_id: null })
  fixture.metadata.identity_last_known_path = null
  const imported = await page.request.post(`${api}/design/import`, { headers, data: { content: JSON.stringify(fixture) } })
  expect(imported.ok()).toBeTruthy()
  await page.goto(`/cadnano-editor.html?doc=${doc}`)
  await page.locator('#pathview-canvas').waitFor()
  fixture.id = '__e2e__current_hinge'
  await page.evaluate(async content => {
    await (await import('/src/cadnano-editor/api.js')).importDesign(content)
  }, JSON.stringify(fixture))
  for (const shortcut of ['Control+z', 'Control+y']) {
    const response = page.waitForResponse(r => /\/design\/(undo|redo)$/.test(r.url()))
    await page.keyboard.press(shortcut)
    expect((await response).status()).toBe(404)
  }
  const current = await page.request.get(`${api}/design`, { headers })
  expect((await current.json()).design.id).toBe(fixture.id)
})

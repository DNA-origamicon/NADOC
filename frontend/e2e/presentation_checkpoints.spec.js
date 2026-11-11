import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persistence: only __e2e__ parts/project stores in NADOC_WORKSPACE; the shared
// global teardown removes these. Run with an isolated scratch workspace and
// disabled session cache. No downloads, screenshots or external output files.
test('sidebar checkpoints, hidden history, seeks and playback restore complete presentation states', async ({ page }) => {
  test.setTimeout(120000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__presentation-checkpoints', name: 'presentation-checkpoints' })
  const historyLength = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)
  const before = await historyLength()
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const annotations = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await annotations.locator('.anno-add').click()
  await annotations.locator('.anno-text').fill('Saved caption')
  await annotations.getByRole('button', { name: 'Save to feature log', exact: true }).click()
  await expect(annotations.getByRole('status').filter({ hasText: /^Saved$/ })).toHaveText('Saved')
  expect(await historyLength()).toBe(before + 1)
  await annotations.locator('.anno-text').fill('Working caption')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.annotations[0].text)).toBe('Working caption')
  expect(await historyLength()).toBe(before + 1)

  await page.locator('#right-tab-strip [data-tab="visualization"]').click()
  const volumes = page.locator('#view-volumes-section')
  await volumes.locator('#view-volume-add-box').click()
  await volumes.getByRole('button', { name: 'Save to feature log', exact: true }).click()
  await expect(volumes.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
  expect(await historyLength()).toBe(before + 2)
  await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  await expect(page.locator(`#fl-list [data-fl-row="${before + 1}"]`)).toHaveCount(0)
  await page.locator('#feature-log-panel-body .fl-filter button').click()
  await page.locator('#feature-log-panel-body').getByLabel('Annotations and view volumes', { exact: true }).check()
  await expect(page.locator(`#fl-list [data-fl-row="${before + 1}"]`)).toBeVisible()
  await page.locator('#feature-log-panel-body .fl-filter button').click()

  await page.evaluate(async index => { const api = await import('/src/api/client.js'); await api.seekFeatures(index) }, before)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.annotations[0]?.text)).toBe('Saved caption')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.view_volumes.length)).toBe(0)
  await page.evaluate(async () => { const api = await import('/src/api/client.js'); await api.seekFeatures(-1) })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.view_volumes.length)).toBe(1)

  // Drive the actual player, then verify its transient display never edits the store.
  await page.evaluate(async index => {
    const player = window.__nadocTest.animPlayer
    await player.play({ id: 'preview', fps: 30, keyframes: [
      { id: 'empty', feature_log_index: -2, transition_duration_s: 0, hold_duration_s: 1 },
      { id: 'saved', feature_log_index: index, transition_duration_s: 0, hold_duration_s: 2 },
    ] })
    player.pause(); await player.seekTo(0.5)
  }, before + 1)
  await expect(page.locator('.nadoc-anno:not([hidden])')).toHaveCount(0)
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.annotations[0].text)).toBe('Saved caption')
  await page.evaluate(() => window.__nadocTest.animPlayer.seekTo(1.5))
  await expect(page.locator('.nadoc-anno:not([hidden])')).toContainText('Saved caption')
  await page.evaluate(() => window.__nadocTest.animPlayer.stop())
  await expect(page.locator('.nadoc-anno:not([hidden])')).toContainText('Saved caption')
  expect(errors).toEqual([])
})

test('assembly sidebar checkpoints remain separate from configuration poses', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1800, height: 1000 })
  await page.goto('/?doc=__e2e__assembly-presentation-checkpoints')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.createAssembly('__e2e__assembly-presentation-checkpoints')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  })
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const annotations = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await annotations.locator('.anno-add').click()
  await annotations.locator('.anno-text').fill('Assembly caption')
  await annotations.getByRole('button', { name: 'Save to feature log', exact: true }).click()
  await expect(annotations.getByRole('status').filter({ hasText: /^Saved$/ })).toHaveText('Saved')
  const index = await page.evaluate(() => window.__nadocTest.store.getState().currentAssembly.feature_log.length - 1)
  await page.locator('#right-tab-strip [data-tab="visualization"]').click()
  const volumes = page.locator('#view-volumes-section')
  await volumes.locator('#view-volume-add-box').click()
  await volumes.getByRole('button', { name: 'Save to feature log', exact: true }).click()
  await expect(volumes.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
  const result = await page.evaluate(async index => {
    const player = window.__nadocTest.animPlayer
    await player.play({ id: 'assembly-preview', fps: 30, keyframes: [
      { id: 'initial', feature_log_index: -2, transition_duration_s: 0, hold_duration_s: 1 },
      { id: 'saved', feature_log_index: index, transition_duration_s: 0, hold_duration_s: 2 },
    ] })
    player.pause(); await player.seekTo(0.5)
    return window.__nadocTest.store.getState().currentAssembly.annotations[0].text
  }, index + 1)
  expect(result).toBe('Assembly caption')
  await expect(page.locator('.nadoc-anno:not([hidden])')).toHaveCount(0)
  await page.evaluate(() => window.__nadocTest.animPlayer.seekTo(1.5))
  await expect(page.locator('.nadoc-anno:not([hidden])')).toContainText('Assembly caption')
  await page.evaluate(() => window.__nadocTest.animPlayer.stop())
  expect(errors).toEqual([])
})

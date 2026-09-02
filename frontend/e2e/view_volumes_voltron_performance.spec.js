import { expect, test } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const DESIGN = '/home/joshua/NADOC/workspace/VoltronCoreArm.nadoc'

test('VoltronCoreArm Volume 1 changes representation once without an operation cascade', async ({ page }) => {
  test.setTimeout(720_000)
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=e2e-view-volume-voltron')
  await page.evaluate(async path => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive', 'hidden')
  }, DESIGN)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length ?? 0), { timeout: 120_000 }).toBeGreaterThan(1000)
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  let volumeCount = await page.locator('.view-volume-row').count()
  if (!volumeCount) {
    await page.locator('#view-volume-add').click()
    await expect(page.locator('.view-volume-row')).toHaveCount(1)
    await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing().counters.persisted), { timeout: 60_000 }).toBeGreaterThanOrEqual(1)
    volumeCount = 1
  }
  await page.evaluate(() => {
    const debug = window.__NADOC_VIEW_VOLUMES__
    debug.select(debug.volumes()[0].id)
  })
  await expect(page.locator('.view-volume-row')).toHaveCount(volumeCount)
  await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selectedMembership().count), { timeout: 60_000 }).toBeGreaterThan(0)

  const persistedOnBase = await page.request.get('/api/design/view-volumes', { headers: { 'X-NADOC-Doc': 'e2e-view-volume-voltron' } })
  const persistedVolumes = (await persistedOnBase.json()).view_volumes ?? []
  expect(persistedVolumes).toHaveLength(volumeCount)
  expect(persistedVolumes[0].id).toBe(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[0].id))

  // Keep this orchestration test deterministic: Voltron's complete atom build is
  // independently covered by atomistic tests and can take minutes. Here we count
  // requests and return an empty valid payload to detect duplicate/cancelled work.
  let atomRequests = 0
  let releaseAtom
  const atomGate = new Promise(resolve => { releaseAtom = resolve })
  await page.route('**/api/design/atomistic*', async route => {
    atomRequests += 1
    await atomGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ atoms: [], bonds: [], element_meta: {}, stats: {} }) })
  })
  const persistedBeforeRepresentation = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing().counters.persisted)
  const representation = page.locator('.view-volume-row').first().locator('.view-volume-representation')
  await representation.selectOption('stick')
  await expect.poll(() => atomRequests, { timeout: 30_000 }).toBe(1)
  await expect(page.locator('#view-volume-busy')).toBeVisible()
  releaseAtom()
  await expect(page.locator('#view-volume-busy')).toBeHidden({ timeout: 30_000 })
  await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing().counters.persisted), { timeout: 60_000 }).toBe(persistedBeforeRepresentation + 1)
  await expect(page.locator('.view-volume-row')).toHaveCount(volumeCount)

  await representation.selectOption('beads')
  await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing().counters.persisted), { timeout: 60_000 }).toBe(persistedBeforeRepresentation + 2)
  await page.waitForTimeout(500)
  expect(atomRequests).toBe(1)
  await expect(page.locator('.view-volume-row')).toHaveCount(volumeCount)
  const persistedAfterRepresentation = await page.request.get('/api/design/view-volumes', { headers: { 'X-NADOC-Doc': 'e2e-view-volume-voltron' } })
  expect((await persistedAfterRepresentation.json()).view_volumes[0].representation).toBe('beads')

  const metrics = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing())
  expect(metrics.counters.commits).toBe(0)
  expect(errors, errors.join('\n')).toEqual([])
})

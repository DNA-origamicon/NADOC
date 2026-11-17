import { expect, test } from '@playwright/test'
import { readFileSync, existsSync } from 'node:fs'

// Read-only legacy fixture: saves blocked, source checked even on failure.
// No authored structures. Session cache disabled by config. Global teardown
// removes bridge credentials and __e2e__ scratch; reporter cleans screenshots.
const fixturePath = existsSync(new URL('../../workspace/duplex.nadoc', import.meta.url)) ? 'workspace/duplex.nadoc' : 'Examples/U6hb.nadoc'
const fixture = new URL(`../../${fixturePath}`, import.meta.url)
let original
test.beforeEach(async ({ page }) => {
  original = readFileSync(fixture, 'utf8')
  await page.route('**/api/design/save-workspace', route => route.abort())
  await page.route('**/api/design/save', route => route.abort())
  // Keep the real Open UI lifecycle while loading this out-of-workspace legacy
  // fixture read-only, without library identity registration or file rewriting.
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', {
      data: { path: fixturePath },
      headers: { 'X-NADOC-Doc': route.request().headers()['x-nadoc-doc'] },
    })
    await route.fulfill({ response })
  })
})
test.afterEach(() => expect(readFileSync(fixture, 'utf8')).toBe(original))

test('base contacts toggle and single-base automatic display in atomistic views', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  page.setDefaultTimeout(15_000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto(`/?doc=__e2e__base-interactions&open=${encodeURIComponent(fixturePath)}`)
  await page.waitForFunction(() => !!window.__nadocTest && !document.getElementById('right-tab-strip')?.classList.contains('locked-inactive'))
  await expect(page.locator('#file-load-progress')).not.toBeVisible()
  await page.keyboard.press('F7')
  await page.waitForFunction(() => window.__nadocTest.getAtomisticRenderer().getMode() === 'ballstick')
  await page.locator('#right-tab-strip [data-tab="visualization"]').click()
  const column = page.locator('#right-panel .sidebar-column[data-panel-type="visualization"]').last()
  const control = id => column.locator(`#${id}, [data-sidebar-source-id="${id}"]`)
  if (!await control('slab-body').isVisible()) await control('slab-heading').click()
  await expect(control('show-base-interactions')).toBeVisible()
  const contacts = () => page.evaluate(() => {
    const out = []
    window._nadocDebug.scene.traverse(o => {
      if (o.name.startsWith('base-interactions-')) out.push(...o.userData.contacts.map(c => ({ ...c, type: o.name })))
    })
    return out
  })
  await expect.poll(contacts).toEqual([])
  await control('show-base-interactions').check()
  await expect.poll(async () => (await contacts()).filter(c => c.type.endsWith('hydrogen')).length).toBeGreaterThan(0)
  await expect.poll(async () => (await contacts()).filter(c => c.type.endsWith('stacking')).length).toBeGreaterThan(0)
  const all = await contacts()
  const key = all.filter(c => c.type.endsWith('hydrogen')).flatMap(c => c.keys)
    .find(key => all.filter(c => c.type.endsWith('stacking') && c.keys.includes(key)).length >= 2)
  expect(key).toBeTruthy()
  await control('show-base-interactions').uncheck()
  await expect.poll(contacts).toEqual([])
  await page.evaluate(async key => {
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'base', key }])
  }, key)
  await expect.poll(async () => (await contacts()).length).toBeGreaterThan(0)
  expect((await contacts()).every(c => c.keys.includes(key))).toBe(true)
  // Clear selection before switching global representation, then select again.
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).clear()
  })
  await expect.poll(contacts).toEqual([])
  await column.getByRole('button', { name: 'Stick', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest.getAtomisticRenderer().getMode() === 'stick')
  await page.evaluate(async key => {
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'base', key }])
  }, key)
  await expect.poll(async () => (await contacts()).length).toBeGreaterThan(0)
  if (process.env.NADOC_INTERACTIONS_REVIEW) {
    await page.evaluate(() => {
      const line = window._nadocDebug.scene.getObjectByName('base-interactions-hydrogen')
      const p = line.geometry.getAttribute('position').array
      const target = [(p[0] + p[3]) / 2, (p[1] + p[4]) / 2, (p[2] + p[5]) / 2]
      window.__nadocTest.applyCameraPoseForTest({ target, position: target.map((v, i) => v + [2.5, 3, 1][i]) })
    })
    await page.waitForTimeout(300)
    await page.screenshot({ path: testInfo.outputPath('contacts.png') })
    console.log('REVIEW', testInfo.outputPath('contacts.png'))
    await page.waitForTimeout(20_000)
  }
  expect(errors).toEqual([])
})

import { test, expect } from '@playwright/test'

// Persistent inventory: no design is created (New Part is cancelled). Backend
// uses the isolated workspace; screenshots/traces stay in Playwright output.
// global-teardown removes isolated bridge credentials and any __e2e__ artifacts.
// Native transport is intercepted, leaving the physical headset untouched.
test('File actions reach the real filename dialog and workspace picker', async ({ page }, info) => {
  let wire, sequence = 0
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/vr/**', route => route.fulfill({ json: { running: false } }))
  await page.route('**/api/vr/routing', async route => { wire = route.request().postDataJSON(); await route.fulfill({ json: { published: true } }) })
  await page.goto('/?test=1&doc=__e2e__vr-files&scrywrite=inspect')
  await page.waitForFunction(() => window.__nadocTest?.scrywrite?.publishFileControls)
  const publish = () => page.evaluate(() => window.__nadocTest.scrywrite.publishFileControls())
  const click = async id => {
    await publish()
    await page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event), { type: 'routing', sequence: ++sequence, version: wire.version, id })
  }
  await publish()
  expect(wire.roots.find(r => r.id === 'file-assembly').enabled).toBe(false)
  await click('file-new')
  await expect(page.locator('#new-design-name')).toBeVisible()
  await publish()
  expect(wire.title).toBe('Filename keyboard')
  for (const id of ['a','b','c','1','delete','shift','d']) await click(`file-key-${id}`)
  await expect(page.locator('#new-design-name')).toHaveValue('abcD')
  await page.screenshot({ path: info.outputPath('filename.png') })
  await publish(); await click(wire.controls.find(r => r.label === 'Cancel').id)
  await expect(page.locator('.modal__overlay')).toHaveCount(0)
  await click('file-open')
  await expect(page.locator('[data-vr-file-browser]')).toBeVisible()
  await publish(); expect(wire.title).toBe('Open / Save File')
  await page.screenshot({ path: info.outputPath('open.png') })
  await click(wire.controls.find(r => r.label === 'Cancel').id)
  await expect(page.locator('[data-vr-file-browser]')).toHaveCount(0)
  expect(errors).toEqual([])
})

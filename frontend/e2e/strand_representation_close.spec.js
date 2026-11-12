import { expect, test } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'

// Existing design is read only. Intercept saves; verify source even on failure.
// Session persistence is disabled; global teardown removes credentials/scratch.
const fixture = new URL('../../workspace/2hb_1xT.nadoc', import.meta.url)
let original
test.beforeEach(async ({ page }) => {
  test.skip(!existsSync(fixture), 'Existing 2hb_1xT fixture unavailable')
  original = readFileSync(fixture, 'utf8')
  await page.route('**/api/design/save-workspace', route => route.fulfill({ json: { path: 'workspace/2hb_1xT.nadoc' } }))
})
test.afterEach(() => { if (original) expect(readFileSync(fixture, 'utf8')).toBe(original) })

test('Close Session releases a strand after ballstick to Full round trip', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const errors = []
  page.on('pageerror', e => { errors.push(e.message); console.log(e.stack) })
  await page.goto('/?doc=e2e-strand-close')
  await page.waitForFunction(() => !!window._nadocDebug)
  const id = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    await api.loadDesign('workspace/2hb_1xT.nadoc')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const strand = store.getState().currentDesign.strands.find(s => s.strand_type === 'staple')
    createSelectionController({ store }).replace([{ kind: 'strand', id: strand.id }])
    return strand.id
  })
  for (const [key, rep] of [['F7', 'ballstick'], ['F4', 'full']]) {
    await page.keyboard.press(key)
    await page.waitForFunction(({ id, rep }) => {
      const root = window._nadocDebug.scene.getObjectByName(`view-volume-display-strand:${id}`)
      let ready = false
      root?.traverse(o => { if (rep === 'full' ? ['backboneSpheres', 'backboneCubes'].includes(o.name) : o.name === 'atomSpheres') ready = true })
      return ready
    }, { id, rep })
  }
  await page.evaluate(() => document.getElementById('menu-file-close-session').click())
  await expect(page.locator('#welcome-screen')).toBeVisible()
  await page.waitForTimeout(300)
  expect(await page.evaluate(() => window._nadocDebug.scene.children.filter(o => o.name.startsWith('view-volume-display-')).map(o => o.name))).toEqual([])
  expect(errors).toEqual([])
  if (process.env.NADOC_STRAND_CLOSE_REVIEW) {
    await page.screenshot({ path: testInfo.outputPath('closed.png') })
    console.log('REVIEW', testInfo.outputPath('closed.png'))
    await page.waitForTimeout(15_000)
  }
})

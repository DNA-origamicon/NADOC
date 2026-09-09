import { test, expect } from '@playwright/test'

// No saved designs, jobs, downloads, or custom artifact paths. Browser storage is
// confined to Playwright's disposable context; the backend disables session cache.
test('nanopore display controls affect preview and MD independently of inclusion', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/?doc=__e2e__graphene-display')
  await page.waitForFunction(() => !!window.__nadocTest)
  // Show the actual MD card without creating or editing a workspace document.
  await page.evaluate(() => {
    const card = document.getElementById('md-surface-body').parentElement
    document.body.appendChild(card)
    Object.assign(card.style, { position: 'fixed', zIndex: '99999', top: '40px', right: '10px', width: '280px', background: '#161b22' })
    document.getElementById('md-surface-body').style.display = 'block'
    const include = document.getElementById('md-surface-enable')
    include.checked = true
    include.dispatchEvent(new Event('change'))
  })
  const meshInfo = () => page.evaluate(() => {
    const mesh = window.__nadocScene.getObjectByName('Graphene nanopore preview')
    return mesh && { visible: mesh.visible, instanced: !!mesh.isInstancedMesh, count: mesh.count,
      style: mesh.userData.grapheneRepresentation || 'plane' }
  })
  const include = await page.locator('#md-surface-enable').isChecked()
  await expect.poll(async () => (await meshInfo())?.style).toBe('plane')
  for (const style of ['ball', 'stick', 'plane']) {
    await page.locator('#md-graphene-representation').selectOption(style)
    await expect.poll(async () => (await meshInfo())?.style).toBe(style)
    await page.locator('#md-graphene-show').uncheck()
    await expect.poll(async () => (await meshInfo())?.visible).toBe(false)
    await page.locator('#md-graphene-show').check()
    await expect.poll(async () => (await meshInfo())?.visible).toBe(true)
    expect(await page.locator('#md-surface-enable').isChecked()).toBe(include)
  }
  // Use the real MD overlay with a deterministic carbon ring; no trajectory/job is created.
  await page.evaluate(async () => {
    const { initMdSolventOverlay } = await import('/src/scene/md_solvent_overlay.js')
    const { initGrapheneDisplayControls } = await import('/src/ui/graphene_display_controls.js')
    const overlay = initMdSolventOverlay(window.__nadocScene)
    initGrapheneDisplayControls({ simulation: overlay })
    overlay.setMode('sphere')
    overlay.setFrame({ nWater: 0, ions: new Float32Array(), graphene: new Float32Array(
      Array.from({ length: 6 }, (_, i) => [0.142 * Math.cos(i * Math.PI / 3), 0, 0.142 * Math.sin(i * Math.PI / 3)]).flat()) })
    window.dispatchEvent(new CustomEvent('nadoc:graphene-md-active', { detail: { active: true } }))
  })
  await expect.poll(async () => (await meshInfo())?.visible).toBe(false)
  for (const style of ['ball', 'stick', 'plane']) {
    await page.locator('#md-graphene-representation').selectOption(style)
    await expect.poll(() => page.evaluate(() => window.__nadocScene.getObjectByName('Graphene nanopore')?.userData.grapheneRepresentation)).toBe(style)
    await page.locator('#md-graphene-show').uncheck()
    await expect.poll(() => page.evaluate(() => window.__nadocScene.getObjectByName('Graphene nanopore')?.visible)).toBe(false)
    await page.locator('#md-graphene-show').check()
  }
  expect(await page.locator('#md-surface-enable').isChecked()).toBe(include)
  expect(errors).toEqual([])
})

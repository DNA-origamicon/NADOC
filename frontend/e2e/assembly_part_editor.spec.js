import { expect, test } from '@playwright/test'

test('part opened from an assembly has clean part-mode UI and no inactive gizmos', async ({ page, context }) => {
  test.setTimeout(120_000)
  await page.goto('/?doc=__e2e__assembly-part-editor&open=smallO-poly.nass&open-type=assembly')
  await page.waitForFunction(() =>
    window.__NADOC_DBG__?.store.getState().currentAssembly?.instances?.length === 3,
  null, { timeout: 90_000 })

  const popupPromise = context.waitForEvent('page')
  await page.locator('#assembly-instance-list [data-instance-id]').first()
    .getByTitle('Edit part in new tab').click()
  const editor = await popupPromise
  const errors = []
  editor.on('pageerror', error => errors.push(String(error)))
  editor.on('console', message => {
    if (message.type() === 'error') errors.push(message.text())
  })
  await editor.waitForFunction(() =>
    window.__NADOC_DBG__?.store.getState().currentDesign?.metadata?.name === 'smallO',
  null, { timeout: 30_000 })
  await expect(editor.locator('#file-load-progress')).not.toHaveClass(/visible/, { timeout: 20_000 })

  const state = await editor.evaluate(() => ({
    assemblyActive: window.__NADOC_DBG__.store.getState().assemblyActive,
    activeSidebar: document.querySelector('.right-tab-btn.active')?.dataset.tab,
    assemblyTabHidden: document.querySelector('.right-tab-btn[data-tab="assembly"]')?.hidden,
    surface: window.__nadocSurfStrands.debug(),
  }))
  expect(state.assemblyActive).toBe(false)
  expect(state.activeSidebar).toBe('properties')
  expect(state.assemblyTabHidden).toBe(true)
  expect(state.surface.gizmoVisible).toBe(false)
  expect(state.surface.gizmoAttached).toBe(false)
  expect(state.surface.gizmoEnabled).toBe(false)
  expect(errors).toEqual([])
})

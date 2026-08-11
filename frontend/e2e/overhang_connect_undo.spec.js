import { test, expect } from '@playwright/test'

const FIXTURE = '/home/joshua/NADOC/workspace/2x2_OH_test.nadoc'

test('Connect row disappears from Linkers & Bindings after one Undo', async ({ page }) => {
  test.setTimeout(90_000)
  await page.goto('/')
  await page.waitForSelector('#canvas')

  // Start from a real two-overhang fixture, then remove its legacy materialization
  // through public APIs. This leaves a clean, connectable pair in the live app.
  const pair = await page.evaluate(async (path) => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    await api.loadDesign(path)
    let d = store.getState().currentDesign
    for (const b of [...(d.overhang_bindings ?? [])]) await api.deleteOverhangBinding(b.id)
    d = store.getState().currentDesign
    for (const dx of [...(d.duplexes ?? [])]) await api.deleteDuplex(dx.id)
    d = store.getState().currentDesign
    for (const v of [...(d.connection_versions ?? [])]) await api.deleteConnectionVersion(v.id)
    d = store.getState().currentDesign
    document.getElementById('welcome-screen')?.classList.add('hidden')
    return d.overhangs.map(o => o.id)
  }, FIXTURE)
  expect(pair).toHaveLength(2)

  // The fixture load does not switch the welcome layout's sidebar visibility,
  // so expose the real mounted sidebar section before driving its controls.
  await page.evaluate(() => {
    const panel = document.getElementById('right-panel')
    if (panel) { panel.style.display = 'block'; panel.classList.remove('hidden') }
    const section = document.getElementById('overhang-connections-section')
    if (section) { section.style.display = 'block'; section.scrollIntoView() }
  })
  await page.evaluate(([a, b]) => {
    document.getElementById('oconn-heading').click()
    const sa = document.getElementById('oconn-select-a')
    const sb = document.getElementById('oconn-select-b')
    sa.value = a; sa.dispatchEvent(new Event('change'))
    sb.value = b; sb.dispatchEvent(new Event('change'))
  }, pair)

  // Recreate the fixture's real direct binding through the sidebar.
  await page.evaluate(() => {
    document.getElementById('oconn-button-box').click()
    document.querySelector('#oconn-popover [data-variant="end-to-root"]').click()
  })
  await expect(page.locator('#oconn-generate')).toHaveText('Connect')
  expect(await page.locator('#oconn-generate').isDisabled()).toBe(false)
  const connectResponse = page.waitForResponse(r =>
    r.url().includes('/api/design/connection-versions/connect'))
  await page.evaluate(() => document.getElementById('oconn-generate').click())
  const response = await connectResponse
  expect(response.status(), await response.text()).toBe(201)

  const rows = page.locator('#oconn-list .oconn-version-row')
  await expect(rows).toHaveCount(1, { timeout: 15_000 })
  await expect(page.locator('#oconn-list')).toContainText('V1')

  // Exercise the real menu handler, not a direct API shortcut.
  await page.evaluate(() => document.getElementById('menu-edit-undo').click())
  await expect(rows).toHaveCount(0, { timeout: 15_000 })
  await expect(page.locator('#oconn-list')).toContainText('No connections yet')

  const state = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    return {
      versions: d.connection_versions?.length ?? 0,
      connections: d.overhang_connections?.length ?? 0,
      bindings: d.overhang_bindings?.length ?? 0,
      duplexes: d.duplexes?.length ?? 0,
    }
  })
  expect(state).toEqual({ versions: 0, connections: 0, bindings: 0, duplexes: 0 })
})

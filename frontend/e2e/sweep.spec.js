import { test, expect } from '@playwright/test'
import path from 'node:path'

// Persistent inventory: __e2e__Sweep parts + their hidden revision stores are
// removed by global-teardown.js, including on failure. Smoke servers disable
// session caching. Four screenshots are retained as review evidence in
// .development-artifacts/sweep-popup.png, sweep-gizmo.png, sweep-reloaded.png
// and sweep-continuation.png.
test('Sweep creates one editable spline feature with nm point controls and undo/redo', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?test=1&doc=__e2e__sweep')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__Sweep')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await page.click('#menu-tools-sweep')
  await expect(page.locator('#sweep-panel')).toBeVisible()
  await page.evaluate(() => window.SLICE.setSelectedCells([[0,0],[0,1]]))
  await expect(page.locator('#sweep-step')).toContainText('1/2')
  await expect(page.locator('#sweep-path')).not.toBeVisible()
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('#sweep-step')).toContainText('2/2')
  expect(await page.evaluate(() => window.SLICE.isVisible())).toBe(false)
  await expect(page.locator('#sweep-footprint')).not.toBeVisible()
  await page.getByRole('button', { name: 'Add sweep point' }).click()
  await page.getByRole('spinbutton', { name: 'Point X (nm)' }).fill('8')
  await page.getByRole('spinbutton', { name: 'Point Y (nm)' }).fill('4')
  await expect.poll(async () => `${await page.locator('#sweep-apply').isEnabled()}:${await page.locator('#sweep-status').textContent()}`).toMatch(/^true:/)
  await expect(page.locator('#sweep-status')).toContainText('bp per helix')
  // Real raycast selection + TransformControls drag, using read-only screen locations.
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [12,16,38], target: [-8,0,9] }))
  let locations = await page.evaluate(() => window.__nadocTest.getSweepScreenPositions())
  const point = locations.points.find(p => p.name === 'sweep-point-1')
  await page.mouse.click(point.x, point.y)
  await expect(page.getByRole('option', { name: /Point 1 / })).toHaveAttribute('aria-selected', 'true')
  locations = await page.evaluate(() => window.__nadocTest.getSweepScreenPositions())
  const handle = locations.handles.find(p => p.name === 'X')
  await page.mouse.move(handle.x, handle.y)
  await page.mouse.down()
  expect(await page.evaluate(() => window.__nadocTest.controlsEnabled())).toBe(false)
  await page.mouse.move(handle.x + 35, handle.y, { steps: 8 })
  await page.mouse.up()
  await expect.poll(async () => Number(await page.getByRole('spinbutton', { name: 'Point X (nm)' }).inputValue())).toBeGreaterThan(1)
  expect(await page.evaluate(() => window.__nadocTest.controlsEnabled())).toBe(true)
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.screenshot({ path: path.resolve(import.meta.dirname, '../../.development-artifacts/sweep-gizmo.png') })
  await page.getByRole('button', { name: 'Previous', exact: true }).click()
  expect(await page.evaluate(() => window.SLICE.isVisible())).toBe(true)
  await expect(page.locator('#sweep-path')).not.toBeVisible()
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.getByRole('option', { name: /Origin/ }).click()
  await expect(page.getByRole('spinbutton', { name: 'Point X (nm)' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Delete point 0' })).toHaveCount(0)
  await page.screenshot({ path: path.resolve(import.meta.dirname, '../../.development-artifacts/sweep-popup.png') })
  await page.click('#sweep-apply')
  await expect(page.locator('#sweep-panel')).not.toBeVisible()
  const summary = () => page.evaluate(async () => {
    const d = (await import('/src/state/store.js')).store.getState().currentDesign
    return { helices: d.helices.length, log: d.feature_log.map(e => e.op_kind), deformations: d.deformations.map(d => d.type) }
  })
  expect(await summary()).toEqual({ helices: 2, log: ['sweep'], deformations: ['sweep'] })
  await page.evaluate(async () => { await (await import('/src/api/client.js')).undo() })
  expect((await summary()).helices).toBe(0)
  await page.evaluate(async () => { await (await import('/src/api/client.js')).redo() })
  expect((await summary()).helices).toBe(2)
  const row = page.locator('#feature-log-panel-body [data-fl-row="1"]')
  await row.getByRole('button', { name: '✎' }).click()
  await expect(page.locator('#sweep-panel')).toBeVisible()
  await page.getByRole('option', { name: /Point 2/ }).click()
  await expect(page.getByRole('spinbutton', { name: 'Point X (nm)' })).toHaveValue('8')
  await page.getByRole('spinbutton', { name: 'Point X (nm)' }).fill('12')
  await expect.poll(async () => `${await page.locator('#sweep-apply').isEnabled()}:${await page.locator('#sweep-status').textContent()}`).toMatch(/^true:/)
  await page.click('#sweep-apply')
  await expect(page.locator('#sweep-panel')).not.toBeVisible()
  // Round-trip the representative .nadoc payload through the real loader.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const content = JSON.stringify(store.getState().currentDesign)
    if (!await api.importDesign(content)) throw new Error('Sweep reload failed')
  })
  expect(await summary()).toEqual({ helices: 2, log: ['sweep'], deformations: ['sweep'] })
  await page.locator('#canvas').focus()
  await page.keyboard.press('f')
  await page.screenshot({ path: path.resolve(import.meta.dirname, '../../.development-artifacts/sweep-reloaded.png') })
  expect(errors).toEqual([])
})

test('Sweep continues from a selected existing end', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('response', r => { if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`) })
  await page.goto('/?test=1&doc=__e2e__sweep-continuation')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__Sweep continuation')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: [[0,0],[0,1]], lengthBp: 21, name: '__e2e__Sweep continuation' })
  })
  // Finish fixture autosave before testing continuation; its design refresh
  // otherwise invalidates preflight between the Next button's down/up events.
  await expect(page.locator('#sync-status-text')).toContainText('saved')
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    store.setState({ toolFilters: { ...store.getState().toolFilters, bluntEnds: true } })
    window.__nadocTest.applyCameraPoseForTest({ position: [12,12,-25], target: [0,0,3] })
  })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions().length)).toBeGreaterThan(0)
  const ends = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions())
  const startEnd = ends.find(e => e.openSide === -1)
  await page.mouse.click(startEnd.x, startEnd.y, { button: 'right' })
  await expect(page.locator('#blunt-end-ctx-menu')).toBeVisible()
  await page.click('#blunt-sweep-btn-ctx')
  await expect(page.locator('#sweep-step')).toContainText('1/2')
  await expect.poll(async () => `${await page.locator('#sweep-apply').isEnabled()}:${await page.locator('#sweep-status').textContent()}`).toMatch(/^true:/)
  await page.evaluate(() => window.SLICE.setSelectedCells([[0,0],[0,1]]))
  await expect.poll(async () => `${await page.locator('#sweep-apply').isEnabled()}:${await page.locator('#sweep-status').textContent()}`).toMatch(/^true:/)
  await page.click('#sweep-apply')
  await expect(page.getByRole('spinbutton', { name: 'Point Z (nm)' })).toHaveValue('-10')
  expect(await page.evaluate(() => window.SLICE.isVisible())).toBe(false)
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.locator('#sweep-panel')).not.toBeVisible()
  const result = await page.evaluate(async () => {
    const d = (await import('/src/state/store.js')).store.getState().currentDesign
    return { count: d.helices.length, domains: d.strands.map(s => s.domains.length), feature: d.feature_log.at(-1).op_kind }
  })
  expect(result.count).toBe(4)
  expect(result.domains.every(n => n === 2)).toBe(true)
  expect(result.feature).toBe('sweep')
  const continuationRender = () => page.evaluate(async () => {
    const d = (await import('/src/state/store.js')).store.getState().currentDesign
    const renderer = window.__nadocDR
    const bonds = renderer.getHelixCtrl().coneEntries.filter(c => c.fromNuc.helix_id !== c.toNuc.helix_id)
    return {
      forcedLigations: d.forced_ligations.length,
      ordinaryBonds: bonds.filter(c => !c.isCrossHelix && c.coneRadius > 0).length,
      arcs: renderer.getCrossHelixConnections().length,
    }
  })
  await expect.poll(continuationRender).toEqual({ forcedLigations: 0, ordinaryBonds: 4, arcs: 0 })
  // Loading must not invent forced-ligation records for these ordinary joins.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const response = await fetch('/api/design/export', {
      headers: { 'X-NADOC-Doc': new URLSearchParams(location.search).get('doc') },
    })
    if (!response.ok || !await api.importDesign(await response.text())) throw new Error('Sweep continuation reload failed')
  })
  await expect.poll(continuationRender).toEqual({ forcedLigations: 0, ordinaryBonds: 4, arcs: 0 })
  await page.locator('#canvas').focus()
  await page.keyboard.press('f')
  await page.screenshot({ path: path.resolve(import.meta.dirname, '../../.development-artifacts/sweep-continuation.png') })
  expect(errors).toEqual([])
})

import { test, expect } from '@playwright/test'
import { readFileSync, copyFileSync } from 'node:fs'
import path from 'node:path'

const source = process.env.NADOC_JOIN_VERIFY_DESIGN
const fixture = source ? JSON.parse(readFileSync(source, 'utf8')) : null

test.use({ deviceScaleFactor: 0.5, trace: 'off', viewport: { width: 1920, height: 1100 } })
test('saved joined document offers all tethers when Move/Rotate opens before selection', async ({ page }) => {
  test.skip(!source, 'Set NADOC_JOIN_VERIFY_DESIGN to verify a saved design in an isolated workspace')
  test.setTimeout(240000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  copyFileSync(source, path.join(process.env.SCRYWRITE_TEST_WORKSPACE, 'T-junction.nadoc'))
  await page.goto('/?doc=e2e-joined-document')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.lib-file-row').filter({ hasText: 'T-junction' }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(id => window.__nadocTest?.store.getState().currentDesign?.id === id, fixture.id)
  const ids = fixture.cluster_transforms.map(c => c.id)
  const info = await page.evaluate(async () => (await import('/src/api/client.js')).getFlexibleConnections())
  expect(info.connections.length).toBe(fixture.flexible_connections.length)
  for (const id of ids) expect(info.gates[id].gate).toBe(true)
  // Exercise the user's menu path, not the pre-targeted test entry point.
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-translate-rotate').click()
  for (const id of ids) {
    await page.evaluate(async id => {
      const { store } = await import('/src/state/store.js')
      const item = { kind: 'cluster', id }
      store.setState({ selection: { context: 'design', level: 'cluster', items: [item], primary: item } })
    }, id)
    const pivot = page.locator('#mr-pivot-sel')
    await expect(pivot).toBeEnabled()
    await expect(pivot.locator('option[value="ssdna"]')).toHaveCount(1)
    await pivot.selectOption('ssdna')
    await expect(page.getByText('Constrained: drag the cluster — ssDNA tethers & connections won’t overstretch', { exact: true }).last()).toBeVisible()
    const resolved = await page.evaluate(async id => {
      const t = window.__nadocTest
      const api = await import('/src/api/client.js')
      const { buildTetherPayload } = await import('/src/scene/flex_relax.js')
      const info = await api.getFlexibleConnections()
      const p = buildTetherPayload(info.connections, id, t.store.getState().currentDesign, t.getDesignRenderer().getBackboneEntries())
      return { count: p.connections.length, resolved: p.connections.every(c => p.resolveWorldPos(c.movingKey) && p.resolveWorldPos(c.fixedKey)) }
    }, id)
    expect(resolved.count).toBe(fixture.flexible_connections.length)
    expect(resolved.resolved).toBe(true)
  }
  expect(errors).toEqual([])
})

test('Autoscaffold routes the saved joined document and retains all flexible bonds', async ({ page }) => {
  test.skip(!source, 'Set NADOC_JOIN_VERIFY_DESIGN to verify a saved design in an isolated workspace')
  test.setTimeout(240000)
  copyFileSync(source, path.join(process.env.SCRYWRITE_TEST_WORKSPACE, 'T-junction.nadoc'))
  await page.goto('/?doc=e2e-joined-autoscaffold')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.lib-file-row').filter({ hasText: 'T-junction' }).click()
  await page.waitForFunction(id => window.__nadocTest?.store.getState().currentDesign?.id === id, fixture.id)
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-item-tools .submenu-item').filter({ has: page.locator('#menu-routing-scaffold-ends') }).hover()
  await page.locator('#menu-routing-scaffold-ends').click()
  await expect(page.locator('#autoscaffold-modal')).toBeVisible()
  await page.locator('input[name="as-mode"][value="seamed"]').check()
  const responsePromise = page.waitForResponse(r => r.url().includes('/design/auto-scaffold-seamed') && r.request().method() === 'POST')
  await page.locator('#as-run').click()
  const response = await responsePromise
  console.log('Autoscaffold HTTP', response.status())
  expect(response.status(), await response.text()).toBe(200)
  await page.waitForFunction(() => {
    const d = window.__nadocTest.store.getState().currentDesign
    return d.strands.filter(s => s.strand_type === 'scaffold' && !s.is_reference).length === 1
  })
  const routed = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
  expect(routed.forced_ligations).toEqual(fixture.forced_ligations)
  expect(routed.cluster_transforms).toEqual(fixture.cluster_transforms)
  const info = await page.evaluate(async () => (await import('/src/api/client.js')).getFlexibleConnections())
  expect(info.connections).toHaveLength(fixture.flexible_connections.length)
  for (const id of fixture.cluster_transforms.map(c => c.id)) expect(info.gates[id].gate).toBe(true)
  // The same menu path must still expose constrained movement after rerouting.
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-translate-rotate').click()
  await page.evaluate(async id => {
    const { store } = await import('/src/state/store.js')
    const item = { kind: 'cluster', id }
    store.setState({ selection: { context: 'design', level: 'cluster', items: [item], primary: item } })
  }, fixture.cluster_transforms[1].id)
  const pivot = page.locator('#mr-pivot-sel')
  await expect(pivot).toBeEnabled()
  await expect(pivot.locator('option[value="ssdna"]')).toHaveCount(1)
  await pivot.selectOption('ssdna')
  await expect(page.getByText('Constrained: drag the cluster — ssDNA tethers & connections won’t overstretch', { exact: true }).last()).toBeVisible()
})

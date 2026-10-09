import { expect, test } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Only __e2e__ named parts/autosaves/project stores are persisted; the existing
// global teardown removes them on success, failure and timeout. No source files.
test('right-click attachment selects only overhangs and commits one fitted feature', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('response', async response => {
    if (response.url().includes('/attach-overhang')) console.log('Attachment response', response.status(),
      response.ok() ? 'ok' : await response.text())
  })
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__nanoparticle_attach')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  const pid = await page.evaluate(async () => {
    const t = window.__nadocTest
    const design = structuredClone(t.store.getState().currentDesign)
    design.helices = [{ id: 'target', axis_start: { x: 14, y: 3, z: 0 }, axis_end: { x: 14, y: 3, z: 5.78 }, length_bp: 18 }]
    design.strands = [{ id: 'target-strand', strand_type: 'staple', sequence: 'GGCGACTGTGCTACTTAT',
      domains: [{ helix_id: 'target', start_bp: 0, end_bp: 17, direction: 'FORWARD', overhang_id: 'target_3p' }] }]
    design.overhangs = [{ id: 'target_3p', helix_id: 'target', strand_id: 'target-strand', sequence: 'GGCGACTGTGCTACTTAT' }]
    await t.nanoparticles.importDesign(JSON.stringify(design))
    const { nanoparticle_id: id } = await t.nanoparticles.create(10)
    await t.nanoparticles.conjugation.apply(id, { scheme: 'direct_thiol', sequence: 'ATAAGTAGCACAGTCGCC', count: 1, attach_end: '5p', seed: 3 })
    t.applyCameraPoseForTest({ position: [7, 4, 55], target: [7, 1, 2] })
    return id
  })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getOverhangBeadScreenPositions().length)).toBeGreaterThan(0)
  const before = await page.evaluate(() => ({ count: window.__nadocTest.store.getState().currentDesign.feature_log.length,
    filters: window.__nadocTest.store.getState().selectableTypes }))
  const point = await page.evaluate(id => window.__nadocTest.nanoparticles.screenPosition(id), pid)
  await page.mouse.click(point.x, point.y, { button: 'right' })
  await page.getByRole('button', { name: 'Attach to overhang', exact: true }).click()
  expect(await page.evaluate(() => window.__nadocTest.store.getState().selectableTypes.overhangs)).toBe(true)
  expect(await page.evaluate(() => window.__nadocTest.store.getState().selectableTypes.strands)).toBe(false)
  // Let the selection/sidebar layout settle before projecting a world point.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect.poll(() => page.evaluate(() => {
    const p = window.__nadocTest.getOverhangBeadScreenPositions().find(p => p.id === 'target_3p')
    return p && document.elementFromPoint(p.x, p.y)?.id === 'canvas'
  }), { timeout: 60000 }).toBe(true)
  const target = await page.evaluate(() => window.__nadocTest.getOverhangBeadScreenPositions().find(p => p.id === 'target_3p'))
  const canvas = page.locator('#canvas')
  const bounds = await canvas.boundingBox()
  await canvas.click({ position: { x: target.x - bounds.x, y: target.y - bounds.y }, timeout: 60000 })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1)?.op_kind), { timeout: 30000 }).toBe('nanoparticle-attach-overhang')
  const result = await page.evaluate(() => {
    const s = window.__nadocTest.store.getState()
    return { count: s.currentDesign.feature_log.length, version: s.currentDesign.nanoparticle_connection_versions[0], filters: s.selectableTypes }
  })
  expect(result.count).toBe(before.count + 1)
  expect(result.version.residual_nm).toBeLessThan(0.02)
  expect(result.filters).toEqual(before.filters)
  expect(errors).toEqual([])
})

test('regenerated 4NP attachment history loads and displays', async ({ page }) => {
  const root = fileURLToPath(new URL('../../', import.meta.url))
  const fixture = `${root}.development-artifacts/np-attachment-review/generated.nadoc`
  test.skip(!existsSync(fixture), 'Optional local generator audit artifact')
  test.setTimeout(300000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?doc=__e2e__np-attach-4np')
  await page.waitForFunction(() => window.__nadocTest?.nanoparticles)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__np-attach-4np')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(content => window.__nadocTest.nanoparticles.importDesign(content), readFileSync(fixture, 'utf8'))
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentGeometry?.length > 1000)
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [30, 140, 70], target: [30, 0, 20] }))
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered().length)).toBe(4)
  const residuals = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.nanoparticle_connection_versions.filter(v => v.applied).map(v => v.residual_nm))
  expect(residuals).toHaveLength(4)
  expect(Math.max(...residuals)).toBeLessThan(0.02)
  // Deliberately retained review evidence; all authored/autosaved parts have
  // __e2e__ names and use the global failure-safe teardown.
  await page.locator('#canvas').screenshot({ path: `${root}.development-artifacts/np-attachment-review/generated-view.png` })
  await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  await expect(page.locator('#fl-rail .fl-autogenerated-dot')).toHaveCount(33)
  await expect(page.locator('#fl-rail .fl-autogenerated-connection')).toHaveCount(32)
  const dot = page.locator('#fl-rail .fl-autogenerated-dot').first()
  await dot.scrollIntoViewIfNeeded()
  await dot.hover()
  await expect(dot).toHaveAttribute('title', 'This feature was autogenerated.')
  await expect(dot).toHaveCSS('background-color', 'rgb(242, 140, 69)')
  await page.screenshot({ path: `${root}.development-artifacts/np-attachment-review/autogenerated-rail.png` })
  expect(errors).toEqual([])
})

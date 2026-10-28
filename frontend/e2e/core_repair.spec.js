import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'

const endpoint = 'http://127.0.0.1:8004/api'
const invoke = (page, method, ...args) => page.evaluate(async ({ method, args }) =>
  (await import('/src/api/client.js'))[method](...args), { method, args })
const paths = { bend: ['affected_helix_ids', 0], cluster_op: ['cluster_id'], routing: ['helix_id'] }
const read = (value, path) => path.reduce((object, token) => object[token], value)

for (const family of Object.keys(paths)) test(`core repair ${family}: private review, cancel, apply and reopen`, async ({ page, request }) => {
  test.setTimeout(120000)
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const original = await f.browser(), path = paths[family]
    const feature = original.design.feature_log.find(row => family === 'routing' ? row.id === 'selected-parent'
      : row.id === (family === 'bend' ? 'edited-feature' : 'selected-transform'))
    const child = family === 'routing' ? feature.children[0] : null
    const values = design => {
      const row = design.feature_log.find(row => row.id === feature.id)
      return family === 'bend' ? row.op_snapshot : family === 'routing' ? row.children[0].params : row
    }
    const replacement = family === 'cluster_op' ? original.design.cluster_transforms[0].id : original.design.helices[0].id
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const open = async () => {
      await page.getByRole('button', { name: /^(?:Check \/ repair recipe|Repair · saved proposal)$/ }).first().click()
      const panel = page.getByRole('dialog').filter({ hasText: 'Check and repair part recipe' })
      await expect(panel.getByRole('button', { name: 'Reload saved proposal', exact: true })).toBeEnabled()
      return panel
    }
    const select = async panel => {
      await panel.getByLabel('Feature to repair').selectOption(JSON.stringify([feature.id, child?.id ?? null]))
      await panel.locator(`[data-repair-path='${JSON.stringify(path)}']`).getByRole('button', { name: 'Find replacements', exact: true }).click()
      await panel.getByRole('button').filter({ hasText: `(${replacement})` }).click()
    }
    let panel = await open()
    await panel.getByRole('button', { name: 'Check published recipe', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Inspect failing input', exact: true }).first()).toBeVisible({ timeout: 15000 })
    await expect(page.locator('#fl-list [data-history-status="error"]')).toHaveCount(1)
    const beforeCancel = await f.checkpoint()
    await select(panel)
    await panel.getByRole('button', { name: 'Close', exact: true }).click()
    expect(await f.checkpoint()).toEqual(beforeCancel)
    panel = await open()
    await select(panel)
    await panel.getByRole('button', { name: 'Save proposal', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Evaluate proposal', exact: true })).toBeEnabled()
    await panel.getByRole('button', { name: 'Close', exact: true }).click()
    await invoke(page, 'saveDesign', f.file)
    await invoke(page, 'loadDesign', f.file)
    panel = await open()
    await expect(panel.locator('.part-repair__proposal li')).toHaveCount(1)
    await panel.getByRole('button', { name: 'Evaluate proposal', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeEnabled({ timeout: 15000 })
    const beforeReview = await f.checkpoint(), geometry = (await f.browser()).geometry
    const timings = []
    for (let cycle = 0; cycle < 3; cycle++) {
      const started = Date.now()
      const reply = page.waitForResponse(response => /\/features\/evaluation\/jobs\/[^/]+\/comparison$/.test(response.url()))
      await panel.getByRole('button', { name: 'Compare authored geometry', exact: true }).click()
      const response = await reply
      expect(response.ok(), await response.text()).toBe(true)
      const packet = await response.json()
      expect(packet.projection_version).toBe(2)
      expect(packet.coverage.complete).toBe(true)
      const comparison = panel.getByRole('region', { name: 'Private proposal comparison' })
      await expect(comparison.locator('canvas')).toBeVisible()
      timings.push(Date.now() - started)
      await comparison.getByRole('button', { name: 'Fit comparison', exact: true }).click()
      await comparison.locator('canvas').press('ArrowRight')
      if (family === 'bend' && cycle === 0 && process.env.NADOC_HISTORY_E2E_VISUAL === '1') {
        await page.screenshot({ path: `${f.root}/playwright/core-repair.png` })
        console.log(`FH26 visual review: ${f.root}/playwright/core-repair.png`)
        await page.waitForTimeout(20000)
      }
      await comparison.getByRole('button', { name: 'Close comparison', exact: true }).click()
      await expect(comparison.locator('canvas')).toHaveCount(0)
      expect(await f.checkpoint()).toEqual(beforeReview)
    }
    console.log(`FH26 comparison ${family} request/display ms: ${JSON.stringify(timings)}`)
    expect((await f.browser()).geometry).toEqual(geometry)
    await panel.getByRole('button', { name: 'Cancel evaluation', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeDisabled()
    expect(await f.checkpoint()).toEqual(beforeReview)
    await panel.getByRole('button', { name: 'Evaluate proposal', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeEnabled({ timeout: 15000 })
    const beforeApply = await f.checkpoint(), started = Date.now()
    await panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true }).click()
    await expect.poll(async () => read(values((await f.browser()).design), path)).toBe(replacement)
    console.log(`FH26 apply ${family} request/adopt ms: ${Date.now() - started}`)
    expect((await f.checkpoint()).history).toHaveLength(beforeApply.history.length + 1)
    await panel.getByRole('button', { name: 'Close', exact: true }).click()
    await invoke(page, 'undo')
    expect(read(values((await f.browser()).design), path)).toBe('missing-core-target')
    await invoke(page, 'redo')
    await invoke(page, 'saveDesign', f.file)
    await invoke(page, 'loadDesign', f.file)
    expect(read(values((await f.browser()).design), path)).toBe(replacement)
    const proof = await request.get(`${endpoint}/__e2e__/history/proof`, { headers: f.headers })
    expect((await proof.json()).status).toBe('verified')
  }, `repair-core-${family}`, { pauseRendering: true })
})

test('core repair upstream delete lists the full affected chain and requires explicit cascade', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const original = await f.browser(), before = await f.checkpoint()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const openDelete = async () => {
      await page.locator('#fl-list [title="Delete this feature"]').first().click()
      const dialog = page.getByRole('dialog').filter({ hasText: 'Delete dependent features?' })
      await expect(dialog).toBeVisible()
      return dialog
    }
    let dialog = await openDelete()
    await expect(dialog.locator('li')).toHaveCount(3)
    expect(await f.checkpoint()).toEqual(before)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    expect(await f.browser()).toEqual(original)
    dialog = await openDelete()
    await dialog.getByRole('button', { name: 'Delete all (4)', exact: true }).click()
    await expect.poll(async () => (await f.browser()).design.feature_log.map(row => row.id)).toEqual(['independent-extrusion'])
    expect((await f.checkpoint()).history).toHaveLength(before.history.length + 1)
    await invoke(page, 'undo')
    expect((await f.browser()).design.feature_log.map(row => row.id)).toEqual(original.design.feature_log.map(row => row.id))
    await invoke(page, 'redo')
    await invoke(page, 'saveDesign', f.file)
    await invoke(page, 'loadDesign', f.file)
    const proof = await request.get(`${endpoint}/__e2e__/history/proof`, { headers: f.headers })
    expect((await proof.json()).status).toBe('verified')
  }, 'repair-core-cascade', { pauseRendering: true })
})

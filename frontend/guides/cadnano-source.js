import { expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { designState } from './workflow.js'

// Prerequisite specimen creation uses the ordinary editor and export dialog.
// It is outside the tutorial/count, and its complete source part is published
// and replayed alongside the imported part by the generator.
export async function createCadnanoSource(page, output) {
  await page.goto('/?doc=__e2e__6hb84-source')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__6hb84-source')
  await page.locator('input[name="new-lattice-type"][value="HONEYCOMB"]').check()
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.locator('#menu-item-tools').hover()
  await page.locator('#menu-tools-extrude').click()
  await page.locator('#extrude-from').selectOption('XY')
  await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
  for (const [row, col] of [[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]]) {
    const point = await page.evaluate(([r,c]) => window.__nadocTest.getSliceCellScreenPositions().find(p => p.row === r && p.col === c), [row,col])
    expect(point).toBeTruthy()
    expect(await page.evaluate(p => document.elementFromPoint(p.x,p.y)?.id, point)).toBe('canvas')
    await page.mouse.click(point.x,point.y)
  }
  await page.locator('#extrude-next').click()
  await page.locator('#slice-length').fill('63')
  await page.locator('#slice-extrude-btn').click()
  const routing = async () => {
    await page.locator('#menu-item-tools').hover()
    await page.locator('#menu-item-tools .submenu-item').filter({ hasText: /^Routing/ }).hover()
  }
  await routing()
  await page.locator('#menu-routing-scaffold-ends').click()
  await page.locator('input[name="as-mode"][value="seamed"]').check()
  await page.locator('#as-run').click()
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(2)
  await routing()
  await page.locator('#menu-routing-full-autostaple').click()
  await page.getByRole('dialog', { name: 'Autostaple method', exact: true }).getByRole('button', { name: 'OK', exact: true }).click()
  await expect.poll(async () => (await designState(page)).feature_log.length, { timeout: 120000 }).toBe(3)
  await expect.poll(async () => {
    try { return JSON.parse(await readFile(path.join(process.env.NADOC_WORKSPACE, '__e2e__6hb84-source.nadoc'), 'utf8')).feature_log.length }
    catch { return 0 }
  }).toBe(3)
  const source = await designState(page)
  expect(source.helices).toHaveLength(6)
  expect(source.helices.every(h => h.length_bp === 84)).toBe(true)
  expect(source.strands.filter(s => s.strand_type === 'scaffold')).toHaveLength(1)
  const downloaded = page.waitForEvent('download')
  await page.locator('#menu-item-export > button').click()
  await page.locator('#menu-file-export-cadnano').click()
  const lossReview = page.getByRole('button', { name: 'Export with listed losses', exact: true })
  await expect(lossReview).toBeVisible()
  const losses = await page.getByRole('dialog', { name: 'caDNAno export compatibility' }).innerText()
  await lossReview.click()
  const file = path.join(output, '6hb84-cadnano.json')
  await (await downloaded).saveAs(file)
  await writeFile(path.join(output, 'export-review.json'), JSON.stringify({
    source_part: 'source.nadoc', export: '6hb84-cadnano.json',
    operation: 'Export → caDNAno → Export with listed losses',
    review_text: losses, initial_extrusion_bp: 63, routed_length_bp: 84,
    helix_lengths_bp: source.helices.map(h => h.length_bp),
    source_commands: source.feature_log.map(f => f.op_kind),
  }, null, 2))
  return file
}

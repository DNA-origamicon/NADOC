/** All designs use __e2e__ names in the isolated smoke workspace. No exports.
 * Workspace/session artifacts are removed by global teardown; the launcher
 * removes its entire scratch directory, including traces and screenshots. */
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

for (const editor of ['3d', 'cadnano']) test(`${editor}: scaffold scope, No, Yes, and default`, async ({ page, request }, testInfo) => {
  test.setTimeout(60000)
  const errors = trackConsoleErrors(page)
  const api = process.env.NADOC_E2E_API_BASE
  const doc = `__e2e__sequence_scope_${editor}`
  const headers = { 'X-NADOC-Doc': doc }
  const created = await request.post(`${api}/api/design/bundle`, { headers, data: {
    name: doc, cells: [[0,0],[0,3],[0,6]], length_bp: 42, lattice_type: 'HONEYCOMB', ligate_adjacent: false,
  } })
  expect(created.ok()).toBe(true)
  const design = (await created.json()).design
  const grouped = await request.post(`${api}/api/design/cluster`, { headers, data: {
    name: 'Sequence target', helix_ids: design.helices.slice(0,2).map(h => h.id),
  } })
  expect(grouped.ok()).toBe(true)
  const cluster = (await grouped.json()).design.cluster_transforms.at(-1).id
  const read = async () => (await (await request.get(`${api}/api/design`, { headers })).json()).design
  await page.goto(editor === '3d' ? `/?doc=${doc}&readiness=simulation` : `/cadnano-editor.html?doc=${doc}`)
  if (editor === '3d') {
    await page.waitForFunction(() => window.__nadocTest?.getDesignRenderer()?.getBackboneEntries()?.length > 0)
    await page.evaluate(id => window.__nadocTest.selectRefsForTest([{ kind: 'cluster', id }]), cluster)
    await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
  } else {
    await page.waitForFunction(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design?.strands?.length > 0)
  }
  await page.locator('#menu-seq-assign-scaffold').evaluate(el => el.click())
  const target = page.getByLabel('Scaffold sequence target', { exact: true })
  if (editor === '3d') await expect(target).toHaveValue(`cluster:${cluster}`)
  else await target.selectOption(`cluster:${cluster}`)
  const dialog = editor === '3d' ? page.locator('.modal__overlay').filter({ has: target }) : page.locator('#assign-scaffold-modal')
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  const confirm = page.locator('.modal__overlay').filter({ hasText: 'Multiple scaffolds detected, assign sequence to all?' })
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: 'No', exact: true }).click()
  await expect(target).toBeVisible()
  expect((await read()).strands.filter(s => s.strand_type === 'scaffold').every(s => !s.sequence)).toBe(true)
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  await confirm.getByRole('button', { name: 'Yes', exact: true }).click()
  await expect(target).toBeHidden()
  await expect.poll(async () => (await read()).strands.filter(s => s.strand_type === 'scaffold' && s.sequence).length).toBe(2)
  const result = await read()
  expect(result.feature_log.at(-1).params.cluster_id).toBe(cluster)
  // An explicit strand overrides the cluster and needs no bulk confirmation.
  await page.locator('#menu-seq-assign-scaffold').evaluate(el => el.click())
  const third = design.strands.filter(s => s.strand_type === 'scaffold')[2].id
  await target.selectOption(`strand:${third}`)
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect.poll(async () => (await read()).strands.filter(s => s.strand_type === 'scaffold' && s.sequence).length).toBe(3)
  if (editor === '3d') await page.evaluate(() => window.__nadocTest.selectRefsForTest([]))
  await page.locator('#menu-seq-assign-scaffold').evaluate(el => el.click())
  await expect(target).toHaveValue('default')
  await page.screenshot({ path: testInfo.outputPath('sequence-scope.png') })
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(errors, errors.join('\n')).toEqual([])
})

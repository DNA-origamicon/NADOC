import { test, expect } from '@playwright/test'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'

const projects = []
test.afterAll(async () => cleanupProjectArtifacts(process.env.NADOC_WORKSPACE || '../workspace', projects))

test('experimental scaffold start sweeps and applies through the real menu', async ({ page }) => {
  test.setTimeout(60000)
  const doc = '__e2e__scaffold-register'
  const headers = { 'X-NADOC-Doc': doc }
  const base = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002') + '/api'
  const domain = (helix_id, start_bp, end_bp) => ({ helix_id, start_bp, end_bp, direction: end_bp >= start_bp ? 'FORWARD' : 'REVERSE' })
  const sequence = 'AGGCTAACATCGGATCTTGCGATACGATTCGCGATTACGCTAGCTATCGACATGCTAGCTAACGTACCGGATCTAGGCTAACGATTCGACGTAGCATGCTAGGACTACGTATCGATAGCTAACGATCG'
  expect(sequence.length).toBe(128)
  const design = { id: '__e2e__scaffold-register-design', metadata: { name: '__e2e__scaffold-register' }, lattice_type: 'HONEYCOMB',
    helices: [0, 1].map(i => ({ id: `h${i}`, axis_start: { x: i*2.5, y: 0, z: 0 }, axis_end: { x: i*2.5, y: 0, z: 21.76 }, length_bp: 64, bp_start: 0 })),
    strands: [{ id: 'scaf', strand_type: 'scaffold', sequence,
      domains: [domain('h0', 9, 63), domain('h1', 63, 0), domain('h0', 0, 8)] },
    ...[0,16,32,48].map(i => ({ id: `s${i}`, strand_type: 'staple', domains: [domain('h0', i+15, i), domain('h1', i, i+15)] }))] }
  projects.push(design.id)
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.getByRole('button', { name: 'File', exact: true }).hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__scaffold-register-boot')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  projects.push(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.id))
  const imported = await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    return api.importDesign(content)
  }, JSON.stringify(design))
  expect(imported).toBeTruthy()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.getByRole('button', { name: 'Help', exact: true }).hover()
  await page.locator('#menu-help-experimental').hover()
  await page.locator('#menu-help-scaffold-register').click()
  const dialog = page.getByRole('dialog').filter({ hasText: 'Scaffold sequence start — experimental' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Evaluate all starts' }).click()
  await expect(dialog.getByRole('status')).toContainText('eligible starts')
  // Select any evaluated nonzero candidate even if this fixture's current
  // register happens to tie for best after thermodynamic parameter changes.
  const selector = dialog.getByLabel('Scaffold start candidate')
  const choice = await selector.locator('option').evaluateAll(options => options.find(o => o.value !== '0').value)
  await selector.selectOption(choice)
  await dialog.getByRole('button', { name: 'Apply selected start' }).click()
  await expect(dialog.getByRole('status')).toContainText('Undo restores')
  const updated = await (await page.request.get(`${base}/design`, { headers })).json()
  const current = updated.design || updated
  expect(current.strands.find(s => s.id === 'scaf').sequence).toBe(sequence)
  expect(current.feature_log.at(-1).label).toBe('Optimize scaffold sequence start (circular)')
})

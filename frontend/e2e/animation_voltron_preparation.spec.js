import { test, expect } from '@playwright/test'
import { readFile, writeFile, cp, rm, access } from 'node:fs/promises'
import path from 'node:path'

// Persistent inventory: one __e2e__ design and two PRIVATE job directory copies,
// including any frame/bundle caches created by the API. afterAll removes the exact
// copies even after a test failure; global teardown also removes the design.
// Workspace autosave is intercepted (no project revision artifacts).
// Session persistence is disabled by the standard isolated-server config.
const workspace = path.resolve('../workspace')
const filename = '__e2e__VoltronCoreScad_preparation.nadoc'
const ids = { '35f1a833c203': '__e2e__voltron_prep_a', 'b0ce0d0aa40b': '__e2e__voltron_prep_b' }
const created = []
test.beforeAll(async () => {
  const session = await readFile(path.resolve('../.nadoc-test-session'), 'utf8').catch(() => '')
  test.skip(Number(session.split('\n')[0]) <= Date.now() / 1000 || !session, 'Requires a user-opened just test-session')
  const design = JSON.parse(await readFile(path.join(workspace, 'VoltronCoreScad.nadoc'), 'utf8'))
  for (const [original, id] of Object.entries(ids)) {
    const dest = path.join(workspace, 'oxdna_jobs', id)
    await expect(access(dest)).rejects.toThrow()
    created.push(dest)
    await cp(path.join(workspace, 'oxdna_jobs', original), dest, { recursive: true })
    const job = JSON.parse(await readFile(path.join(dest, 'job.json'), 'utf8'))
    Object.assign(job, { job_id: id, parent_job_id: null, design_source_path: filename, archived: false, archive_path: null })
    await writeFile(path.join(dest, 'job.json'), JSON.stringify(job))
  }
  for (const animation of design.animations) for (const kf of animation.keyframes) {
    if (ids[kf.trajectory_job_id]) kf.trajectory_job_id = ids[kf.trajectory_job_id]
  }
  created.push(path.join(workspace, filename))
  await writeFile(path.join(workspace, filename), JSON.stringify(design))
})
test.afterAll(async () => {
  for (const entry of created) await rm(entry, { recursive: true, force: true })
  for (const entry of created) await expect(access(entry)).rejects.toThrow()
})

test('VoltronCoreScad prepares its saved trajectories without a modal and accepts cancellation', async ({ page }) => {
  test.setTimeout(900_000)
  page.setDefaultTimeout(10_000)
  const errors = []
  page.on('pageerror', e => { errors.push(e.message); console.log('VOLTRON browser error:', e.message) })
  const requests = []
  page.on('request', r => { if (/trajectory|frames-atomistic/.test(r.url())) requests.push(r.url()) })
  await page.route('**/api/design/save-workspace', route => route.fulfill({ json: { path: filename, identity_disposition: 'confirmed' } }))
  await page.goto(`/?doc=__e2e__voltron-preparation&open=${filename}`)
  await expect.poll(() => page.evaluate(() => window.__nadocTest?.store.getState().currentDesign?.helices?.length || 0), { timeout: 180_000 }).toBeGreaterThan(0)
  // Software WebGL takes seconds per draw at this scale. Keep the real model and
  // reconstruction pipeline, but exclude raster cost from background UX assertions.
  await page.evaluate(() => { window.__nadocTest.scene.visible = false })
  await page.locator('.left-tab-btn[data-tab="scene"]').click({ timeout: 180_000 })
  console.log('VOLTRON design loaded')
  await page.evaluate(() => window.__nadocTest.setRepresentation('oxdna'))
  if (!await page.locator('#animation-panel-body').isVisible()) await page.locator('#animation-panel-heading').click()
  const status = page.locator('[data-role="trajectory-download-status"]')
  await expect(status).toHaveCount(2)
  await expect.poll(() => status.allTextContents(), { timeout: 300_000 }).toEqual([
    'Trajectory preview frames ready', 'Trajectory preview frames ready',
  ])
  console.log('VOLTRON coordinate readiness:', await status.allTextContents())
  await page.evaluate(() => window.__nadocTest.setRepresentation('vdw'))
  await expect(page.locator('progress[aria-label="Trajectory frame preparation"]').first()).toBeVisible()
  await page.locator('#anim-playpause-btn').click()
  await expect(page.locator('[data-role="animation-preparation"]')).toBeVisible()
  await expect(page.locator('#op-progress')).not.toBeVisible()
  // Opening a menu does not reset the animation panel's preview state.
  await page.getByRole('button', { name: 'Help', exact: true }).click({ timeout: 5000 })
  await page.keyboard.press('Escape')
  console.log('VOLTRON heavy progress:', await status.allTextContents())
  await page.locator('[data-role="animation-preparation"] button').click()
  await expect(page.locator('#anim-playpause-btn')).toBeEnabled({ timeout: 30_000 })
  await expect(page.locator('#op-progress')).not.toBeVisible()
  console.log('VOLTRON requests:', requests.length, 'browser errors:', errors)
  expect(errors).toEqual([])
})

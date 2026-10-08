import { test, expect } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { trackConsoleErrors } from './helpers/scene_harness.js'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'

const reviewProjectIds = []
test.afterEach(async ({ page }) => {
  // Open Part may assign an independent identity to a copied file. Include
  // that live identity as well as the source IDs, even after a failed assertion.
  try { reviewProjectIds.push(await page.evaluate(() => window.__nadocTest?.viewerDiagnostic().designId)) } catch {}
  await cleanupProjectArtifacts(fileURLToPath(new URL('../../workspace/', import.meta.url)), reviewProjectIds.splice(0))
})

// Persistence inventory: __e2e__ workspace parts/project revisions are removed
// by global-teardown; session caching is disabled by the isolated smoke config.
// The .nadoc and screenshot below are retained review evidence under the
// gitignored .development-artifacts directory. No other files are written.
test('four fixed, uneven-height particles on a square-lattice curved rod', async ({ page, request }) => {
  test.setTimeout(300_000)
  const api = `${process.env.NADOC_E2E_API_BASE}/api`
  const doc = crypto.randomUUID()
  const headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page)
  await page.goto(`/?doc=${doc}`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.fill('#new-design-name', '__e2e__curved_generator')
  await page.locator('input[name="new-lattice-type"][value="SQUARE"]').check()
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await expect.poll(async () => (await request.get(`${api}/design`, { headers })).status()).toBe(200)
  let response
  const refresh = async () => page.evaluate(docId => {
    const channel = new BroadcastChannel('nadoc-design')
    channel.postMessage({ type: 'design-changed', source: 'generator-e2e', docId })
    channel.close()
  }, doc)
  const centers = [[0, 0, 0], [28, 1, 0], [28, 0, 30], [0, 0, 30]].map(([x, y, z]) => [30 + .8*x + .6*z, 12 + y, -10 - .6*x + .8*z])
  for (const [x, y, z] of centers) {
    response = await request.post(`${api}/design/nanoparticles/gold-nanospheres`, { headers, data: { diameter_nm: 10 } })
    expect(response.ok()).toBe(true)
    const { nanoparticle_id } = await response.json()
    response = await request.patch(`${api}/design/nanoparticles/${nanoparticle_id}`, { headers, data: { pose: [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1] } })
    expect(response.ok()).toBe(true)
  }
  await refresh()
  await page.waitForTimeout(500)
  await page.locator('#menu-bar > .menu-item').filter({ has: page.getByRole('button', { name: 'Help', exact: true }) }).hover()
  await page.locator('#menu-help-generate-design').click()
  await expect(page.getByLabel('Design shape')).toBeEnabled({ timeout: 120_000 })
  await page.getByLabel('Design shape').selectOption('curved-rod')
  await expect(page.getByLabel('Pathing')).toHaveClass('select')
  await expect(page.getByLabel('Pathing')).toHaveValue('colocalized')
  await expect(page.getByLabel('New duplex length (bp)')).toHaveClass('input')
  await page.getByRole('button', { name: 'Calculate design', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Generate in current loadout' })).toBeEnabled({ timeout: 120_000 })
  console.log('[generator] plan ready')
  await expect(page.getByLabel('Particle visit order')).toHaveValue(/\d, \d, \d, \d/)
  const generatedResponse = page.waitForResponse(r => r.request().method() === 'POST' && r.url().includes('/design/generate-design') && !r.url().includes('/plan'), { timeout: 240_000 })
  const progressStages = []
  page.on('response', async response => {
    if (response.url().includes('/generate-design/progress/') && response.ok()) {
      try {
        const stage = (await response.json()).stage
        if (stage !== progressStages.at(-1)) console.log(`[generator] ${stage}`)
        progressStages.push(stage)
      } catch {}
    }
  })
  await page.getByRole('button', { name: 'Generate in current loadout' }).click()
  await expect(page.getByLabel('Design generation progress')).toBeVisible()
  await expect.poll(() => progressStages.length, { timeout: 30_000 }).toBeGreaterThan(0)
  const progressEvidence = fileURLToPath(new URL('../../.development-artifacts/generator-standard-operations/', import.meta.url))
  await mkdir(progressEvidence, { recursive: true })
  await page.screenshot({ path: path.join(progressEvidence, 'generation-progress.png') })
  const generated = await generatedResponse
  console.log('[generator] response received')
  expect(generated.ok(), await generated.text()).toBe(true)
  await expect(page.getByRole('status').filter({ hasText: 'Added 4 connections' })).toBeVisible({ timeout: 120_000 })
  console.log('[generator] response applied')
  const final = await (await request.get(`${api}/design`, { headers })).json()
  expect(final.design.deformations.length).toBeGreaterThan(0)
  expect(final.design.feature_log.some(e => e.feature_type === 'deformation')).toBe(true)
  expect(final.design.feature_log.some(e => ['curve-path', 'cluster-pose', 'nanoparticle-connection-relax'].includes(e.op_kind))).toBe(false)
  expect(progressStages.some(stage => stage.includes('attachment'))).toBe(true)
  await expect(page.getByLabel('Design generation progress')).toHaveJSProperty('value', 1)
  expect(final.design.nanoparticle_connection_versions).toHaveLength(4)
  for (let i = 0; i < 4; i++) {
    const pose = final.design.nanoparticles[i].pose.values
    expect([pose[3], pose[7], pose[11]]).toEqual(centers[i])
    expect(final.design.nanoparticle_connection_versions[i].residual_nm).toBeLessThan(1e-8)
  }
  const evidence = fileURLToPath(new URL('../../.development-artifacts/curved-generator/', import.meta.url))
  await mkdir(evidence, { recursive: true })
  const saved = path.join(evidence, 'four-particle-square.nadoc')
  await writeFile(saved, await (await request.get(`${api}/design/export`, { headers })).text())
  await page.keyboard.press('Escape')
  response = await request.post(`${api}/design/load`, { headers, data: { path: saved } })
  expect(response.ok()).toBe(true)
  await refresh()
  await page.waitForTimeout(500)
  await page.locator('#canvas').click()
  await page.keyboard.press('f')
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(evidence, 'four-particle-square.png') })
  expect(errors).toEqual([])
})

// Optional local visual review of the user's arrangement, regenerated in an
// isolated scratch session. Input copies have fresh IDs and __e2e__ names;
// global teardown removes their workspace files and project revision stores.
// Only screenshots are retained in the existing review-evidence directory.
// Run separately with -g review and NADOC_E2E_REVIEW_PATHING set to a comma-
// separated list of modes; these full reloads exceed the regular smoke budget.
test('review equatorial pathing and compact generator controls', async ({ page }) => {
  test.setTimeout(300_000)
  const modes = (process.env.NADOC_E2E_REVIEW_PATHING || '').split(',').filter(Boolean)
  test.skip(!modes.length, 'Explicit local visual review only')
  const evidence = fileURLToPath(new URL('../../.development-artifacts/curved-generator-pathing/', import.meta.url))
  let designs
  try { designs = await Promise.all(modes.map(async mode => [mode, JSON.parse(await readFile(path.join(evidence, `${mode}.nadoc`), 'utf8'))])) }
  catch { test.skip(true, 'Local review designs are generated separately'); return }
  const doc = crypto.randomUUID()
  const errors = trackConsoleErrors(page)
  const failedResponses = []
  page.on('response', response => {
    if (response.status() >= 400) failedResponses.push({ status: response.status(), path: new URL(response.url()).pathname })
  })
  const scratch = fileURLToPath(new URL('../../workspace/playwright_tests/', import.meta.url))
  await mkdir(scratch, { recursive: true })
  for (const [mode, design] of designs) {
    Object.assign(design, { id: crypto.randomUUID(), feature_log: [], loadouts: [], active_loadout_id: null, last_editable_loadout_id: null })
    reviewProjectIds.push(design.id)
    Object.assign(design.metadata, { name: `__e2e__pathing_${mode}`, identity_last_known_path: `__e2e__pathing_${mode}.nadoc`, identity_confirmed_at: '' })
    const input = path.join(scratch, `__e2e__pathing_${mode}.nadoc`)
    await writeFile(input, JSON.stringify(design))
    // Use the real Open Part workflow so the autosave path follows the new file.
    await page.goto(`/?doc=${doc}&open=${encodeURIComponent(`playwright_tests/__e2e__pathing_${mode}.nadoc`)}`)
    await page.waitForFunction(() => {
      let ready = false
      window.__nadocTest?.scene?.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ready = true })
      return ready && window.__nadocTest.nanoparticles.rendered().length === 4
    }, null, { timeout: 30_000 })
    await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({
      position: [170, 190, 220], target: [32, 0, 35], up: [0, 1, 0], fov: 40,
    }))
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(evidence, `${mode}.png`) })
    await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({
      position: [32, 240, 18], target: [32, 0, 18], up: [0, 0, -1], fov: 40,
    }))
    await page.waitForTimeout(300)
    await page.screenshot({ path: path.join(evidence, `${mode}-top.png`) })
  }
  await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
  await page.locator('#menu-bar > .menu-item').filter({ has: page.getByRole('button', { name: 'Help', exact: true }) }).hover()
  await page.locator('#menu-help-generate-design').click()
  await page.screenshot({ path: path.join(evidence, 'generator-dialog-loading.png') })
  await expect(page.getByLabel('Design shape')).toBeEnabled({ timeout: 90_000 })
  await expect(page.getByRole('status').filter({ hasText: 'Neither 7249 nor 8064' })).toBeVisible()
  await page.getByLabel('Design shape').selectOption('curved-rod')
  await page.getByLabel('Pathing').selectOption('interior')
  await expect(page.getByLabel('Pathing')).toHaveAttribute('title', /equators/)
  await expect(page.locator('.modal__body p')).toHaveCount(0)
  await page.getByRole('button', { name: 'Calculate design', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Generate in current loadout' })).toBeEnabled({ timeout: 90_000 })
  await page.screenshot({ path: path.join(evidence, 'generator-dialog.png') })
  // The initial Platform calculation is intentionally unreachable for this
  // wide arrangement; changing to Curved rod must recover to a usable plan.
  expect(failedResponses).toEqual([{ status: 422, path: '/api/design/generate-design/plan' }])
  expect(errors).toHaveLength(1)
  expect(errors[0]).toContain('422 (Unprocessable Entity)')
})

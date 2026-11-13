import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { rm } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persistent artifacts: __e2e__ part + its project history (global teardown),
// isolated Vite credentials (global teardown); session cache is disabled by config.
// Guard staging is removed by publish's finally and this failure-safe hook.
const root = fileURLToPath(new URL('../../', import.meta.url))
const savedPath = fileURLToPath(new URL('../../workspace/__e2e__zoom-bases.nadoc', import.meta.url))
test.afterEach(async () => { await rm(`${savedPath}.agent-writing`, { force: true }) })
test('zoom volumes retain individual extension and crossover-insert selections across reload', async ({ page }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page)
  const doc = 'e2e-zoom-bases'
  await loadScaffoldedPart(page, { doc, name: 'zoom-bases', extraQuery: '&debug=1' })
  const apiRoot = `${process.env.NADOC_E2E_API_BASE}/api`
  const headers = { 'X-NADOC-Doc': doc }
  const added = await page.request.post(`${apiRoot}/design/helix-at-cell`, { headers, data: { row: 0, col: 1, length_bp: 200 } })
  expect(added.ok()).toBe(true)
  const { design } = await (await page.request.get(`${apiRoot}/design`, { headers })).json()
  expect((await page.request.post(`${apiRoot}/design/scaffold-domain-paint`, { headers,
    data: { helix_id: design.helices[1].id, lo_bp: 0, hi_bp: 199 } })).ok()).toBe(true)
  const keys = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    await api.getDesign(); await api.getGeometry()
    const strands = store.getState().currentDesign.strands
    await api.forcedLigation(strands[0].id, strands[1].id)
    let d = store.getState().currentDesign
    const ligation = d.forced_ligations[0]
    if (!ligation) throw new Error('Forced ligation was not recorded')
    await api.patchForcedLigationExtraBases(ligation.id, 'ATC')
    d = store.getState().currentDesign
    await api.createStrandExtension(d.strands[0].id, 'five_prime', { sequence: 'TT' })
    const ext = store.getState().currentGeometry.find(n => n.extension_id)
    if (!ext) throw new Error('Extension geometry missing')
    const { baseKey } = await import('/src/scene/base_ref.js')
    document.querySelector('.right-tab-btn[data-tab="visualization"]').click()
    return [baseKey(ext), `__xb__:${ligation.id}:1`]
  })
  for (const key of keys) {
    await page.evaluate(async key => {
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      createSelectionController({ store: window.__nadocTest.store }).replace([{ kind: 'base', key }])
    }, key)
    await page.locator('#zoom-volume-add').click()
    const row = page.locator('.zoom-volume-row').last()
    await expect(row.locator('[data-control="status"]')).toContainText('1 bases')
    for (const representation of ['beads', 'full', 'cylinders', 'ballstick', 'stick', 'surface', 'vdw']) {
      await row.locator('[data-control="representation"]').selectOption(representation)
      await expect(row.locator('[data-control="status"]')).toContainText('1 bases', { timeout: 60000 })
      await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries.at(-1).triangles), { message: `${key} in ${representation}` }).toBeGreaterThan(0)
    }
  }
  const second = page.locator('.zoom-volume-row').nth(1)
  await second.locator('summary').click()
  await second.locator('[data-control="position"]').selectOption('bl')
  const first = page.locator('.zoom-volume-row').first()
  await first.locator('[data-control="name"]').fill('Crossover detail')
  await first.locator('[data-control="name"]').press('Tab')
  await first.locator('summary').click()
  await first.locator('[data-control="title-size"]').selectOption('32')
  await first.locator('[data-control="title-font"]').selectOption('Georgia')
  const title = page.locator('.zoom-volume-title').first()
  await expect(title).toHaveText('Crossover detail')
  await expect(title).toHaveCSS('font-size', '32px')
  await expect(title).toHaveCSS('font-family', 'Georgia')
  await expect(title).toHaveCSS('height', '48px')
  if (process.env.NADOC_INSET_TITLE_SCREENSHOT) await page.locator('.zoom-volume-inset').first().screenshot({ path: process.env.NADOC_INSET_TITLE_SCREENSHOT })
  const exportedTitles = await page.evaluate(async () => {
    const { settleZoomVolumes, drawZoomVolumes } = await import('/src/scene/zoom_volume_export.js')
    await settleZoomVolumes(window.__nadocTest.scene)
    const output = document.createElement('canvas'); output.width = 1600; output.height = 1000
    const ctx = output.getContext('2d'), titles = []
    const fill = ctx.fillText.bind(ctx)
    ctx.fillText = (text, ...args) => { titles.push({ text, font: ctx.font }); fill(text, ...args) }
    drawZoomVolumes(window.__nadocTest.scene, ctx, output.width, output.height)
    return titles
  })
  expect(exportedTitles[0].text).toBe('Crossover detail')
  expect(exportedTitles[0].font).toContain('Georgia')
  expect(exportedTitles).toHaveLength(2)
  // Save/reopen through the application retains exact base keys and construction history.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    // Join the serialized metadata queue before saving the audited fixture.
    await api.saveZoomVolumes(window.__nadocTest.store.getState().currentDesign.zoom_volumes)
    await api.saveDesign('workspace/__e2e__zoom-bases.nadoc')
  })
  execFileSync('uv', ['run', 'python', '-c', `
import hashlib, sys
from pathlib import Path
from backend.core.models import Design
from scripts.agent_structure_guard import publish
path = Path(sys.argv[1])
raw = path.read_bytes()
publish(Design.model_validate_json(raw), path,
        expected_existing_sha256=hashlib.sha256(raw).hexdigest())
`, savedPath], { cwd: root, timeout: 60000 })
  await page.evaluate(async () => {
    await (await import('/src/api/client.js')).loadDesign('workspace/__e2e__zoom-bases.nadoc')
  })
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries.map(e => e.targets[0].refs[0].key))).toEqual(keys)
  await expect(page.locator('.zoom-volume-title').first()).toHaveText('Crossover detail')
  await expect(page.locator('.zoom-volume-title').first()).toHaveCSS('font-size', '32px')
  await expect(page.locator('.zoom-volume-title').first()).toHaveCSS('font-family', 'Georgia')
  expect(errors).toEqual([])
})

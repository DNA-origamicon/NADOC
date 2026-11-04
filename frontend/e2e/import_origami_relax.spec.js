import { test, expect } from '@playwright/test'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'
const root = path.resolve(import.meta.dirname, '../..')
const workspace = path.join(root, 'workspace')
const projectIds = []
test.afterAll(async () => { await cleanupProjectArtifacts(workspace, projectIds) })

for (const format of ['cadnano', 'scadnano']) {
  test(`optional relaxation through the ${format} file picker`, async ({ page }) => {
    test.setTimeout(120000)
    const cadnanoPath = path.join(workspace, 'Experimental/D003/registered.cadnano.json')
    test.skip(format === 'cadnano' && !existsSync(cadnanoPath), 'Requires the local D003 reconstruction')
    const stem = `__e2e__auto-relax-${format}`
    const source = format === 'cadnano' ? JSON.parse(await readFile(cadnanoPath, 'utf8')) : {
      version: '0.19.0', grid: 'square',
      helices: [{ grid_position: [0, 0], max_offset: 32 }, { grid_position: [9, 0], max_offset: 32 }],
      strands: [{ is_scaffold: true, domains: [
        { helix: 0, forward: true, start: 0, end: 32 },
        { helix: 1, forward: false, start: 0, end: 32 },
      ] }],
    }
    source.name = stem
    await page.goto(`/?doc=${stem}`)
    await page.waitForFunction(() => !!window.__nadocTest?.store)
    await page.locator('#menu-bar > .menu-item').filter({ has: page.locator(`#menu-file-import-${format}`) }).hover()
    const chooserPromise = page.waitForEvent('filechooser')
    await page.locator(`#menu-file-import-${format}`).click()
    const chooser = await chooserPromise
    await chooser.setFiles({ name: `${stem}.${format === 'cadnano' ? 'json' : 'sc'}`, mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(source)) })
    const modal = page.locator('.origami-import-options')
    await expect(modal.locator('input')).not.toBeChecked()
    await modal.locator('input').check()
    const responsePromise = page.waitForResponse(r => r.url().endsWith(`/design/import/${format}`) && r.request().method() === 'POST')
    await modal.getByRole('button', { name: 'Import design', exact: true }).click()
    const response = await responsePromise
    const result = await response.json()
    expect(response.ok()).toBe(true)
    // A prefixed manifest survives until global teardown so it can remove any
    // project revisions written after afterAll, even when later assertions fail.
    projectIds.push(result.design.id)
    console.log('IMPORT_RELAX_PROJECT', result.design.id)
    await writeFile(path.join(workspace, `${stem}.nadoc`), JSON.stringify(result.design))
    expect(result.relaxation.status).toBe('applied')
    expect(result.relaxation.clashes.after.overlapping_body_pairs).toBe(0)
    expect(result.relaxation.rigid_bundle_sizes).toEqual(format === 'cadnano' ? [22, 22, 22, 22] : [1, 1])
    await page.waitForFunction(id => window.__nadocTest.store.getState().currentDesign?.id === id, result.design.id)
    // The normal Save As dialog follows import. The manifest already retains
    // the exact returned document; cancel this dialog without changing it.
    await page.getByPlaceholder('filename').waitFor({ state: 'visible' })
    await page.getByRole('button', { name: 'Cancel', exact: true }).last().click()
    await page.waitForFunction(() => window.__nadocTest.store.getState().currentGeometry?.length > 0)
    await page.evaluate(() => {
      const points = window.__nadocTest.store.getState().currentGeometry.map(n => n.backbone_position)
      const lo = [0, 1, 2].map(i => Math.min(...points.map(p => p[i])))
      const hi = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])))
      const target = lo.map((x, i) => (x + hi[i]) / 2)
      const distance = 2 * Math.max(...hi.map((x, i) => x - lo[i]))
      window.__nadocTest.applyCameraPoseForTest({ position: [target[0] + distance, target[1], target[2]], target, up: [0, 1, 0] })
    })
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
    const evidence = path.join(root, '.development-artifacts/import-relaxation')
    await mkdir(evidence, { recursive: true })
    await page.screenshot({ path: path.join(evidence, `${format}.png`) })
    // Recent raw sources must offer the same opt-in; cancelling preserves the
    // already imported document and its fitted poses.
    await page.getByRole('menubar').getByRole('button', { name: 'File', exact: true }).hover()
    const recent = page.locator('.submenu-item').filter({ has: page.locator('#recent-files-submenu') })
    await recent.hover()
    await page.getByRole('button').filter({ hasText: `${stem}.${format === 'cadnano' ? 'json' : 'sc'}` }).last().click()
    await expect(page.locator('.origami-import-options')).toBeVisible()
    await page.locator('.origami-import-options .modal__close').click()
    expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.id)).toBe(result.design.id)
  })
}

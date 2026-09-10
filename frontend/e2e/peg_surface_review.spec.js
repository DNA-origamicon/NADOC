import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))
const design = execFileSync(`${root}/.venv/bin/python`, ['-c', 'from scripts.create_peg_surface_review import make_review_design; print(make_review_design().model_dump_json())'], { cwd: root, encoding: 'utf8' })

test('saved PEG surface restores beads, updates CM trajectory, and persists setup', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route(/\/(oxdna|md|mrdna|lammps)\/jobs(?:\?.*)?$/, route =>
    route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.continue())
  await page.goto('/?doc=e2e-peg-surface-review')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, design)
  await expect(page.locator('#oxdna-peg-enable')).toBeChecked()
  await expect.poll(() => page.evaluate(() => window.__nadocSurfStrands.debug().pegBeads)).toBe(36)
  const frame = await page.evaluate(() => {
    window.__nadocSurfStrands.applyPegFrame([{ helix_id: 'cap0', bp: 1000000, cm_position: [1,2,3], backbone_position: [9,9,9] }])
    let xyz = null
    window.__nadocTest.scene.traverse(object => {
      if (object.name === 'peg-surface-beads') xyz = Array.from(object.children[0].instanceMatrix.array.slice(12,15))
    })
    return xyz
  })
  expect(frame).toEqual([1,2,3])
  await page.locator('#oxdna-peg-store').evaluate(el => el.click())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.metadata.peg_surface?.surface_strands?.segments)).toBe(8)
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.metadata.peg_surface.anchors)).toEqual([{kind:'strand',id:'probe_forward'}])
  expect(errors).toEqual([])
})

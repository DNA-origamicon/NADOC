import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Existing parts are READ ONLY: autosave is disabled before boot; save routes
// are blocked; the isolated backend's session cache is disabled. Annotation
// metadata is edited only in its memory. The File > New empty host uses the
// __e2e__ prefix and is removed with project history by global teardown.
// Vite credentials and Playwright outputs are removed by global teardown/reporter.
const root = path.resolve(process.cwd(), '..')
async function openReadOnly(page, file) {
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.route('**/api/design/save**', route => route.fulfill({ status: 409, json: { detail: 'Read-only test' } }))
  await page.goto('/?doc=__e2e__annotation-branches')
  await page.waitForFunction(() => !!window.__nadocTest)
  // File > New enables the editor shell; the empty host stays in memory.
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__annotation-branch-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name)).toBe('__e2e__annotation-branch-host')
  await page.evaluate(async file => {
    const api = await import('/src/api/client.js')
    document.getElementById('welcome-screen').classList.add('hidden')
    if (file.includes('Voltron')) window.__nadocTest.setRepresentation('beads')
    await api.loadDesign(file)
  }, file)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length ?? 0), { timeout: 60000 }).toBeGreaterThan(0)
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
}
async function annotateSelection(page, text) {
  const column = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await column.locator('.anno-add').click()
  const card = column.locator('.anno-card').last()
  await card.locator('[data-field="useSelection"]').click()
  await card.locator('[data-field="text"]').fill(text)
  return card
}
test('dispersed bases and domains become multiple branches in the running editor', async ({ page }) => {
  test.setTimeout(120000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const errors = trackConsoleErrors(page)
  await openReadOnly(page, path.join(root, 'Examples/2hb_xover_atoms_test.nadoc'))
  await page.locator('#select-filter-trigger').click()
  await page.locator('#select-filter .sf-btn[data-key="base"]').click()
  const candidates = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(1000))
  const canvas = await page.locator('#canvas').boundingBox()
  const visible = candidates.filter(p => p.x > canvas.x + 300 && p.x < canvas.x + canvas.width - 340 && p.y > canvas.y + 80 && p.y < canvas.y + canvas.height - 60)
  expect(visible.length).toBeGreaterThan(1)
  let first = null
  for (const candidate of visible) {
    await page.mouse.click(candidate.x, candidate.y)
    if (await page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.length === 1)) { first = candidate; break }
  }
  expect(first).not.toBeNull()
  // Retry actual raycast picks: a projected bead may be occluded or move a pixel
  // while the fitted camera settles. Never substitute a programmatic base pick.
  const farCandidates = visible.filter(p => Math.hypot(p.x - first.x, p.y - first.y) > 80)
    .sort((a, b) => Math.hypot(b.x - first.x, b.y - first.y) - Math.hypot(a.x - first.x, a.y - first.y))
  expect(farCandidates.length).toBeGreaterThan(0)
  for (const candidate of farCandidates.slice(0, 20)) {
    await page.keyboard.down('Control')
    await page.mouse.click(candidate.x, candidate.y)
    await page.keyboard.up('Control')
    if (await page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.length === 2)) break
  }
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.length)).toBe(2)
  const card = await annotateSelection(page, 'Separated bases')
  await expect(card.locator('.anno-target')).toContainText('2 bases')
  await expect(card.locator('[data-field="multiAnchor"]')).not.toBeChecked()
  await expect(page.locator('.nadoc-anno-leaders circle')).toHaveCount(1)
  await card.locator('[data-field="multiAnchor"]').check()
  await expect(page.locator('.nadoc-anno-leaders circle')).toHaveCount(2)
  await page.evaluate(() => {
    const t = window.__nadocTest, d = t.store.getState().currentDesign
    t.selectRefsForTest(d.strands.slice(0, 2).map(s => ({ kind: 'domain', strandId: s.id, domainIndex: 0 })))
  })
  await card.locator('[data-field="useSelection"]').click()
  await expect(card.locator('.anno-target')).toContainText('2 domains')
  await expect(page.locator('.nadoc-anno-leaders circle')).toHaveCount(2)
  await card.locator('[data-field="multiAnchor"]').uncheck()
  await expect(page.locator('.nadoc-anno-leaders circle')).toHaveCount(1)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.annotations?.at(-1)?.multi_anchor)).toBe(false)
  expect(errors).toEqual([])
})
test('Voltron X3–X15 each receive a branch from one annotation', async ({ page }) => {
  // This large local file includes saved silhouette highlights; software WebGL
  // on CI is substantially slower than the normal GPU viewport.
  test.setTimeout(300000)
  const file = path.join(root, 'workspace/VoltronCoreArmV2.nadoc')
  test.skip(!existsSync(file), 'Local user example is not checked in')
  const hash = () => createHash('sha256').update(readFileSync(file)).digest('hex')
  const before = hash(), errors = trackConsoleErrors(page)
  try {
    await page.setViewportSize({ width: 1800, height: 1100 })
    await openReadOnly(page, file)
    const selected = await page.evaluate(async () => {
      const t = window.__nadocTest, d = t.store.getState().currentDesign
      const { buildStrandDisplayIdMap } = await import('/src/ui/design_display_labels.js')
      const labels = buildStrandDisplayIdMap(d.strands)
      const strands = d.strands.filter(s => /^X(?:[3-9]|1[0-5])$/.test(labels.get(s.id)))
      t.selectRefsForTest(strands.map(s => ({ kind: 'strand', id: s.id })))
      const ids = new Set(strands.map(s => s.id))
      const points = t.store.getState().currentGeometry.filter(n => ids.has(n.strand_id)).map(n => n.backbone_position)
      const lo = [0, 1, 2].map(i => Math.min(...points.map(p => p[i])))
      const hi = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])))
      const target = lo.map((v, i) => (v + hi[i]) / 2), distance = Math.max(10, ...hi.map((v, i) => v - lo[i])) * 2
      t.applyCameraPoseForTest({ target, position: [target[0] + distance * .7, target[1] + distance * .5, target[2] + distance] })
      return strands.map(s => ({ label: labels.get(s.id), color: s.color }))
    })
    expect(selected).toHaveLength(13)
    expect(selected.every(s => s.color === '#c050d0')).toBe(true)
    const card = await annotateSelection(page, 'X3–X15 purple strands')
    await expect(card.locator('.anno-target')).toContainText('13 strands')
    const leaderId = await card.getAttribute('data-annotation-id')
    await expect(card.locator('[data-field="multiAnchor"]')).not.toBeChecked()
    await expect(page.locator(`[data-annotation-leaders="${leaderId}"] circle`)).toHaveCount(1)
    await card.locator('[data-field="multiAnchor"]').check()
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.annotations?.at(-1)?.text)).toBe('X3–X15 purple strands')
    const branches = await page.evaluate(async () => {
      const t = window.__nadocTest, d = t.store.getState().currentDesign
      const { annotationTargetGroups } = await import('/src/scene/annotation_branches.js')
      const annotation = d.annotations.at(-1)
      const entries = t.store.getState().currentGeometry.map(n => ({ nuc: n, pos: { x: n.backbone_position[0], y: n.backbone_position[1], z: n.backbone_position[2] } }))
      return annotationTargetGroups(annotation.refs, d, entries).length
    })
    expect(branches).toBe(13)
    const id = await card.getAttribute('data-annotation-id')
    await expect.poll(() => page.locator(`[data-annotation-leaders="${id}"] circle`).count(), { timeout: 30000 }).toBeGreaterThanOrEqual(13)
    console.log('Voltron X3–X15 branches:', await page.locator(`[data-annotation-leaders="${id}"] circle`).count())
    await card.locator('[data-field="multiAnchor"]').uncheck()
    await expect(page.locator(`[data-annotation-leaders="${id}"] circle`)).toHaveCount(1)
    expect(errors).toEqual([])
  } finally { expect(hash()).toBe(before) }
})

import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFile } from 'node:fs/promises'

// Read-only fixture load and transient selection only. No saved designs,
// downloads or custom screenshots; standard Playwright output is the only artifact.
test('spreadsheet follows domain and individual-base selections in the running app', async ({ page }) => {
  const designPath = path.resolve(process.cwd(), '..', 'Examples', '26hb_platform_v3.nadoc')
  const design = JSON.parse(await readFile(designPath, 'utf8'))
  const strand = design.strands.find(s => s.domains?.some(d => !d.overhang_id && Math.abs(d.end_bp - d.start_bp) > 2))
  const domainIndex = strand.domains.findIndex(d => !d.overhang_id && Math.abs(d.end_bp - d.start_bp) > 2)
  const d = strand.domains[domainIndex]
  test.setTimeout(60_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async file => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(file)
  }, designPath)
  // API-only loading intentionally avoids library identity registration/writes.
  // Reveal the spreadsheet as the normal File/Open host does after loading.
  await page.evaluate(() => {
    window.__nadocTest.pauseViewerRenderingForTest()
    document.getElementById('spreadsheet-panel').style.display = ''
  })
  await page.locator('#sheet-toggle').click()
  await expect(page.locator(`tr[data-strand-id="${strand.id}"]`)).toBeVisible()
  await page.evaluate(ref => window.__nadocTest.selectRefsForTest([ref]), { kind: 'domain', strandId: strand.id, domainIndex })
  const marks = page.locator(`tr[data-strand-id="${strand.id}"] .sheet-seq-selected-base`)
  const helix = design.helices.find(h => h.id === d.helix_id)
  const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
  const length = hi - lo + 1 + (helix.loop_skips ?? [])
    .filter(ls => ls.bp_index >= lo && ls.bp_index <= hi).reduce((sum, ls) => sum + ls.delta, 0)
  await expect(marks).toHaveCount(length)
  await page.evaluate(ref => window.__nadocTest.selectRefsForTest([ref]), {
    kind: 'base', key: `${d.helix_id}:${d.start_bp}:${d.direction}`,
  })
  await expect(marks).toHaveCount(1)
  await page.evaluate(() => window.__nadocTest.selectRefsForTest([]))
  await expect(marks).toHaveCount(0)
  expect(errors).toEqual([])
})

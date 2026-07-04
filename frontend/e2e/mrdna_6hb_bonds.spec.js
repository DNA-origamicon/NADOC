/**
 * Playwright troubleshooting: overstretched backbone bonds in the mrDNA deform
 * display of 6hb_2xT.  Loads the design, applies the live /display payload through
 * the real renderer, measures consecutive same-helix backbone bond lengths, and
 * screenshots.  Ideal backbone P-P ≈ 0.67 nm; anything > ~1.3 nm is a stretched
 * stick in the view.
 */

import { test, expect } from '@playwright/test'

const JOB_ID = 'b4aa0eccf111'   // completed 200k-fine job for 6hb_2xT

test('6hb_2xT mrDNA deform display backbone bond stretch report', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('#library-panel-mount')).toBeVisible()
  const item = page.locator('#library-panel-mount').getByText('6hb_2xT', { exact: false }).first()
  if (!(await item.count())) test.skip(true, 'workspace design 6hb_2xT not present')
  await item.click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 15_000 })
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.designRenderer)
  await page.waitForTimeout(1200)

  const report = await page.evaluate(async (jobId) => {
    const res = await fetch(`/api/mrdna/jobs/${jobId}/display`)
    if (!res.ok) return { error: `display ${res.status}` }
    const data = await res.json()
    const positions = Array.isArray(data) ? data : data.positions
    window.__NADOC_DBG__.designRenderer.applyFemPositions(positions)

    // consecutive same-helix, same-direction backbone bonds
    const by = {}
    for (const p of positions) {
      if (p.helix_id === '__xb__') continue
      const k = `${p.helix_id}|${p.direction}`
      ;(by[k] ||= {})[p.bp_index] = p.backbone_position
    }
    const lens = []
    for (const bpmap of Object.values(by)) {
      const bps = Object.keys(bpmap).map(Number).sort((a, b) => a - b)
      for (let i = 1; i < bps.length; i++) {
        if (bps[i] - bps[i - 1] !== 1) continue
        const a = bpmap[bps[i - 1]], b = bpmap[bps[i]]
        lens.push(Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]))
      }
    }
    lens.sort((a, b) => b - a)
    const over = (t) => lens.filter((x) => x > t).length
    return { n: lens.length, max: lens[0], median: lens[Math.floor(lens.length / 2)],
             over1: over(1.0), over1_3: over(1.3), over2: over(2.0), worst: lens.slice(0, 8) }
  }, JOB_ID)

  await page.waitForTimeout(600)
  await page.screenshot({ path: 'e2e/bench_results/mrdna_6hb_display.png' })

  console.log('6hb_2xT deform backbone bonds:', JSON.stringify(report))
  expect(report.error).toBeFalsy()
})

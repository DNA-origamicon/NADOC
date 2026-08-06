/**
 * View ▸ Adjust for Extra Bases — verifies the toggle picks the MD-measured
 * spacing for the design's largest extra-base count and actually moves helices.
 *
 * Two designs, identical apart from their crossover inserts:
 *   6hbx100_noT → no inserts   → 2.45 nm (the no-insert relaxed baseline)
 *   6hbx100_2xT → TT inserts   → 2.55 nm
 *
 * The spacing assertion reads `expanded_spacing.js`'s own `[EXPAND]` log rather
 * than inferring a pitch from bead positions: the log states the chosen target
 * directly, so a wrong table lookup cannot hide behind geometry noise. Bead
 * movement is asserted separately (lateral bbox grows, then returns) so a log
 * line alone can never pass this.
 *
 * Fixtures are `__e2e__`-prefixed copies (global teardown removes them); the
 * originals are never opened, so nothing can autosave onto the user's designs.
 */

import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const WORKSPACE = path.resolve(fileURLToPath(import.meta.url), '../../../workspace')

// Fixture stems carry no leading underscores on purpose: the library listing
// hides `__`-prefixed files, so the usual `__e2e__` convention would make the
// row unclickable here. They are deleted by this spec's own teardown instead.
const CASES = [
  { fixture: 'e2exbnoT', label: 'no inserts', expectNm: 2.45 },
  { fixture: 'e2exb2xT', label: 'TT inserts', expectNm: 2.55 },
]

const NATURAL_NM = 2.25

// Copies of 6hbx100_noT / 6hbx100_2xT. Created here and removed after the run so
// the originals are never opened — the app autosaves an opened design, and these
// are the user's real fixtures.
const SOURCES = { e2exbnoT: '6hbx100_noT.nadoc', e2exb2xT: '6hbx100_2xT.nadoc' }

function makeFixtures() {
  for (const [stem, src] of Object.entries(SOURCES)) {
    fs.copyFileSync(path.join(WORKSPACE, src), path.join(WORKSPACE, `${stem}.nadoc`))
  }
}

function removeFixtures() {
  for (const stem of Object.keys(SOURCES)) {
    fs.rmSync(path.join(WORKSPACE, `${stem}.nadoc`), { force: true })
  }
}

async function openDesign(page, doc, design) {
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  const needsPick = await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)
  if (needsPick) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${design}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
  await page.waitForFunction(() => {
    let n = 0
    window.__nadocTest?.scene?.traverse(o => {
      if (o.isInstancedMesh && o.name === 'backboneSpheres') n += o.count
    })
    return n > 0
  }, null, { timeout: 60_000 })
  await page.waitForTimeout(500)
}

/**
 * Lateral (X/Y) extent of every backbone bead, in the design's own frame.
 *
 * Read straight off `instanceMatrix.array` (column-major; translation at 12/13/14)
 * so this needs no THREE handle on `window`. Local space is deliberate: the
 * spacing offsets are applied in the same space, and before/after are compared
 * in that one frame, so a root transform cannot skew the comparison.
 */
async function lateralExtent(page, meshName = 'backboneSpheres') {
  return page.evaluate((name) => {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, n = 0
    window.__nadocTest.scene.traverse(o => {
      if (!o.isInstancedMesh || o.name !== name) return
      const a = o.instanceMatrix.array
      for (let i = 0; i < o.count; i++) {
        const x = a[i * 16 + 12], y = a[i * 16 + 13]
        if (x < minX) minX = x;  if (x > maxX) maxX = x
        if (y < minY) minY = y;  if (y > maxY) maxY = y
        n++
      }
    })
    return { x: maxX - minX, y: maxY - minY, n }
  }, meshName)
}

/**
 * Mean position of the extra-base beads. These are NOT moved by the offset map
 * directly — they ride the crossover arc, whose endpoints are the offset helix
 * nucleotides (`unfold_view._updateArcPositions` → `updateExtraBaseArc`). That
 * indirection is the thing most likely to silently not fire, which would strand
 * the inserts between helices that had already spread apart.
 */
async function extraBaseCentroidSpread(page) {
  return page.evaluate(() => {
    let sx = 0, sy = 0, n = 0
    const pts = []
    window.__nadocTest.scene.traverse(o => {
      if (!o.isInstancedMesh || o.name !== 'xoverExtraBeads') return
      const a = o.instanceMatrix.array
      for (let i = 0; i < o.count; i++) {
        const x = a[i * 16 + 12], y = a[i * 16 + 13]
        pts.push([x, y]); sx += x; sy += y; n++
      }
    })
    if (!n) return { n: 0, rms: 0 }
    const cx = sx / n, cy = sy / n
    let s = 0
    for (const [x, y] of pts) s += (x - cx) ** 2 + (y - cy) ** 2
    return { n, rms: Math.sqrt(s / n) }
  })
}

async function toggleAdjust(page) {
  const viewMenu = page.locator('.menu-item').filter({ hasText: 'View' }).first()
  await viewMenu.hover()
  await page.click('#menu-view-extra-base-spacing')
  await page.waitForTimeout(700)   // 300 ms animation + settle
}

test.describe('View ▸ Adjust for Extra Bases', () => {
  test.beforeAll(makeFixtures)
  test.afterAll(removeFixtures)

  for (const { fixture, label, expectNm } of CASES) {
    test(`${label} → ${expectNm} nm`, async ({ page }) => {
    const errors = trackConsoleErrors(page)
    const logs = []
    page.on('console', m => { if (m.text().includes('[EXPAND]')) logs.push(m.text()) })

    await openDesign(page, `xbspace-${fixture}`, fixture)

    const before   = await lateralExtent(page)
    const xbBefore = await extraBaseCentroidSpread(page)

    await toggleAdjust(page)

    // The module logs the target it resolved — assert the table lookup directly.
    const onLog = logs.find(l => l.includes('extra-base ON'))
    expect(onLog, `no "[EXPAND] extra-base ON" log; saw: ${JSON.stringify(logs)}`).toBeTruthy()
    expect(onLog).toContain(`spacing=${expectNm.toFixed(2)} nm`)

    // The pill reflects the on state.
    await expect(page.locator('#menu-view-extra-base-spacing')).toHaveClass(/is-on/)

    // Helices really moved, and by about the lattice ratio. The bbox includes a
    // constant bead-radius margin on each side, so the observed growth is a
    // LOWER bound on the centre-span ratio — assert it lands between "moved at
    // all" and the exact ratio rather than pinning a value the margin skews.
    const on = await lateralExtent(page)
    const ratio = expectNm / NATURAL_NM
    for (const axis of ['x', 'y']) {
      expect(on[axis], `${axis} should grow`).toBeGreaterThan(before[axis] * 1.01)
      expect(on[axis], `${axis} should not exceed the lattice ratio`).toBeLessThanOrEqual(before[axis] * ratio + 0.01)
    }

    // The inserts must spread WITH the helices. On the 2xT design they exist;
    // on the noT control there are none, which the count assertion pins so a
    // silently-empty mesh cannot make this pass by accident.
    const xbOn = await extraBaseCentroidSpread(page)
    if (expectNm > 2.45) {
      expect(xbOn.n, 'the TT design must have extra-base beads').toBeGreaterThan(0)
      expect(xbOn.rms, 'inserts must spread with their helices')
        .toBeGreaterThan(xbBefore.rms * 1.01)
    } else {
      expect(xbOn.n, 'the control design must have no extra-base beads').toBe(0)
    }

    // Toggling off restores the as-built lattice exactly.
    await toggleAdjust(page)
    const off = await lateralExtent(page)
    expect(off.x).toBeCloseTo(before.x, 3)
    expect(off.y).toBeCloseTo(before.y, 3)
    await expect(page.locator('#menu-view-extra-base-spacing')).not.toHaveClass(/is-on/)

    expect(errors, `console errors: ${errors.join('\n')}`).toEqual([])
    })
  }
})

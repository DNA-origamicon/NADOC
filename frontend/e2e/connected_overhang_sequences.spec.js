import { test, expect } from '@playwright/test'

// Verifies: (1) connected overhangs appear in the sidebar Overhangs section with
// their sequences; (2) "show base sequences" renders base letters in BOTH 3D and
// the cadnano 2D editor. Fixture = two extruded overhangs + a ds linker + set
// sequences + assigned scaffold (built by the headless probe).
const FIXTURE = '/home/joshua/NADOC/workspace/playwright_tests/connected_overhangs_seq.nadoc'

async function letterInstanceCount(page) {
  return await page.evaluate(() => {
    const dbg = window.__NADOC_DBG__
    if (!dbg?.scene) return -1
    let total = 0
    dbg.scene.traverse(o => {
      if (o.name && o.name.startsWith('seqLabel_') && o.isInstancedMesh && o.visible) {
        total += o.count
      }
    })
    return total
  })
}

test('connected overhang sequences: sidebar + 3D + cadnano base labels', async ({ page }) => {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await page.goto('/')
  await page.waitForTimeout(1500)

  // Load the fixture into the tab's own doc context.
  await page.evaluate(async (p) => {
    const a = await import('/src/api/client.js')
    await a.loadDesign(p)
    await a.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await page.waitForTimeout(1500)

  // ── 1. Sidebar: open the Overhangs section, read the rows ──────────────────
  await page.evaluate(() => {
    document.getElementById('overhang-panel-heading')?.click()
  })
  await page.waitForTimeout(400)
  const seqInputs = await page.evaluate(() => {
    const list = document.getElementById('overhang-list')
    if (!list) return []
    return [...list.querySelectorAll('input')]
      .map(i => i.value)
      .filter(v => /^[ACGT]+$/.test(v))      // real-base values only
  })
  // Both overhang sequences should be present in the sidebar.
  expect(seqInputs).toContain('ACGTACGT')
  expect(seqInputs).toContain('TTTTGGGG')

  // ── 2. 3D base-sequence overlay ───────────────────────────────────────────
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    store.setState({ showSequences: true })
  })
  await page.waitForTimeout(800)
  const count3d = await letterInstanceCount(page)
  await page.screenshot({ path: 'e2e/screenshots/seq_overhang_3d.png', fullPage: true })
  expect(count3d).toBeGreaterThan(0)

  // ── 3. Cadnano editor base-sequence overlay ───────────────────────────────
  await page.evaluate(() => { document.getElementById('canvas')?.focus() })
  await page.keyboard.press('k')
  await page.waitForTimeout(2500)
  const cadnanoActive = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    return store.getState().cadnanoActive
  })
  expect(cadnanoActive).toBe(true)
  const countCad = await letterInstanceCount(page)
  await page.screenshot({ path: 'e2e/screenshots/seq_overhang_cadnano.png', fullPage: true })
  expect(countCad).toBeGreaterThan(0)   // sequences now render in cadnano too

  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})

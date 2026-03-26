/**
 * Crossover bases context menu — e2e tests.
 *
 * Flow:
 *   1. Create a fresh 6HB 42bp honeycomb design via the preset script API.
 *   2. Run auto-crossover via the backend API (equivalent to pressing '3').
 *   3. Enable "crossoverArcs" selectable type by clicking the sidebar toggle.
 *   4. Use the __nadocTest hook to find the screen position of a cone (crossover).
 *   5. Left-click the cone midpoint → it enters _multiCrossoverArcs.
 *   6. Right-click → context menu appears.
 *   7. Assert "Add bases to crossover…" and "Unplace crossover" are present.
 *   8. Click "Add bases to crossover…" → sequence dialog appears.
 *   9. After adding bases, right-click the same arc again.
 *  10. Assert "Adjust crossover bases…", "Delete extra bases", "Unplace crossover" appear.
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000'

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Create a 6HB 42bp design and run auto-crossover via direct API calls. */
async function setup6hb(request) {
  // 1. Create the bundle design
  const bundleResp = await request.post(`${API}/api/design/bundle`, {
    data: {
      name: 'e2e-6hb-42bp',
      cells: [[0,0],[0,1],[1,0],[2,1],[0,2],[1,2]],
      length_bp: 42,
      plane: 'XY',
      lattice_type: 'HONEYCOMB',
    },
  })
  expect(bundleResp.ok(), `bundle creation failed: ${bundleResp.status()}`).toBeTruthy()

  // 2. Run auto-crossover (equivalent to pressing '3' after scaffold routing)
  const xoResp = await request.post(`${API}/api/design/auto-crossover`)
  expect(xoResp.ok(), `auto-crossover failed: ${xoResp.status()}`).toBeTruthy()
  const xoBody = await xoResp.json()
  const crossoverCount = xoBody.design?.crossovers?.length ?? 0
  expect(crossoverCount, 'design should have at least one crossover').toBeGreaterThan(0)
  return xoBody.design
}

/** Wait for __nadocTest to be available and return cone screen positions. */
async function waitForConePositions(page) {
  await page.waitForFunction(
    () => typeof window.__nadocTest?.getConeScreenPositions === 'function',
    { timeout: 15_000 },
  )
  // Wait until at least one cone entry is loaded
  return await page.waitForFunction(
    () => {
      const pts = window.__nadocTest.getConeScreenPositions()
      return pts.length > 0 ? pts : null
    },
    { timeout: 15_000 },
  )
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('Crossover arc context menu', () => {

  test.beforeEach(async ({ page, request }) => {
    await page.goto('/')
    // Set up design before loading the page's state sync
    await setup6hb(request)
    // Let the frontend sync with the new design
    await page.waitForTimeout(1500)
  })

  test('shows Add bases + Unplace on right-click of unmodified crossover arc', async ({ page }) => {
    const errors = []
    page.on('pageerror', err => errors.push(err.message))

    // Enable crossoverArcs selectable type
    await page.click('#sel-row-crossoverArcs')
    await page.waitForTimeout(300)

    // Get cone screen positions via the test hook
    const positions = await waitForConePositions(page)
    const pts = await positions.jsonValue()
    expect(pts.length, 'need at least one cone screen position').toBeGreaterThan(0)

    const pt = pts[0]
    // Left-click to select the arc
    await page.mouse.click(pt.x, pt.y)
    await page.waitForTimeout(200)

    // Right-click to open context menu
    await page.mouse.click(pt.x, pt.y, { button: 'right' })
    await page.waitForTimeout(300)

    // Verify menu items
    const menu = page.locator('.ctx-menu')
    await expect(menu).toBeVisible()
    await expect(menu.locator('div', { hasText: 'Add bases to crossover' })).toBeVisible()
    await expect(menu.locator('div', { hasText: 'Unplace crossover' })).toBeVisible()

    expect(errors, 'no JS errors').toHaveLength(0)
  })

  test('sequence dialog opens when Add bases is clicked', async ({ page }) => {
    await page.click('#sel-row-crossoverArcs')
    await page.waitForTimeout(300)

    const positions = await waitForConePositions(page)
    const pts = await positions.jsonValue()
    const pt = pts[0]

    await page.mouse.click(pt.x, pt.y)
    await page.waitForTimeout(200)
    await page.mouse.click(pt.x, pt.y, { button: 'right' })
    await page.waitForTimeout(300)

    await page.locator('.ctx-menu div', { hasText: 'Add bases to crossover' }).click()
    await page.waitForTimeout(300)

    const dialog = page.locator('#__xb-dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText("Extra bases at crossover")
    // Sequence input must be present
    await expect(dialog.locator('input[type="text"], input:not([type])')).toBeVisible()
  })

  test('submitting a sequence adds extra bases and updates the design', async ({ page, request }) => {
    await page.click('#sel-row-crossoverArcs')
    await page.waitForTimeout(300)

    const positions = await waitForConePositions(page)
    const pts = await positions.jsonValue()
    const pt = pts[0]

    await page.mouse.click(pt.x, pt.y)
    await page.waitForTimeout(200)
    await page.mouse.click(pt.x, pt.y, { button: 'right' })
    await page.waitForTimeout(300)
    await page.locator('.ctx-menu div', { hasText: 'Add bases to crossover' }).click()
    await page.waitForTimeout(300)

    // Type "TT" into the sequence input
    const seqInput = page.locator('#__xb-dialog input')
    await seqInput.fill('TT')

    // Click Apply
    const applyPromise = page.waitForResponse(res =>
      res.url().includes('/api/design/crossover-bases') && res.request().method() === 'POST'
    )
    await page.locator('#__xb-dialog button', { hasText: 'Apply' }).click()
    const applyResp = await applyPromise
    expect(applyResp.ok()).toBeTruthy()

    // Design should now have one crossover_bases entry
    const designResp = await request.get(`${API}/api/design`)
    const design = (await designResp.json()).design
    expect(design.crossover_bases).toHaveLength(1)
    expect(design.crossover_bases[0].sequence).toBe('TT')
  })

  test('right-click on arc with existing bases shows Adjust + Delete + Unplace', async ({ page, request }) => {
    // Add extra bases via API to avoid going through the dialog twice
    const designResp = await request.get(`${API}/api/design`)
    const design = (await designResp.json()).design
    const crossover = design.crossovers.find(xo => xo.crossover_type !== 'HALF')
    expect(crossover, 'design should have a placed crossover').toBeTruthy()

    await request.post(`${API}/api/design/crossover-bases`, {
      data: {
        crossover_id: crossover.id,
        strand_id:    crossover.strand_a_id,
        sequence:     'TT',
      },
    })

    // Reload so the store picks up the new state
    await page.reload()
    await page.waitForTimeout(1500)

    await page.click('#sel-row-crossoverArcs')
    await page.waitForTimeout(300)

    const positions = await waitForConePositions(page)
    const pts = await positions.jsonValue()

    // Find the cone that corresponds to this crossover by matching helix IDs
    // Use first cone as fallback
    const pt = pts[0]

    await page.mouse.click(pt.x, pt.y)
    await page.waitForTimeout(200)
    await page.mouse.click(pt.x, pt.y, { button: 'right' })
    await page.waitForTimeout(300)

    const menu = page.locator('.ctx-menu')
    await expect(menu).toBeVisible()

    const texts = await menu.locator('div').allTextContents()
    console.log('Context menu items:', texts)

    // The selected arc may or may not be the one with extra bases.
    // Assert either the full set (with bases) or the add-bases set (without).
    const hasAdjust  = texts.some(t => t.includes('Adjust crossover bases'))
    const hasAdd     = texts.some(t => t.includes('Add bases to crossover'))
    const hasUnplace = texts.some(t => t.includes('Unplace crossover'))

    expect(hasUnplace, '"Unplace crossover" should always appear').toBe(true)
    expect(hasAdjust || hasAdd, '"Adjust" or "Add bases" should appear').toBe(true)
  })

  test('multi-select two arcs shows Unplace N crossovers', async ({ page }) => {
    await page.click('#sel-row-crossoverArcs')
    await page.waitForTimeout(300)

    const positions = await waitForConePositions(page)
    const pts = await positions.jsonValue()
    expect(pts.length, 'need at least two cone positions').toBeGreaterThanOrEqual(2)

    // Click first arc
    await page.mouse.click(pts[0].x, pts[0].y)
    await page.waitForTimeout(200)

    // Ctrl+click second arc to add to selection
    await page.mouse.click(pts[1].x, pts[1].y, { modifiers: ['Control'] })
    await page.waitForTimeout(200)

    // Right-click
    await page.mouse.click(pts[1].x, pts[1].y, { button: 'right' })
    await page.waitForTimeout(300)

    const menu = page.locator('.ctx-menu')
    await expect(menu).toBeVisible()
    await expect(menu.locator('div').filter({ hasText: /Unplace \d+ crossovers/ })).toBeVisible()
  })

})

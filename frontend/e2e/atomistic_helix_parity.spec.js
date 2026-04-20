/**
 * Atomistic rendering parity test.
 *
 * Compares the atomistic model for a REVERSE-parity helix at (0,1) against a
 * FORWARD-parity helix at (1,1).  In a correct implementation both should
 * produce visually equivalent D-DNA geometry (same handedness, same atom
 * distances from helix axis, same glycosidic bond lengths).
 *
 * Strategy:
 *   1. Create a design with a single helix at (0,1)  [REVERSE parity, (row+col)%2=1].
 *   2. Fetch /api/design/atomistic and inspect key geometric properties.
 *   3. Create a fresh design with a single helix at (1,1) [FORWARD parity, (row+col)%2=0].
 *   4. Repeat inspection.
 *   5. Assert the two helices agree within tolerance.
 *   6. Enable Ball-&-Stick view and take screenshots for visual inspection.
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000/api'

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Create a fresh design with one helix and a scaffold strand routed on it. */
async function freshDesignWithHelix(request, label, row, col, length_bp = 21) {
  const r1 = await request.post(`${API}/design`, {
    data: { name: label, lattice_type: 'HONEYCOMB' },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(r1.ok(), `POST /design (${label}) failed`).toBeTruthy()

  const r2 = await request.post(`${API}/design/helix-at-cell`, {
    data: { row, col, length_bp },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(r2.ok(), `POST helix-at-cell (${row},${col}) failed`).toBeTruthy()

  // Auto-scaffold so the atomistic model has atoms to place.
  // Falls back to scaffold-domain-paint for single-helix designs where
  // auto-scaffold can't find a Hamiltonian path.
  const r3 = await request.post(`${API}/design/auto-scaffold`, {
    data: {},
    headers: { 'Content-Type': 'application/json' },
  })
  if (!r3.ok()) {
    const dr = await request.get(`${API}/design`)
    const { design } = await dr.json()
    const h = design.helices[0]
    await request.post(`${API}/design/scaffold-domain-paint`, {
      data: { helix_id: h.id, lo_bp: 0, hi_bp: length_bp - 1 },
      headers: { 'Content-Type': 'application/json' },
    })
  }
}

/**
 * Fetch the atomistic model and return key geometric properties at the given bp.
 */
async function fetchAtomisticSummary(request, bpIndex) {
  const r = await request.get(`${API}/design/atomistic`)
  expect(r.ok(), 'GET /api/design/atomistic failed').toBeTruthy()
  const { atoms } = await r.json()

  const atBp = atoms.filter(a => a.bp_index === bpIndex)

  const pAtoms    = atBp.filter(a => a.name === 'P')
  const c1pAtoms  = atBp.filter(a => a.name === "C1'")
  const glyAtoms  = atBp.filter(a => a.name === 'N9' || a.name === 'N1')

  function dist(a, b) {
    return Math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)
  }

  const glycoDistances = []
  for (const c1 of c1pAtoms) {
    const gly = glyAtoms.find(g => g.direction === c1.direction)
    if (gly) glycoDistances.push({ direction: c1.direction, dist_nm: dist(c1, gly) })
  }

  const fwdP = pAtoms.find(a => a.direction === 'FORWARD')
  const revP = pAtoms.find(a => a.direction === 'REVERSE')
  const p2p  = (fwdP && revP) ? dist(fwdP, revP) : null

  const fwdC1 = c1pAtoms.find(a => a.direction === 'FORWARD')
  const revC1 = c1pAtoms.find(a => a.direction === 'REVERSE')
  const c1c1  = (fwdC1 && revC1) ? dist(fwdC1, revC1) : null

  return { glycoDistances, p2p, c1c1 }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Atomistic helix parity (REVERSE vs FORWARD)', () => {
  const BP = 10   // middle of a 21-bp helix

  test('REVERSE-parity helix (0,1): glycosidic bonds near 1.46–1.48 Å', async ({ request }) => {
    await freshDesignWithHelix(request, 'parity-reverse', 0, 1)
    const { glycoDistances } = await fetchAtomisticSummary(request, BP)
    expect(glycoDistances.length, 'Expected C1′–glyco pairs at bp 10').toBeGreaterThan(0)
    for (const { direction, dist_nm } of glycoDistances) {
      const dist_ang = dist_nm * 10
      console.log(`(0,1) ${direction} C1′–glyco: ${dist_ang.toFixed(4)} Å`)
      expect(dist_ang).toBeGreaterThan(1.40)
      expect(dist_ang).toBeLessThan(1.55)
    }
  })

  test('FORWARD-parity helix (1,1): glycosidic bonds near 1.46–1.48 Å', async ({ request }) => {
    await freshDesignWithHelix(request, 'parity-forward', 1, 1)
    const { glycoDistances } = await fetchAtomisticSummary(request, BP)
    expect(glycoDistances.length, 'Expected C1′–glyco pairs at bp 10').toBeGreaterThan(0)
    for (const { direction, dist_nm } of glycoDistances) {
      const dist_ang = dist_nm * 10
      console.log(`(1,1) ${direction} C1′–glyco: ${dist_ang.toFixed(4)} Å`)
      expect(dist_ang).toBeGreaterThan(1.40)
      expect(dist_ang).toBeLessThan(1.55)
    }
  })

  test('P-to-P and C1′–C1′ distances match between (0,1) and (1,1)', async ({ request }) => {
    await freshDesignWithHelix(request, 'p2p-reverse', 0, 1)
    const rev = await fetchAtomisticSummary(request, BP)

    await freshDesignWithHelix(request, 'p2p-forward', 1, 1)
    const fwd = await fetchAtomisticSummary(request, BP)

    console.log(`(0,1) P–P: ${(rev.p2p*10).toFixed(4)} Å   C1′–C1′: ${(rev.c1c1*10).toFixed(4)} Å`)
    console.log(`(1,1) P–P: ${(fwd.p2p*10).toFixed(4)} Å   C1′–C1′: ${(fwd.c1c1*10).toFixed(4)} Å`)

    // Both parities should have essentially identical cross-strand distances
    expect(Math.abs(rev.p2p - fwd.p2p) * 10).toBeLessThan(0.5)
    expect(Math.abs(rev.c1c1 - fwd.c1c1) * 10).toBeLessThan(0.5)
  })

  // ── Screenshot tests ───────────────────────────────────────────────────────
  // Opens the UI, loads each helix, enables Ball-and-Stick, takes a screenshot.
  // Inspect playwright-report/atomistic_*.png to visually compare the two.

  async function screenshotHelix(page, label, row, col) {
    await page.goto('/')
    await page.waitForSelector('#canvas')
    // Dismiss the splash screen via File > New, creating the actual target design in one go
    const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
    await fileMenu.hover()
    await page.click('#menu-file-new')
    await page.fill('#new-design-name', label)
    await page.click('#new-design-create')
    await expect(page.locator('#splash-screen')).not.toBeVisible({ timeout: 10_000 })
    await page.waitForTimeout(500)

    // Add helix via API (same backend session)
    await page.request.post(`${API}/design/helix-at-cell`, {
      data: { row, col, length_bp: 21 },
      headers: { 'Content-Type': 'application/json' },
    })
    // Scaffold: auto-scaffold first; fall back to domain-paint for single-helix
    const scfR = await page.request.post(`${API}/design/auto-scaffold`, {
      data: {}, headers: { 'Content-Type': 'application/json' },
    })
    if (!scfR.ok()) {
      const dr = await page.request.get(`${API}/design`)
      const { design } = await dr.json()
      const h = design.helices[0]
      await page.request.post(`${API}/design/scaffold-domain-paint`, {
        data: { helix_id: h.id, lo_bp: 0, hi_bp: 20 },
        headers: { 'Content-Type': 'application/json' },
      })
    }
    // Allow the frontend to receive the updated design
    await page.waitForTimeout(2000)

    // Enable Ball & Stick atomistic mode: View → Representation → Ball & Stick
    const viewMenu = page.locator('.menu-item').filter({ hasText: 'View' }).first()
    await viewMenu.hover()
    await page.waitForTimeout(300)
    const reprItem = page.locator('.submenu-item').filter({ hasText: 'Representation' }).first()
    await reprItem.hover()
    await page.waitForTimeout(200)
    await page.click('#menu-view-atomistic-ballstick')
    await page.waitForTimeout(3000)
    // Click the canvas to close any open menu
    await page.locator('#canvas').click({ force: true })
    await page.waitForTimeout(500)
  }

  test('Screenshot: (0,1) REVERSE-parity helix atomistic view', async ({ page }) => {
    await screenshotHelix(page, 'screenshot-reverse', 0, 1)
    await page.screenshot({ path: 'playwright-report/atomistic_0_1_reverse.png' })
    console.log('Saved: playwright-report/atomistic_0_1_reverse.png')
  })

  test('Screenshot: (1,1) FORWARD-parity helix atomistic view', async ({ page }) => {
    await screenshotHelix(page, 'screenshot-forward', 1, 1)
    await page.screenshot({ path: 'playwright-report/atomistic_1_1_forward.png' })
    console.log('Saved: playwright-report/atomistic_1_1_forward.png')
  })
})

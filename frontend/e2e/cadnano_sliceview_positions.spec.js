/**
 * Cadnano editor sliceview label test.
 *
 * Verifies that each occupied cell in the sliceview shows a label equal to
 * the helix's index in design.helices — purely the user-determined creation
 * order, with no geometric sorting of any kind.
 *
 * Test strategy:
 *   1. Create a fresh HC design.
 *   2. Add 6 helices in a deliberate non-geometric order.
 *   3. Fetch design.helices to learn the canonical index of each helix.
 *   4. Open the cadnano editor and scrape SVG label text from .sv-cell.occupied.
 *   5. Assert every cell's SVG label == that helix's index in design.helices.
 *
 * Also verifies y-flip: row 0 (bottom in 3D / backend) appears LOWER on screen
 * than row 2 (SVG ty increases downward).
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000/api'

// Six cells added in a deliberate order that is NOT boustrophedon and NOT
// any geometric sort, so any sorting in sliceview.js will produce wrong labels.
const CREATION_ORDER = [
  [2, 1],  // first  → design index 0
  [0, 1],  // second → design index 1
  [2, 0],  // third  → design index 2
  [1, 1],  // fourth → design index 3
  [0, 0],  // fifth  → design index 4
  [1, 0],  // sixth  → design index 5
]

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Parse "translate(tx, ty)" from an SVG transform attribute. */
function parseTr(transform) {
  const m = (transform ?? '').match(/translate\(\s*([^,]+),\s*([^)]+)\)/)
  return m ? { tx: parseFloat(m[1]), ty: parseFloat(m[2]) } : null
}

/** Parse "[row, col] — ..." from an sv-cell title text. */
function parseRowCol(title) {
  const m = (title ?? '').match(/\[(-?\d+),\s*(-?\d+)\]/)
  return m ? [parseInt(m[1]), parseInt(m[2])] : null
}

// ── Test ─────────────────────────────────────────────────────────────────────

test('cadnano sliceview labels match design.helices creation order', async ({ page }) => {
  // ── 1. Create a fresh HC design ─────────────────────────────────────────
  const newResp = await page.request.post(`${API}/design`, {
    data: { name: 'creation-order label test', lattice_type: 'HONEYCOMB' },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(newResp.ok(), 'POST /design failed').toBeTruthy()

  // ── 2. Add helices in creation order ────────────────────────────────────
  for (const [row, col] of CREATION_ORDER) {
    const r = await page.request.post(`${API}/design/helix-at-cell`, {
      data: { row, col, length_bp: 42 },
      headers: { 'Content-Type': 'application/json' },
    })
    expect(r.ok(), `POST helix-at-cell (${row},${col}) failed`).toBeTruthy()
  }

  // ── 3. Fetch design.helices to get canonical indices ─────────────────────
  const designResp = await page.request.get(`${API}/design`)
  expect(designResp.ok()).toBeTruthy()
  const { design } = await designResp.json()
  expect(design.helices.length).toBe(6)

  // Build expected label map: "row,col" → design index
  const expectedLabel = new Map()
  for (let i = 0; i < design.helices.length; i++) {
    const h = design.helices[i]
    const row = h.grid_pos?.[0]
    const col = h.grid_pos?.[1]
    expect(row, `helix[${i}] missing grid_pos`).not.toBeUndefined()
    expectedLabel.set(`${row},${col}`, i)
  }
  console.log('\nExpected labels (from design.helices order):')
  for (const [key, idx] of expectedLabel) console.log(`  (${key}) → label ${idx}`)

  // ── 4. Open cadnano editor and wait for cells ────────────────────────────
  await page.goto('/cadnano-editor')
  await page.waitForFunction(
    () => document.querySelectorAll('.sv-cell.occupied').length === 6,
    { timeout: 15_000 },
  )

  // ── 5. Scrape SVG cells ──────────────────────────────────────────────────
  const rawCells = await page.$$eval('.sv-cell.occupied', els => els.map(el => ({
    title:     el.querySelector('title')?.textContent ?? '',
    transform: el.getAttribute('transform') ?? '',
    label:     el.querySelector('text.sv-label')?.textContent?.trim() ?? '',
  })))

  expect(rawCells.length).toBe(6)

  const byRC = new Map()
  for (const c of rawCells) {
    const rc = parseRowCol(c.title)
    const tr = parseTr(c.transform)
    expect(rc, `Could not parse row/col from title: "${c.title}"`).not.toBeNull()
    expect(tr, `Could not parse tx/ty from transform: "${c.transform}"`).not.toBeNull()
    byRC.set(`${rc[0]},${rc[1]}`, { tx: tr.tx, ty: tr.ty, label: c.label, row: rc[0], col: rc[1] })
  }

  console.log('\nActual cell labels from sliceview:')
  for (const [key, v] of byRC) console.log(`  (${key}) → label "${v.label}"`)

  // ── 6. Assert each cell label == design.helices index ───────────────────
  for (const [key, expected] of expectedLabel) {
    const cell = byRC.get(key)
    expect(cell, `Cell (${key}) not found in sliceview`).not.toBeUndefined()
    const actual = parseInt(cell.label)
    expect(
      actual,
      `Cell (${key}): expected label ${expected} (design.helices index) but got "${cell.label}". ` +
      `Sliceview is applying sorting — labels must reflect user creation order only.`,
    ).toBe(expected)
  }

  // ── 7. Assert y-flip: row 0 appears LOWER on screen than row 2 ──────────
  // SVG ty increases downward; backend/3D have row 0 at bottom (y=0), row 2 higher.
  // After y-flip, row 0 must have larger ty than row 2.
  const row0cells = CREATION_ORDER.filter(([r]) => r === 0)
  const row2cells = CREATION_ORDER.filter(([r]) => r === 2)
  for (const [r0, c0] of row0cells) {
    for (const [r2, c2] of row2cells) {
      const ty0 = byRC.get(`${r0},${c0}`)?.ty
      const ty2 = byRC.get(`${r2},${c2}`)?.ty
      expect(ty0, `(${r0},${c0}) ty missing`).not.toBeNull()
      expect(ty2, `(${r2},${c2}) ty missing`).not.toBeNull()
      expect(
        ty0 > ty2,
        `Y-flip broken: row=${r0} ty=${ty0?.toFixed(1)} should be > row=${r2} ty=${ty2?.toFixed(1)}`,
      ).toBeTruthy()
    }
  }

  console.log('\nAll assertions passed.')
  console.log('Creation order → label mapping:')
  for (const [row, col] of CREATION_ORDER) {
    const exp = expectedLabel.get(`${row},${col}`)
    const act = byRC.get(`${row},${col}`)?.label
    console.log(`  step ${exp}: (${row},${col}) → label "${act}"`)
  }
})

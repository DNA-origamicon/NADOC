/**
 * Playwright investigation: caDNAno import cross-section / slice plane.
 *
 * Imports the 18HB honeycomb caDNAno file, activates the slice plane,
 * and captures screenshots to check helix placement.
 */

import { test, expect } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const BASE_URL = 'http://localhost:8000'

test('cadnano 18HB cross-section helix positions', async ({ page }) => {
  await page.goto(BASE_URL)

  // Read the 18HB caDNAno file
  const cadnanoPath = path.join(
    import.meta.dirname ?? __dirname,
    '../../Examples/cadnano/18hb_symm_p7249_21_even_spacing_sequential_coloring.json'
  )
  const cadnanoJson = JSON.parse(fs.readFileSync(cadnanoPath, 'utf8'))

  // POST directly to the API to import the design
  const response = await page.request.post(`${BASE_URL}/api/design/import/cadnano`, {
    data: cadnanoJson,
    headers: { 'Content-Type': 'application/json' },
  })
  expect(response.ok()).toBeTruthy()
  const designData = await response.json()

  // Print helix positions for debugging
  const helices = designData.design.helices
  console.log(`Imported ${helices.length} helices`)
  for (const h of helices) {
    const row = h.id.split('_')[2]
    const col = h.id.split('_')[3]
    const x = h.axis_start.x.toFixed(3)
    const y = h.axis_start.y.toFixed(3)
    console.log(`  ${h.id}  row=${row} col=${col}  x=${x} y=${y}  num=${h.cadnano_num}`)
  }

  // Also check distances between adjacent pairs
  console.log('\nChecking inter-helix distances...')
  const tol = 0.01
  const expected = 2.25  // nm
  let violations = []
  for (let i = 0; i < helices.length; i++) {
    for (let j = i + 1; j < helices.length; j++) {
      const a = helices[i], b = helices[j]
      const dx = a.axis_start.x - b.axis_start.x
      const dy = a.axis_start.y - b.axis_start.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist < expected - tol) {
        violations.push(`${a.id} <-> ${b.id}: dist=${dist.toFixed(3)}nm (too close!)`)
      }
    }
  }
  if (violations.length === 0) {
    console.log('  No inter-helix distance violations (all pairs >= 2.25nm)')
  } else {
    for (const v of violations) console.log('  VIOLATION: ' + v)
  }

  // Check which helices land in NADOC honeycomb "holes"
  console.log('\nChecking NADOC honeycomb validity for each helix:')
  const HONEYCOMB_COL_PITCH = 1.125 * Math.sqrt(3)
  const HONEYCOMB_ROW_PITCH = 2.25
  const HONEYCOMB_LATTICE_RADIUS = 1.125
  function honeycombCellValue(row, col) {
    return ((row + (col % 2)) % 3 + 3) % 3
  }
  const LABELS = ['FORWARD', 'REVERSE', 'HOLE']
  for (const h of helices) {
    const parts = h.id.split('_')
    const row = parseInt(parts[2])
    const col = parseInt(parts[3])
    const val = honeycombCellValue(row, col)
    const expectedDir = h.cadnano_num % 2 === 0 ? 'FORWARD' : 'REVERSE'
    const nadocLabel = LABELS[val]
    const ok = val !== 2
    const dirMatch = (val === 0 && expectedDir === 'FORWARD') || (val === 1 && expectedDir === 'REVERSE')
    console.log(`  ${h.id}  cadnano_dir=${expectedDir}  NADOC_cell=${nadocLabel}  ${ok ? (dirMatch ? 'OK' : 'DIR_MISMATCH') : 'HOLE!'}`)
  }

  // Now also compute what the CORRECT positions should be with caDNAno's odd-col convention
  console.log('\nExpected positions with caDNAno odd-col convention:')
  for (const h of helices) {
    const parts = h.id.split('_')
    const row = parseInt(parts[2])
    const col = parseInt(parts[3])
    const x = col * HONEYCOMB_COL_PITCH
    const y = row * HONEYCOMB_ROW_PITCH + (col % 2 !== 0 ? HONEYCOMB_LATTICE_RADIUS : 0)
    const xCurr = h.axis_start.x
    const yCurr = h.axis_start.y
    const diff = Math.abs(y - yCurr) > 0.001 ? ' <-- DIFFERS' : ''
    console.log(`  ${h.id}  expected=(${x.toFixed(3)}, ${y.toFixed(3)})  actual=(${xCurr.toFixed(3)}, ${yCurr.toFixed(3)})${diff}`)
  }

  // Basic assertion - just check it ran
  expect(helices.length).toBeGreaterThan(10)
})

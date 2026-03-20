/**
 * Playwright investigation: blunt-end trimming after caDNAno import.
 *
 * Imports 18hb_seamless.json (array_len=462, active bp≈23–431) and verifies
 * that axis_start.z and axis_end.z are trimmed to the actual DNA extent
 * rather than spanning the full empty caDNAno array.
 *
 * Also captures screenshots from the side to visually confirm the rings
 * sit flush with the structure.
 */

import { test, expect } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const BACKEND = 'http://localhost:8000'
const FRONTEND = 'http://localhost:5173'
const BDNA_RISE = 0.33200  // nm per bp

// Use 6HB for screenshot tests — smaller scene renders faster in SwiftShader
const CADNANO_FILE_6HB = path.join(
  import.meta.dirname ?? __dirname,
  '../../Examples/cadnano/Honeycomb_6hb_test1.json'
)
// 18HB for the numerical axis-trim test (it has the larger empty bp padding)
const CADNANO_FILE_18HB = path.join(
  import.meta.dirname ?? __dirname,
  '../../Examples/cadnano/18hb_seamless.json'
)

// ── helpers ──────────────────────────────────────────────────────────────────

async function importDesign(request, file = CADNANO_FILE_18HB) {
  const cadnanoContent = fs.readFileSync(file, 'utf8')
  const resp = await request.post(`${BACKEND}/api/design/import/cadnano`, {
    data: { content: cadnanoContent },
    headers: { 'Content-Type': 'application/json' },
  })
  if (!resp.ok()) {
    const body = await resp.text()
    throw new Error(`Import failed ${resp.status()}: ${body.slice(0, 300)}`)
  }
  return resp.json()
}

// ── API checks ───────────────────────────────────────────────────────────────

test('axis_start.z and axis_end.z are trimmed to active bp range', async ({ request }) => {
  const data = await importDesign(request)
  const helices = data.design.helices

  console.log(`Imported ${helices.length} helices from 18hb_seamless.json`)

  // For each helix: axis_start.z and axis_end.z must NOT be the extremes of
  // the full empty caDNAno array (0 and (462-1)*RISE = 153.1 nm).
  const arrayMaxZ = (462 - 1) * BDNA_RISE   // 153.09 nm if untrimmed

  let anyUntrimmedStart = false
  let anyUntrimmedEnd   = false
  const summary = []

  for (const h of helices) {
    const zStart = h.axis_start.z
    const zEnd   = h.axis_end.z
    const isUntrimmedStart = zStart < 0.001                   // still at 0
    const isUntrimmedEnd   = Math.abs(zEnd - arrayMaxZ) < 0.1 // still at 153 nm

    if (isUntrimmedStart) anyUntrimmedStart = true
    if (isUntrimmedEnd)   anyUntrimmedEnd   = true

    summary.push(
      `  ${h.id}  z_start=${zStart.toFixed(3)}  z_end=${zEnd.toFixed(3)}` +
      (isUntrimmedStart ? '  ⚠ UNTRIMMED_START' : '') +
      (isUntrimmedEnd   ? '  ⚠ UNTRIMMED_END'   : '')
    )
  }

  for (const line of summary) console.log(line)

  if (anyUntrimmedStart) console.log('\n⚠  Some helices still have z_start=0 (untrimmed leading gap)')
  if (anyUntrimmedEnd)   console.log('\n⚠  Some helices still have z_end at full array length (untrimmed trailing gap)')

  // Assert: every helix must have its end trimmed away from the full-array max
  expect(anyUntrimmedEnd, 'axis_end.z should be trimmed away from full caDNAno array end').toBe(false)

  // Also assert all helices share a consistent active range (18hb_seamless is uniform)
  const zStarts = helices.map(h => h.axis_start.z)
  const zEnds   = helices.map(h => h.axis_end.z)
  const minStart = Math.min(...zStarts)
  const maxEnd   = Math.max(...zEnds)

  console.log(`\nActive bp range across all helices: z=${minStart.toFixed(3)} → ${maxEnd.toFixed(3)} nm`)
  console.log(`Full array would be: z=0.000 → ${arrayMaxZ.toFixed(3)} nm`)
  console.log(`Trimmed leading: ${minStart.toFixed(3)} nm  Trimmed trailing: ${(arrayMaxZ - maxEnd).toFixed(3)} nm`)

  // Expect meaningful trim (at least 1 nm trimmed from each end)
  expect(minStart).toBeGreaterThan(1.0)
  expect(maxEnd).toBeLessThan(arrayMaxZ - 1.0)
})

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Load a cadnano file through the File > Import caDNAno UI menu.
 *
 *  NOTE: Playwright uses SwiftShader (software WebGL), so Three.js scene
 *  construction is ~10-50x slower than with GPU acceleration.  We wait for
 *  the welcome-screen to hide (fires after the API responds, before render)
 *  then give SwiftShader time to paint one frame.
 */
async function importViaUI(page, file = CADNANO_FILE_6HB) {
  await page.goto(FRONTEND)

  // Open the File dropdown then click the import item
  const fileMenuItem = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenuItem.hover()
  await page.waitForTimeout(150)  // let CSS :hover dropdown appear

  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 10_000 }),
    page.locator('#menu-file-import-cadnano').click(),
  ])
  await fileChooser.setFiles(file)

  // Wait for the API response to be processed (welcome screen hides)
  await page.waitForFunction(
    () => document.getElementById('welcome-screen')?.classList.contains('hidden'),
    { timeout: 15_000 }
  )

  // Allow SwiftShader time to paint the initial frame
  await page.waitForTimeout(1_500)
}

// ── Visual screenshots ────────────────────────────────────────────────────────

test('screenshots: 18hb_seamless blunt ends (default + rotated views)', async ({ page }) => {
  test.setTimeout(120_000)
  await importViaUI(page)

  const canvas = page.locator('#canvas')
  await expect(canvas).toBeVisible()

  // Reset camera for a clean starting view
  await page.click('#reset-btn').catch(() => {})
  await page.waitForTimeout(600)

  // Clip to the 3D canvas — this bypasses Playwright's "wait for fonts"
  // heuristic which can block for 30s even though Three.js is WebGL.
  const canvasBox = await canvas.boundingBox()
  const shot = (savePath) => page.screenshot({
    path: savePath,
    clip: canvasBox,
    timeout: 8_000,
  })

  // Default (cross-section) view
  await shot('playwright-report/blunt_ends_default.png')
  console.log('Screenshot saved: blunt_ends_default.png')

  // Rotate to reveal helix length axis (horizontal drag = orbit around Y)
  const box = canvasBox
  const cx = box.x + box.width / 2
  const cy = box.y + box.height / 2

  await page.mouse.move(cx, cy)
  await page.mouse.down()
  await page.mouse.move(cx - box.width * 0.4, cy, { steps: 20 })
  await page.mouse.up()
  await page.waitForTimeout(400)

  await shot('playwright-report/blunt_ends_side.png')
  console.log('Screenshot saved: blunt_ends_side.png')

  // Slight upward tilt for 3D perspective
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  await page.mouse.move(cx, cy - box.height * 0.12, { steps: 10 })
  await page.mouse.up()
  await page.waitForTimeout(400)

  await shot('playwright-report/blunt_ends_side_tilted.png')
  console.log('Screenshot saved: blunt_ends_side_tilted.png')
})

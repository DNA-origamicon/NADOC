/**
 * Assembly filter-view-strip cleanup — verification
 *
 * In assembly mode the top filter-view strip is trimmed to overhang-relevant
 * controls only: overhang-locations tool, sequence/grid/overhang-name view
 * toggles, expanded spacing. The whole Selectable section is hidden (assembly
 * overhang selection is done by hovering/clicking overhangs in 3D, not via a
 * selection filter), along with the blunt/xover tools, length/undef toggles,
 * and deform/unfold/cadnano mode buttons. Everything restores on exit.
 *
 * Servers must be running (Vite :5173, FastAPI :8000).
 */

import { test, expect } from '@playwright/test'

const MODE = '#mode-indicator'
const ASSEMBLY_NAME = 'Strip Cleanup Assembly'

// The New-Assembly flow auto-saves a .nass to the workspace; remove it so the
// test leaves no artifact behind.
test.afterEach(async ({ request }) => {
  await request.delete('http://localhost:8000/api/library/file', {
    params: { path: `${ASSEMBLY_NAME}.nass` },
  }).catch(() => {})
})

// Selectors that should stay VISIBLE in assembly mode.
const KEEP = [
  '#view-tools [data-key="ovhg"]',
  '#view-tools [data-vt="sequences"]',
  '#view-tools [data-vt="grid"]',
  '#view-tools [data-vt="overhangNames"]',
  '#view-tools [data-vt="expanded"]',
]

// Selectors that should HIDE in assembly mode.
const HIDE = [
  '#select-filter',                            // whole Selectable section (no selectable button)
  '#view-tools > .sf-divider:first-child',     // leading divider before Tools:
  '#view-tools [data-key="blunt"]',
  '#view-tools [data-key="fxover"]',
  '#view-tools [data-vt="lengthHeatmap"]',
  '#view-tools [data-vt="undefinedBases"]',
  '#view-tools [data-vt="deform"]',
  '#view-tools [data-vt="unfold"]',
  '#view-tools [data-vt="cadnano2d"]',
]

/** Map selector -> computed display ('none' means hidden). */
async function stripDisplays(page, selectors) {
  return page.evaluate((sels) => {
    const out = {}
    for (const s of sels) {
      const el = document.querySelector(s)
      out[s] = el ? getComputedStyle(el).display : 'MISSING'
    }
    return out
  }, selectors)
}

test('assembly mode trims the filter-view strip; exit restores it', async ({ page, request }) => {
  // Ensure a server-side design exists so the app leaves the splash.
  const dr = await request.get('http://localhost:8000/api/design')
  if ((await dr.json()).design?.helices?.length === undefined) {
    await request.post('http://localhost:8000/api/design', {
      data: { name: 'Strip Cleanup Test', lattice_type: 'HONEYCOMB' },
    })
  }

  await page.goto('/')

  // Dismiss splash if present.
  const splash = page.locator('#splash-screen')
  if (await splash.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
    await page.click('#menu-file-new')
    await page.fill('#new-design-name', 'Strip Cleanup Test')
    await page.click('#new-design-create')
    await expect(splash).toBeHidden({ timeout: 10_000 })
  }

  await expect(page.locator(MODE)).not.toContainText('ASSEMBLY', { timeout: 5_000 })

  // --- Design mode: everything visible ---
  const designKeep = await stripDisplays(page, KEEP)
  const designHide = await stripDisplays(page, HIDE)
  console.log('[design] KEEP displays:', JSON.stringify(designKeep))
  console.log('[design] HIDE displays:', JSON.stringify(designHide))
  for (const s of [...KEEP, ...HIDE]) {
    expect(designKeep[s] ?? designHide[s], `${s} should exist + be visible in design mode`).not.toBe('none')
    expect(designKeep[s] ?? designHide[s]).not.toBe('MISSING')
  }

  // --- Enter assembly mode (File ▸ New Assembly…) ---
  // The name prompt is a native window.prompt; auto-accept it.
  await page.evaluate((name) => { window.prompt = () => name }, ASSEMBLY_NAME)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new-assembly')
  await expect(page.locator(MODE)).toContainText('ASSEMBLY', { timeout: 10_000 })
  await page.waitForTimeout(300)

  const asmKeep = await stripDisplays(page, KEEP)
  const asmHide = await stripDisplays(page, HIDE)
  console.log('[assembly] KEEP displays:', JSON.stringify(asmKeep))
  console.log('[assembly] HIDE displays:', JSON.stringify(asmHide))

  for (const s of KEEP) {
    expect(asmKeep[s], `${s} should stay visible in assembly mode`).not.toBe('none')
  }
  for (const s of HIDE) {
    expect(asmHide[s], `${s} should be hidden in assembly mode`).toBe('none')
  }

  // --- Exit assembly mode (File ▸ Close Session) → restore ---
  // Close Session may prompt before unload; auto-confirm any dialogs.
  page.on('dialog', d => d.accept().catch(() => {}))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-close-session')
  await expect(page.locator(MODE)).not.toContainText('ASSEMBLY', { timeout: 10_000 })
  await page.waitForTimeout(300)

  const restored = await stripDisplays(page, [...KEEP, ...HIDE])
  console.log('[restored] displays:', JSON.stringify(restored))
  for (const s of [...KEEP, ...HIDE]) {
    expect(restored[s], `${s} should be restored after exiting assembly mode`).not.toBe('none')
  }
})

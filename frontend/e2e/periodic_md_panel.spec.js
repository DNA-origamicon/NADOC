/**
 * Periodic MD panel — load + apply/revert toggle test.
 *
 * Verifies:
 *   1. Selecting a PDB file enables #pmd-load-btn.
 *   2. Selecting a DCD file shows atom/frame counts in the log.
 *   3. Clicking Load shows P-atom count in the log and exposes the scrubber.
 *   4. #pmd-apply-btn becomes enabled after Load.
 *   5. Clicking Apply hides the CG representation and sets periodicMdOverlay.isApplied().
 *   6. Clicking "Revert to CG" restores CG and clears isApplied().
 *
 * Prerequisites:
 *   - Both servers running (playwright.config.js webServer stanzas cover this).
 *   - B_tube design at /home/jojo/Work/NADOC/workspace/B_tube.nadoc
 *   - Periodic cell run at:
 *       /home/jojo/Work/NADOC/experiments/exp23_periodic_cell_benchmark/results/periodic_cell_run/
 *
 * Run:
 *   cd /home/jojo/Work/NADOC/frontend
 *   npx playwright test e2e/periodic_md_panel.spec.js --headed
 */

import { test, expect } from '@playwright/test'
import path             from 'path'

const API         = 'http://127.0.0.1:8000/api'
const DESIGN_PATH = '/home/jojo/Work/NADOC/workspace/B_tube.nadoc'
const RUN_DIR     = path.resolve(
  '/home/jojo/Work/NADOC/experiments/exp23_periodic_cell_benchmark/results/periodic_cell_run'
)
const PSF_PATH = path.join(RUN_DIR, 'B_tube_periodic_1x.psf')
const PDB_PATH = path.join(RUN_DIR, 'B_tube_periodic_1x.pdb')
const DCD_PATH = path.join(RUN_DIR, 'output', 'B_tube_periodic_1x.dcd')

async function bootWithBTube(page, request) {
  const r = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(r.ok(), 'POST /design/load for B_tube failed').toBeTruthy()

  await page.goto('/')
  await page.waitForSelector('#canvas')

  await page.evaluate(() => {
    const splash = document.getElementById('splash-screen')
    if (splash) splash.style.display = 'none'
  })
}

async function expandPeriodicMdPanel(page) {
  const body = page.locator('#periodic-md-body')
  const visible = await body.isVisible()
  if (!visible) {
    await page.click('#periodic-md-heading')
    await expect(body).toBeVisible()
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Periodic MD panel', () => {

  test('PDB selection enables load button', async ({ page, request }) => {
    await bootWithBTube(page, request)
    await expandPeriodicMdPanel(page)

    const loadBtn = page.locator('#pmd-load-btn')
    await expect(loadBtn).toBeDisabled()

    // Provide PDB via the hidden file input (accept=".pdb")
    const pdbInput = page.locator('input[type="file"][accept=".pdb"]')
    await pdbInput.setInputFiles(PDB_PATH)

    await expect(loadBtn).not.toBeDisabled({ timeout: 10_000 })

    const pdbName = page.locator('#pmd-pdb-name')
    await expect(pdbName).toContainText('B_tube_periodic_1x.pdb')
  })

  test('DCD selection logs atom and frame counts', async ({ page, request }) => {
    await bootWithBTube(page, request)
    await expandPeriodicMdPanel(page)

    const dcdInput = page.locator('input[type="file"][accept=".dcd"]')
    await dcdInput.setInputFiles(DCD_PATH)

    const logEl = page.locator('#pmd-log')
    // DCD handler reads the header (4 KB) and logs: "DCD: <name>  (<N> atoms, <F> frames, <T> ns)"
    await expect(logEl).toContainText('atoms,', { timeout: 15_000 })
    await expect(logEl).toContainText('frames,')

    const dcdName = page.locator('#pmd-dcd-name')
    await expect(dcdName).toContainText('B_tube_periodic_1x.dcd')
  })

  test('Load shows P-atom count and exposes scrubber', async ({ page, request }) => {
    await bootWithBTube(page, request)
    await expandPeriodicMdPanel(page)

    // Supply PSF, PDB, and DCD
    await page.locator('input[type="file"][accept=".psf"]').setInputFiles(PSF_PATH)
    await page.locator('input[type="file"][accept=".pdb"]').setInputFiles(PDB_PATH)
    await page.locator('input[type="file"][accept=".dcd"]').setInputFiles(DCD_PATH)

    const loadBtn = page.locator('#pmd-load-btn')
    await expect(loadBtn).not.toBeDisabled({ timeout: 10_000 })
    await loadBtn.click()

    const logEl = page.locator('#pmd-log')
    // Log should mention heavy atoms after mesh build
    await expect(logEl).toContainText('heavy atoms', { timeout: 30_000 })

    // PSF atom count should be logged
    await expect(logEl).toContainText('PSF NATOM:')

    // DCD scrubber should appear
    const scrubWrap = page.locator('#pmd-scrub-wrap')
    await expect(scrubWrap).toBeVisible({ timeout: 5_000 })

    // Apply button should now be enabled
    const applyBtn = page.locator('#pmd-apply-btn')
    await expect(applyBtn).not.toBeDisabled({ timeout: 5_000 })
  })

  test('Apply hides CG and sets isApplied; Revert restores CG', async ({ page, request }) => {
    test.setTimeout(120_000)

    await bootWithBTube(page, request)
    await expandPeriodicMdPanel(page)

    await page.locator('input[type="file"][accept=".psf"]').setInputFiles(PSF_PATH)
    await page.locator('input[type="file"][accept=".pdb"]').setInputFiles(PDB_PATH)
    await page.locator('input[type="file"][accept=".dcd"]').setInputFiles(DCD_PATH)

    const loadBtn = page.locator('#pmd-load-btn')
    await expect(loadBtn).not.toBeDisabled({ timeout: 10_000 })
    await loadBtn.click()

    const applyBtn = page.locator('#pmd-apply-btn')
    await expect(applyBtn).not.toBeDisabled({ timeout: 30_000 })

    // CG should be visible before apply
    const cgVisibleBefore = await page.evaluate(() => window.__nadocTest?.isCGVisible?.())
    expect(cgVisibleBefore).toBe(true)

    // Click Apply — reads N frames from DCD (may take a few seconds)
    await applyBtn.click()

    // Wait for button to switch to "Revert to CG" (signals apply completed)
    await expect(applyBtn).toContainText('Revert to CG', { timeout: 60_000 })

    // CG should now be hidden
    const cgVisibleAfterApply = await page.evaluate(() => window.__nadocTest?.isCGVisible?.())
    expect(cgVisibleAfterApply).toBe(false)

    // periodicMdOverlay.isApplied() should be true
    const isApplied = await page.evaluate(() => window.__nadocTest?.getPeriodicMdOverlay?.()?.isApplied?.())
    expect(isApplied).toBe(true)

    // Log should confirm applied windows
    const logEl = page.locator('#pmd-log')
    await expect(logEl).toContainText('Applied:')

    // ── Revert ────────────────────────────────────────────────────────────────
    await applyBtn.click()
    await expect(applyBtn).toContainText('Apply to Design', { timeout: 10_000 })

    const cgVisibleAfterRevert = await page.evaluate(() => window.__nadocTest?.isCGVisible?.())
    expect(cgVisibleAfterRevert).toBe(true)

    const isAppliedAfterRevert = await page.evaluate(() => window.__nadocTest?.getPeriodicMdOverlay?.()?.isApplied?.())
    expect(isAppliedAfterRevert).toBe(false)

    await expect(logEl).toContainText('Reverted to CG')
  })

})

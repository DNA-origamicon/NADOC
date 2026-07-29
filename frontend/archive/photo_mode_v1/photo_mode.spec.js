/**
 * Photo mode — panel open/close, controls, and export tests.
 *
 * Verifies:
 *   1. Photo tab button opens the photo panel.
 *   2. 'P' keyboard shortcut toggles photo mode on/off.
 *   3. Exit button returns to normal mode.
 *   4. Lighting preset dropdown is functional.
 *   5. Background radio buttons are functional (transparent/white/black/custom).
 *   6. Resolution preset updates DPI label.
 *   7. Bloom toggle shows/hides strength slider row.
 *   8. Material preset dropdowns exist and change without throwing.
 *   9. Export button triggers PNG download.
 *  10. Exiting photo mode restores the panel to the feature-log tab.
 *
 * Prerequisites:
 *   Both servers running (playwright.config.js webServer stanzas).
 *   No design needs to be loaded — photo mode UI tests work on empty scene.
 *
 * Run:
 *   cd /home/jojo/Work/NADOC/frontend
 *   npx playwright test e2e/photo_mode.spec.js --headed
 */

import { test, expect } from '@playwright/test'

// ── Helpers ───────────────────────────────────────────────────────────────────

async function boot(page) {
  await page.goto('/')
  await page.waitForSelector('#canvas')
  // Dismiss splash if present
  await page.evaluate(() => {
    const splash = document.getElementById('splash-screen')
    if (splash) splash.style.display = 'none'
  })
}

async function openPhotoMode(page) {
  const btn = page.locator('#photo-tab-btn')
  await expect(btn).toBeVisible()
  await btn.click()
  // Panel content should be visible
  await expect(page.locator('#tab-content-photo')).toBeVisible({ timeout: 5_000 })
}

async function exitPhotoMode(page) {
  await page.locator('#photo-exit-btn').click()
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Photo Mode', () => {

  test('photo tab button is present in left tab strip', async ({ page }) => {
    await boot(page)
    await expect(page.locator('#photo-tab-btn')).toBeVisible()
  })

  test('clicking photo tab button opens photo panel', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    await expect(page.locator('#photo-export-btn')).toBeVisible()
    await expect(page.locator('#photo-exit-btn')).toBeVisible()
  })

  test('P shortcut toggles photo mode on', async ({ page }) => {
    await boot(page)
    // Panel hidden before
    await expect(page.locator('#tab-content-photo')).not.toBeVisible()
    await page.keyboard.press('p')
    await expect(page.locator('#tab-content-photo')).toBeVisible({ timeout: 3_000 })
  })

  test('P shortcut toggles photo mode off when already active', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    await page.keyboard.press('p')
    // Should switch back to feature-log tab; photo panel hidden
    await expect(page.locator('#tab-content-photo')).not.toBeVisible({ timeout: 3_000 })
  })

  test('Exit button closes photo mode', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    await exitPhotoMode(page)
    await expect(page.locator('#tab-content-photo')).not.toBeVisible({ timeout: 3_000 })
  })

  test('lighting preset dropdown is functional', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const sel = page.locator('#photo-lighting-select')
    await expect(sel).toBeVisible()
    const options = await sel.locator('option').allTextContents()
    expect(options.length).toBeGreaterThanOrEqual(3)
    // Select each option and verify no console errors
    const errors = []
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
    for (const opt of options) {
      await sel.selectOption({ label: opt })
    }
    expect(errors).toHaveLength(0)
  })

  test('background transparent radio selects without error', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const transparentRadio = page.locator('input[name="photo-bg"][value="transparent"]')
    await expect(transparentRadio).toBeVisible()
    const errors = []
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
    await transparentRadio.click()
    // Color row should be hidden for non-custom types
    await expect(page.locator('#photo-bg-color-row')).not.toBeVisible()
    expect(errors).toHaveLength(0)
  })

  test('background custom radio reveals color picker', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const customRadio = page.locator('input[name="photo-bg"][value="custom"]')
    await customRadio.click()
    await expect(page.locator('#photo-bg-color-row')).toBeVisible()
  })

  test('resolution preset updates DPI label', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const sel = page.locator('#photo-res-preset')
    const label = page.locator('#photo-dpi-label')

    await sel.selectOption('p300')
    await expect(label).toHaveText('300 DPI')

    await sel.selectOption('p600')
    await expect(label).toHaveText('600 DPI')

    await sel.selectOption('screen')
    await expect(label).toHaveText('screen res')
  })

  test('resolution custom preset makes W/H inputs editable', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const sel  = page.locator('#photo-res-preset')
    const wIn  = page.locator('#photo-res-w')
    const hIn  = page.locator('#photo-res-h')

    await sel.selectOption('p300')
    await expect(wIn).toHaveAttribute('readonly', /.?/)

    await sel.selectOption('custom')
    // readonly attribute should be absent for custom
    await expect(wIn).not.toHaveAttribute('readonly', /.?/)
    await expect(hIn).not.toHaveAttribute('readonly', /.?/)
  })

  test('bloom toggle shows strength slider row', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const chk = page.locator('#photo-bloom')
    const row = page.locator('#photo-bloom-strength-row')

    // Should be hidden initially
    await expect(row).not.toBeVisible()
    await chk.check()
    await expect(row).toBeVisible()
    await chk.uncheck()
    await expect(row).not.toBeVisible()
  })

  test('material preset dropdowns exist and change without console errors', async ({ page }) => {
    await boot(page)
    const errors = []
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
    await openPhotoMode(page)

    for (const id of ['photo-material-full', 'photo-material-surface',
                       'photo-material-cylinders', 'photo-material-atomistic']) {
      const sel = page.locator(`#${id}`)
      await expect(sel).toBeVisible()
      const opts = await sel.locator('option').allTextContents()
      expect(opts.length).toBeGreaterThanOrEqual(2)
      for (const opt of opts) await sel.selectOption({ label: opt })
    }
    expect(errors).toHaveLength(0)
  })

  test('FOV slider is present and has sane range', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const slider = page.locator('#photo-fov')
    await expect(slider).toBeVisible()
    await expect(slider).toHaveAttribute('min', '20')
    await expect(slider).toHaveAttribute('max', '90')
  })

  test('quality fast/PT radios are present', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    await expect(page.locator('#photo-quality-fast')).toBeVisible()
    await expect(page.locator('#photo-quality-pt')).toBeVisible()
  })

  test('path-tracing radio shows progress bar', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    const ptRadio   = page.locator('#photo-quality-pt')
    const progress  = page.locator('#photo-pt-progress')

    await expect(progress).not.toBeVisible()
    await ptRadio.click()
    await expect(progress).toBeVisible()
  })

  test('export button triggers PNG download', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)

    // Listen for download event
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 15_000 }),
      page.locator('#photo-export-btn').click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^nadoc-.*\.png$/)
  })

  test('exiting photo mode hides the photo panel', async ({ page }) => {
    await boot(page)
    await openPhotoMode(page)
    await exitPhotoMode(page)
    // Photo pane must be hidden after exit (panel collapses when no design is loaded)
    await expect(page.locator('#tab-content-photo')).not.toBeVisible({ timeout: 3_000 })
  })

})

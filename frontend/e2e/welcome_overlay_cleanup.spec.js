/**
 * Welcome-screen overlay cleanup — verification (bug repro).
 *
 * Closing a session must return to a clean welcome screen. Two overlays were
 * leaking: the view-cube 90° roll buttons (#vc-roll — sibling of the hidden
 * #vc-wrap) and the CanDo RMSF/deviation legend (#cando-legend). This drives
 * load → close and asserts both are hidden afterwards (and #vc-roll shows while
 * a design is loaded).
 *
 * Servers must be running (Vite :5173, FastAPI :8000).
 */

import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

async function display(page, sel) {
  return page.evaluate((s) => {
    const el = document.querySelector(s)
    return el ? getComputedStyle(el).display : 'MISSING'
  }, sel)
}

test('close-session hides the view-cube roll buttons and CanDo legend', async ({ page }) => {
  await loadScaffoldedPart(page, { doc: 'overlay-cleanup', name: 'overlay_cleanup' })

  // --- Design loaded: the view-cube roll buttons are visible ---
  expect(await display(page, '#vc-roll'), '#vc-roll visible with a design loaded').not.toBe('none')

  // --- Close Session → welcome screen ---
  page.on('dialog', d => d.accept().catch(() => {}))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-close-session')
  await expect(page.locator('#welcome-screen')).toBeVisible({ timeout: 10_000 })
  await page.waitForTimeout(300)

  // Both overlays gone.
  expect(await display(page, '#vc-wrap'), '#vc-wrap hidden on welcome').toBe('none')
  expect(await display(page, '#vc-roll'), '#vc-roll hidden on welcome').toBe('none')
  expect(await display(page, '#cando-legend'), '#cando-legend hidden on welcome').toBe('none')
})

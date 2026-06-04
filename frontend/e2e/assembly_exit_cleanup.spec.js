/**
 * Assembly-mode exit cleanup — regression guard.
 *
 * Exiting assembly mode runs the `subscribeSlice('assembly')` tear-down
 * (gizmo detach, renderer dispose, multi-select union-box dispose, listener
 * removal). After extraction #34 made `_assemblyMultiBox` a `const` factory
 * object, the old inline disposal still did `_assemblyMultiBox = null` —
 * an assignment-to-const TypeError that threw on EVERY assembly exit. No test
 * covered this path (the gesture specs never exit), so it escaped. This spec
 * drives enter → exit and asserts the tear-down is clean.
 *
 * Servers auto-start via playwright.config.js. Run on demand:
 *   cd frontend && npx playwright test assembly_exit_cleanup.spec.js
 */
import { test, expect } from '@playwright/test'
import { trackConsoleErrors, loadAssemblyWithParts } from './helpers/scene_harness.js'

const DOC = 'e2e-asm-exit'

test('exiting assembly mode tears down cleanly (no console error)', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  // Build + enter a 2-part assembly.
  const ids = await loadAssemblyWithParts(page, { doc: DOC, n: 2, name: 'exit' })
  expect(ids).toHaveLength(2)
  expect(await page.evaluate(() => window.__nadocTest.isAssemblyActive())).toBe(true)

  // Exit assembly mode → fires the tear-down subscriber. (The multi-box disposal
  // ran unconditionally — the old `_assemblyMultiBox = null` on a const threw
  // here regardless of whether a box mesh was present.)
  await page.evaluate(() => window.__nadocTest.exitAssemblyMode())
  await expect(page.locator('#mode-indicator')).toContainText('WORKSPACE', { timeout: 10_000 })
  expect(await page.evaluate(() => window.__nadocTest.isAssemblyActive())).toBe(false)

  expect(errors, errors.join('\n')).toEqual([])
})

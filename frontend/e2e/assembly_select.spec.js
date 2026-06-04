/**
 * Assembly instance-select gesture (canvas pick).
 *
 * Validates the assembly canvas pointer handlers (_onAssemblyPointerDown +
 * _onAssemblyClick → part selection) through the REAL raycast, asserting on
 * exposed state (`__nadocTest.getActiveInstanceId`) with retry-on-miss — the
 * same robust pattern as measurement_tool.spec.js, but for part INSTANCES
 * rather than backbone beads.
 *
 * This is the gesture GATE for safely lifting the (a)/(b) sub-parts of the
 * Assembly canvas pointer handler region out of main.js (see main_js_carveup.md
 * Tier 3). Unlike assembly_gizmo.spec.js (which selects via the panel row on an
 * empty inline design), this builds a geometry-bearing assembly and clicks the
 * part BODY in the 3D view.
 *
 * Servers auto-start via playwright.config.js. Not in `just smoke` (that's the
 * fast generic boot gate); run on demand:
 *   cd frontend && npx playwright test assembly_select.spec.js
 */
import { test, expect } from '@playwright/test'
import {
  trackConsoleErrors,
  loadAssemblyWithParts,
  assemblyInstanceCandidates,
  selectAssemblyInstance,
  clickEmptyAssemblySpace,
} from './helpers/scene_harness.js'

const DOC = 'e2e-asm-select'

test('canvas click selects a part instance; empty click clears the selection', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  const ids = await loadAssemblyWithParts(page, { doc: DOC, n: 2, name: 'select' })
  expect(ids).toHaveLength(2)

  // Nothing selected on entry.
  expect(await page.evaluate(() => window.__nadocTest.getActiveInstanceId())).toBeNull()

  // Click a part body → it becomes the active instance.
  const active = await selectAssemblyInstance(page)
  expect(ids).toContain(active)

  // Click empty space → selection clears.
  await clickEmptyAssemblySpace(page)
  expect(await page.evaluate(() => window.__nadocTest.getActiveInstanceId())).toBeNull()

  expect(errors, errors.join('\n')).toEqual([])
})

test('clicking a second instance switches the active selection', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  const ids = await loadAssemblyWithParts(page, { doc: DOC, n: 2, name: 'switch' })
  expect(ids).toHaveLength(2)

  // Drive by what's actually pickable on screen (both rods, separated on X).
  const cands = await assemblyInstanceCandidates(page)
  const pickable = [...new Set(cands.map(c => c.id))]
  expect(pickable.length).toBeGreaterThanOrEqual(2)

  const first = await selectAssemblyInstance(page, { id: pickable[0] })
  expect(first).toBe(pickable[0])

  // Clear (also exits the auto-armed MOVE gizmo) before selecting the other, so
  // the gizmo doesn't occlude the second instance's pixel.
  await clickEmptyAssemblySpace(page)

  const second = await selectAssemblyInstance(page, { id: pickable[1] })
  expect(second).toBe(pickable[1])
  expect(second).not.toBe(first)

  expect(errors, errors.join('\n')).toEqual([])
})

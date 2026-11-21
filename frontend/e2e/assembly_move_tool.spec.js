/**
 * Assembly Move/Rotate tool gesture (primary instance transform).
 *
 * Exercises the move-tool path that records a PRIMARY instance transform (as
 * opposed to a part-joint rotation, covered by assembly_joint_drag.spec.js):
 *   _activateTranslateRotateTool (assembly branch → _createAssemblyTransformContext
 *     + _attachGroupGizmo + show the Move/Rotate panel)
 *   → Move/Rotate panel numeric input `change` → _mrCommitInputs
 *     → _queueAssemblyPrimaryCommit → _assemblyPendingTransforms.set(...)
 *   → empty-space click → _onAssemblyClick commits the pending transform.
 *
 * This is the GESTURE GATE for the HARD assembly transform band (Move/Rotate
 * viewport popup + Translate/Rotate tool). Per the #36/#37 ledger lesson,
 * it drives the non-flaky DOM-input commit path — NOT a TransformControls handle
 * drag (those handles are too small to hit at integer pixels). The gizmo's own
 * onLiveTransform/onCommit callbacks feed the SAME _assemblyPendingTransforms map,
 * so this gate covers the observable both paths produce.
 *
 * Servers auto-start via playwright.config.js. Run on demand:
 *   cd frontend && npx playwright test assembly_move_tool.spec.js
 */
import { test, expect } from '@playwright/test'
import {
  trackConsoleErrors,
  loadAssemblyWithParts,
  loadScaffoldedPart,
  activateAssemblyMoveTool,
  moveActiveInstanceViaPanel,
  clickEmptyAssemblySpace,
} from './helpers/scene_harness.js'

const DOC = '__e2e__asm-move'
test.setTimeout(120_000)
test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1800, height: 1000 })
})

async function expectViewportPopup(page) {
  const popup = page.locator('.tool-popup[data-tool-panel="move-rotate-panel"]')
  await expect(popup).toBeVisible()
  await expect(page.locator('#right-panel #move-rotate-panel')).toHaveCount(0)
  const box = await popup.boundingBox(), canvas = await page.locator('#canvas').boundingBox()
  expect(box.x).toBeGreaterThanOrEqual(canvas.x)
  expect(box.y).toBeGreaterThanOrEqual(canvas.y)
  expect(box.x + box.width).toBeLessThanOrEqual(canvas.x + canvas.width + 1)
  expect(box.y + box.height).toBeLessThanOrEqual(canvas.y + canvas.height + 1)
  return popup
}

test('part Move/Rotate opens in the viewport and close cancels its preview', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__part-move-popup', name: 'part-move-popup' })
  const clusterId = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.cluster_transforms[0].id)
  await page.evaluate(id => window.__nadocTest.activateDesignMoveTool(id), clusterId)
  const popup = await expectViewportPopup(page)
  await page.locator('#mr-tx').fill('3')
  await page.locator('#mr-tx').press('Tab')
  await expect(page.locator('#mr-tx')).toHaveValue('3.000')
  await popup.getByRole('button', { name: 'Close Move / Rotate', exact: true }).click()
  await expect(popup).not.toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().translateRotateActive)).toBe(false)
  await page.evaluate(id => window.__nadocTest.activateDesignMoveTool(id), clusterId)
  await expect(popup).toBeVisible()
  await expect(page.locator('#mr-tx')).toHaveValue('0.000')
  await page.locator('#mr-cancel-btn').click()
  expect(errors, errors.join('\n')).toEqual([])
})

test('Move/Rotate tool records a primary instance transform and commits it on empty click', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  const [activeId] = await loadAssemblyWithParts(page, { doc: DOC, n: 2, name: 'move', frame: false })

  // Use the real assembly tree so this panel test does not depend on pixel picking.
  await page.locator(`#assembly-panel [data-instance-id="${activeId}"]`).click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getActiveInstanceId())).toBe(activeId)

  // No pending primary transform before the move.
  const before = await page.evaluate(() => window.__nadocTest.getAssemblyPendingTransforms())
  expect(before).toHaveLength(0)

  // Activate the Move/Rotate tool on the active instance → tool arms + panel shows.
  const armed = await activateAssemblyMoveTool(page)
  expect(armed, 'translateRotateActive should be true after activating the tool').toBe(true)

  await expectViewportPopup(page)

  // Set a +5 nm Z translation via the panel inputs (the real DOM commit path).
  const pending = await moveActiveInstanceViaPanel(page, { tz: 5 })
  const mine = pending.find(p => p.instanceId === activeId)
  expect(mine, `pending=${JSON.stringify(pending)}`).toBeTruthy()
  expect(mine.translation[2]).toBeCloseTo(5, 1)

  // Click empty space → _onAssemblyClick commits the pending transform (clears it).
  await clickEmptyAssemblySpace(page)
  const after = await page.evaluate(() => window.__nadocTest.getAssemblyPendingTransforms())
  expect(after, `still pending after commit: ${JSON.stringify(after)}`).toHaveLength(0)

  expect(errors, errors.join('\n')).toEqual([])
})

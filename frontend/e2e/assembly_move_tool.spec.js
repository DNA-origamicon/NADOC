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
 * right-sidebar panel + Translate/Rotate tool). Per the #36/#37 ledger lesson,
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
  selectAssemblyInstance,
  activateAssemblyMoveTool,
  moveActiveInstanceViaPanel,
  clickEmptyAssemblySpace,
} from './helpers/scene_harness.js'

const DOC = 'e2e-asm-move'

test('Move/Rotate tool records a primary instance transform and commits it on empty click', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  await loadAssemblyWithParts(page, { doc: DOC, n: 2, name: 'move' })

  // Select an instance (any pickable one) → it becomes the active instance.
  const activeId = await selectAssemblyInstance(page, {})
  expect(activeId, 'an instance should select').toBeTruthy()

  // No pending primary transform before the move.
  const before = await page.evaluate(() => window.__nadocTest.getAssemblyPendingTransforms())
  expect(before).toHaveLength(0)

  // Activate the Move/Rotate tool on the active instance → tool arms + panel shows.
  const armed = await activateAssemblyMoveTool(page)
  expect(armed, 'translateRotateActive should be true after activating the tool').toBe(true)

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

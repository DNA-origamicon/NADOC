/**
 * Assembly part-joint ring-drag gesture (cluster rotation).
 *
 * Exercises the part-joint drag path in the assembly canvas pointer handlers:
 *   _onAssemblyPointerDown (Priority 2b — selected cluster + allow_part_joints)
 *     → _partJointDrag → _updatePartJointDrag (builds the revolute world-delta
 *     via gear_math.rotationDeltaMatrix) → _onAssemblyDragUp (commits a pending
 *     part-joint).
 *
 * This is the GESTURE GATE for the (a) sub-part of the Assembly canvas pointer
 * handler region, and retroactively covers the rotationDeltaMatrix dedup
 * (extraction #28) — the only production change in that batch with no automated
 * coverage. Drives a REAL pointer drag through the real raycast and asserts on
 * exposed state (the recorded joint rotation), like assembly_select.spec.js.
 *
 * Servers auto-start via playwright.config.js. Run on demand:
 *   cd frontend && npx playwright test assembly_joint_drag.spec.js
 */
import { test, expect } from '@playwright/test'
import {
  trackConsoleErrors,
  loadAssemblyWithClusterJoint,
  dragPartJointRing,
} from './helpers/scene_harness.js'

const DOC = 'e2e-asm-joint'

test('dragging a selected cluster rotates it about its joint (records a part-joint rotation)', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  const { instanceId, clusterId } = await loadAssemblyWithClusterJoint(page, { doc: DOC, name: 'jdrag' })
  expect(instanceId).toBeTruthy()
  expect(clusterId).toBeTruthy()

  // No pending part-joint before the drag.
  const before = await page.evaluate(() => window.__nadocTest.getAssemblyPendingPartJoints())
  expect(before).toHaveLength(0)

  // Drag the cluster's ring → a non-zero rotation is recorded for this cluster.
  const pending = await dragPartJointRing(page, { instanceId, clusterId })
  const mine = pending.find(p => p.key === `${instanceId}:${clusterId}`)
  expect(mine, `pending=${JSON.stringify(pending)}`).toBeTruthy()
  expect(Math.abs(mine.jointValue)).toBeGreaterThan(1e-6)

  expect(errors, errors.join('\n')).toEqual([])
})

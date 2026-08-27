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
  frameAssembly,
} from './helpers/scene_harness.js'

const DOC = 'e2e-asm-select'

/** Ctrl+click a part instance: hold Control so the pointerdown carries ctrlKey
 *  (which arms the lasso; a zero-distance drag finalizes as a Ctrl-click toggle).
 *  Retries candidate pixels until the multi-select set changes. Returns the
 *  toggled id (or null on miss). */
async function ctrlClickInstance(page, { id = null } = {}) {
  await frameAssembly(page)
  const cands = await assemblyInstanceCandidates(page)
  const targets = id ? cands.filter(c => c.id === id) : cands
  // Signature = active id + sorted multi-set, so a toggle-OFF (set shrinks /
  // active clears) is detected too, not just an add.
  const sig = async () => JSON.stringify([
    await page.evaluate(() => window.__nadocTest.getActiveInstanceId()),
    (await getMultiSelected(page)).slice().sort(),
  ])
  const before = await sig()
  for (const c of targets) {
    await page.keyboard.down('Control')
    await page.mouse.click(Math.round(c.x), Math.round(c.y))
    await page.keyboard.up('Control')
    await page.waitForTimeout(250)
    if ((await sig()) !== before) return c.id
  }
  return null
}

function getMultiSelected(page) {
  return page.evaluate(() => window.__nadocTest.getMultiSelectedInstanceIds?.() ?? [])
}

test('canvas click selects a part instance; empty click clears the selection', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  const ids = await loadAssemblyWithParts(page, { doc: `${DOC}-select`, n: 2, name: 'select' })
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

  const ids = await loadAssemblyWithParts(page, { doc: `${DOC}-switch`, n: 2, name: 'switch' })
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

// ISSUE-3 (issues_ledger.md): Ctrl+click multi-select feedback. Two symptoms:
//   (a) a single Ctrl+click showed NO visual feedback (union box gated at ≥2);
//   (b) plain-click A then Ctrl+click A left a phantom size-1 multi-set that drew
//       nothing and re-surfaced when another part was added.
//
// The fix is split across THREE tests, by what each layer can actually observe:
//   - The box's white-for-1 / purple-for-2+ rendering (symptom a's visual + the
//     decision-3 color rule) is pinned in src/scene/assembly_multi_box.test.js —
//     it mocks getInstanceCenters(), which is EMPTY in this e2e fixture (the
//     renderer never materializes these instances' centers, so NO box draws here
//     at any count — see loadAssemblyWithParts). So box visibility is NOT
//     asserted in e2e.
//   - The toggle SET math (fold the active pick in = decision 1; remove on
//     re-click = decision 2) is pinned in src/scene/assembly_lasso.test.js
//     (toggleInstanceSelection).
//   - This e2e gates the GESTURE WIRING through the real raycast: that a Ctrl+click
//     reaches the toggle AND that it reads activeInstanceId. The discriminating
//     case is 3b (Ctrl+click the active part → clean empty; pre-fix left [a]).
//     The "plain A then Ctrl+click a DIFFERENT part" case can't run here — the
//     auto-armed move gizmo on A occludes the second rod in this tightly-spaced
//     fixture — so its active-fold is covered by the unit test above.

test('ISSUE-3b: Ctrl+click the only selected part deselects it cleanly', async ({ page }) => {
  const errors = trackConsoleErrors(page)

  const ids = await loadAssemblyWithParts(page, { doc: `${DOC}-ctrl2`, n: 2, name: 'ctrl2' })
  expect(ids).toHaveLength(2)

  const cands = await assemblyInstanceCandidates(page)
  const pickable = [...new Set(cands.map(c => c.id))]
  const a = await selectAssemblyInstance(page, { id: pickable[0] })
  expect(a).toBe(pickable[0])

  // Ctrl+click the already-active part → toggles it OFF (decision 2). The fix
  // reads activeInstanceId, so the selection ends CLEAN: nothing active, EMPTY
  // multi-set. Pre-fix the toggle ignored active and left a phantom [a].
  await ctrlClickInstance(page, { id: a })
  expect(await page.evaluate(() => window.__nadocTest.getActiveInstanceId())).toBeNull()
  expect(await getMultiSelected(page)).toEqual([])

  expect(errors, errors.join('\n')).toEqual([])
})

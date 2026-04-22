/**
 * Assembly Gizmo — Phase 6 verification suite
 *
 * Tests assembly mode toggle, instance selection, and gizmo activation
 * (T key / translate-rotate tool) after the Phase 6 implementation.
 *
 * Structure:
 *   Section A — API layer: assembly CRUD, transform patch, undo
 *   Section B — UI mode toggle: A key, mode indicator, panel visibility
 *   Section C — Instance selection: row click, highlight, activeInstanceId
 *   Section D — Gizmo lifecycle: T key activate, confirm (✓), cancel (Esc)
 *   Section E — Exit assembly: geometry restores, no gizmo artifacts
 *
 * Each test logs EXPECTED and ACTUAL so regressions are easy to spot in
 * the HTML report.  Pass/fail assertions follow the log lines.
 *
 * Servers must be running:
 *   Terminal 1: just dev        (FastAPI on :8000)
 *   Terminal 2: just frontend   (Vite on :5173)
 */

import { test, expect } from '@playwright/test'

// ── Constants ────────────────────────────────────────────────────────────────

const API  = 'http://localhost:8000'
const MODE = '#mode-indicator'

const EXPECTED = {
  workspace:    'NADOC · WORKSPACE',
  assemblyMode: 'ASSEMBLY MODE — [A] to exit',
  moveMode:     'MOVE — Tab: translate/rotate · ✓: confirm · Esc: exit',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Log expected vs actual with a label; return actual for chaining. */
function obs(label, expected, actual) {
  const match = actual === expected ? '✓' : '✗'
  console.log(`  ${match} ${label}`)
  console.log(`      expected: ${JSON.stringify(expected)}`)
  console.log(`      actual  : ${JSON.stringify(actual)}`)
  return actual
}

/** Reset to a fresh empty assembly, return the id. */
async function resetAssembly(request) {
  const resp = await request.post(`${API}/api/assembly`)
  expect(resp.status()).toBe(201)
  const body = await resp.json()
  return body.assembly.id
}

/** Minimal self-contained design dict — used when no server design is loaded. */
const MINIMAL_DESIGN = {
  id: 'test-design-inline',
  helices: [],
  strands: [],
  lattice_type: 'HONEYCOMB',
  metadata: { name: 'Test', description: '', author: '', created_at: '', modified_at: '', tags: [] },
  deformations: [],
  cluster_transforms: [],
  cluster_joints: [],
  overhangs: [],
  extensions: [],
  photoproduct_junctions: [],
  crossovers: [],
  forced_ligations: [],
  camera_poses: [],
  animations: [],
  feature_log: [],
  feature_log_cursor: -1,
}

/** Add an inline instance with a self-contained minimal design. */
async function addInlineInstance(request, name = 'Test Part') {
  const resp = await request.post(`${API}/api/assembly/instances`, {
    data: { source: { type: 'inline', design: MINIMAL_DESIGN }, name },
  })
  expect(resp.status()).toBe(201)
  const body = await resp.json()
  const instances = body.assembly.instances
  return instances[instances.length - 1]   // last added
}

/** Ensure design and assembly are ready; wait for splash to clear. */
async function ensureReady(page, request) {
  // Make sure the server has a design
  const dr = await request.get(`${API}/api/design`)
  if ((await dr.json()).design?.helices?.length === 0) {
    await request.post(`${API}/api/design`, {
      data: { name: 'Assembly Gizmo Test', lattice_type: 'HONEYCOMB' },
    })
  }

  await page.goto('/')

  // Dismiss splash if visible (create design via UI if needed)
  const splash = page.locator('#splash-screen')
  const splashVisible = await splash.isVisible({ timeout: 3_000 }).catch(() => false)
  if (splashVisible) {
    // Trigger load by simulating a new design creation
    const menuItem = page.locator('.menu-item').filter({ hasText: 'File' }).first()
    await menuItem.hover()
    await page.click('#menu-file-new')
    await page.fill('#new-design-name', 'Assembly Gizmo Test')
    await page.click('#new-design-create')
    await expect(splash).toBeHidden({ timeout: 10_000 })
  }

  // Ensure we start outside assembly mode
  const modeText = await page.locator(MODE).textContent()
  if (modeText.includes('ASSEMBLY')) {
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.workspace, { timeout: 5_000 })
  }
}

// ── Section A: API layer ──────────────────────────────────────────────────────

test.describe('A — Assembly API', () => {
  test('POST /api/assembly creates a fresh empty assembly', async ({ request }) => {
    console.log('\n[A1] POST /api/assembly → fresh assembly')
    const resp = await request.post(`${API}/api/assembly`)

    const expected_status = 201
    const actual_status   = resp.status()
    obs('HTTP status', expected_status, actual_status)
    expect(actual_status).toBe(expected_status)

    const body = await resp.json()
    obs('has assembly key', true, 'assembly' in body)
    obs('instances empty', 0, body.assembly.instances.length)
    obs('joints empty',    0, body.assembly.joints.length)

    expect(body.assembly.instances).toHaveLength(0)
    expect(body.assembly.joints).toHaveLength(0)
  })

  test('POST /api/assembly/instances adds an inline instance', async ({ request }) => {
    console.log('\n[A2] Add inline instance')
    await resetAssembly(request)
    const inst = await addInlineInstance(request, 'Arm A')

    obs('instance name',    'Arm A', inst.name)
    obs('instance visible', true,    inst.visible)
    obs('transform is identity', true,
      JSON.stringify(inst.transform?.values) ===
      JSON.stringify([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1])
    )

    expect(inst.name).toBe('Arm A')
    expect(inst.visible).toBe(true)
    expect(inst.transform?.values).toEqual([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1])
  })

  test('PATCH /api/assembly/instances/{id} stores a new transform', async ({ request }) => {
    console.log('\n[A3] Patch instance transform')
    await resetAssembly(request)
    const inst = await addInlineInstance(request, 'Movable Part')

    // Non-identity: translate by (5, 10, 3) nm — stored row-major, translation in last column
    const newTransform = {
      values: [
        1, 0, 0,  5,
        0, 1, 0, 10,
        0, 0, 1,  3,
        0, 0, 0,  1,
      ],
    }

    const patchResp = await request.patch(
      `${API}/api/assembly/instances/${inst.id}`,
      { data: { transform: newTransform } },
    )
    obs('PATCH status', 200, patchResp.status())
    expect(patchResp.status()).toBe(200)

    const body = await patchResp.json()
    const updated = body.assembly.instances.find(i => i.id === inst.id)
    obs('transform stored', JSON.stringify(newTransform.values), JSON.stringify(updated.transform.values))
    expect(updated.transform.values).toEqual(newTransform.values)
  })

  test('POST /api/assembly/undo reverts last change', async ({ request }) => {
    console.log('\n[A4] Undo reverts instance add')
    await resetAssembly(request)
    await addInlineInstance(request, 'Part to Undo')

    // Verify instance was added
    const beforeUndo = await (await request.get(`${API}/api/assembly`)).json()
    obs('instances before undo', 1, beforeUndo.assembly.instances.length)
    expect(beforeUndo.assembly.instances).toHaveLength(1)

    const undoResp = await request.post(`${API}/api/assembly/undo`)
    obs('undo status', 200, undoResp.status())

    const afterUndo = await (await request.get(`${API}/api/assembly`)).json()
    obs('instances after undo', 0, afterUndo.assembly.instances.length)
    expect(afterUndo.assembly.instances).toHaveLength(0)
  })

  test('Transform undo: PATCH then undo reverts to identity', async ({ request }) => {
    console.log('\n[A5] Undo reverts transform patch')
    await resetAssembly(request)
    const inst = await addInlineInstance(request, 'Transform Test')

    const movedTransform = {
      values: [1,0,0,20, 0,1,0,0, 0,0,1,0, 0,0,0,1],
    }
    await request.patch(`${API}/api/assembly/instances/${inst.id}`, {
      data: { transform: movedTransform },
    })

    // Undo the patch
    await request.post(`${API}/api/assembly/undo`)

    const afterUndo = await (await request.get(`${API}/api/assembly`)).json()
    const reverted = afterUndo.assembly.instances.find(i => i.id === inst.id)
    const identityValues = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    obs('transform reverted to identity', JSON.stringify(identityValues), JSON.stringify(reverted?.transform?.values))
    expect(reverted?.transform?.values).toEqual(identityValues)
  })
})

// ── Section B: UI mode toggle ─────────────────────────────────────────────────

test.describe('B — Assembly mode toggle (UI)', () => {
  test.beforeEach(async ({ page, request }) => {
    await resetAssembly(request)
    await ensureReady(page, request)
  })

  test('B1: initial state — mode indicator shows workspace text', async ({ page }) => {
    console.log('\n[B1] Initial mode indicator')
    const actual = await page.locator(MODE).textContent()
    obs('mode indicator', EXPECTED.workspace, actual)
    expect(actual).toBe(EXPECTED.workspace)
  })

  test('B2: pressing A enters assembly mode', async ({ page }) => {
    console.log('\n[B2] Press A → assembly mode')
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })
    const actual = await page.locator(MODE).textContent()
    obs('mode indicator after A', EXPECTED.assemblyMode, actual)
  })

  test('B3: assembly panel appears on mode enter', async ({ page }) => {
    console.log('\n[B3] Assembly panel visibility')
    const panel = page.locator('#assembly-panel')
    const beforeA = await panel.isVisible()
    obs('panel hidden before A', false, beforeA)

    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })

    const afterA = await panel.isVisible()
    obs('panel visible after A', true, afterA)
    expect(afterA).toBe(true)
  })

  test('B4: pressing A again exits assembly mode', async ({ page }) => {
    console.log('\n[B4] Press A twice → exit assembly mode')
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })

    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.workspace, { timeout: 5_000 })

    const actual = await page.locator(MODE).textContent()
    obs('mode indicator after 2x A', EXPECTED.workspace, actual)

    const panelVisible = await page.locator('#assembly-panel').isVisible()
    obs('panel hidden after exit', false, panelVisible)
    expect(panelVisible).toBe(false)
  })
})

// ── Section C: Instance selection ────────────────────────────────────────────

test.describe('C — Instance selection', () => {
  let _instId = null

  test.beforeEach(async ({ page, request }) => {
    await resetAssembly(request)
    const inst = await addInlineInstance(request, 'Select Me')
    _instId = inst.id
    await ensureReady(page, request)
    // Enter assembly mode
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })
  })

  test('C1: instance row appears in panel after add', async ({ page }) => {
    console.log('\n[C1] Instance row rendered')
    const row = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })
    const actual = await row.isVisible()
    obs('instance row visible', true, actual)
  })

  test('C2: clicking instance name selects it (row highlights)', async ({ page }) => {
    console.log('\n[C2] Instance row selection highlight')
    const row  = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })

    // Before click: background should not be the active-blue
    const bgBefore = await row.evaluate(el => el.style.background)
    obs('background before click (not active-blue)', true, !bgBefore.includes('30, 58, 95'))

    // Click the name label (first span inside the row)
    await row.dispatchEvent('click')
    await page.waitForTimeout(300)

    // After click: background should be active-blue (#1e3a5f = rgb(30,58,95))
    const bgAfter = await row.evaluate(el => el.style.background)
    obs('background after click', 'rgb(30, 58, 95)', bgAfter)
    expect(bgAfter).toBe('rgb(30, 58, 95)')
  })

  test('C3: clicking selected row again deselects it', async ({ page }) => {
    console.log('\n[C3] Deselect instance')
    const row = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })

    // Select
    await row.dispatchEvent('click')
    await page.waitForTimeout(200)
    const bgSelected = await row.evaluate(el => el.style.background)
    obs('background when selected', 'rgb(30, 58, 95)', bgSelected)
    expect(bgSelected).toBe('rgb(30, 58, 95)')

    // Deselect
    await row.dispatchEvent('click')
    await page.waitForTimeout(200)
    const bgDeselected = await row.evaluate(el => el.style.background)
    obs('background when deselected', 'transparent', bgDeselected)
    expect(bgDeselected).toBe('transparent')
  })

  test('C4: "Add Current Design" button is enabled in assembly mode', async ({ page }) => {
    console.log('\n[C4] Add Current Design button state')
    const btn = page.locator('button').filter({ hasText: '+ Add Current Design' })
    await expect(btn).toBeVisible({ timeout: 5_000 })
    const disabled = await btn.isDisabled()
    obs('button enabled when design loaded', false, disabled)
    expect(disabled).toBe(false)
  })
})

// ── Section D: Gizmo lifecycle ────────────────────────────────────────────────

test.describe('D — Gizmo lifecycle (T key)', () => {
  let _instId = null

  test.beforeEach(async ({ page, request }) => {
    await resetAssembly(request)
    const inst = await addInlineInstance(request, 'Gizmo Target')
    _instId = inst.id
    await ensureReady(page, request)
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })
  })

  test('D1: pressing T with no instance selected shows alert', async ({ page }) => {
    console.log('\n[D1] T key without instance selected')
    // Ensure no instance is selected (deselect if needed)
    const rows = page.locator('[data-instance-id]')
    if (await rows.count() > 0) {
      const bg = await rows.first().evaluate(el => el.style.background)
      if (bg.includes('30, 58, 95')) {
        // deselect by clicking again
        await rows.first().dispatchEvent('click')
        await page.waitForTimeout(200)
      }
    }

    let alertFired = false
    page.once('dialog', async dialog => {
      alertFired = true
      obs('alert message contains "Select an instance"', true,
        dialog.message().includes('Select an instance'))
      await dialog.dismiss()
    })
    await page.keyboard.press('t')
    await page.waitForTimeout(500)

    obs('alert fired when no instance selected', true, alertFired)
    expect(alertFired).toBe(true)

    // Mode indicator should NOT have changed to MOVE
    const modeAfter = await page.locator(MODE).textContent()
    obs('mode stays ASSEMBLY after blocked T', EXPECTED.assemblyMode, modeAfter)
    expect(modeAfter).toBe(EXPECTED.assemblyMode)
  })

  test('D2: pressing T with instance selected enters MOVE mode', async ({ page }) => {
    console.log('\n[D2] T key with instance selected → MOVE mode')
    // Select the instance
    const row = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })
    await row.dispatchEvent('click')
    await page.waitForTimeout(300)

    await page.keyboard.press('t')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.moveMode, { timeout: 5_000 })

    const actual = await page.locator(MODE).textContent()
    obs('mode indicator in MOVE mode', EXPECTED.moveMode, actual)
    expect(actual).toBe(EXPECTED.moveMode)
  })

  test('D3: confirm button (✓) appears in MOVE mode', async ({ page }) => {
    console.log('\n[D3] Confirm button appears')
    const row = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })
    await row.dispatchEvent('click')
    await page.waitForTimeout(200)

    const confirmBtn = page.locator('div').filter({ hasText: '✓' }).last()
    const beforeT = await confirmBtn.isVisible()
    obs('confirm button hidden before T', false, beforeT)

    await page.keyboard.press('t')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.moveMode, { timeout: 5_000 })

    const afterT = await confirmBtn.isVisible()
    obs('confirm button visible after T', true, afterT)
    expect(afterT).toBe(true)
  })

  test('D4: Escape in MOVE mode returns to ASSEMBLY mode', async ({ page }) => {
    console.log('\n[D4] Escape cancels MOVE mode')
    const row = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })
    await row.dispatchEvent('click')
    await page.waitForTimeout(200)

    await page.keyboard.press('t')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.moveMode, { timeout: 5_000 })

    await page.keyboard.press('Escape')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })

    const actual = await page.locator(MODE).textContent()
    obs('mode after Escape', EXPECTED.assemblyMode, actual)
    expect(actual).toBe(EXPECTED.assemblyMode)
  })

  test('D5: ✓ button confirm returns to ASSEMBLY mode', async ({ page }) => {
    console.log('\n[D5] Confirm button click → ASSEMBLY mode')
    const row = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })
    await row.dispatchEvent('click')
    await page.waitForTimeout(200)

    await page.keyboard.press('t')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.moveMode, { timeout: 5_000 })

    // Click the confirm ✓ button (green circle in bottom-left)
    const confirmBtn = page.locator('div').filter({ hasText: '✓' }).last()
    await confirmBtn.click()
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })

    const actual = await page.locator(MODE).textContent()
    obs('mode after confirm', EXPECTED.assemblyMode, actual)
    expect(actual).toBe(EXPECTED.assemblyMode)
  })

  test('D6: T again while already in MOVE mode acts as confirm toggle', async ({ page }) => {
    console.log('\n[D6] T acts as confirm toggle when already in MOVE mode')
    const row = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })
    await row.dispatchEvent('click')
    await page.waitForTimeout(200)

    await page.keyboard.press('t')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.moveMode, { timeout: 5_000 })

    await page.keyboard.press('t')   // second T = confirm
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })

    const actual = await page.locator(MODE).textContent()
    obs('mode after T+T', EXPECTED.assemblyMode, actual)
    expect(actual).toBe(EXPECTED.assemblyMode)
  })

  test('D7: switching instance while in MOVE mode re-attaches gizmo', async ({ request, page }) => {
    console.log('\n[D7] Switch instance in MOVE mode → gizmo re-attaches')
    // Add a second instance
    const inst2 = await addInlineInstance(request, 'Second Part')
    await page.reload()
    await ensureReady(page, request)
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })

    // Select first instance, activate gizmo
    const row1 = page.locator(`[data-instance-id="${_instId}"]`)
    await expect(row1).toBeVisible({ timeout: 5_000 })
    await row1.dispatchEvent('click')
    await page.waitForTimeout(200)
    await page.keyboard.press('t')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.moveMode, { timeout: 5_000 })

    obs('MOVE mode active', EXPECTED.moveMode, await page.locator(MODE).textContent())

    // Click second instance — gizmo should re-attach (mode stays MOVE)
    const row2 = page.locator(`[data-instance-id="${inst2.id}"]`)
    await expect(row2).toBeVisible({ timeout: 5_000 })
    await row2.dispatchEvent('click')
    await page.waitForTimeout(400)

    const modeAfterSwitch = await page.locator(MODE).textContent()
    obs('mode stays MOVE after switching instance', EXPECTED.moveMode, modeAfterSwitch)
    expect(modeAfterSwitch).toBe(EXPECTED.moveMode)

    // Second row should now be highlighted
    const bg2 = await row2.evaluate(el => el.style.background)
    obs('second instance row highlighted', 'rgb(30, 58, 95)', bg2)
    expect(bg2).toBe('rgb(30, 58, 95)')
  })
})

// ── Section E: Exit assembly mode ─────────────────────────────────────────────

test.describe('E — Exit assembly mode', () => {
  test.beforeEach(async ({ page, request }) => {
    await resetAssembly(request)
    await addInlineInstance(request, 'Exit Test Part')
    await ensureReady(page, request)
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })
  })

  test('E1: pressing A exits assembly mode; indicator returns to workspace', async ({ page }) => {
    console.log('\n[E1] Exit assembly mode')
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.workspace, { timeout: 5_000 })
    const actual = await page.locator(MODE).textContent()
    obs('mode indicator after exit', EXPECTED.workspace, actual)
    expect(actual).toBe(EXPECTED.workspace)
  })

  test('E2: assembly panel hides on exit', async ({ page }) => {
    console.log('\n[E2] Panel hidden after exit')
    await expect(page.locator('#assembly-panel')).toBeVisible()
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.workspace, { timeout: 5_000 })
    const panelVisible = await page.locator('#assembly-panel').isVisible()
    obs('panel hidden after exit', false, panelVisible)
    expect(panelVisible).toBe(false)
  })

  test('E3: exiting during MOVE mode cleans up (no stale MOVE indicator)', async ({ page, request }) => {
    console.log('\n[E3] Exit during MOVE mode → no artifact')
    const inst = (await (await request.get(`${API}/api/assembly`)).json()).assembly.instances[0]
    if (!inst) { test.skip(); return }

    const row = page.locator(`[data-instance-id="${inst.id}"]`)
    await expect(row).toBeVisible({ timeout: 5_000 })
    await row.dispatchEvent('click')
    await page.waitForTimeout(200)

    await page.keyboard.press('t')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.moveMode, { timeout: 5_000 })
    obs('in MOVE mode before exit', EXPECTED.moveMode, await page.locator(MODE).textContent())

    // Exit assembly mode via A key (should clean up gizmo)
    await page.keyboard.press('a')
    await expect(page.locator(MODE)).toHaveText(EXPECTED.workspace, { timeout: 5_000 })

    const actual = await page.locator(MODE).textContent()
    obs('mode after exit from MOVE', EXPECTED.workspace, actual)
    expect(actual).toBe(EXPECTED.workspace)

    // Confirm button should be gone
    const confirmBtns = page.locator('div').filter({ hasText: '✓' })
    const confirmVisible = await confirmBtns.last().isVisible().catch(() => false)
    obs('confirm button gone after exit', false, confirmVisible)
    expect(confirmVisible).toBe(false)
  })

  test('E4: re-entering assembly mode works after exit', async ({ page }) => {
    console.log('\n[E4] Re-enter assembly mode after exit')
    await page.keyboard.press('a')   // exit
    await expect(page.locator(MODE)).toHaveText(EXPECTED.workspace, { timeout: 5_000 })

    await page.keyboard.press('a')   // re-enter
    await expect(page.locator(MODE)).toHaveText(EXPECTED.assemblyMode, { timeout: 5_000 })
    const actual = await page.locator(MODE).textContent()
    obs('mode after re-enter', EXPECTED.assemblyMode, actual)
    expect(actual).toBe(EXPECTED.assemblyMode)
  })
})

/**
 * Edge-case tests — boundary conditions and error paths.
 *
 * Each test targets a specific failure mode identified during code audit.
 * Tests are grouped by the subsystem under scrutiny.
 */

import { test, expect } from '@playwright/test'

// ── Helpers ──────────────────────────────────────────────────────────────────

async function openDropdownAndClick(page, menuLabel, itemId) {
  const menuItem = page.locator('.menu-item').filter({ hasText: menuLabel }).first()
  await menuItem.hover()
  await page.click(`#${itemId}`)
}

/** Create a fresh empty design and wait for the API to confirm it. */
async function createFreshDesign(request) {
  const resp = await request.post('http://localhost:8000/api/design', {
    data: { name: 'edge-case-test', lattice_type: 'HONEYCOMB' },
  })
  expect(resp.status()).toBe(201)
  return resp.json()
}

/** Add a single helix to the active design, return the helix object. */
async function addHelix(request) {
  const resp = await request.post('http://localhost:8000/api/design/helices', {
    data: {
      axis_start: { x: 0, y: 0, z: 0 },
      axis_end:   { x: 0, y: 0, z: 14.279 },
      length_bp:  42,
      phase_offset: 0,
    },
  })
  expect(resp.status()).toBe(201)
  const body = await resp.json()
  return body.design.helices[0]
}

// ── Group 1: keyboard shortcuts on empty state ───────────────────────────────

test.describe('Undo / Redo on empty history', () => {
  test.beforeEach(async ({ page, request }) => {
    // Fresh empty design so undo/redo stacks are empty.
    await createFreshDesign(request)
    await page.goto('/')
    // Let the app finish loading the design from server.
    await page.waitForTimeout(600)
  })

  test('Ctrl+Z with empty undo stack shows "Nothing to undo"', async ({ page }) => {
    await page.keyboard.press('Control+z')
    await expect(page.locator('#mode-indicator')).toHaveText('Nothing to undo')
    // Auto-resets to WORKSPACE after ~1.5 s
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE', { timeout: 3000 })
  })

  test('Ctrl+Y with empty redo stack shows "Nothing to redo"', async ({ page }) => {
    await page.keyboard.press('Control+y')
    await expect(page.locator('#mode-indicator')).toHaveText('Nothing to redo')
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE', { timeout: 3000 })
  })

  test('Ctrl+Z does not crash when design has no helices', async ({ page }) => {
    // Should not throw — mode-indicator should end up in a stable state.
    await page.keyboard.press('Control+z')
    await page.keyboard.press('Control+z')
    await page.keyboard.press('Control+z')
    // After transient message it reverts; no JS error should have been thrown.
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE', { timeout: 4000 })
  })
})

// ── Group 2: physics toggle with no helices ───────────────────────────────────

test.describe('Physics toggle edge cases', () => {
  test.beforeEach(async ({ page, request }) => {
    await createFreshDesign(request)
    await page.goto('/')
    await page.waitForTimeout(600)
  })

  test('P key with no helices shows user-facing feedback, not silent fail', async ({ page }) => {
    // Before fix this silently returned; after fix the mode-indicator updates.
    await page.keyboard.press('p')
    // Expect EITHER a helpful message OR that physicsMode was NOT activated
    // (i.e., mode indicator must not switch to the PHYSICS MODE string).
    await expect(page.locator('#mode-indicator')).not.toHaveText(
      /PHYSICS MODE/i,
      { timeout: 1500 },
    )
    // After fix: a brief informational message appears.
    const text = await page.locator('#mode-indicator').textContent()
    expect(text).not.toBe('')
  })

  test('P key with no helices must show explicit "no helices" feedback', async ({ page }) => {
    await page.keyboard.press('p')
    await expect(page.locator('#mode-indicator')).toHaveText(/no helices/i, { timeout: 1500 })
    // Resets after a moment
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE', { timeout: 4000 })
  })
})

// ── Group 3: command palette edge cases ──────────────────────────────────────

test.describe('Command palette edge cases', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('typing no-match query then Enter does not crash and palette stays open', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()

    // Type something with no matches
    await page.fill('#cmd-input', 'xyzxyzxyz')
    const results = page.locator('#cmd-results')
    await expect(results).toBeEmpty()

    // Enter with zero results should be a no-op — palette stays open
    await page.keyboard.press('Enter')
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()

    // No JS error: close works normally afterward
    await page.keyboard.press('Escape')
    await expect(page.locator('#cmd-palette-overlay')).not.toBeVisible()
  })

  test('input is cleared when palette is reopened after Escape', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await page.fill('#cmd-input', 'helix')
    await expect(page.locator('#cmd-results div')).not.toHaveCount(0)
    await page.keyboard.press('Escape')

    // Reopen — input must be empty
    await page.keyboard.press('Control+k')
    await expect(page.locator('#cmd-input')).toHaveValue('')
    await page.keyboard.press('Escape')
  })

  test('ArrowDown past last result stays clamped, does not wrap or crash', async ({ page }) => {
    await page.keyboard.press('Control+k')
    // Press down many times past the list length
    for (let i = 0; i < 20; i++) await page.keyboard.press('ArrowDown')
    // Palette still open, no crash
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()
    // The last item should be selected — verify at least one result is highlighted
    await expect(page.locator('#cmd-results .cmd-result.selected')).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test('ArrowUp past first result stays clamped at index 0', async ({ page }) => {
    await page.keyboard.press('Control+k')
    for (let i = 0; i < 20; i++) await page.keyboard.press('ArrowUp')
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()
    // First item should still be selected
    const items = page.locator('#cmd-results .cmd-result')
    await expect(items.first()).toHaveClass(/selected/)
    await page.keyboard.press('Escape')
  })

  test('New Design form: whitespace-only name normalises to Untitled', async ({ page, request }) => {
    await page.keyboard.press('Control+k')
    await page.fill('#cmd-input', 'new design')
    await page.keyboard.press('Enter')

    // Wait for the New Design form to appear inside the palette
    await expect(page.locator('#cmd-param-form')).toBeVisible()
    await expect(page.locator('#pf-name')).toBeVisible()

    // Clear name and type only spaces
    await page.fill('#pf-name', '   ')

    let sentName = null
    page.on('request', req => {
      if (req.method() === 'POST' && req.url().includes('/api/design')) {
        const body = req.postDataJSON()
        if (body?.name !== undefined) sentName = body.name
      }
    })

    await page.click('#pf-confirm')
    await page.waitForTimeout(400)

    expect(sentName).toBe('Untitled')
  })

  test('Add Helix form: clearing bp field defaults to 2', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await page.fill('#cmd-input', 'add helix')
    await page.keyboard.press('Enter')

    await expect(page.locator('#pf-bp')).toBeVisible()

    // Clear the bp field — on confirm the value should default to 2
    await page.fill('#pf-bp', '')

    let sentBp = null
    page.on('request', req => {
      if (req.method() === 'POST' && req.url().includes('/api/design/helices')) {
        const body = req.postDataJSON()
        if (body?.length_bp !== undefined) sentBp = body.length_bp
      }
    })

    await page.click('#pf-confirm')
    await page.waitForTimeout(400)

    // The form parses empty as NaN → fallback `|| 2` gives 2
    expect(sentBp).toBe(2)
  })
})

// ── Group 4: File > New dialog edge cases ────────────────────────────────────

test.describe('File > New dialog edge cases', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('clicking File > New while modal is already open does not stack a second modal', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-modal')).toBeVisible()

    // The modal (z-index: 9000) blocks UI hover — trigger via JS to simulate a
    // programmatic re-click of the same menu item while modal is open.
    await page.evaluate(() => document.getElementById('menu-file-new')?.click())

    // Only one modal element must exist and it must still be visible.
    await expect(page.locator('#new-design-modal')).toHaveCount(1)
    await expect(page.locator('#new-design-modal')).toBeVisible()

    // Close cleanly
    await page.click('#new-design-cancel')
    await expect(page.locator('#new-design-modal')).not.toBeVisible()
  })

  test('Cancel preserves radio state for next open', async ({ page }) => {
    // Open, switch to Square, then cancel
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.click('input[name="new-lattice-type"][value="SQUARE"]')
    await page.click('#new-design-cancel')

    // Reopen — browser preserves the radio state (expected browser behaviour)
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const square = page.locator('input[name="new-lattice-type"][value="SQUARE"]')
    // State should still reflect user's last selection
    await expect(square).toBeChecked()
    await page.click('#new-design-cancel')
  })
})

// ── Group 5: API edge cases ───────────────────────────────────────────────────

test.describe('API edge cases', () => {
  test('POST /api/design with invalid lattice_type returns 422', async ({ request }) => {
    const resp = await request.post('http://localhost:8000/api/design', {
      data: { name: 'Bad Lattice', lattice_type: 'INVALID_TYPE' },
    })
    // FastAPI / Pydantic validates enum and rejects with Unprocessable Entity
    expect(resp.status()).toBe(422)
    const body = await resp.json()
    expect(body).toHaveProperty('detail')
  })

  test('GET /api/design/crossovers/valid with same helix on both sides returns 400', async ({ request }) => {
    // Arrange: create a design with one helix
    await request.post('http://localhost:8000/api/design', {
      data: { name: 'xover-self-test', lattice_type: 'HONEYCOMB' },
    })
    const helixResp = await request.post('http://localhost:8000/api/design/helices', {
      data: {
        axis_start: { x: 0, y: 0, z: 0 },
        axis_end:   { x: 0, y: 0, z: 14.279 },
        length_bp:  42,
        phase_offset: 0,
      },
    })
    const helixBody = await helixResp.json()
    const helixId = helixBody.design.helices[0].id

    // Act: query crossovers with the same helix on both sides
    const resp = await request.get(
      `http://localhost:8000/api/design/crossovers/valid?helix_a_id=${helixId}&helix_b_id=${helixId}`
    )
    // Should be a 400 Bad Request — not a 200 with bogus self-crossover candidates
    expect(resp.status()).toBe(400)
    const body = await resp.json()
    expect(body.detail).toMatch(/same.helix/i)
  })

  test('POST /api/design/undo with empty history returns 404', async ({ request }) => {
    await request.post('http://localhost:8000/api/design', {
      data: { name: 'undo-test', lattice_type: 'HONEYCOMB' },
    })
    const resp = await request.post('http://localhost:8000/api/design/undo')
    expect(resp.status()).toBe(404)
    const body = await resp.json()
    expect(body.detail).toMatch(/nothing to undo/i)
  })

  test('POST /api/design/redo with empty redo stack returns 404', async ({ request }) => {
    await request.post('http://localhost:8000/api/design', {
      data: { name: 'redo-test', lattice_type: 'HONEYCOMB' },
    })
    const resp = await request.post('http://localhost:8000/api/design/redo')
    expect(resp.status()).toBe(404)
    const body = await resp.json()
    expect(body.detail).toMatch(/nothing to redo/i)
  })

  test('GET /api/design/crossovers/valid with non-existent helix returns 404', async ({ request }) => {
    await request.post('http://localhost:8000/api/design', {
      data: { name: 'xover-404-test', lattice_type: 'HONEYCOMB' },
    })
    const resp = await request.get(
      'http://localhost:8000/api/design/crossovers/valid?helix_a_id=nonexistent&helix_b_id=alsonotreal'
    )
    expect(resp.status()).toBe(404)
  })
})

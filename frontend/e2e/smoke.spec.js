/**
 * Smoke tests — basic UI and API functionality.
 *
 * These tests verify that the app loads correctly and core interactions work.
 * They require both servers to be running (playwright.config.js starts them
 * automatically via webServer, or reuses existing processes).
 */

import { test, expect } from '@playwright/test'

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Hover a CSS-based dropdown menu by menu label text, then click a dropdown item. */
async function openDropdownAndClick(page, menuLabel, itemId) {
  // CSS hover dropdowns require the mouse to be over the menu-item wrapper
  const menuItem = page.locator('.menu-item').filter({ hasText: menuLabel }).first()
  await menuItem.hover()
  await page.click(`#${itemId}`)
}

// ── App boot ────────────────────────────────────────────────────────────────

test.describe('App boot', () => {
  test('page title is NADOC', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle('NADOC')
  })

  test('Three.js canvas is visible', async ({ page }) => {
    await page.goto('/')
    const canvas = page.locator('#canvas')
    await expect(canvas).toBeVisible()
    // Canvas should have non-zero dimensions
    const box = await canvas.boundingBox()
    expect(box.width).toBeGreaterThan(100)
    expect(box.height).toBeGreaterThan(100)
  })

  test('menu bar is rendered with expected menus', async ({ page }) => {
    await page.goto('/')
    const menuBar = page.locator('#menu-bar')
    await expect(menuBar).toBeVisible()
    await expect(menuBar.locator('.menu-item > button', { hasText: 'File' })).toBeVisible()
    await expect(menuBar.locator('.menu-item > button', { hasText: 'Edit' })).toBeVisible()
    await expect(menuBar.locator('.menu-item > button', { hasText: 'View' })).toBeVisible()
  })

  test('mode indicator shows NADOC · WORKSPACE on load', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE')
  })
})

// ── File > New ───────────────────────────────────────────────────────────────

test.describe('File > New Part dialog', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('opens when File > New Part is clicked', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const modal = page.locator('#new-design-modal')
    await expect(modal).toBeVisible()
    await expect(modal).toContainText('New Part')
  })

  test('modal has a required name field', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-name')).toBeVisible()
    await expect(page.locator('#new-design-name')).toHaveValue('')
  })

  test('Create button is disabled until name is entered', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const createBtn = page.locator('#new-design-create')
    await expect(createBtn).toBeDisabled()
    await page.fill('#new-design-name', 'My Part')
    await expect(createBtn).toBeEnabled()
    await page.fill('#new-design-name', '')
    await expect(createBtn).toBeDisabled()
  })

  test('shows Honeycomb and Square lattice options', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const modal = page.locator('#new-design-modal')
    await expect(modal).toContainText('Honeycomb lattice')
    await expect(modal).toContainText('Square lattice')
  })

  test('Honeycomb radio is selected by default', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const honeycombRadio = page.locator('input[name="new-lattice-type"][value="HONEYCOMB"]')
    await expect(honeycombRadio).toBeChecked()
  })

  test('Cancel closes the dialog', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-modal')).toBeVisible()
    await page.click('#new-design-cancel')
    await expect(page.locator('#new-design-modal')).not.toBeVisible()
  })

  test('splash screen hides after Create', async ({ page }) => {
    await expect(page.locator('#splash-screen')).toBeVisible()
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', 'Test Part')
    await page.click('#new-design-create')
    await expect(page.locator('#splash-screen')).not.toBeVisible()
  })

  test('Create with Honeycomb closes the dialog and calls API with part name', async ({ page }) => {
    const apiCall = page.waitForRequest(req =>
      req.method() === 'POST' && req.url().includes('/api/design')
    )

    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', 'My Honeycomb Part')
    await page.click('#new-design-create')

    await expect(page.locator('#new-design-modal')).not.toBeVisible()
    const req = await apiCall
    expect(req.postDataJSON()?.name).toBe('My Honeycomb Part')
  })

  test('Create with Square lattice fires API with SQUARE lattice type', async ({ page }) => {
    let capturedBody = null
    page.on('request', req => {
      if (req.method() === 'POST' && req.url().includes('/api/design')) {
        capturedBody = req.postDataJSON()
      }
    })

    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', 'Square Test')
    await page.click('input[name="new-lattice-type"][value="SQUARE"]')
    await page.click('#new-design-create')

    await expect(page.locator('#new-design-modal')).not.toBeVisible()
    await page.waitForTimeout(500) // let request fire
    expect(capturedBody?.lattice_type).toBe('SQUARE')
  })
})

// ── Command palette ──────────────────────────────────────────────────────────

test.describe('Command palette', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('opens with Ctrl+K', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()
    await expect(page.locator('#cmd-input')).toBeFocused()
  })

  test('closes with Escape', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.locator('#cmd-palette-overlay')).not.toBeVisible()
  })

  test('filters commands as user types', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await page.fill('#cmd-input', 'scaffold')
    // Should show results matching "scaffold"
    const results = page.locator('#cmd-results')
    await expect(results).not.toBeEmpty()
  })
})

// ── API connectivity ─────────────────────────────────────────────────────────

test.describe('API', () => {
  test('GET /api/design returns a valid design', async ({ request }) => {
    const resp = await request.get('http://localhost:8000/api/design')
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    expect(body).toHaveProperty('design')
    expect(body.design).toHaveProperty('metadata')
    expect(body.design).toHaveProperty('helices')
    expect(body.design).toHaveProperty('strands')
  })

  test('POST /api/design creates a new empty design', async ({ request }) => {
    const resp = await request.post('http://localhost:8000/api/design', {
      data: { name: 'Playwright Test Design', lattice_type: 'HONEYCOMB' },
    })
    expect(resp.status()).toBe(201)
    const body = await resp.json()
    expect(body.design.metadata.name).toBe('Playwright Test Design')
    expect(body.design.helices).toHaveLength(0)
  })

  test('GET /api/design/geometry returns geometry data', async ({ request }) => {
    // First create a fresh design
    await request.post('http://localhost:8000/api/design', {
      data: { name: 'geo-test', lattice_type: 'HONEYCOMB' },
    })
    const resp = await request.get('http://localhost:8000/api/design/geometry')
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    // Geometry response shape: { helix_axes: [...], nucleotides: [...] }
    expect(body).toHaveProperty('helix_axes')
    expect(body).toHaveProperty('nucleotides')
  })
})

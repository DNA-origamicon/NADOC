/**
 * Smoke tests — basic UI and API functionality.
 *
 * These tests verify that the app loads correctly and core interactions work.
 * They require both servers to be running (playwright.config.js starts them
 * automatically via webServer, or reuses existing processes).
 */

import { test, expect } from '@playwright/test'
import path from 'node:path'

// Representative design loaded by the console-error gate below. teeth.nadoc (the
// CLAUDE.md example) does not exist in Examples/; 26hb_platform_v3 is a real
// 26-helix honeycomb bundle — substantial enough to exercise the render paths,
// small enough (~22 KB) to keep the gate fast.
const SMOKE_DESIGN = '26hb_platform_v3.nadoc'

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
  test('page title is NADOC 3D', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle('NADOC 3D')
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
    // Match only the top-level menu labels (direct children of #menu-bar) with
    // exact text — dropdowns contain nested .menu-item entries (e.g. "Edit…") that
    // would otherwise make a loose ".menu-item > button" match resolve to >1 element.
    for (const label of ['File', 'Edit', 'View']) {
      await expect(
        page.locator('#menu-bar > .menu-item > button').filter({ hasText: new RegExp(`^${label}$`) }),
      ).toBeVisible()
    }
  })

  test('mode indicator shows NADOC · WORKSPACE on load', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE')
  })

  test('welcome screen renders on boot', async ({ page }) => {
    await page.goto('/')
    // The welcome screen mounts the library panel (the primary New-Part entry point).
    await expect(page.locator('#welcome-screen')).toBeVisible()
    await expect(page.locator('#library-panel-mount')).toBeVisible()
  })
})

// ── File > New ───────────────────────────────────────────────────────────────
//
// The dialog chrome is now built by createModal(): the form fields live in the
// (un-hidden) #new-design-modal-body, the header title is .modal__title, and
// Cancel/Create are .modal__actions buttons addressed by accessible name. Name
// validation is inline (error text shown on empty submit), not button-disable.

test.describe('File > New Part dialog', () => {
  // "New Part" opens its modal in-place only when the current doc is empty; with
  // content it spawns a new tab (multi-document). Reset the server's active design
  // to empty before each test so New opens the modal here, deterministically,
  // regardless of what the dev server (or another spec) left loaded.
  test.beforeEach(async ({ page, request }) => {
    await request.post('http://localhost:8000/api/design', {
      data: { name: 'smoke-reset', lattice_type: 'HONEYCOMB' },
    })
    await page.goto('/')
  })

  // The New-Part modal overlay, identified by the form body it contains.
  const modalOf = (page) =>
    page.locator('.modal__overlay').filter({ has: page.locator('#new-design-modal-body') })

  test('opens when File > New Part is clicked', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-modal-body')).toBeVisible()
    await expect(modalOf(page).locator('.modal__title')).toHaveText('New Part')
  })

  test('modal has a required name field', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-name')).toBeVisible()
    await expect(page.locator('#new-design-name')).toHaveValue('')
  })

  test('Create with an empty name shows a validation error', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const modal = modalOf(page)
    await modal.getByRole('button', { name: 'Create' }).click()
    // Inline validation: error shown, dialog stays open.
    await expect(page.locator('#new-design-name-error')).toBeVisible()
    await expect(page.locator('#new-design-modal-body')).toBeVisible()
  })

  test('shows Honeycomb and Square lattice options', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const body = page.locator('#new-design-modal-body')
    await expect(body).toContainText('Honeycomb')
    await expect(body).toContainText('Square')
  })

  test('Honeycomb radio is selected by default', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const honeycombRadio = page.locator('input[name="new-lattice-type"][value="HONEYCOMB"]')
    await expect(honeycombRadio).toBeChecked()
  })

  test('Cancel closes the dialog', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-modal-body')).toBeVisible()
    await modalOf(page).getByRole('button', { name: 'Cancel' }).click()
    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
  })

  test('Create dismisses the dialog and leaves the welcome screen', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', 'Test Part')
    await modalOf(page).getByRole('button', { name: 'Create' }).click()
    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
  })

  test('Create with Honeycomb closes the dialog and calls API with part name', async ({ page }) => {
    const apiCall = page.waitForRequest(req =>
      req.method() === 'POST' && /\/api\/design(\?|$)/.test(req.url())
    )

    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', 'My Honeycomb Part')
    await modalOf(page).getByRole('button', { name: 'Create' }).click()

    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
    const req = await apiCall
    expect(req.postDataJSON()?.name).toBe('My Honeycomb Part')
  })

  test('Create with Square lattice fires API with SQUARE lattice type', async ({ page }) => {
    let capturedBody = null
    page.on('request', req => {
      if (req.method() === 'POST' && /\/api\/design(\?|$)/.test(req.url())) {
        capturedBody = req.postDataJSON()
      }
    })

    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.click('input[name="new-lattice-type"][value="SQUARE"]')
    await page.fill('#new-design-name', 'Square Test')
    await modalOf(page).getByRole('button', { name: 'Create' }).click()

    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
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

// ── Console-error gate (the main.js refactor commit gate) ─────────────────────
//
// This is the one check unit tests structurally cannot replace: it loads a real
// design and renders the full scene, asserting nothing throws. An extraction that
// breaks main()'s init order, subscription order, or closure scope surfaces here
// as an uncaught exception (pageerror) or console error — invisible to vitest.
//
// Run via `just smoke` before any main.js-touching commit.

test.describe('Console-error gate', () => {
  // Substrings of console-error messages that are known-benign environment noise,
  // NOT app regressions. Keep this list tight — every entry weakens the gate.
  const BENIGN = [
    'favicon.ico',          // browser auto-requests it; we don't ship one
    'WebSocket',            // ws may not be connected during a static smoke load
    'Failed to load resource', // covers the favicon 404 line in some browsers
  ]
  const isBenign = (text) => BENIGN.some((b) => text.includes(b))

  test('loads a real design and renders with zero console errors', async ({ page, request }) => {
    const consoleErrors = []
    const pageErrors = []
    page.on('console', (msg) => {
      if (msg.type() === 'error' && !isBenign(msg.text())) consoleErrors.push(msg.text())
    })
    page.on('pageerror', (err) => pageErrors.push(err.message))

    // Load the representative design into the server's active state, using an
    // absolute path so it resolves regardless of which CWD the server was started
    // from (`just dev` from repo root vs. Playwright's webServer from frontend/).
    const designPath = path.resolve(process.cwd(), '..', 'Examples', SMOKE_DESIGN)
    const loadResp = await request.post('http://localhost:8000/api/design/load', {
      data: { path: designPath },
    })
    expect(loadResp.status(), `failed to load ${SMOKE_DESIGN}`).toBe(200)

    // Now boot the frontend — it fetches the active design + geometry and renders.
    await page.goto('/')
    await expect(page.locator('#canvas')).toBeVisible()
    // Give the geometry round-trip + renderer rebuild time to run and throw if broken.
    await page.waitForTimeout(1500)

    expect(pageErrors, `uncaught exceptions during load/render:\n${pageErrors.join('\n')}`).toEqual([])
    expect(consoleErrors, `console errors during load/render:\n${consoleErrors.join('\n')}`).toEqual([])
  })
})

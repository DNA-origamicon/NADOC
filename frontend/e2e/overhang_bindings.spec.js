/**
 * OverhangBinding end-to-end tests (Phase 5 overhang revamp).
 *
 * Exercises the Bindings (n) subsection rendered under the Domain Designer
 * cross-refs panel. Assertions are DOM-only — WebGL gizmo state is the
 * cluster-gizmo module's responsibility and Playwright headless WebGL is
 * not reliable for visual comparisons.
 *
 * Backend must be running (`just dev`). Frontend dev server auto-starts via
 * playwright.config.js webServer.
 */

import { test, expect } from '@playwright/test'
import path from 'path'

const API = 'http://127.0.0.1:8000/api'

const HINGE_NADOC = path.resolve(
  import.meta.dirname ?? __dirname,
  '../../workspace/hinge.nadoc',
)


/** Load a real design with overhangs into both backend and frontend. Mirrors
 *  domain_designer.spec.js's bootstrap helper.
 */
async function loadHinge(page) {
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', 'DD-bind-test')
  await page.click('#new-design-create')
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 10_000 })

  const r = await page.request.post(`${API}/design/load`, {
    data: { path: HINGE_NADOC },
  })
  expect(r.ok()).toBeTruthy()

  await page.evaluate(async () => {
    const apiMod = await import('/src/api/client.js')
    await apiMod.getDesign()
  })
}

async function openOverhangsManager(page) {
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')
  await expect(page.locator('#overhangs-manager-modal')).toBeVisible()
  await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
  await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
}


test.describe('Overhang Bindings — Domain Designer cross-refs', () => {
  test.setTimeout(30_000)

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.evaluate(() => {
      try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {}
    })
    await loadHinge(page)
  })

  test('Bindings (n) header renders under cross-refs', async ({ page }) => {
    await openOverhangsManager(page)
    const crossRefs = page.locator('#dd-cross-refs')
    await expect(crossRefs).toBeVisible()
    // The Bindings header must appear (with count 0 when nothing exists).
    await expect(crossRefs).toContainText(/Bindings \(\d+\)/)
  })

  test('Create binding button is present and toggleable', async ({ page }) => {
    await openOverhangsManager(page)
    const addBtn = page.locator('[data-test="dd-bind-create-btn"]')
    await expect(addBtn).toBeVisible()
    await addBtn.click()
    const form = page.locator('[data-test="dd-bind-create-form"]')
    await expect(form).toBeVisible()
    // Second click closes.
    await addBtn.click()
    await expect(form).toHaveCount(0)
  })

  test('Create-binding form exposes partner select + mode radios + joint select', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('[data-test="dd-bind-create-btn"]').click()
    await expect(page.locator('[data-test="dd-bind-partner-select"]')).toBeVisible()
    await expect(page.locator('[data-test="dd-bind-mode-duplex"]')).toBeVisible()
    await expect(page.locator('[data-test="dd-bind-mode-toehold"]')).toBeVisible()
    await expect(page.locator('[data-test="dd-bind-joint-select"]')).toBeVisible()
    await expect(page.locator('[data-test="dd-bind-submit"]')).toBeVisible()
    // Duplex is selected by default.
    await expect(page.locator('[data-test="dd-bind-mode-duplex"]')).toBeChecked()
  })

  test('API: list bindings endpoint reachable from frontend client', async ({ page }) => {
    await openOverhangsManager(page)
    const result = await page.evaluate(async () => {
      const mod = await import('/src/api/overhang_endpoints.js')
      return await mod.listOverhangBindings()
    })
    expect(result).toBeTruthy()
    expect(Array.isArray(result.overhang_bindings)).toBe(true)
  })

  test('Empty-state message renders when no bindings exist', async ({ page }) => {
    await openOverhangsManager(page)
    const crossRefs = page.locator('#dd-cross-refs')
    // hinge.nadoc has no bindings out of the box.
    await expect(crossRefs).toContainText('No bindings reference this overhang.')
  })

  test('createOverhangBinding wrapper exists on the client module', async ({ page }) => {
    await openOverhangsManager(page)
    const wrappers = await page.evaluate(async () => {
      const mod = await import('/src/api/overhang_endpoints.js')
      return {
        list: typeof mod.listOverhangBindings,
        create: typeof mod.createOverhangBinding,
        patch: typeof mod.patchOverhangBinding,
        del: typeof mod.deleteOverhangBinding,
      }
    })
    expect(wrappers.list).toBe('function')
    expect(wrappers.create).toBe('function')
    expect(wrappers.patch).toBe('function')
    expect(wrappers.del).toBe('function')
  })
})

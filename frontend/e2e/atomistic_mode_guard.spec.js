/**
 * Atomistic-mode guard — unfold and cadnano views are not allowed while an
 * atomistic representation (VDW / Ball-and-Stick) is active. Toggling either
 * should be blocked with an explanatory toast (and must NOT activate the view).
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000/api'

async function buildScaffoldedPart(page, name) {
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#splash-screen')).not.toBeVisible({ timeout: 10_000 })
  await page.waitForTimeout(500)

  await page.request.post(`${API}/design/helix-at-cell`, {
    data: { row: 0, col: 0, length_bp: 200 }, headers: { 'Content-Type': 'application/json' },
  })
  // Scaffold by painting a domain over the full helix. (Was a POST to
  // /design/auto-scaffold with this as a fallback; e9d6750 removed that route in
  // favour of -seamed/-seamless, so the fallback is what has always run.)
  const dr = await page.request.get(`${API}/design`)
  const { design } = await dr.json()
  await page.request.post(`${API}/design/scaffold-domain-paint`, {
    data: { helix_id: design.helices[0].id, lo_bp: 0, hi_bp: 199 },
    headers: { 'Content-Type': 'application/json' },
  })
  await page.evaluate(() => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed' }); bc.close()
  })
  await page.waitForFunction(() => {
    const scene = window.__nadocTest?.scene
    if (!scene) return false
    let ok = false
    scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 20_000 })
}

async function enableAtomisticVdw(page) {
  const view = page.locator('.menu-item').filter({ hasText: 'View' }).first()
  await view.hover()
  await page.locator('.submenu-item').filter({ hasText: 'Representation' }).first().hover()
  await page.click('#menu-view-atomistic-vdw')
  // Atomistic geometry fetch + build; wait until the element meshes exist.
  await page.waitForFunction(() => {
    const ar = window.__nadocTest?.getAtomisticRenderer?.()
    return !!ar && Object.keys(ar?._state?.elementMeshes ?? {}).length > 0
  }, null, { timeout: 20_000 }).catch(() => {})
  await page.waitForTimeout(500)
}

test.describe('Atomistic mode guard', () => {
  test('unfold + cadnano are blocked with a toast while atomistic is active', async ({ page }) => {
    await page.goto('/')
    await buildScaffoldedPart(page, 'atom-guard')
    await enableAtomisticVdw(page)

    // Use the keyboard shortcuts ([U]/[K]) — robust vs. re-opening the menu.
    // Click the canvas first so focus is off any input (shortcuts are
    // blockedInInput) and any open menu is dismissed.
    await page.locator('#canvas').click({ position: { x: 600, y: 350 } })

    // Unfold → blocked + toast, view does not activate.
    await page.keyboard.press('u')
    await expect(page.locator('.toast', { hasText: 'Unfold view is not available in atomistic' })).toBeVisible()
    expect(await page.locator('#mode-indicator').textContent()).not.toContain('UNFOLD')

    // Cadnano → blocked + toast.
    await page.keyboard.press('k')
    await expect(page.locator('.toast', { hasText: 'Cadnano view is not available in atomistic' })).toBeVisible()
  })
})

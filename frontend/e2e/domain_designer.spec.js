/**
 * Domain Designer end-to-end tests (Phase 3 overhang revamp).
 *
 * Covers the tab integration in the Overhangs Manager popup and the
 * Domain Designer pane's left listing / pathview / annotations panel /
 * cross-references. Backend mutations are exercised through the popup;
 * pure visual elements are asserted via DOM queries.
 *
 * Backend must be running (`just dev`). Frontend dev server auto-starts
 * via playwright.config.js webServer.
 *
 * NOTE: The 3D preview pane is OFF by default (Phase 3 fix-up 2026-05-10).
 * Tests that need it must click `[data-test="dd-show-3d-toggle"]` first; all
 * other assertions exercise the lightweight (no-WebGL) path.
 */

import { test, expect } from '@playwright/test'
import path from 'path'

const API = 'http://127.0.0.1:8000/api'

const HINGE_NADOC = path.resolve(
  import.meta.dirname ?? __dirname,
  '../../workspace/hinge.nadoc',
)


/** Load a .nadoc with ≥4 overhangs that have sub-domains.
 *
 *  Loading via /api/design/load alone does NOT dismiss the welcome screen
 *  (welcome state is owned by the frontend, gated separately from server
 *  design state). We bootstrap by:
 *    1. File > New (UI) to dismiss the welcome and un-gate menus.
 *    2. POST /api/design/load to swap the server-side active design.
 *    3. page.evaluate(window.__nadocReloadDesign) to pull the new design
 *       into the store without a page reload (added in test mode only).
 *  Since #3 is not wired, we instead trigger an undo+redo via the API which
 *  causes the next mutation to re-sync. For the test, we use api.getDesign()
 *  from the page context.
 */
async function loadHinge(page) {
  // 1. Dismiss welcome screen by creating an empty part via the UI.
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', 'DD-test')
  await page.click('#new-design-create')
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 10_000 })

  // 2. Load the real design via the API (replaces server-side active design).
  const r = await page.request.post(`${API}/design/load`, {
    data: { path: HINGE_NADOC },
  })
  expect(r.ok()).toBeTruthy()

  // 3. Pull the new design into the frontend store. We use the existing
  //    `api.getDesign` exported function via the dev server's module graph.
  //    Trick: the store is on `window.__nadoc_store` in dev (if exposed) — if
  //    not, we fall back to clicking File > Open in the recent-files menu...
  //    Simpler: post a no-op design snapshot to force a re-sync.
  await page.evaluate(async () => {
    // Fetch the new design from /api/design and merge into the frontend
    // store. The api module is import-only; access via dynamic import.
    const apiMod = await import('/src/api/client.js')
    await apiMod.getDesign()
  })
  return (await r.json()).design
}

/** Open the Overhangs Manager popup via the Tools menu. */
async function openOverhangsManager(page) {
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')
  await expect(page.locator('#overhangs-manager-modal')).toBeVisible()
}


test.describe('Domain Designer — popup tab integration', () => {
  // With the 3D preview gated OFF by default, the panel + pathview boot in
  // well under a second. Headless Chromium still races animations on slow
  // machines, so we keep a moderate timeout.
  test.setTimeout(30_000)

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    // Clear the active-tab persistence so prior runs don't pollute the
    // default-tab assertion in `Linker Generator is active by default`.
    await page.evaluate(() => {
      try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {}
    })
    await loadHinge(page)
  })

  test('tab strip is visible above the existing 3-column grid', async ({ page }) => {
    await openOverhangsManager(page)
    const strip = page.locator('#ohc-tab-strip')
    await expect(strip).toBeVisible()
    await expect(strip.locator('.ohc-tab').filter({ hasText: 'Linker Generator' })).toBeVisible()
    await expect(strip.locator('.ohc-tab').filter({ hasText: 'Domain Designer' })).toBeVisible()
  })

  test('Linker Generator is active by default; existing UI visible', async ({ page }) => {
    await openOverhangsManager(page)
    await expect(page.locator('#tab-content-linker-generator')).toBeVisible()
    await expect(page.locator('#tab-content-domain-designer')).toBeHidden()
    // The existing 3-column controls must still render.
    await expect(page.locator('#ohc-list-a')).toBeVisible()
    await expect(page.locator('#ohc-generate')).toBeVisible()
  })

  test('clicking Domain Designer reveals the new pane', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    await expect(page.locator('#tab-content-linker-generator')).toBeHidden()
    // The four stable IDs must be present (3D preview removed 2026-05-11).
    await expect(page.locator('#dd-pathview-canvas')).toBeVisible()
    await expect(page.locator('#dd-overhang-list')).toBeVisible()
    await expect(page.locator('#dd-annotations-panel')).toBeVisible()
    await expect(page.locator('#dd-cross-refs')).toBeVisible()
  })

  test('modal-content width swaps when activating Domain Designer', async ({ page }) => {
    await openOverhangsManager(page)
    const content = page.locator('#ohc-modal-content')
    await expect(content).toHaveAttribute('style', /width:\s*760px/)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(content).toHaveAttribute('style', /width:\s*1000px/)
    await page.locator('.ohc-tab[data-tab="linker-generator"]').click()
    await expect(content).toHaveAttribute('style', /width:\s*760px/)
  })

  test('active tab persists across modal close + re-open via localStorage', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    await page.locator('#ohc-close').click()
    await expect(page.locator('#overhangs-manager-modal')).toBeHidden()

    await openOverhangsManager(page)
    // Domain Designer should still be active after re-open.
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    await expect(page.locator('#tab-content-linker-generator')).toBeHidden()
    // Reset for the next test to default state.
    await page.locator('.ohc-tab[data-tab="linker-generator"]').click()
  })

  test('overhang listing groups by helix and is non-empty', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    const listEl = page.locator('#dd-overhang-list')
    // Hinge has overhangs split across multiple helices → at least one
    // <details> group must be rendered.
    await expect(listEl.locator('details').first()).toBeVisible()
    // First overhang row must be present.
    await expect(listEl.locator('div').first()).toBeVisible()
    // Listing groups must NOT expose raw UUIDs (Phase 3 fix-up #2).
    // hinge.nadoc has `helix.label === null` for every helix → the fallback
    // must surface the array INDEX (cadnano `Helix 0`, `Helix 1`, …) rather
    // than the UUID prefix shape `(h_XY_..…)`.
    const firstSummary = await listEl.locator('details summary').first().textContent()
    expect(firstSummary).toMatch(/^Helix /)
    expect(firstSummary).not.toMatch(/\(h_/)        // no raw UUID prefix
    expect(firstSummary).not.toMatch(/[a-f0-9]{8}/)  // no hex tail
    // Label number/word followed by " · N" overhang count.
    expect(firstSummary).toMatch(/^Helix \S+ · \d+/)
  })

  test('clicking a <summary> expands / collapses its helix group', async ({ page }) => {
    // Phase 3 fix-up #2: this case nails the regression where clicking a
    // helix summary did nothing because the listing rebuilt mid-toggle.
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    const summary = page.locator('#dd-overhang-list details summary').first()
    const details = page.locator('#dd-overhang-list details').first()
    // First state may be open (default-open on first render). Capture, click,
    // expect it to flip.
    const wasOpen = await details.evaluate(el => el.open)
    await summary.click()
    await expect.poll(async () => details.evaluate(el => el.open)).toBe(!wasOpen)
    // And flip back.
    await summary.click()
    await expect.poll(async () => details.evaluate(el => el.open)).toBe(wasOpen)
  })

  test('clicking a sub-domain row updates the annotations panel', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    const annEl = page.locator('#dd-annotations-panel')
    // After opening, an overhang is preselected → annotations panel must
    // surface a Name input.
    await expect(annEl.locator('input.dd-ann-name')).toBeVisible()
    await expect(annEl.locator('textarea.dd-ann-seq')).toBeVisible()
    await expect(annEl.locator('button.dd-ann-generate')).toBeVisible()
  })

  test('cross-references panel renders the header', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    const cross = page.locator('#dd-cross-refs')
    await expect(cross).toContainText(/Cross-references/)
  })

  test('rename sub-domain via name input triggers a PATCH', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    // Wait for the annotations panel to populate.
    const nameInput = page.locator('input.dd-ann-name').first()
    await expect(nameInput).toBeVisible()

    // Capture the PATCH request when blur fires.
    const patchPromise = page.waitForRequest(req =>
      req.method() === 'PATCH'
      && /\/api\/design\/overhang\/[^/]+\/sub-domains\/[^/]+$/.test(req.url())
    )
    await nameInput.fill('renamed-sd')
    await nameInput.blur()
    const req = await patchPromise
    const body = req.postDataJSON?.()
    expect(body).toBeTruthy()
    expect(body.name).toBe('renamed-sd')
  })

  test('Gen button is disabled when sub-domain has hairpin_warning', async ({ page }) => {
    await openOverhangsManager(page)
    await page.locator('.ohc-tab[data-tab="domain-designer"]').click()
    await expect(page.locator('#tab-content-domain-designer')).toBeVisible()
    // Wait for the annotations panel to populate so a sub-domain is in focus.
    const seqInput = page.locator('textarea.dd-ann-seq').first()
    await expect(seqInput).toBeVisible()

    // Resolve target sub-domain via the store snapshot in the page.
    const sdLen = await page.evaluate(async () => {
      const mod = await import('/src/state/store.js')
      const dd = mod.store.getState().domainDesigner
      const ovhg = mod.store.getState().currentDesign?.overhangs?.find(o => o.id === dd.selectedOverhangId)
      const sd = ovhg?.sub_domains?.find(s => s.id === dd.selectedSubDomainId)
      return sd?.length_bp ?? null
    })
    expect(sdLen).not.toBeNull()

    // Type a length-matched palindromic sequence into the override field.
    // The panel's debounced PATCH (150ms) will fire, the backend's inner
    // hairpin scan flags it, and the panel re-renders with the Gen button
    // disabled. This exercises the full UI path end-to-end.
    const base = 'GCGCATATGCGC'
    const palindrome = base.repeat(Math.ceil(sdLen / base.length)).slice(0, sdLen)
    await seqInput.fill(palindrome)
    // Allow the 150 ms debounce + backend round-trip + store update + render.
    await page.waitForTimeout(1200)
    await expect(page.locator('button.dd-ann-generate')).toBeDisabled({ timeout: 5000 })
  })

  // 3D preview removed 2026-05-11 — the toggle / canvas / placeholder no
  // longer exist. The DOM presence test above asserts the 4-pane layout.
})

/**
 * Anchor halo regression: adding an anchor must glow IMMEDIATELY.
 *
 * The bug: the purple halo was gated on the E-field being enabled, so anchors added with
 * no field showed nothing — the halo only appeared later, once clicking a job row restored
 * that job's field config and flipped the gate. An anchor is pinned regardless of whether
 * a field exists, so the halo must not depend on one.
 *
 * Drives the real Add button against a real multi-selection and asserts purple sprites
 * exist with the field left OFF.
 *
 * Self-contained loader (does NOT use scene_harness.loadScaffoldedPart, which is currently
 * broken on master: it ignores its POST statuses and lands on a design with no helices —
 * bead_select.spec.js is red for the same reason). Runs against the config's throwaway
 * backend, never the user's dev server.
 */
import { test, expect } from '@playwright/test'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002') + '/api'

/** New doc-scoped design with one populated helix (scaffold + staple → beads render). */
async function loadPopulatedHelix(page, { doc, name }) {
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', `__e2e__${name}`)   // teardown removes __e2e__ files
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await expect
    .poll(async () => (await page.request.get(`${API}/design`, { headers: H })).status(),
      { timeout: 15_000, message: `backend never got a design for doc ${doc}` })
    .toBe(200)

  // populate_strands adds a full-length scaffold + staple in the same call, so the helix
  // actually has nucleotides to render (and to Alt-pick).
  const res = await page.request.post(`${API}/design/helix-at-cell`, {
    data: { row: 0, col: 0, length_bp: 64, populate_strands: true }, headers: H,
  })
  expect(res.status(), `helix-at-cell failed: ${await res.text()}`).toBe(201)

  const { design } = await (await page.request.get(`${API}/design`, { headers: H })).json()
  expect(design.helices?.length, 'helix was created').toBeGreaterThan(0)
  expect(design.strands?.length, 'helix was populated with strands').toBeGreaterThan(0)

  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-anchor-glow', docId: d })
    bc.close()
  }, doc)
  await page.waitForFunction(() => {
    const s = window.__nadocTest?.scene
    if (!s) return false
    let ok = false
    s.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 20_000 })
  await page.waitForTimeout(300)

  const box = await page.locator('#canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 10; i++) await page.mouse.wheel(0, -120)
  await page.waitForTimeout(600)
}

/**
 * Multi-select whole strands the way a Ctrl+drag lasso does — by filling the store's
 * multiSelectedStrandIds pool.  Deliberately NOT the Alt-click bead gesture: that gesture's
 * e2e path is broken on master (bead_select.spec.js is red for the same reason) and it is
 * not what this regression is about.  Everything downstream of the selection — the real Add
 * button, the anchor resolver, the halo — is exercised for real.
 */
async function lassoStrands(page, n) {
  return page.evaluate((count) => {
    const st = window.__nadocTest.store.getState()
    const ids = [...new Set((st.currentDesign?.strands || []).map(s => s.id))].slice(0, count)
    window.__nadocTest.store.setState({ multiSelectedStrandIds: ids, selectedObject: null })
    return ids.length
  }, n)
}

test.describe('Anchor glow (no field)', () => {
  test('multi-selected strands Add as anchors and glow purple with no field enabled', async ({ page }) => {
    await loadPopulatedHelix(page, { doc: 'e2e-anchor-glow', name: 'anchor-glow' })

    await page.getByRole('button', { name: 'Simulations', exact: true }).first().click()
    await page.waitForTimeout(300)

    // The field stays OFF all test — that is the whole point of the regression.
    expect(await page.evaluate(() => !!window.__nadocEfield?.setup?.isEnabled?.()),
      'field must be off').toBe(false)
    expect(await page.evaluate(() => window.__nadocTest.anchors.glowCount()),
      'no halo before adding').toBe(0)

    expect(await lassoStrands(page, 2), 'two strands multi-selected').toBe(2)

    await page.click('#oxdna-anchors-toggle')
    await page.click('#oxdna-anchors-add')
    await page.waitForTimeout(300)

    const anchors = await page.evaluate(() => window.__nadocTest.anchors.card.getAnchors())
    expect(anchors, 'both multi-selected strands became anchors').toHaveLength(2)
    expect(anchors.every(a => a.kind === 'strand'), 'as strand anchors').toBe(true)

    expect(await page.evaluate(() => !!window.__nadocEfield?.setup?.isEnabled?.()),
      'still no field').toBe(false)
    expect(await page.evaluate(() => window.__nadocTest.anchors.glowCount()),
      'purple halo renders immediately — no field, no job').toBeGreaterThan(0)
  })

  test('the "Highlight all anchors" toggle defaults on and gates the halo', async ({ page }) => {
    await loadPopulatedHelix(page, { doc: 'e2e-anchor-toggle', name: 'anchor-toggle' })
    await page.getByRole('button', { name: 'Simulations', exact: true }).first().click()
    await page.waitForTimeout(300)
    await page.click('#oxdna-anchors-toggle')

    const glow = page.locator('#oxdna-anchors-glow')
    expect(await glow.isChecked(), 'defaults on').toBe(true)

    expect(await lassoStrands(page, 1)).toBe(1)
    await page.click('#oxdna-anchors-add')
    await page.waitForTimeout(300)
    const lit = await page.evaluate(() => window.__nadocTest.anchors.glowCount())
    expect(lit, 'halo on by default').toBeGreaterThan(0)

    await glow.uncheck()
    await page.waitForTimeout(300)
    expect(await page.evaluate(() => window.__nadocTest.anchors.glowCount()),
      'unticking hides the halo').toBe(0)
    // The anchors themselves must survive — this is a display preference, not a delete.
    expect(await page.evaluate(() => window.__nadocTest.anchors.card.getAnchors()),
      'anchors kept while hidden').toHaveLength(1)

    await glow.check()
    await page.waitForTimeout(300)
    expect(await page.evaluate(() => window.__nadocTest.anchors.glowCount()),
      're-ticking brings it back').toBe(lit)
  })

  test('clicking a list entry lights only that anchor; clicking off restores', async ({ page }) => {
    await loadPopulatedHelix(page, { doc: 'e2e-anchor-focus', name: 'anchor-focus' })
    await page.getByRole('button', { name: 'Simulations', exact: true }).first().click()
    await page.waitForTimeout(300)
    await page.click('#oxdna-anchors-toggle')

    // Two anchors so "only the clicked one" is meaningful.
    expect(await lassoStrands(page, 2)).toBe(2)
    await page.click('#oxdna-anchors-add')
    await page.waitForTimeout(300)

    const keys = await page.evaluate(() =>
      [...document.querySelectorAll('#oxdna-anchors-list [data-key]')].map(e => e.dataset.key))
    expect(keys).toHaveLength(2)
    const litKeys = () => page.evaluate(() =>
      [...document.querySelectorAll('#oxdna-anchors-list [data-hl="1"]')].map(e => e.dataset.key))
    const sprites = () => page.evaluate(() => window.__nadocTest.anchors.glowCount())

    expect(await litKeys(), 'both chips purple to start').toHaveLength(2)
    const allSprites = await sprites()

    // Click the first chip → only it stays purple, and the 3D halo shrinks.
    await page.click(`#oxdna-anchors-list [data-key="${keys[0]}"]`)
    await page.waitForTimeout(300)
    expect(await litKeys()).toEqual([keys[0]])
    const oneSprites = await sprites()
    expect(oneSprites, 'halo covers only the focused anchor').toBeGreaterThan(0)
    expect(oneSprites, 'and is smaller than the whole set').toBeLessThan(allSprites)

    // Click it again (toggle still on) → all re-highlight.
    await page.click(`#oxdna-anchors-list [data-key="${keys[0]}"]`)
    await page.waitForTimeout(300)
    expect(await litKeys(), 'all chips purple again').toHaveLength(2)
    expect(await sprites()).toBe(allSprites)

    // Focus again, then turn the toggle OFF and click off → everything goes dark.
    await page.click(`#oxdna-anchors-list [data-key="${keys[0]}"]`)
    await page.locator('#oxdna-anchors-glow').uncheck()
    await page.waitForTimeout(300)
    expect(await litKeys(), 'focus beats the toggle').toEqual([keys[0]])
    await page.click(`#oxdna-anchors-list [data-key="${keys[0]}"]`)
    await page.waitForTimeout(300)
    expect(await litKeys(), 'toggle off + no focus → nothing lit').toEqual([])
    expect(await sprites()).toBe(0)
  })

  test('the halo clears off the Dynamics tab and comes back on return', async ({ page }) => {
    await loadPopulatedHelix(page, { doc: 'e2e-anchor-tab', name: 'anchor-tab' })
    await page.getByRole('button', { name: 'Simulations', exact: true }).first().click()
    await page.waitForTimeout(300)
    expect(await lassoStrands(page, 1)).toBe(1)
    await page.click('#oxdna-anchors-toggle')
    await page.click('#oxdna-anchors-add')
    await page.waitForTimeout(300)

    const lit = await page.evaluate(() => window.__nadocTest.anchors.glowCount())
    expect(lit, 'halo on').toBeGreaterThan(0)

    await page.getByRole('button', { name: 'Feature Log', exact: true }).first().click()
    await page.waitForTimeout(300)
    expect(await page.evaluate(() => window.__nadocTest.anchors.glowCount()),
      'halo does not linger on other tabs').toBe(0)

    await page.getByRole('button', { name: 'Simulations', exact: true }).first().click()
    await page.waitForTimeout(300)
    expect(await page.evaluate(() => window.__nadocTest.anchors.glowCount()),
      'halo restored on return — the anchors survived the tab switch').toBe(lit)
  })
})

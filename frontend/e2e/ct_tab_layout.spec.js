/**
 * Connection Types tab layout screenshot — verifies the ported Linker
 * Generator elements (overhang lists, linker-length field, Generate button,
 * Linkers table) render as expected inside the new tab.
 */

import { test, expect } from '@playwright/test'
import path from 'node:path'

const API = 'http://127.0.0.1:8000/api'
const HINGE = path.resolve(import.meta.dirname, '../../workspace/hinge.nadoc')

async function loadHinge(page) {
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', 'CT-tab-test')
  await page.click('#new-design-create')
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 10_000 })
  const r = await page.request.post(`${API}/design/load`, { data: { path: HINGE } })
  expect(r.ok()).toBeTruthy()
  await page.evaluate(async () => {
    const apiMod = await import('/src/api/client.js')
    await apiMod.getDesign()
  })
}

test('Connection Types tab layout', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => {
    try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {}
  })
  await loadHinge(page)

  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')
  await expect(page.locator('#overhangs-manager-modal')).toBeVisible()
  await page.locator('.ohc-tab[data-tab="connection-types"]').click()
  await expect(page.locator('#tab-content-connection-types')).toBeVisible()

  // Lists populated, generate button visible, table attached
  await expect(page.locator('#ct-list-a .ohc-list-row').first()).toBeVisible({ timeout: 5000 })
  await expect(page.locator('#ct-list-b .ohc-list-row').first()).toBeVisible()
  await expect(page.locator('#ct-generate')).toBeVisible()
  await expect(page.locator('#ct-table-body')).toBeAttached()

  // Default selection (end-to-root) is a direct type — length row hidden
  await expect(page.locator('#ct-length-row')).toBeHidden()
  await page.locator('#ohc-modal-content').screenshot({ path: 'e2e/screenshots/ct_tab_direct.png' })

  // Pick a linker type → length row should appear
  await page.click('#ct-button-box')
  await page.locator('.ct-option[data-variant="root-to-root-ssdna-linker"]').click()
  await expect(page.locator('#ct-length-row')).toBeVisible()
  await page.locator('#ohc-modal-content').screenshot({ path: 'e2e/screenshots/ct_tab_linker.png' })

  // Selecting an overhang on each side should highlight the row in the
  // matching neon color and tint the strand in the icon.
  await page.locator('#ct-list-a .ohc-list-row').first().click()
  await page.locator('#ct-list-b .ohc-list-row').nth(1).click()
  await expect(page.locator('#ct-list-a .ohc-list-row.ct-selected-a')).toHaveCount(1)
  await expect(page.locator('#ct-list-b .ohc-list-row.ct-selected-b')).toHaveCount(1)
  // Sequence rows should appear for the selected sides.
  await expect(page.locator('#ct-seq-row-a')).toBeVisible()
  await expect(page.locator('#ct-seq-row-b')).toBeVisible()
  await page.locator('#ohc-modal-content').screenshot({ path: 'e2e/screenshots/ct_tab_selected.png' })
})

test('Connection Types — sequence edit + Gen wires through to backend', async ({ page }) => {
  test.setTimeout(60_000)  // multiple round-trip waits + popover interactions
  await page.goto('/')
  await page.evaluate(() => {
    try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {}
  })
  await loadHinge(page)

  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')
  await page.locator('.ohc-tab[data-tab="connection-types"]').click()
  await expect(page.locator('#tab-content-connection-types')).toBeVisible()

  // Pick the first overhang on the LEFT side.
  await page.locator('#ct-list-a .ohc-list-row').first().click()
  const seqInputA = page.locator('#ct-seq-input-a')
  await expect(seqInputA).toBeVisible()

  // Read the overhang ID we just selected (read from the highlighted row).
  const ovhgId = await page.locator('#ct-list-a .ohc-list-row.ct-selected-a')
    .getAttribute('data-ovhg-id')
  expect(ovhgId).toBeTruthy()

  // Find what length the selected overhang needs (must match for patchOverhang).
  const overhangLen = await page.evaluate(async (id) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const o = json?.design?.overhangs?.find(x => x.id === id)
    return (o?.sub_domains ?? []).reduce((s, sd) => s + (sd.length_bp ?? 0), 0)
  }, ovhgId)
  expect(overhangLen).toBeGreaterThan(0)
  const seq = 'A'.repeat(overhangLen)

  // Type a sequence and blur — should commit via patchOverhang.
  await seqInputA.click()
  await seqInputA.fill(seq)
  await seqInputA.press('Tab')
  // Wait for store update by polling the design.
  await page.waitForFunction(async (args) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const o = json?.design?.overhangs?.find(x => x.id === args.id)
    return o?.sequence === args.seq
  }, { id: ovhgId, seq }, { timeout: 5000 })
  // Input value should reflect the saved sequence.
  await expect(seqInputA).toHaveValue(seq)

  // Generate-Linker button is disabled for the default direct type.
  await expect(page.locator('#ct-generate')).toHaveAttribute('disabled', '')

  // Switch to a linker type → button label becomes "Generate Linker".
  // (Hinge design's overhangs are all 5p, so root-to-root-dsdna-linker is the
  // valid pick — its rule is forbidden when L != R, and 5p/5p satisfies it.)
  await page.evaluate(() => document.getElementById('ct-button-box').click())
  await expect(page.locator('#ct-popover')).toBeVisible()
  await page.locator('#ct-popover .ct-option[data-variant="root-to-root-dsdna-linker"]').click()
  await expect(page.locator('#ct-generate')).toHaveText('Generate Linker')
  // Pick a different overhang on the right side so both A and B are set →
  // button enabled (5p/5p valid for dsDNA linker).
  await page.locator('#ct-list-b .ohc-list-row').nth(1).click()
  await expect(page.locator('#ct-generate')).not.toHaveAttribute('disabled', '')
})

test('Connection Types — Gen button invokes overhang generator', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => { try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {} })
  await loadHinge(page)
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')
  await page.locator('.ohc-tab[data-tab="connection-types"]').click()

  // Pick an overhang on the LEFT and click Gen — backend should populate a
  // sequence (might already have one; we just verify it's set + ACGT-only after).
  await page.locator('#ct-list-a .ohc-list-row').first().click()
  const id = await page.locator('#ct-list-a .ohc-list-row.ct-selected-a').getAttribute('data-ovhg-id')
  await page.click('#ct-seq-gen-a')
  await page.waitForFunction(async (oid) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const o = json?.design?.overhangs?.find(x => x.id === oid)
    return o?.sequence && /^[ACGT]+$/i.test(o.sequence)
  }, id, { timeout: 10_000 })
  // Sequence input should reflect the now-generated sequence.
  const seq = await page.locator('#ct-seq-input-a').inputValue()
  expect(seq).toMatch(/^[ACGT]+$/i)
})

test('Connection Types — forbidden combo shows red rule tooltip on hover', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => { try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {} })
  await loadHinge(page)
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')

  // Hinge overhangs are all 5p. Pick an ssDNA linker variant — its rule is
  // forbidden when L === R, so a 5p/5p pair triggers the warning.
  await page.click('#ct-button-box')
  await page.locator('.ct-option[data-variant="root-to-root-ssdna-linker"]').click()
  await page.locator('#ct-list-a .ohc-list-row').nth(0).click()
  await page.locator('#ct-list-b .ohc-list-row').nth(1).click()

  // Before hover: tooltip element is either absent or hidden.
  expect(await page.locator('#ct-rule-tooltip').count()).toBeLessThanOrEqual(1)
  if (await page.locator('#ct-rule-tooltip').count()) {
    await expect(page.locator('#ct-rule-tooltip')).toBeHidden()
  }

  // Hover the button-box — tooltip appears, in red, with rule-specific text.
  await page.locator('#ct-button-box').hover()
  await expect(page.locator('#ct-rule-tooltip')).toBeVisible({ timeout: 2000 })
  const text = await page.locator('#ct-rule-tooltip').textContent()
  expect(text).toMatch(/single-strand|continuous|5'.*3'|5'\/3'|opposite polarities/i)
  const color = await page.locator('#ct-rule-tooltip').evaluate(el => getComputedStyle(el).color)
  // CSS color reports `rgb(...)`. Our style sets #ff6b6b → rgb(255, 107, 107).
  expect(color).toMatch(/rgb\(255,\s*107,\s*107\)/)

  // Moving the cursor off the button-box hides the tooltip again.
  await page.locator('#ct-button-box').dispatchEvent('mouseleave')
  await expect(page.locator('#ct-rule-tooltip')).toBeHidden({ timeout: 2000 })
})

test('Connection Types — direct types: "Make complementary" + warnings', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => { try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {} })
  await loadHinge(page)
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')
  await page.locator('.ohc-tab[data-tab="connection-types"]').click()

  // Default type is end-to-root (direct). Button label should be "Make
  // complementary" and disabled (no selections yet).
  await expect(page.locator('#ct-generate')).toHaveText('Make complementary')
  await expect(page.locator('#ct-generate')).toHaveAttribute('disabled', '')

  // Select two DIFFERENT overhangs from the hinge design — list rows are
  // sorted identically on both sides, so picking the first row on A and the
  // second on B guarantees they're not the same overhang.
  await page.locator('#ct-list-a .ohc-list-row').nth(0).click()
  await page.locator('#ct-list-b .ohc-list-row').nth(1).click()
  const aId = await page.locator('#ct-list-a .ohc-list-row.ct-selected-a').getAttribute('data-ovhg-id')
  const bId = await page.locator('#ct-list-b .ohc-list-row.ct-selected-b').getAttribute('data-ovhg-id')

  // Both overhangs in the hinge design end with "_5p" → end-to-root direct
  // requires L != R to be forbidden, so 5p/5p is VALID. The warning yellow
  // triangle should NOT be present.
  const aPol = aId.endsWith('_5p') ? '5p' : '3p'
  const bPol = bId.endsWith('_5p') ? '5p' : '3p'
  if (aPol !== bPol) {
    // Different polarities: end-to-root direct is forbidden → warning shown.
    await expect(page.locator('#ct-button-box svg polygon[fill="#f5c518"]')).toBeAttached()
  } else {
    // Same polarities: end-to-root direct is valid → no warning.
    await expect(page.locator('#ct-button-box svg polygon[fill="#f5c518"]')).toHaveCount(0)
  }

  // Set a sequence on overhang A.
  const aLen = await page.evaluate(async (id) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const o = json?.design?.overhangs?.find(x => x.id === id)
    return (o?.sub_domains ?? []).reduce((s, sd) => s + (sd.length_bp ?? 0), 0)
  }, aId)
  const seq = 'A'.repeat(aLen)
  await page.locator('#ct-seq-input-a').fill(seq)
  await page.locator('#ct-seq-input-a').press('Tab')
  await page.waitForFunction(async (args) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const o = json?.design?.overhangs?.find(x => x.id === args.id)
    return o?.sequence === args.seq
  }, { id: aId, seq }, { timeout: 5000 })

  // Now both A and B selected, A has a sequence → button enabled.
  await expect(page.locator('#ct-generate')).not.toHaveAttribute('disabled', '')

  // Click "Make complementary" — B's sequence should become the rev comp of
  // A's. For all-As that's all-Ts (same length).
  await page.click('#ct-generate')
  await page.waitForFunction(async (args) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const o = json?.design?.overhangs?.find(x => x.id === args.id)
    return o?.sequence === args.expected
  }, { id: bId, expected: 'T'.repeat(aLen) }, { timeout: 8000 })
})

test('Connection Types — Generate Linker creates a row visible in both tabs', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => { try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {} })
  await loadHinge(page)
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')
  await page.locator('.ohc-tab[data-tab="connection-types"]').click()

  // The Connection Types table is populated from the design's
  // overhang_connections list — hinge.nadoc ships with one (L1) so the
  // initial row count is at least 1. We just verify it stays in sync below.

  // Pick a linker connection type whose forbidden rule is "L != R" so a
  // 5p/5p pair (hinge's overhangs are all 5p) is VALID — that's the dsDNA
  // linker family.
  await page.evaluate(() => document.getElementById('ct-button-box').click())
  await page.locator('#ct-popover .ct-option[data-variant="root-to-root-dsdna-linker"]').click()

  // Pick two overhangs NOT already used by the existing L1 connection.
  // L1 binds OH1 + OH2 in hinge.nadoc → use the remaining two (derdy,
  // herdy) to avoid backend rejection.
  await page.locator('#ct-list-a .ohc-list-row', { hasText: 'derdy' }).click()
  await page.locator('#ct-list-b .ohc-list-row', { hasText: 'herdy' }).click()

  // Generate Linker button should be enabled now.
  await expect(page.locator('#ct-generate')).toHaveText('Generate Linker')
  await expect(page.locator('#ct-generate')).not.toHaveAttribute('disabled', '')

  // Set a length and click Generate Linker.
  await page.locator('#ct-length').fill('12')
  const beforeCount = await page.evaluate(async () => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    return (json?.design?.overhang_connections ?? []).length
  })
  await page.click('#ct-generate')

  // Backend should add a new connection — poll until reflected.
  await page.waitForFunction(async (prev) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    return (json?.design?.overhang_connections ?? []).length > prev
  }, beforeCount, { timeout: 8000 })

  // Connection Types tab's table picks up the new row.
  await expect(page.locator('#ct-table-body tr')).toHaveCount(beforeCount + 1)
  await expect(page.locator('#ct-table-body')).not.toContainText('No linkers defined.')
})

test('Connection Types — clicking a linker row autopopulates the selector', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => { try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {} })
  await loadHinge(page)
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')

  // hinge.nadoc ships with L1 — a dsDNA linker between OH1 and OH2, both
  // `root` attach. The button-box should snap to root-to-root-dsdna-linker
  // and both overhang rows should be highlighted.
  const l1 = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const c = (store.getState().currentDesign?.overhang_connections ?? [])
      .find(x => x.name === 'L1')
    return c ? { id: c.id, a: c.overhang_a_id, b: c.overhang_b_id } : null
  })
  expect(l1).not.toBeNull()

  // Start from a deliberately different state so the row click has a visible effect.
  await page.evaluate(() => document.getElementById('ct-button-box').click())
  await page.locator('#ct-popover .ct-option[data-variant="end-to-root"]').click()
  await expect(page.locator('#ct-list-a .ohc-list-row.ct-selected-a')).toHaveCount(0)
  await expect(page.locator('#ct-list-b .ohc-list-row.ct-selected-b')).toHaveCount(0)

  // Click the L1 row — target the Sequence cell explicitly. The Name and
  // Length cells stop click propagation (they enter inline-edit mode); the
  // Sequence cell bubbles to the row handler.
  await page.locator(`#ct-table-body tr[data-conn-id="${l1.id}"] td.ct-link-seq-cell`).click()

  // Persisted CT variant flips to root-to-root dsDNA linker. Verifying via
  // localStorage avoids depending on the popover being open.
  await expect.poll(
    () => page.evaluate(() => localStorage.getItem('nadoc.overhangsManager.connectionType')),
    { timeout: 2000 },
  ).toBe('root-to-root-dsdna-linker')

  // Both overhang rows are highlighted on the matching side.
  await expect(page.locator(`#ct-list-a .ohc-list-row.ct-selected-a[data-ovhg-id="${l1.a}"]`)).toHaveCount(1)
  await expect(page.locator(`#ct-list-b .ohc-list-row.ct-selected-b[data-ovhg-id="${l1.b}"]`)).toHaveCount(1)

  // The highlighted rows should be on-screen (scrollIntoView, with
  // `behavior:smooth`, settles deterministically after a short delay).
  for (const [listId, ovhgId] of [['ct-list-a', l1.a], ['ct-list-b', l1.b]]) {
    const onScreen = await page.evaluate(({ listId, ovhgId }) => {
      const list = document.getElementById(listId)
      const row  = list?.querySelector(`.ohc-list-row[data-ovhg-id="${ovhgId}"]`)
      if (!list || !row) return false
      const lr = list.getBoundingClientRect()
      const rr = row.getBoundingClientRect()
      return rr.top >= lr.top - 1 && rr.bottom <= lr.bottom + 1
    }, { listId, ovhgId })
    expect(onScreen).toBe(true)
  }
})

test('Connection Types — bridge box: selection-gated, ds RC mirror, sequence column composes full strand', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => { try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {} })
  await loadHinge(page)
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')

  // Pick the dsDNA variant — both bridge rows visible.
  await page.evaluate(() => document.getElementById('ct-button-box').click())
  await page.locator('#ct-popover .ct-option[data-variant="root-to-root-dsdna-linker"]').click()
  await expect(page.locator('#ct-bridge-section')).toBeVisible()
  await expect(page.locator('#ct-bridge-row-b')).toBeVisible()

  // With no row selected, bridge input + Gen are disabled and empty.
  await expect(page.locator('#ct-bridge-input-a')).toBeDisabled()
  await expect(page.locator('#ct-bridge-input-a')).toHaveValue('')
  await expect(page.locator('#ct-bridge-gen-a')).toBeDisabled()

  // Generate a new linker. derdy / herdy are unbound in hinge (L1 already
  // binds OH1+OH2). The new linker auto-selects, enabling the bridge editor.
  await page.fill('#ct-length', '12')
  await page.locator('#ct-list-a .ohc-list-row', { hasText: 'derdy' }).click()
  await page.locator('#ct-list-b .ohc-list-row', { hasText: 'herdy' }).click()
  const beforeCount = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    return (store.getState().currentDesign?.overhang_connections ?? []).length
  })
  await page.click('#ct-generate')
  await page.waitForFunction(async (prev) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    return (json?.design?.overhang_connections ?? []).length > prev
  }, beforeCount, { timeout: 8000 })

  const newConn = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const conns = store.getState().currentDesign?.overhang_connections ?? []
    const c = conns.find(x => x.name !== 'L1')
    return c ? { id: c.id, name: c.name, bridge: c.bridge_sequence } : null
  })
  expect(newConn?.bridge ?? null).toBeNull()   // create no longer seeds the bridge

  // The new row is auto-selected → highlight class + bridge box enabled.
  await expect(page.locator(`#ct-table-body tr[data-conn-id="${newConn.id}"].ohc-link-row-selected`))
    .toHaveCount(1)
  await expect(page.locator('#ct-bridge-input-a')).toBeEnabled()
  await expect(page.locator('#ct-bridge-gen-a')).toBeEnabled()

  // Type a bridge and commit (Tab → blur) — backend persists it.
  await page.locator('#ct-bridge-input-a').fill('ACGTACGTACGT')
  await expect(page.locator('#ct-bridge-input-b'))
    .toHaveValue('ACGTACGTACGT'.split('').reverse().map(b => ({A:'T',T:'A',C:'G',G:'C'}[b])).join(''))
  await page.locator('#ct-bridge-input-a').press('Tab')
  await page.waitForFunction(async (id) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const c = (json?.design?.overhang_connections ?? []).find(x => x.id === id)
    return c?.bridge_sequence === 'ACGTACGTACGT'
  }, newConn.id, { timeout: 5000 })

  // Sequence column for the selected row now contains the bridge on strand
  // __a AND its RC on strand __b. Complement portions are N's (overhangs
  // aren't sequenced).
  const seqLines = await page.locator(
    `#ct-table-body tr[data-conn-id="${newConn.id}"] td.ct-link-seq-cell div[data-strand-id]`
  ).allTextContents()
  expect(seqLines.length).toBe(2)
  expect(seqLines[0]).toContain('ACGTACGTACGT')
  expect(seqLines[1]).toContain('ACGTACGTACGT'.split('').reverse().map(b => ({A:'T',T:'A',C:'G',G:'C'}[b])).join(''))

  // Delete the selected row → selection clears, bridge box clears + disables.
  page.once('dialog', d => d.accept())
  await page.locator(`#ct-table-body tr[data-conn-id="${newConn.id}"] .ohc-row-delete`).click()
  await expect(page.locator(`#ct-table-body tr[data-conn-id="${newConn.id}"]`)).toHaveCount(0, { timeout: 5000 })
  await expect(page.locator('#ct-bridge-input-a')).toBeDisabled()
  await expect(page.locator('#ct-bridge-input-a')).toHaveValue('')
  await expect(page.locator('#ct-bridge-gen-a')).toBeDisabled()
})

test('Connection Types — Sequence column refreshes when overhang sequence changes', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await page.evaluate(() => { try { localStorage.removeItem('nadoc.overhangsManager.activeTab') } catch {} })
  await loadHinge(page)
  const tools = page.locator('.menu-item').filter({ hasText: 'Tools' }).first()
  await tools.hover()
  await page.click('#menu-tools-overhangs-manager')

  // L1 from hinge has no overhang sequences yet — its Sequence column
  // initially has only N's (plus whatever bridge_sequence is on disk; the
  // existing L1 was saved before bridge_sequence existed, so it's null).
  const l1 = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const c = (store.getState().currentDesign?.overhang_connections ?? [])
      .find(x => x.name === 'L1')
    return c ? { id: c.id, a: c.overhang_a_id } : null
  })

  // Snapshot the L1 row's strand-A complement-portion text before the edit.
  const beforeText = await page.locator(
    `#ct-table-body tr[data-conn-id="${l1.id}"] td.ct-link-seq-cell div[data-strand-id$="__a"]`
  ).innerText()
  // Should be only N + bridge placeholder pre-edit (no overhang sequences).
  expect(beforeText).toMatch(/^[N]+$/)

  // Select overhang A in the side list and assign it a sequence by typing
  // into the side-input box. Length is whatever sub_domains report.
  await page.locator(`#ct-list-a .ohc-list-row[data-ovhg-id="${l1.a}"]`).click()
  const aLen = await page.evaluate(async (id) => {
    const apiMod = await import('/src/api/client.js')
    const json = await apiMod.getDesign()
    const o = json?.design?.overhangs?.find(x => x.id === id)
    return (o?.sub_domains ?? []).reduce((s, sd) => s + (sd.length_bp ?? 0), 0)
  }, l1.a)
  const aSeq = 'AAAA'.repeat(20).slice(0, aLen)   // all-A, length-matched
  await page.locator('#ct-seq-input-a').fill(aSeq)
  await page.locator('#ct-seq-input-a').press('Tab')

  // After commit, the L1 row's strand-A complement portion (RC of all-A) must
  // appear as a run of Ts on the line. The bridge portion stays N's; depending
  // on the strand's domain order (comp_first vs bridge_first), the run sits
  // either at the start or the end of the line.
  await expect.poll(
    () => page.locator(
      `#ct-table-body tr[data-conn-id="${l1.id}"] td.ct-link-seq-cell div[data-strand-id$="__a"]`
    ).innerText(),
    { timeout: 5000 },
  ).toMatch(new RegExp(`T{${aLen}}`))
})

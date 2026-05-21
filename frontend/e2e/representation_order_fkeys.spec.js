/**
 * View → Representation menu: compute-intensity ordering + F1…F7 hotkeys.
 *
 * Verifies (1) the menu lists representations least→most compute-intensive
 * with matching F-key hint labels, and (2) pressing F1…F4 switches the active
 * representation (the `is-checked` radio mark moves to the right item).
 */

import { test, expect } from '@playwright/test'

// Expected order, top → bottom in the menu and F1 → F7 on the keyboard.
const ORDER = [
  { id: 'menu-view-hull-prism',          label: 'Hull Prism',       hint: 'F1' },
  { id: 'menu-view-detail-cylinders',    label: 'Cylinders',        hint: 'F2' },
  { id: 'menu-view-detail-beads',        label: 'Beads',            hint: 'F3' },
  { id: 'menu-view-detail-full',         label: 'Full',             hint: 'F4' },
  { id: 'menu-view-surface',             label: 'Surface',          hint: 'F5' },
  { id: 'menu-view-atomistic-vdw',       label: 'VDW / Space-fill', hint: 'F6' },
  { id: 'menu-view-atomistic-ballstick', label: 'Ball & Stick',     hint: 'F7' },
]

const API = 'http://localhost:8000/api'

async function loadDesign(page) {
  // Small real design in backend memory; boot picks it up via GET /api/design.
  const r = await page.request.post(`${API}/design/bundle`, {
    data: { cells: [[0, 0], [0, 1]], length_bp: 42, name: 'repr-test', plane: 'XY' },
  })
  expect(r.ok()).toBeTruthy()
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.evaluate(() => {
    const splash = document.getElementById('splash-screen')
    if (splash) splash.style.display = 'none'
  })
  // Pull the just-created backend design into the frontend store so the
  // representation menu's click handlers see a currentDesign.
  await page.waitForFunction(() => !!window._nadocDebug?.refetch, null, { timeout: 10_000 })
  await page.evaluate(() => window._nadocDebug.refetch())
  await page.waitForTimeout(500)
}

test.describe('Representation menu order + F-key bindings', () => {
  test('menu lists reprs least→most compute with matching F-key hints', async ({ page }) => {
    await loadDesign(page)

    // DOM order of the representation buttons must match ORDER.
    const ids = await page.$$eval(
      '#menu-view-hull-prism, #menu-view-detail-cylinders, #menu-view-detail-beads, ' +
      '#menu-view-detail-full, #menu-view-surface, #menu-view-atomistic-vdw, ' +
      '#menu-view-atomistic-ballstick',
      els => els
        .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
        .map(el => el.id),
    )
    expect(ids).toEqual(ORDER.map(o => o.id))

    // Each button carries the correct F-key hint, in order.
    // Use textContent (not innerText): the submenu is display:none until hovered,
    // and innerText returns '' for unrendered elements.
    for (const { id, hint } of ORDER) {
      const txt = await page.locator(`#${id} .repr-fkey-hint`).evaluate(el => el.textContent)
      expect(txt.trim()).toBe(hint)
    }
  })

  test('F1…F4 switch the active representation (radio mark moves)', async ({ page }) => {
    await loadDesign(page)

    // Default is Full (F4).
    await expect(page.locator('#menu-view-detail-full')).toHaveClass(/is-checked/)

    const checkSwitch = async (key, id) => {
      await page.locator('body').click({ position: { x: 5, y: 5 } }) // ensure focus off inputs
      await page.keyboard.press(key)
      await expect(page.locator(`#${id}`)).toHaveClass(/is-checked/, { timeout: 5_000 })
      // exactly one representation checked
      const checked = await page.$$eval(
        '.dropdown-item.is-checked',
        els => els.filter(e => e.querySelector('.repr-fkey-hint')).map(e => e.id),
      )
      expect(checked).toEqual([id])
    }

    await checkSwitch('F2', 'menu-view-detail-cylinders')
    await checkSwitch('F3', 'menu-view-detail-beads')
    await checkSwitch('F1', 'menu-view-hull-prism')
    await checkSwitch('F4', 'menu-view-detail-full')
  })

  test('repeat-pressing a key cycles that representation’s coloring modes', async ({ page }) => {
    await loadDesign(page)

    // Which coloring menu item is currently checked (id → mode).
    const COLOR_IDS = {
      'menu-view-coloring-strand':        'strand',
      'menu-view-coloring-base':          'base',
      'menu-view-coloring-cluster':       'cluster',
      'menu-view-coloring-overhang-only': 'overhang-only',
      'menu-view-coloring-cpk':           'cpk',
    }
    const activeColoring = () => page.evaluate((ids) => {
      for (const id of Object.keys(ids)) {
        if (document.getElementById(id)?.classList.contains('is-checked')) return ids[id]
      }
      return null
    }, COLOR_IDS)

    const press = async (key) => {
      await page.locator('body').click({ position: { x: 5, y: 5 } })
      await page.keyboard.press(key)
      await page.waitForTimeout(150)
    }

    // Default repr is Full (already active) with strand coloring.
    await expect(page.locator('#menu-view-detail-full')).toHaveClass(/is-checked/)
    expect(await activeColoring()).toBe('strand')

    // Full supports strand → base → cluster → overhang-only → (wrap) strand.
    await press('F4'); expect(await activeColoring()).toBe('base')
    await press('F4'); expect(await activeColoring()).toBe('cluster')
    await press('F4'); expect(await activeColoring()).toBe('overhang-only')
    await press('F4'); expect(await activeColoring()).toBe('strand')

    // Switch to Cylinders (F2) — first press switches, not cycles.
    await press('F2')
    await expect(page.locator('#menu-view-detail-cylinders')).toHaveClass(/is-checked/)
    const cylStart = await activeColoring()
    expect(['strand', 'cluster', 'overhang-only']).toContain(cylStart)

    // Cylinders skips 'base' (unsupported): cycle stays within its 3 modes.
    const seen = new Set([cylStart])
    for (let i = 0; i < 3; i++) {
      await press('F2')
      const m = await activeColoring()
      expect(['strand', 'cluster', 'overhang-only']).toContain(m) // never 'base'
      seen.add(m)
    }
    expect([...seen].sort()).toEqual(['cluster', 'overhang-only', 'strand'])
  })
})

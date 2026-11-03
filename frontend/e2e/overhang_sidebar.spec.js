import { test, expect } from '@playwright/test'

test('overhang sidebar reveals scene selections and opens secondary-structure warnings', async ({ page }) => {
  await page.route('**/__overhang-sidebar-test', route => route.fulfill({
    contentType: 'text/html', body: '<html><body style="width:500px"></body></html>',
  }))
  await page.goto('/__overhang-sidebar-test')
  await page.evaluate(async () => {
    const { initOverhangSequencesPanel } = await import('/src/ui/overhang_sequences_panel.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    const { store } = await import('/src/state/store.js')
    const { mountIds } = await import('/src/test-helpers/factory_dom.js')
    const { makeDesign, makeReport } = await import('/src/test-helpers/hairpin_dimer_fixture.js')
    mountIds({
      'overhang-panel': 'div', 'overhang-panel-heading': 'h2', 'overhang-panel-arrow': 'span',
      'overhang-label-size-row': 'div', 'overhang-list': 'div',
    })
    document.getElementById('overhang-list').style.cssText = 'max-height:140px;overflow-y:auto'
    const design = makeDesign()
    for (let i = 0; i < 40; i++) {
      design.strands.push({ id: `staple-${i}`, domains: [] })
      design.overhangs.push({ id: `oh-${i}`, strand_id: `staple-${i}`, label: `Handle ${i}`, sequence: 'ACGT' })
    }
    store.setState({ currentDesign: design, hairpinDimerReport: makeReport() })
    const selection = createSelectionController({ store })
    initOverhangSequencesPanel({
      store, selectionManager: { selectOverhang: id => selection.select({ kind: 'overhang', id }) },
      api: {}, overhangNameOverlay: {},
    })
    window.pickSidebarTarget = ref => selection.replace([ref])
  })

  const list = page.locator('#overhang-list')
  await expect(list).toBeHidden()
  const assertVisibleWithinList = async (id) => {
    const row = await page.locator(`[data-overhang-id="${id}"]`).boundingBox()
    const bounds = await list.boundingBox()
    expect(row.y).toBeGreaterThanOrEqual(bounds.y - 1)
    expect(row.y + row.height).toBeLessThanOrEqual(bounds.y + bounds.height + 1)
  }
  await page.evaluate(() => window.pickSidebarTarget({ kind: 'overhang', id: 'ovhg_h_a_0_5p' }))
  await expect(list).toBeVisible()
  await assertVisibleWithinList('ovhg_h_a_0_5p')
  expect(await list.evaluate(el => el.scrollTop)).toBeGreaterThan(0)

  await page.locator('[data-overhang-id="ovhg_h_a_0_5p"] .hd-warn-icon').click()
  await expect(page.locator('.hd-window')).toBeVisible()
  await expect(page.locator('.hd-window__generate')).toHaveText('Generate new sequence')
  await page.keyboard.press('Escape')

  await page.evaluate(() => window.pickSidebarTarget({ kind: 'strand', id: 'staple-0' }))
  await assertVisibleWithinList('oh-0')
})

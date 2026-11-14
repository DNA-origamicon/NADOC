import { test, expect } from '@playwright/test'

// Read an existing example only. No authoring/save requests; isolated backend
// disables session caching. Browser storage dies with its test context.
test('false colors survive strand selection and deselection', async ({ page }) => {
  test.setTimeout(60000)
  await page.goto('/?doc=__e2e__false-color-selection')
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.loadDesign('Examples/2hb_xover_atoms_test.nadoc')
    await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  })
  await expect.poll(() => page.evaluate(() => window.__nadocTest?.getDesignRenderer().getBackboneEntries().length ?? 0)).toBeGreaterThan(0)
  await page.keyboard.press('f')
  for (const layer of ['scalar', 'stapleTemperature', 'lengthHeatmap']) {
    const result = await page.evaluate(async layer => {
      const t = window.__nadocTest, r = t.getDesignRenderer()
      const entries = [...r.getBackboneEntries(), ...r.getSlabEntries(), ...r.getConeEntries()]
      const native = entries.map(e => e.defaultColor)
      if (layer === 'scalar') {
        const colors = Object.fromEntries(r.getBackboneEntries().map(e =>
          [`${e.nuc.helix_id}:${e.nuc.bp_index}:${e.nuc.direction}:${e.nuc.copy_k ?? 0}`, 0xff3300]))
        r.applyScalarColors(colors)
      } else for (const e of entries) r.paintFalseColor(layer, e, 0xff3300)
      const read = () => entries.map(e => Array.from(e.instMesh.instanceColor.array.slice(e.id * 3, e.id * 3 + 3)))
      const before = read()
      const sid = entries[0].nuc.strand_id
      t.selectRefsForTest([{ kind: 'strand', id: sid }])
      await new Promise(resolve => requestAnimationFrame(resolve))
      const during = read(), selected = t.getCanonicalSelection().items.length
      t.selectRefsForTest([])
      await new Promise(resolve => requestAnimationFrame(resolve))
      const after = read()
      t.renderViewerFrameForTest()
      const pixels = t.renderedPixelCensus()
      if (layer === 'scalar') r.clearScalarColors()
      else r.clearFalseColors(layer)
      return { before, during, after, selected, pixels, count: native.length }
    }, layer)
    expect(result.count).toBeGreaterThan(0)
    expect(result.selected).toBe(1)
    expect(result.during).toEqual(result.before)
    expect(result.after).toEqual(result.before)
    expect(result.pixels.colorful).toBeGreaterThan(0)
  }
})

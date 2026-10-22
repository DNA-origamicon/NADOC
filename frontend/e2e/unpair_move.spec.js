import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'

test('unpair Move Cancel and Continue preserve 3D and relocate cadnano rows', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async ({ page, browser, checkpoint, file, doc, headers }) => {
    await page.keyboard.press('F4')
    const before = await browser()
    const initialProof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await initialProof.json()).status, 'fixture must cold-replay before the move').toBe('verified')
    const staple = before.design.strands.find(s => s.strand_type === 'staple')
    const domain = staple.domains[0]
    const bp = domain.end_bp
    const targetKey = `${domain.helix_id}:${bp}:${domain.direction}`
    let liveDelta
    const start = async () => {
      await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
      // Canvas click clears selection; set it after focusing the canvas.
      await page.evaluate(async key => {
        const { store } = await import('/src/state/store.js')
        const ref = { kind: 'base', key }
        store.setState({ selection: { items: [ref], primary: ref } })
      }, targetKey)
      await page.keyboard.press('m')
      await expect(page.locator('#move-rotate-panel')).toBeVisible()
      const original = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
      const gizmo = await page.evaluate(() => window.__nadocTest.getNucleotideTransformScreenState())
      await page.mouse.move(gizmo.screenPivot.x, gizmo.screenPivot.y)
      await page.mouse.down()
      await page.mouse.move(gizmo.screenPivot.x + 60, gizmo.screenPivot.y - 30, { steps: 12 })
      await page.mouse.up()
      const moved = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
      liveDelta = moved.bead.map((v, i) => v - original.bead[i])
      expect(liveDelta.some(v => Math.abs(v) > .01)).toBe(true)
      await page.locator('#mr-apply-btn').click()
      await expect(page.getByText('Convert separated segment to overhang', { exact: true })).toBeVisible()
    }
    const initial = await checkpoint()
    await start()
    await page.getByRole('button', { name: 'Cancel', exact: true }).last().click()
    expect((await browser()).design).toEqual(before.design)
    expect(await checkpoint()).toEqual(initial)
    await start()
    const saved = page.waitForResponse(r => r.request().method() === 'PUT'
      && new URL(r.url()).pathname === '/api/design/nucleotide-transforms')
    await page.getByRole('button', { name: 'Continue', exact: true }).click()
    const response = await saved
    expect(response.ok(), await response.text()).toBe(true)
    await expect.poll(async () => (await browser()).design.overhangs.length).toBe(1)
    const after = await browser()
    expect(after.design.feature_log.length).toBe(before.design.feature_log.length + 1)
    const overhang = after.design.overhangs[0]
    const relocated = after.design.strands.find(s => s.id === staple.id).domains.find(d => d.overhang_id === overhang.id)
    expect(relocated.start_bp).toBe(bp)
    expect(relocated.end_bp).toBe(bp)
    const newHelix = after.design.helices.find(h => h.id === relocated.helix_id)
    expect(before.design.helices.some(h => JSON.stringify(h.grid_pos) === JSON.stringify(newHelix.grid_pos))).toBe(false)
    for (const old of before.geometry) {
      const actual = after.geometry.find(n => n.strand_id === old.strand_id && n.bp_index === old.bp_index && n.direction === old.direction)
      const selected = old.strand_id === staple.id && old.bp_index === bp
      for (const field of ['backbone_position', 'base_position', 'slab_position']) {
        for (let axis = 0; axis < 3; axis++) expect(actual[field][axis]).toBeCloseTo(old[field][axis] + (selected ? liveDelta[axis] : 0), 5)
      }
    }
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.saveDesign(file)
      await api.loadDesign(file)
    }, file)
    const reopened = await browser()
    expect(reopened.design.strands).toEqual(after.design.strands)
    expect(reopened.design.overhangs).toEqual(after.design.overhangs)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
    expect((await proof.json()).status).toBe('verified')
    if (process.env.NADOC_UNPAIR_REVIEW === '1') {
      console.log('UNPAIR_3D_IMAGE=' + (await page.screenshot()).toString('base64'))
    }
    const editor = await page.context().newPage()
    try {
      await editor.goto(`/cadnano-editor.html?doc=${doc}`)
      await expect(editor.locator('#pathview-canvas')).toBeVisible()
      await expect.poll(() => editor.evaluate(async () => {
        const { editorStore } = await import('/src/cadnano-editor/store.js')
        return editorStore.getState().design?.overhangs?.length
      })).toBe(1)
      if (process.env.NADOC_UNPAIR_REVIEW === '1') {
        console.log('UNPAIR_CADNANO_IMAGE=' + (await editor.screenshot()).toString('base64'))
      }
    } finally { await editor.close() }
  }, 'unpair')
})

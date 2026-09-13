import { test, expect } from '@playwright/test'

test('aptamer menu creates spreadsheet strands and switches folded representations', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?doc=e2e-aptamer-import')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
  await page.locator('#menu-item-import > button').click()
  const catalogResponse = page.waitForResponse(r => r.url().includes('/design/import/aptamers'))
  await page.locator('#menu-file-import-aptamer').click()
  const catalog = await catalogResponse
  expect(catalog.ok(), await catalog.text()).toBe(true)
  const dialog = page.getByRole('dialog', { name: 'Import Aptamer' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Import', exact: true }), await dialog.innerText()).toBeEnabled()
  await dialog.getByRole('button', { name: 'Import', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length)).toBe(15)
  const strandId = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.strands[0].id)
  if (await page.locator('#spreadsheet-panel').evaluate(el => el.getBoundingClientRect().height < 50)) {
    await page.locator('#sheet-toggle').click()
  }
  await expect(page.locator(`#spreadsheet-tbody tr[data-strand-id="${strandId}"]`)).toBeVisible()
  for (const repr of ['cylinders', 'full', 'vdw', 'full']) {
    await page.evaluate(r => window.__nadocTest.setRepresentation(r), repr)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length)).toBe(15)
  }
  expect(errors).toEqual([])
})

test('G4 move/rotate previews, commits and history restore the rendered fold', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?doc=e2e-aptamer-history')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.store))
  const cid = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const result = await api.importAptamer({template_id:'148D'})
    api.syncDesignResponse(result)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    return result.design.cluster_transforms.find(c => c.helix_ids.some(id => id.startsWith('apt_'))).id
  })
  await expect.poll(() => page.evaluate(id => window.__nadocTest.getClusterGizmoState(id).beadCount,cid)).toBe(15)
  const beads = () => page.evaluate(id => window.__nadocTest.getClusterGizmoState(id).beads,cid)
  const original = await beads()
  const expectBeads = async expected => {
    await expect.poll(async () => {
      const actual = await beads()
      if(actual.length !== expected.length) return Infinity
      return Math.max(...actual.flatMap((p,i) => p.map((v,j) => Math.abs(v-expected[i][j]))))
    }).toBeLessThan(1e-5)
  }
  const noAxisOverlay = async () => {
    const count = await page.evaluate(() => {
      let n=0
      window.__nadocTest.scene.traverse(o => { if(o.name==='axisLine' && o.visible) n++ })
      return n
    })
    expect(count).toBe(0)
  }
  await noAxisOverlay()
  await page.evaluate(id => window.__nadocTest.activateDesignMoveTool(id),cid)
  await page.evaluate(() => {
    for(const [id,value] of [['mr-tx',3],['mr-ty',-2],['mr-tz',1]]) document.getElementById(id).value=String(value)
    document.getElementById('mr-tz').dispatchEvent(new Event('change',{bubbles:true}))
  })
  const moved = original.map(p => p.map((v,i)=>v+[3,-2,1][i]))
  await expectBeads(moved)
  await page.evaluate(() => document.getElementById('mr-cancel-btn').click())
  await expectBeads(original)
  await page.evaluate(id => window.__nadocTest.activateDesignMoveTool(id),cid)
  await page.evaluate(() => {
    for(const [id,value] of [['mr-tx',3],['mr-ty',-2],['mr-tz',1]]) document.getElementById(id).value=String(value)
    document.getElementById('mr-tz').dispatchEvent(new Event('change',{bubbles:true}))
  })
  await page.evaluate(() => document.getElementById('mr-apply-btn').click())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().translateRotateActive)).toBe(false)
  await expectBeads(moved)
  await page.evaluate(id => window.__nadocTest.activateDesignMoveTool(id),cid)
  await page.evaluate(() => document.getElementById('mr-rz-inc').click())
  const rotated = await beads()
  expect(rotated).not.toEqual(moved)
  await page.evaluate(() => document.getElementById('mr-apply-btn').click())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().translateRotateActive)).toBe(false)
  await expectBeads(rotated)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  await expectBeads(moved)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  await expectBeads(rotated)
  for(const repr of ['ballstick','full']) await page.evaluate(r=>window.__nadocTest.setRepresentation(r),repr)
  await expectBeads(rotated)
  await noAxisOverlay()
  await page.evaluate(async () => (await import('/src/api/client.js')).seekFeatures(0))
  await expectBeads(original)
  await page.evaluate(async () => (await import('/src/api/client.js')).seekFeatures(-1))
  await expectBeads(rotated)
  expect(errors).toEqual([])
})

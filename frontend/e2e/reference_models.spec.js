import { test, expect } from '@playwright/test'

const stl = `solid test
facet normal 0 0 1
outer loop
vertex -30 -15 0
vertex 30 -15 0
vertex 0 15 0
endloop
endfacet
endsolid test`

test('STL references import, cycle gizmos, edit independently and disappear on refresh', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/?debug&doc=e2e-reference-models')
  await page.waitForFunction(() => window.__referenceModels)
  await page.locator('input[data-reference-stl]').setInputFiles({ name: 'reference.stl', mimeType: 'model/stl', buffer: Buffer.from(stl) })
  await expect.poll(() => page.evaluate(() => window.__referenceModels.root.children.length)).toBe(1)
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  const initial = await page.evaluate(() => window.__referenceModels.snapshot())
  expect(Math.max(...initial[0].vertices.filter((_, i) => i % 3 === 0))).toBe(30)
  await page.locator('#canvas').evaluate(canvas => { canvas.tabIndex = 0; canvas.focus() })
  for (const mode of [1, 2, 0]) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => window.__referenceModels.mode)).toBe(mode)
  }
  // Drive a real scale handle and verify that an axis drag preserves proportions.
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab')
  const handle = await page.evaluate(() => {
    const refs = window.__referenceModels
    const tc = refs.root.parent.children.find(o => o.controls?.object === refs.selected).controls
    tc.getHelper().updateMatrixWorld(true)
    const bounds = document.querySelector('#canvas').getBoundingClientRect()
    return tc._gizmo.gizmo.scale.children.filter(o => o.name === 'X' && o.geometry.type === 'BoxGeometry').map(mesh => {
      mesh.geometry.computeBoundingBox()
      const point = mesh.geometry.boundingBox.getCenter(mesh.position.clone()).applyMatrix4(mesh.matrixWorld).project(tc.camera)
      return { x: bounds.x + (point.x + 1) * bounds.width / 2, y: bounds.y + (1 - point.y) * bounds.height / 2 }
    }).sort((a, b) => b.x - a.x)[0]
  })
  await page.mouse.move(handle.x, handle.y)
  await page.mouse.down(); await page.mouse.move(handle.x + 45, handle.y, { steps: 8 }); await page.mouse.up()
  const scale = await page.evaluate(() => window.__referenceModels.selected.scale.toArray())
  expect(scale[0]).toBeGreaterThan(1.05)
  expect(scale[0]).toBeCloseTo(scale[1], 8); expect(scale[0]).toBeCloseTo(scale[2], 8)
  await page.evaluate(() => window.__referenceModels.action('reset'))
  await page.keyboard.press('Tab')
  await page.evaluate(() => { const refs = window.__referenceModels; refs.action('color'); refs.action('opacity'); refs.selected.position.set(12, 3, -2); refs.action('duplicate') })
  const duplicate = await page.evaluate(() => window.__referenceModels.snapshot())
  expect(duplicate).toHaveLength(2)
  expect(duplicate[0].id).not.toBe(duplicate[1].id)
  expect(duplicate[1].matrix.slice(12, 15)).toEqual([12, 3, -2])
  expect(duplicate[1].opacity).toBe(.75)
  await page.evaluate(() => { window.__referenceModels.action('reset'); window.__referenceModels.action('delete') })
  expect(await page.evaluate(() => window.__referenceModels.root.children.length)).toBe(1)
  await page.keyboard.press('Escape')
  expect(await page.evaluate(() => window.__referenceModels.selected)).toBeNull()
  // Real viewport picking and Linux press-time context menus.
  const bounds = await page.locator('#canvas').boundingBox()
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  expect(await page.evaluate(() => !!window.__referenceModels.selected)).toBe(true)
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2, { button: 'right' })
  await expect(page.getByRole('menuitem', { name: 'Reset transforms', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'Cycle transparency', exact: true })).toHaveCount(0)
  await page.getByRole('menuitem', { name: 'Color…', exact: true }).click()
  const popup = page.getByRole('dialog').filter({ hasText: 'Reference color' })
  await expect(popup).toBeVisible()
  await popup.getByRole('textbox', { name: 'Hex color' }).fill('#1278ab')
  await popup.getByRole('slider', { name: 'Transparency' }).fill('63')
  expect(await page.evaluate(() => window.__referenceModels.selected.material.color.getHexString())).toBe('1278ab')
  expect(await page.evaluate(() => window.__referenceModels.selected.material.opacity)).toBeCloseTo(.37)
  await popup.getByRole('button', { name: 'Done', exact: true }).click()
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2, { button: 'right' })
  await page.getByRole('menuitem', { name: 'Color…', exact: true }).click()
  await expect(popup.getByRole('textbox', { name: 'Hex color' })).toHaveValue('#1278ab')
  await expect(popup.getByRole('slider', { name: 'Transparency' })).toHaveValue('63')
  await popup.getByRole('slider', { name: 'Transparency' }).fill('100')
  expect(await page.evaluate(() => window.__referenceModels.selected.material.opacity)).toBe(0)
  await page.keyboard.press('Escape')
  await expect(popup).not.toBeVisible()
  expect(await page.evaluate(() => window.__referenceModels.selected.material.opacity)).toBeCloseTo(.37)
  await page.screenshot({ path: '/tmp/nadoc-stl-reference.png' })
  await page.reload()
  await page.waitForFunction(() => window.__referenceModels)
  expect(await page.evaluate(() => window.__referenceModels.root.children.length)).toBe(0)
  expect(errors).toEqual([])
})


test('VR bridge applies poses and radial commands once and republishes after restart', async ({ page }) => {
  let publication = null, event = null, session = 'reference-session-1', posts = 0
  await page.route('**/api/vr/references', async route => {
    if (route.request().method() === 'POST') {
      publication = route.request().postDataJSON(); posts++
      await route.fulfill({ json: { published: true } })
    } else await route.fulfill({ json: { session, event } })
  })
  await page.goto('/?debug&doc=e2e-reference-bridge')
  await page.waitForFunction(() => window.__referenceModels)
  await page.locator('input[data-reference-stl]').setInputFiles({ name: 'reference.stl', mimeType: 'model/stl', buffer: Buffer.from(stl) })
  await expect.poll(() => publication?.models.length).toBe(1)
  const model = publication.models[0]
  const matrix = [...model.matrix]; matrix[12] = 17
  event = { sequence: 1, revision: publication.revision, id: model.id, matrix, action: '' }
  await expect.poll(() => page.evaluate(() => window.__referenceModels.selected?.position.x)).toBe(17)
  event = { ...event, sequence: 2, action: 'duplicate' }
  await expect.poll(() => publication?.models.length).toBe(2)
  expect(publication.models[1].matrix[12]).toBe(17)
  await page.waitForTimeout(1100)
  expect(await page.evaluate(() => window.__referenceModels.root.children.length)).toBe(2)
  const count = posts; session = 'reference-session-2'; event = null
  await expect.poll(() => posts).toBeGreaterThan(count)
  expect(publication.models).toHaveLength(2)
})

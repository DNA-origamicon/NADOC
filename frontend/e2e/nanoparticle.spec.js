import { expect, test } from '@playwright/test'

test('gold nanosphere is scriptable through create, resize, move, and delete', async ({ page }) => {
  test.setTimeout(90_000)
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  // Persisted E2E designs MUST use this prefix; global-teardown removes them
  // on success, assertion failure, or timeout.
  await page.fill('#new-design-name', '__e2e__nanoparticle')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))

  const created = await page.evaluate(() => window.__nadocTest.nanoparticles.create(10))
  const id = created.nanoparticle_id
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered().length)).toBe(1)

  const initial = await page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0])
  expect(initial).toMatchObject({ diameterNm: 10, metalness: 1, color: 0xd4af37 })
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({
    position: [15, 10, 15], target: [0, 0, 0],
  }))

  // A click is selection, not an orbit gesture, and immediately arms the same
  // Move/Rotate gizmo used by proteins.
  const point = await page.evaluate(id => window.__nadocTest.nanoparticles.screenPosition(id), id)
  expect(await page.evaluate(point => window.__nadocTest.nanoparticles.hitAt(point), point))
    .toMatchObject({ id })
  await page.evaluate(point => {
    const canvas = document.getElementById('canvas')
    canvas.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, button: 0, buttons: 1, clientX: point.x, clientY: point.y,
    }))
    canvas.dispatchEvent(new PointerEvent('pointerup', {
      bubbles: true, button: 0, buttons: 0, clientX: point.x, clientY: point.y,
    }))
  }, point)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.selected()))
    .toEqual({ kind: 'nanoparticle', id })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.gizmoAttached())).toBe(true)
  await expect(page.locator('#move-rotate-panel')).toBeVisible()

  // Right-click actions must remain mounted through the button click. The old
  // unconditional pointerdown closer removed the Edit button before click fired.
  await page.evaluate(point => {
    document.getElementById('canvas').dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, button: 2, buttons: 0, clientX: point.x, clientY: point.y,
    }))
  }, point)
  await expect(page.getByRole('button', { name: 'Edit diameter…' })).toBeVisible()
  page.once('dialog', dialog => dialog.accept('14'))
  await page.getByRole('button', { name: 'Edit diameter…' }).click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0]?.diameterNm)).toBe(14)

  // Orbiting away from the object must not turn the drag's release into an
  // empty-space deselection.
  const canvas = page.locator('#canvas')
  const box = await canvas.boundingBox()
  await page.mouse.move(box.x + box.width * 0.75, box.y + box.height * 0.7)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.6, { steps: 5 })
  await page.mouse.up()
  expect(await page.evaluate(() => window.__nadocTest.nanoparticles.selected())).toEqual({ kind: 'nanoparticle', id })

  // A true empty-space click deselects it.
  await page.evaluate(() => {
    const canvas = document.getElementById('canvas')
    const rect = canvas.getBoundingClientRect()
    const init = { bubbles: true, button: 0, clientX: rect.left + 15, clientY: rect.top + rect.height - 15 }
    canvas.dispatchEvent(new PointerEvent('pointerdown', { ...init, buttons: 1 }))
    canvas.dispatchEvent(new PointerEvent('pointerup', { ...init, buttons: 0 }))
  })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.selected())).toBeNull()

  await page.evaluate(id => window.__nadocTest.nanoparticles.select(id), id)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.gizmoAttached())).toBe(true)
  await page.keyboard.press('Escape')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.selected())).toBeNull()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.gizmoAttached())).toBe(false)

  await page.evaluate(id => window.__nadocTest.nanoparticles.resize(id, 18), id)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0]?.diameterNm)).toBe(18)

  await page.evaluate(id => window.__nadocTest.nanoparticles.move(id, {
    pivot: [0, 0, 0], translation: [3, 4, 5], rotation: [0, 0, 0, 1],
  }), id)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0]?.position))
    .toEqual([3, 4, 5])

  await page.evaluate(id => window.__nadocTest.nanoparticles.remove(id), id)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered().length)).toBe(0)
})

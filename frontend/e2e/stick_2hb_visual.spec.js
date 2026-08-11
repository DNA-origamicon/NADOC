/** Quick visual-quality regression for the F8 Stick representation on a real 2HB. */
import { test, expect } from '@playwright/test'
import { copyFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SOURCE = fileURLToPath(new URL('../../workspace/2hb_1xT.nadoc', import.meta.url))
const STEM = 'e2estick2hbvisual'
const TEMP = path.join(path.dirname(SOURCE), `${STEM}.nadoc`)

test.beforeAll(() => copyFileSync(SOURCE, TEMP))
test.afterAll(() => rmSync(TEMP, { force: true }))

test('F8 renders the 2HB as sticks without atom balls', async ({ page }) => {
  test.setTimeout(180_000)
  const consoleErrors = []
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()) })

  await page.goto('/?doc=e2e-stick-2hb')
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  await welcome.locator('.lib-row-name', { hasText: new RegExp(`^${STEM}$`) }).first().click({ timeout: 60_000 })
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })

  await page.locator('#canvas').click({ position: { x: 20, y: 20 } })
  await page.keyboard.press('F8')
  await expect(page.locator('#menu-view-atomistic-stick')).toHaveClass(/is-checked/)

  await expect.poll(() => page.evaluate(() => {
    let bonds = 0
    window.__nadocTest.scene.traverse(o => { if (o.name === 'atomBonds') bonds += o.count ?? 0 })
    return bonds
  }), { timeout: 120_000 }).toBeGreaterThan(100)

  const counts = await page.evaluate(() => {
    let bonds = 0; let spheres = 0
    window.__nadocTest.scene.traverse(o => {
      if (o.name === 'atomBonds') bonds += o.count ?? 0
      if (o.name === 'atomSpheres') spheres += o.count ?? 0
    })
    return { bonds, spheres }
  })
  expect(counts.spheres).toBe(0)
  expect(counts.bonds).toBeGreaterThan(100)
  expect(consoleErrors).toEqual([])
  await page.screenshot({ path: 'playwright-report/stick_2hb.png', fullPage: true })
})

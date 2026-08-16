import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FIXTURE = readFileSync(fileURLToPath(
  new URL('../../workspace/2hb_1xT.nadoc', import.meta.url)), 'utf8')

test('uniform adjacent domains render as continuous cylinder runs', async ({ page }) => {
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.stack || error.message))
  await page.goto('/?doc=e2e-uniform-cylinder-merge')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await page.evaluate(async () => {
    await window.__nadocTest.setRepresentation('cylinders')
    document.getElementById('menu-view-coloring-overhang-only')?.click()
  })
  await expect.poll(() => page.evaluate(() => {
    const scene = window.__nadocTest.scene
    const merged = scene.getObjectByName('mergedHelixCylinders')
    const domains = scene.getObjectByName('helixCylinders')
    return {
      mergedCount: merged?.count ?? 0,
      domainCount: domains?.count ?? 0,
      mergedVisible: !!merged?.visible,
      domainMaterialVisible: domains?.material?.visible,
    }
  })).toMatchObject({ mergedVisible: true, domainMaterialVisible: false })
  const counts = await page.evaluate(() => ({
    merged: window.__nadocTest.scene.getObjectByName('mergedHelixCylinders').count,
    domains: window.__nadocTest.scene.getObjectByName('helixCylinders').count,
  }))
  expect(counts.merged).toBeGreaterThan(0)
  expect(counts.merged).toBeLessThan(counts.domains)
  expect(pageErrors).toEqual([])
})

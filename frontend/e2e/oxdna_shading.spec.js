import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DESIGN = readFileSync(fileURLToPath(new URL('../../workspace/2hb.nadoc', import.meta.url)), 'utf8')

test('oxDNA uses shared-light shading without losing instance colors', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/?doc=e2e-oxdna-shading')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, DESIGN)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length ?? 0),
    { timeout: 120_000 }).toBeGreaterThan(0)
  await page.evaluate(() => window.__nadocTest.setRepresentation('oxdna'))
  await expect.poll(() => page.evaluate(() => {
    let count = 0
    window.__nadocTest.scene.traverse(object => {
      if (object.userData?.oxdnaPrimitive === 'backbone') count += object.count
    })
    return count
  }), { timeout: 120_000 }).toBeGreaterThan(0)
  const contract = await page.evaluate(() => {
    const materials = [], lights = []
    window.__nadocTest.scene.traverse(object => {
      if (object.isLight) lights.push(object.type)
      if (object.userData?.oxdnaPrimitive) materials.push({
        type: object.material.type,
        white: object.material.color.getHex() === 0xffffff,
        vertexColors: object.material.vertexColors,
        instanceColor: !!object.instanceColor,
      })
    })
    return { materials, lights }
  })
  expect(contract.materials).toHaveLength(4)
  expect(contract.materials.every(material => material.type === 'MeshPhongMaterial')).toBe(true)
  expect(contract.materials.every(material => material.white && !material.vertexColors && material.instanceColor)).toBe(true)
  expect(contract.lights.filter(type => type === 'AmbientLight')).toHaveLength(1)
  expect(contract.lights.filter(type => type === 'DirectionalLight')).toHaveLength(2)

  const coloring = await page.evaluate(async () => {
    const result = {}
    for (const mode of ['strand', 'base', 'cluster', 'overhang-only']) {
      const button = document.getElementById(`repr-color-${mode}`)
      result[mode] = { enabled: !button.disabled, colors: [] }
      button.click()
      await Promise.resolve()
      window.__nadocTest.scene.traverse(object => {
        if (object.userData?.oxdnaPrimitive !== 'backbone' || !object.instanceColor) return
        const color = new (object.material.color.constructor)()
        for (let i = 0; i < Math.min(object.count, 100); i++) {
          object.getColorAt(i, color)
          result[mode].colors.push(color.getHex())
        }
      })
      result[mode].active = window.__nadocTest.store.getState().coloringMode === mode
    }
    return result
  })
  for (const mode of ['strand', 'base', 'cluster', 'overhang-only']) {
    expect(coloring[mode].enabled).toBe(true)
    expect(coloring[mode].active).toBe(true)
    expect(coloring[mode].colors.length).toBeGreaterThan(0)
    expect(coloring[mode].colors.some(color => color !== 0)).toBe(true)
  }
})

import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Read an existing part; no workspace publication or session persistence.
// Saves are blocked, source bytes checked after failure too. Global teardown
// cleans credentials/__e2e__ scratch; reporter cleans screenshots and traces.
const fixture = new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)
let original
test.beforeEach(async ({ page }) => {
  original = readFileSync(fixture, 'utf8')
  await page.route('**/api/design/save-workspace', route => route.abort())
})
test.afterEach(() => expect(readFileSync(fixture, 'utf8')).toBe(original))

test('strand Full round trip follows expanded and unfolded live geometry', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?doc=e2e-strand-motion')
  await page.waitForFunction(() => !!window._nadocDebug)
  const id = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    await api.loadDesign('Examples/2hb_xover_atoms_test.nadoc')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const strand = store.getState().currentDesign.strands.find(s => s.strand_type === 'staple')
    createSelectionController({ store }).replace([{ kind: 'strand', id: strand.id }])
    return strand.id
  })
  async function press(key, representation) {
    await page.keyboard.press(key)
    await page.waitForFunction(async ({ id, representation }) => {
      const { store } = await import('/src/state/store.js')
      return store.getState().currentDesign.representation_overrides.some(r => r.strand_ids?.includes(id) && r.representation === representation)
    }, { id, representation })
  }
  await press('F7', 'ballstick'); await press('F4', 'full')
  const snapshot = () => page.evaluate(async id => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const root = window._nadocDebug.scene.getObjectByName(`view-volume-display-strand:${id}`)
    const matrix = new THREE.Matrix4(), native = [], local = []
    for (const e of [...window._nadocDebug.backboneEntries(), ...window._nadocDebug.slabEntries()].filter(e => e.nuc.strand_id === id)) {
      e.instMesh.getMatrixAt(e.id, matrix); native.push([...matrix.elements])
    }
    root?.traverse(o => {
      if (!['backboneSpheres', 'backboneCubes', 'baseSlabs'].includes(o.name)) return
      for (let i = 0; i < o.count; i++) { o.getMatrixAt(i, matrix); local.push([...matrix.elements]) }
    })
    const error = native.length && local.length === native.length
      ? Math.max(...native.map(a => Math.min(...local.map(b => Math.max(...a.map((v,i) => Math.abs(v-b[i]))))))) : 1e9
    return { native, local, error }
  }, id)
  await expect.poll(async () => (await snapshot()).error).toBeLessThan(1e-5)
  const before = (await snapshot()).native
  await page.keyboard.press('x')
  await page.waitForTimeout(400)
  await expect.poll(async () => JSON.stringify((await snapshot()).native)).not.toBe(JSON.stringify(before))
  await expect.poll(async () => (await snapshot()).error).toBeLessThan(1e-5)
  if (process.env.NADOC_STRAND_MOTION_REVIEW) {
    await page.screenshot({ path: testInfo.outputPath('expanded.png') })
    console.log('REVIEW', testInfo.outputPath('expanded.png'))
    await page.waitForTimeout(15_000)
  }
  await page.keyboard.press('x')
  await page.waitForTimeout(400)
  await expect.poll(async () => (await snapshot()).error).toBeLessThan(1e-5)
  await page.keyboard.press('u')
  await page.waitForTimeout(400)
  await page.waitForFunction(async () => (await import('/src/state/store.js')).store.getState().unfoldActive)
  await expect.poll(async () => (await snapshot()).error).toBeLessThan(1e-5)
  await press('F7', 'ballstick'); await press('F4', 'full')
  await expect.poll(async () => (await snapshot()).error).toBeLessThan(1e-5)
  await page.keyboard.press('F4')
  await page.waitForFunction(async id => (await import('/src/state/store.js')).store.getState().currentDesign.representation_overrides.some(r => r.strand_ids?.includes(id) && r.coloring === 'base'), id)
  await expect.poll(async () => (await snapshot()).error).toBeLessThan(1e-5)
  await page.keyboard.press('u')
  await page.waitForTimeout(400)
  await page.waitForFunction(async () => !(await import('/src/state/store.js')).store.getState().unfoldActive)
  await expect.poll(async () => (await snapshot()).error).toBeLessThan(1e-5)
  const restored = (await snapshot()).native
  expect(restored.length).toBe(before.length)
  expect(Math.max(...restored.flatMap((row, i) => row.map((v, j) => Math.abs(v - before[i][j]))))).toBeLessThan(1e-5)
  expect(errors).toEqual([])
})

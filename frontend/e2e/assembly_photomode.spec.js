import { test, expect } from '@playwright/test'
import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Representation troubleshooting:
//   NADOC_PHOTO_REPRS=surface npx playwright test e2e/assembly_photomode.spec.js
//   NADOC_PHOTO_REPRS=vdw,ballstick,stick npx playwright test e2e/assembly_photomode.spec.js
//   NADOC_PHOTO_REPRS=all npx playwright test e2e/assembly_photomode.spec.js
// Each switch records photomode bounds/shadow diagnostics, renderer counters,
// JavaScript/console errors, and WebGL context-loss events.

const TEST_NAME = '__e2e__assembly-photomode'
const TEST_FILE = `${TEST_NAME}.nass`
const TEST_PATH = resolve(process.cwd(), '..', 'workspace', TEST_FILE)
const ALL_REPRESENTATIONS = ['hull-prism', 'beads', 'full', 'surface', 'vdw', 'ballstick', 'stick', 'cylinders']
const requestedRepresentations = process.env.NADOC_PHOTO_REPRS
const REPRESENTATIONS = (requestedRepresentations === 'all'
  ? ALL_REPRESENTATIONS
  : requestedRepresentations
    ? requestedRepresentations.split(',')
    // Keep the ordinary regression bounded. Heavy representations are each
    // several minutes under SwiftShader and are available through the env seam.
    : ['hull-prism', 'beads', 'full', 'cylinders'])
  .map(value => value.trim()).filter(Boolean)

test.beforeAll(() => {
  const source = JSON.parse(readFileSync(resolve(process.cwd(), '..', 'workspace', 'BigO-poly.nass'), 'utf8'))
  source.metadata = { ...(source.metadata ?? {}), name: TEST_NAME }
  writeFileSync(TEST_PATH, JSON.stringify(source, null, 2))
})

test.afterAll(() => rmSync(TEST_PATH, { force: true }))

test('BigO assembly supports the complete photomode control surface', async ({ page }) => {
  test.setTimeout(1_800_000)
  const errors = []
  await page.addInitScript(() => {
    window.__photoContextLosses = 0
    window.addEventListener('DOMContentLoaded', () => {
      document.getElementById('canvas')?.addEventListener('webglcontextlost', () => {
        window.__photoContextLosses++
      })
    })
  })
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', error => errors.push(String(error)))

  await page.goto(`/?doc=__e2e__assembly-photo&open=${TEST_FILE}&open-type=assembly`)
  await page.waitForFunction(() => {
    const dbg = window.__NADOC_DBG__
    const box = dbg?.assemblyRenderer?.getBoundingBox?.()
    return dbg?.store.getState().assemblyActive && box && !box.isEmpty()
  }, null, { timeout: 45_000 })

  await page.locator('#photo-tab-btn').click()
  await expect(page.locator('#tab-content-photo')).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__photoMode?.isActive())).toBe(true)
  await expect(page.locator('#photo-status')).toContainText('key shadow on')
  await expect.poll(() => page.evaluate(
    () => window.__photoMode?.getStatus?.().radius,
  )).toBeGreaterThan(0)

  // Exercise every live rendering family against assembly geometry. Panel unit
  // tests cover individual wiring; this regression proves the real WebGL scene
  // accepts the resulting material, light, floor, figure and camera rebuilds.
  await page.locator('#photo-mat-full').selectOption('metallic')
  await page.locator('#photo-mat-cylinders').selectOption('glossy')
  await page.locator('#photo-mat-surface').selectOption('glass')
  await page.locator('#photo-mat-atomistic').selectOption('cpk-metallic')
  await page.locator('#photo-key-shadow').uncheck()
  await page.locator('#photo-key-shadow').check()
  await page.locator('#photo-floor-axis').selectOption('+z')
  await page.locator('#photo-floor-offset').fill('4')
  await page.locator('#photo-floor-offset').dispatchEvent('input')
  await page.locator('#photo-outline').check()
  await page.locator('#photo-depthcue').check()
  await page.locator('#photo-parallel').check()
  await page.locator('#photo-bg-type').selectOption('transparent')

  await expect.poll(() => page.evaluate(() => {
    const s = window.__photoMode?.getSettings?.()
    return s && {
      full: s.full,
      cylinders: s.cylinders,
      surface: s.surface,
      atomistic: s.atomistic,
      keyShadow: s.keyShadow,
      floorAxis: s.floorAxis,
      floorOffset: s.floorOffset,
      outline: s.outline,
      depthCue: s.depthCue,
      parallel: s.parallel,
      bgType: s.bgType,
    }
  })).toEqual({
    full: 'metallic', cylinders: 'glossy', surface: 'glass', atomistic: 'cpk-metallic',
    keyShadow: true, floorAxis: '+z', floorOffset: 4,
    outline: true, depthCue: true, parallel: true, bgType: 'transparent',
  })

  // Actual assembly representations, not the photomode MATERIAL dropdowns.
  // Wait on the renderer's rebuild callback so each assertion observes the
  // fresh meshes after its asynchronous surface/atomistic preparation.
  const diagnostics = []
  for (const representation of REPRESENTATIONS) {
    console.log(`[assembly-photomode] switching to ${representation}`)
    await page.evaluate(async rep => {
      const api = await import('/src/api/client.js')
      const dbg = window.__NADOC_DBG__
      const instances = dbg.store.getState().currentAssembly.instances
      const rebuilt = new Promise(resolve => dbg.assemblyRenderer.onRebuildComplete(resolve))
      const result = await api.batchPatchInstances(
        instances.map(instance => ({ id: instance.id, representation: rep })),
      )
      if (!result) throw new Error(`batchPatchInstances failed for ${rep}`)
      await rebuilt
    }, representation)
    await page.waitForTimeout(500)
    diagnostics.push(await page.evaluate(rep => ({
      representation: rep,
      instances: window.__NADOC_DBG__.store.getState().currentAssembly.instances.map(i => i.representation),
      photo: window.__photoMode.getDiagnostics(),
      contextLost: window.__NADOC_DBG__.renderer.getContext().isContextLost(),
      contextLossEvents: window.__photoContextLosses,
      render: { ...window.__NADOC_DBG__.renderer.info.render },
      visibleMeshes: (() => {
        const rows = []
        window.__NADOC_DBG__.scene.traverse(object => {
          if ((!object.isMesh && !object.isInstancedMesh) || !object.visible) return
          let visible = object.material?.visible !== false
          for (let parent = object.parent; visible && parent; parent = parent.parent) visible = parent.visible
          if (visible && (!object.isInstancedMesh || object.count > 0)) {
            rows.push({ name: object.name || '(unnamed)', count: object.count ?? 1 })
          }
        })
        return rows
      })(),
    }), representation))
    console.log(`[assembly-photomode] ${representation} rendered`)
  }
  for (const diagnostic of diagnostics) {
    expect(diagnostic.instances.every(rep => rep === diagnostic.representation), JSON.stringify(diagnostic)).toBe(true)
    expect(diagnostic.photo.active, JSON.stringify(diagnostic)).toBe(true)
    expect(diagnostic.photo.bounds?.radius, JSON.stringify(diagnostic)).toBeGreaterThan(0)
    expect(diagnostic.photo.keyLight?.castShadow, JSON.stringify(diagnostic)).toBe(true)
    expect(diagnostic.photo.keyLight?.mapRendered, JSON.stringify(diagnostic)).toBe(true)
    expect(diagnostic.photo.meshes?.casters, JSON.stringify(diagnostic)).toBeGreaterThan(0)
    expect(diagnostic.photo.meshes?.receivers, JSON.stringify(diagnostic)).toBeGreaterThan(0)
    expect(diagnostic.contextLost, JSON.stringify(diagnostic)).toBe(false)
    expect(diagnostic.contextLossEvents, JSON.stringify(diagnostic)).toBe(0)
    expect(diagnostic.render.calls, JSON.stringify(diagnostic)).toBeGreaterThan(0)
    const names = diagnostic.visibleMeshes.map(mesh => mesh.name)
    const has = name => names.includes(name)
    const hasPrefix = prefix => names.some(name => name.startsWith(prefix))
    if (diagnostic.representation === 'hull-prism') expect(has('sharedLodHull'), JSON.stringify(diagnostic)).toBe(true)
    if (diagnostic.representation === 'beads') {
      expect(has('backboneSpheres'), JSON.stringify(diagnostic)).toBe(true)
      expect(has('baseSlabs'), JSON.stringify(diagnostic)).toBe(false)
    }
    if (diagnostic.representation === 'full') expect(has('baseSlabs'), JSON.stringify(diagnostic)).toBe(true)
    if (diagnostic.representation === 'surface') expect(has('assemblySurface'), JSON.stringify(diagnostic)).toBe(true)
    if (diagnostic.representation === 'vdw' || diagnostic.representation === 'ballstick') {
      expect(hasPrefix('atomImpostor_'), JSON.stringify(diagnostic)).toBe(true)
      expect(has('sharedLodHull'), JSON.stringify(diagnostic)).toBe(false)
    }
    if (diagnostic.representation === 'vdw') expect(hasPrefix('atomBond_'), JSON.stringify(diagnostic)).toBe(false)
    if (diagnostic.representation === 'ballstick') expect(hasPrefix('atomBond_'), JSON.stringify(diagnostic)).toBe(true)
    if (diagnostic.representation === 'stick') {
      expect(hasPrefix('atomBond_'), JSON.stringify(diagnostic)).toBe(true)
      expect(has('sharedLodHull'), JSON.stringify(diagnostic)).toBe(false)
    }
    if (diagnostic.representation === 'cylinders') {
      expect(has('sharedLodMid') || has('sharedLodCurvedCyl'), JSON.stringify(diagnostic)).toBe(true)
    }
  }

  // Let multiple composed frames and the periodic geometry signature check run.
  await page.waitForTimeout(1_000)
  expect(errors).toEqual([])

  // Dispatch in-page: Playwright's physical click waits for a compositor
  // stability round-trip, which can starve behind SwiftShader when a large
  // atomistic assembly is drawing. The DOM event is the application contract.
  // The full/default matrix deliberately ends on Cylinders so physical exit is
  // also covered. A targeted heavy-rep diagnostic may leave software WebGL busy
  // for minutes per frame; closing its isolated browser is the teardown rather
  // than turning compositor starvation into a false application failure.
  if (REPRESENTATIONS.at(-1) === 'cylinders') {
    await page.evaluate(() => document.getElementById('photo-exit-btn')?.click())
    await expect.poll(
      () => page.evaluate(() => window.__photoMode?.isActive()),
      { timeout: 60_000 },
    ).toBe(false)
    await expect(page.locator('#tab-content-photo')).toBeHidden()
    expect(errors).toEqual([])
  }
})

import { test, expect } from '@playwright/test'

// Run through scripts/run_deformation_history_e2e.py: all workspace/autosave,
// project-history, browser and Vite files are inside its fresh owned root and
// removed by its finally block after server shutdown, even on test failure.
// The fixture uses ordinary recorded authoring commands; no copied snapshots.
test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')

async function createPartInEditor(page, name) {
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill(name)
  await Promise.all([
    page.waitForResponse(r => new URL(r.url()).pathname === '/api/design' && r.request().method() === 'POST'),
    page.getByRole('button', { name: 'Create', exact: true }).click(),
  ])
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
}

const scenarios = [
  ['cylinders'], ['beads'], ['vdw'], ['ballstick'], ['stick'], ['surface'], ['hull-prism'],
  ['cylinders', 'vdw'], ['cylinders', 'ballstick', 'cylinders'],
]
const keys = { cylinders: 'F2', beads: 'F3', vdw: 'F6', ballstick: 'F7', stick: 'F8', surface: 'F5', 'hull-prism': 'F1' }
const menu = { cylinders: 'detail-cylinders', beads: 'detail-beads', vdw: 'atomistic-vdw',
  ballstick: 'atomistic-ballstick', stick: 'atomistic-stick', surface: 'surface', 'hull-prism': 'hull-prism' }
for (const switches of scenarios) {
  const representation = switches.at(-1), atomic = ['vdw', 'ballstick', 'stick'].includes(representation)
  const cg = ['cylinders', 'beads'].includes(representation)
  test(`feature scrub preserves ${switches.join(' → ')}`, async ({ page, request }) => {
    page.setDefaultTimeout(10000)
    await page.setViewportSize({ width: 900, height: 650 })
    const doc = `__e2e__seek-representation-${switches.join('-')}`
    const errors = []
    const simulationRequests = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => {
      const path = new URL(request.url()).pathname
      if (/^\/api\/(cando|snupi|mrdna|blade|oxdna|md|lammps|simulate)\/jobs(?:\/|$)/.test(path)) {
        simulationRequests.push(path)
      }
    })
    try {
      await page.goto(`/?doc=${doc}`, { waitUntil: 'domcontentloaded' })
      await page.waitForFunction(() => {
        if (!window.__nadocTest) return false
        window.__nadocTest.pauseViewerRenderingForTest()
        return true
      })
      await createPartInEditor(page, doc)
      await page.evaluate(async name => {
        const api = await import('/src/api/client.js')
        if (!await api.createBundle({ cells: [[0, 0], [0, 1]], lengthBp: 21, name })) throw new Error('Bundle failed')
        if (!await api.addBundleSegment({ cells: [[3, 0]], lengthBp: 21 })) throw new Error('Extrude failed')
      }, doc)
      await expect(page.locator('#fl-list [data-fl-row]')).toHaveCount(3)
      for (const repr of switches) {
        await page.keyboard.press(keys[repr])
        await expect(page.locator(`#menu-view-${menu[repr]}`)).toHaveClass(/is-checked/)
      }
      await page.mouse.move(2, 2)
      await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [24, 30, 42], target: [4, 0, 4] }))

      const display = () => page.evaluate(() => {
        const t = window.__nadocTest, renderer = t.getDesignRenderer()
        const ctrl = renderer.getHelixCtrl()
        const visible = mesh => {
          if (!mesh) return false
          for (let node = mesh; node; node = node.parent) if (!node.visible) return false
          return !!mesh.parent
        }
        const meshes = []
        t.scene.traverseVisible(node => {
          if (node.isMesh && (!node.isInstancedMesh || node.count > 0)) meshes.push(node.name || node.geometry.type)
        })
        return { cg: ctrl.root.visible, detail: renderer.getDetailLevel(),
          beads: visible(renderer.getBackboneEntries()[0]?.instMesh),
          slabs: visible(renderer.getSlabEntries()[0]?.instMesh),
          atomistic: t.getAtomisticRenderer().getMode(), meshes: meshes.sort() }
      })
      const before = await display()
      expect(before.cg).toBe(cg)
      // Render real WebGL frames on demand: software rasterization need not run
      // continuously while waiting for HTTP. No image files are persisted.
      const pixels = () => page.evaluate(() => window.__nadocTest.renderedPixelCensus())
      const beforePixels = await pixels()
      const beforeCamera = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera)
      expect(beforePixels.visible).toBeGreaterThan(0)
      simulationRequests.length = 0
      for (const rowIndex of [1, 2, 1, 2]) {
        const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/seek')
        await page.evaluate(index => {
          const thumb = document.querySelector('#fl-rail .feature-seek-readiness').parentElement
          const row = document.querySelectorAll('#fl-list [data-fl-row]')[index]
          const box = row.getBoundingClientRect()
          thumb.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientY: box.top, pointerId: 1 }))
          document.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientY: box.top + box.height / 2, pointerId: 1 }))
          document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 }))
        }, rowIndex)
        expect((await response).ok()).toBe(true)
        await expect(page.locator('#fl-rail [data-readiness="ready"]')).toBeAttached()
        const after = await display()
        expect(after.cg).toBe(cg)
        expect(after.detail).toBe(before.detail)
        expect(after.beads).toBe(representation === 'beads')
        expect(after.slabs).toBe(false)
        expect(after.atomistic).toBe(atomic ? representation : 'off')
        if (rowIndex === 2) await expect.poll(async () => (await display()).meshes).toEqual(before.meshes)
      }
      expect(await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera)).toEqual(beforeCamera)
      await expect.poll(pixels).toEqual(beforePixels)
      // Let edit-driven freshness debounces expire; an unused engine has no
      // results to check, including after the final scrub has painted.
      await page.waitForTimeout(300)
      expect(simulationRequests).toEqual([])
      expect(errors).toEqual([])
    } finally {
      await page.close()
      // The launcher owns persistent cleanup even if Playwright closes this
      // request context on timeout; do not obscure the original failure.
      await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`, { timeout: 5000 }).catch(() => {})
    }
  })
}

test('empty simulation panels stay idle after edits across engines', async ({ page, request }) => {
  page.setDefaultTimeout(10000)
  await page.setViewportSize({ width: 1600, height: 900 })
  const doc = '__e2e__seek-representation-empty-engines'
  const errors = [], requests = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
    const path = new URL(request.url()).pathname
    if (/^\/api\/(cando|snupi|mrdna|blade|oxdna|md|lammps|simulate)\/jobs(?:\/|$)/.test(path)) requests.push(path)
  })
  const jobsResponse = engine => page.waitForResponse(r => new URL(r.url()).pathname === `/api/${engine}/jobs`)
  try {
    await page.goto(`/?doc=${doc}`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => {
      if (!window.__nadocTest) return false
      window.__nadocTest.pauseViewerRenderingForTest()
      return true
    })
    await createPartInEditor(page, doc)
    await page.evaluate(async name => {
      const api = await import('/src/api/client.js')
      if (!await api.createBundle({ cells: [[0, 0]], lengthBp: 21, name })) throw new Error('Bundle failed')
    }, doc)
    await page.keyboard.press('F6')
    await expect(page.locator('#menu-view-atomistic-vdw')).toHaveClass(/is-checked/)
    const initialJobs = jobsResponse('simulate')
    const initialOxdna = jobsResponse('oxdna')
    await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
    expect(await (await initialJobs).json()).toEqual([])
    expect(await (await initialOxdna).json()).toEqual([])
    for (const [index, engine] of ['cando', 'snupi', 'mrdna', 'namd', 'oxdna'].entries()) {
      const discovery = jobsResponse(engine === 'namd' ? 'md' : engine)
      await page.locator(`.engine-selector-btn[data-engine="${engine}"]`).click()
      expect(await (await discovery).json()).toEqual([])
      await page.waitForTimeout(300)
      requests.length = 0
      await page.evaluate(async index => {
        const api = await import('/src/api/client.js')
        if (!await api.addBundleSegment({ cells: [[3 * (index + 1), 0]], lengthBp: 21 })) throw new Error('Extrude failed')
      }, index)
      await page.waitForTimeout(300)
      expect(requests, `${engine} must not search for absent jobs/results after an edit`).toEqual([])
      expect(await page.evaluate(() => window.__nadocTest.getDesignRenderer().getHelixCtrl().root.visible)).toBe(false)
      expect(await page.evaluate(() => window.__nadocTest.getAtomisticRenderer().getMode())).toBe('vdw')
    }
    expect(errors).toEqual([])
  } finally {
    await page.close()
    await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`, { timeout: 5000 }).catch(() => {})
  }
})

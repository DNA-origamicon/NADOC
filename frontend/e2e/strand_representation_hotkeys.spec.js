import { expect, test } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'

// Existing part, display-only changes in an isolated session. Never publish it.
// No saved designs; save-workspace is blocked. Browser storage dies with context.
// Config disables session persistence; global teardown removes test credentials
// and __e2e__ playback scratch; reporter cleans screenshots/traces.
const fixture = new URL('../../workspace/duplex.nadoc', import.meta.url)
let original
test.beforeEach(async ({ page }) => {
  test.skip(!existsSync(fixture), 'Existing duplex fixture unavailable')
  original = readFileSync(fixture, 'utf8')
  await page.route('**/api/design/save-workspace', route => route.abort())
})
test.afterEach(() => { if (original) expect(readFileSync(fixture, 'utf8')).toBe(original) })

test('F7 and repeat coloring stay on the selected strand', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('requestfailed', request => console.log('Failed request:', new URL(request.url()).pathname, request.failure()?.errorText))
  await page.goto('/?doc=e2e-strand-representation')
  await page.waitForFunction(() => !!window._nadocDebug)
  const id = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    await api.loadDesign('workspace/duplex.nadoc')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const strand = store.getState().currentDesign.strands.find(s => s.strand_type === 'staple')
    createSelectionController({ store }).replace([{ kind: 'strand', id: strand.id }])
    return strand.id
  })
  const snapshot = () => page.evaluate(async id => {
    const { store } = await import('/src/state/store.js')
    const state = store.getState()
    const root = window._nadocDebug.scene.getObjectByName(`view-volume-display-strand:${id}`)
    let instances = 0, colors = []
    root?.traverse(o => { if (o.isInstancedMesh) instances += o.count; if (o.instanceColor) colors.push(...o.instanceColor.array.slice(0, 30)) })
    const beads = window._nadocDebug.backboneEntries().map(e => ({
      strand: e.nuc.strand_id, alpha: e.instMesh._instanceAlpha?.getX(e.id) ?? 1,
    }))
    return { beads, overrides: state.currentDesign.representation_overrides,
      coloring: state.coloringMode, full: document.getElementById('menu-view-detail-full').classList.contains('is-checked'), instances, colors }
  }, id)
  const renderedColors = {}
  for (const coloring of ['strand', 'base', 'cluster', 'cpk', 'strand']) {
    await page.keyboard.press('F7')
    await expect.poll(async () => (await snapshot()).overrides.map(r => ({ ids: r.strand_ids, segments: r.segments, repr: r.representation, coloring: r.coloring })))
      .toEqual([{ ids: [id], segments: [], repr: 'ballstick', coloring }])
    await expect.poll(async () => (await snapshot()).instances, { timeout: 60_000 }).toBeGreaterThan(0)
    const result = await snapshot()
    renderedColors[coloring] = result.colors
    expect(result.coloring).toBe('strand')
    expect(result.full).toBe(true)
    expect(result.beads.filter(b => b.strand === id).every(b => b.alpha === 0)).toBe(true)
    expect(result.beads.filter(b => b.strand !== id).every(b => b.alpha === 1)).toBe(true)
  }
  expect(renderedColors.cpk).not.toEqual(renderedColors.strand)
  expect(errors).toEqual([])
})

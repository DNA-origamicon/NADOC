import { test, expect } from '@playwright/test'
import { readFile, rm } from 'node:fs/promises'

// Persistence inventory: private project identity + one workspace test file and
// revision directory. afterAll removes both after browser contexts close, including
// on failure. Session cache is disabled; the reporter removes Playwright artifacts.
const projectId = '__e2e__hinge_ligation_save'
const savePath = `playwright_tests/${projectId}.nadoc`
test.afterAll(async () => {
  await rm(`../workspace/${savePath}`, { force: true })
  await rm(`../workspace/.nadoc-projects/${projectId}`, { recursive: true, force: true })
})
test('Hinge pencil ligation does not reselect connected strands across tabs', async ({ page, context }) => {
  test.setTimeout(120_000)
  await context.route(/\/api\/(mrdna|oxdna|md)\/jobs(?:\?.*)?$/, route => route.fulfill({ json: { jobs: [] } }))
  // Test-only access to real canvas coordinates and rendered selection.
  await context.route('**/src/cadnano-editor/pathview.js', async route => {
    const response = await route.fetch()
    await route.fulfill({ response, body: (await response.text()).replace('  // ── Public interface', `
  window.__ligationProbe = {
    selected: () => [..._selectedElements], event: () => _dbgLastEvent,
    ends: () => _design.strands.filter(s => !s.is_circular).flatMap(s =>
      [['5p', s.domains[0], 'start_bp'], ['3p', s.domains.at(-1), 'end_bp']].map(([end, d, bp]) => {
        const row = _rowMap.get(d.helix_id)
        const x = _bpCenterX(d[bp]) * _zoom + _panX
        const y = row[d.direction === 'FORWARD' ? 'fwdY' : 'revY'] * _zoom + _panY
        const lineX = _bpCenterX(Math.floor((d.start_bp + d.end_bp) / 2)) * _zoom + _panX
        const hit = _hitTest(x, y)
        const lineWorld = _screenToRealWorld(lineX, y)
        return { id: s.id, type: s.strand_type, end, helix: d.helix_id,
          x, y, lineX,
          hittable: hit?.strand.id === s.id && hit.endWhich === end && !_hitTestCrossoverSprite(x, y),
          lineHittable: _hitTest(lineX, y)?.strand.id === s.id &&
            !_hitTestCrossoverSprite(lineX, y) && !_hitTestArc(lineWorld.wx, lineWorld.wy) }
      })),
  }
  // ── Public interface`) })
  })
  const doc = '__e2e__hinge_ligation'
  const headers = { 'X-NADOC-Doc': doc }
  const api = `${process.env.NADOC_E2E_API_BASE}/api`
  const fixture = JSON.parse(await readFile('../workspace/Hinge_test.nadoc', 'utf8'))
  Object.assign(fixture, { id: projectId, loadouts: [], active_loadout_id: null, last_editable_loadout_id: null })
  fixture.metadata.identity_last_known_path = savePath
  const content = JSON.stringify(fixture)
  expect((await page.request.post(`${api}/design/import`, { headers, data: { content } })).ok()).toBeTruthy()
  expect((await page.request.post(`${api}/design/save-workspace`, { headers, data: { path: savePath, overwrite: true } })).ok()).toBeTruthy()
  await context.addInitScript(({ doc, savePath }) => localStorage.setItem(`nadoc:workspace-path:${doc}`, savePath), { doc, savePath })
  const saves = []
  context.on('response', response => { if (response.url().endsWith('/design/save-workspace')) saves.push(response.status()) })
  await page.goto(`/?doc=${doc}`)
  await page.evaluate(async () => { window.__hingeStore = (await import('/src/state/store.js')).store })
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async () => { const api = await import('/src/api/client.js'); await api.getDesign(); await api.getGeometry() })
  const editor = await context.newPage()
  await editor.goto(`/cadnano-editor.html?doc=${doc}`)
  await editor.waitForFunction(() => window.__ligationProbe?.ends().length > 0)
  await editor.keyboard.press('f')
  const ends = await editor.evaluate(() => window.__ligationProbe.ends())
  const box = await editor.locator('#pathview-canvas').boundingBox()
  const visible = ends.filter(e => e.hittable && e.x > 45 && e.x < box.width - 10 && e.y > 30 && e.y < box.height - 10)
  const a = visible.find(e => e.end === '3p' && e.lineHittable && e.lineX > 45 && e.lineX < box.width - 10 && visible.some(f => f.end === '5p' && f.type === e.type && f.id !== e.id && f.helix !== e.helix))
  expect(a, 'a visible, hit-testable 3′ endpoint with a matching 5′ target').toBeTruthy()
  const b = visible.find(e => e.end === '5p' && e.type === a.type && e.id !== a.id && e.helix !== a.helix)
  await editor.mouse.click(box.x + a.lineX, box.y + a.y)
  await expect.poll(() => editor.evaluate(() => window.__ligationProbe.selected().length)).toBeGreaterThan(0)
  await expect.poll(() => page.evaluate(() => window.__hingeStore.getState().selection.items.map(r => r.id))).toContain(a.id)
  await editor.keyboard.press('r')
  await editor.mouse.click(box.x + a.x, box.y + a.y)
  const done = editor.waitForResponse(r => r.url().endsWith('/design/forced-ligation') && r.request().method() === 'POST')
  await editor.mouse.click(box.x + b.x, box.y + b.y)
  const response = await done
  expect(response.ok(), await response.text()).toBeTruthy()
  const after = await response.json()
  await expect.poll(() => page.evaluate(() => window.__hingeStore.getState().currentDesign.strands.length), { timeout: 30000 }).toBe(after.design.strands.length)
  await editor.waitForTimeout(1500)
  expect(await editor.evaluate(() => window.__ligationProbe.selected())).toEqual([])
  await expect.poll(() => saves.length).toBeGreaterThan(0)
  expect(saves.every(status => status === 200), `save statuses: ${saves}`).toBeTruthy()
  const saved = JSON.parse(await readFile(`../workspace/${savePath}`, 'utf8'))
  expect(saved.forced_ligations.length).toBe(fixture.forced_ligations.length + 1)
  expect(saved.strands.length).toBe(fixture.strands.length - 1)
  for (const [shortcut, count] of [['Control+z', fixture.strands.length], ['Control+y', fixture.strands.length - 1]]) {
    const savedAgain = editor.waitForResponse(r => r.url().endsWith('/design/save-workspace'))
    await editor.keyboard.press(shortcut)
    expect((await savedAgain).status()).toBe(200)
    await expect.poll(async () => JSON.parse(await readFile(`../workspace/${savePath}`, 'utf8')).strands.length).toBe(count)
  }
  expect(saves.every(status => status === 200), `save statuses: ${saves}`).toBeTruthy()
})

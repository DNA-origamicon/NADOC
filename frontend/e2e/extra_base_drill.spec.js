import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002') + '/api'

// Real recorded authoring commands only. File→New in the harness names the
// autosaved part __e2e__*; global teardown removes it and its project history
// even after a failed assertion. No native snapshots or manual feature rows.
test('extra crossover bases: default strand→base drill, Base parity, arc and clipboard', async ({ page, context }) => {
  test.setTimeout(60_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  const doc = `__e2e__extra-base-${Date.now()}`
  const headers = { 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name: 'extra-base-drill' })
  async function command(method, path, data) {
    const response = await page.request[method](`${API}/design/${path}`, { headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return (await response.json()).design
  }
  let design = await command('post', 'helix-at-cell', { row: 0, col: 1, length_bp: 200 })
  const [a, b] = design.helices
  design = await command('post', 'strands', { strand_type: 'staple', sequence: 'CCCCCCCCCC',
    domains: [{ helix_id: a.id, start_bp: 99, end_bp: 90, direction: 'REVERSE' }] })
  const first = design.strands.find(s => s.strand_type === 'staple')
  design = await command('post', 'strands', { strand_type: 'staple', sequence: 'GGGGGGGGGG',
    domains: [{ helix_id: b.id, start_bp: 90, end_bp: 99, direction: 'FORWARD' }] })
  const second = design.strands.find(s => s.strand_type === 'staple' && s.id !== first.id)
  design = await command('post', 'forced-ligation', { three_prime_strand_id: first.id, five_prime_strand_id: second.id })
  const fl = design.forced_ligations[0]
  design = await command('patch', `forced-ligations/${fl.id}/extra-bases`, { sequence: 'ATTTTT' })
  const strand = design.strands.find(s => s.strand_type === 'staple')
  await page.evaluate(d => {
    const channel = new BroadcastChannel('nadoc-design')
    channel.postMessage({ type: 'design-changed', source: 'e2e-extra', docId: d })
    channel.close()
  }, doc)
  await page.waitForFunction(id => Object.values(window.__nadocTest.getRenderedXoverExtraGeometry())
    .filter(e => e.crossoverId === id).length === 6, fl.id)

  // Find a genuinely exposed insert using the rendered meshes. Curved runs
  // can occlude their neighbors, and strand highlighting changes bead radii.
  async function frameInsert(wantedKey = null) {
    return page.evaluate(async ({ id, wantedKey }) => {
      const THREE = await import('/node_modules/three/build/three.module.js')
      const { isVisibleInstance } = await import('/src/scene/base_pick.js')
      const api = window.__nadocTest
      const renderer = api.getDesignRenderer()
      const extras = renderer.getXoverBeadEntries().filter(e => e.xoId === id)
        .sort((a, b) => Math.abs(a.simK - 2.5) - Math.abs(b.simK - 2.5))
      const entries = [...renderer.getBackboneEntries(), ...extras]
      const meshes = [...new Set(entries.map(e => e.instMesh))]
      const matrix = new THREE.Matrix4()
      for (const bead of extras) {
        const key = `__xb__:${id}:${bead.simK}`
        if (wantedKey && key !== wantedKey) continue
        bead.instMesh.getMatrixAt(bead.id, matrix)
        const target = new THREE.Vector3().setFromMatrixPosition(matrix)
        for (const direction of [[0,-1,0], [0,1,0], [1,0,0], [-1,0,0], [1,1,1], [-1,-1,1]]) {
          const offset = new THREE.Vector3(...direction).normalize().multiplyScalar(14)
          const position = target.clone().add(offset)
          const ray = new THREE.Raycaster(position, offset.clone().normalize().negate())
          const hit = ray.intersectObjects(meshes).find(h => isVisibleInstance(h.object, h.instanceId))
          if (hit?.object !== bead.instMesh || hit.instanceId !== bead.id) continue
          api.applyCameraPoseForTest({ position: position.toArray(), target: target.toArray(), up: [0,0,1] })
          return { key, letter: 'ATTTTT'[bead.simK] }
        }
      }
      throw new Error('No exposed crossover insert bead')
    }, { id: fl.id, wantedKey })
  }
  await frameInsert()
  await page.waitForTimeout(300)
  const canvas = await page.locator('#canvas').boundingBox()
  const point = { x: canvas.x + canvas.width / 2, y: canvas.y + canvas.height / 2 }
  await page.mouse.click(point.x, point.y)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getCanonicalSelection().primary))
    .toEqual({ kind: 'strand', id: strand.id })
  const { key, letter } = await frameInsert()
  await page.waitForTimeout(100)
  await page.mouse.click(point.x, point.y)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSelectedBaseKeys())).toEqual([key])

  // A selection reconciliation after refresh must retain forced-ligation bases.
  await page.evaluate(d => {
    const channel = new BroadcastChannel('nadoc-design')
    channel.postMessage({ type: 'design-changed', source: 'e2e-refresh', docId: d })
    channel.close()
  }, doc)
  await page.waitForTimeout(400)
  expect(await page.evaluate(() => window.__nadocTest.getSelectedBaseKeys())).toEqual([key])
  await page.keyboard.press('Escape')
  await page.locator('#canvas').click({ position: { x: 4, y: 4 } })
  await page.locator('#select-filter-trigger').click()
  await page.locator('#select-filter .sf-btn[data-key="base"]').click()
  await frameInsert(key)
  await page.waitForTimeout(100)
  await page.mouse.click(point.x, point.y)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSelectedBaseKeys())).toEqual([key])

  await page.locator('#sheet-toggle').click()
  const row = page.locator(`tr[data-strand-id="${strand.id}"]`)
  const sequence = row.locator('.sheet-seq')
  await expect(sequence).toHaveText('CCCCCCCCCCATTTTTGGGGGGGGGG')
  await expect(sequence.locator('.sheet-seq-extra')).toHaveText('ATTTTT')
  await expect(sequence.locator('.sheet-seq-extra .sheet-seq-selected-base')).toHaveText(letter)
  expect(await sequence.locator('.sheet-seq-extra').evaluate(el =>
    getComputedStyle(el, '::before').borderTopStyle)).toBe('solid')
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await sequence.evaluate(el => {
    const range = document.createRange()
    range.selectNodeContents(el)
    const selection = window.getSelection()
    selection.removeAllRanges()
    selection.addRange(range)
  })
  await page.keyboard.press('Control+c')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('CCCCCCCCCCATTTTTGGGGGGGGGG')
  expect(errors).toEqual([])
})

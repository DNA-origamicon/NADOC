/**
 * Assembly ds-linker connector arcs — port of the per-design overhang_link_arcs
 * connector arcs to the assembly view. A white tube bridges each ds linker
 * strand's complement↔bridge domain junction (the gap between a part's overhang
 * binding domain and the native-length __lnk__ bridge duplex).
 *
 * Probe: load a fixture with a ds linker and report the linker group contents.
 * Requires the shared renderer (default) so window.__NADOC_DBG__ is set.
 */

import { test, expect } from '@playwright/test'

const MODE = '#mode-indicator'
const NASS = 'Linker_Assem_test2'   // pre-existing workspace fixture (1 ds connection)

const PROBE = `(() => {
  const dbg = window.__NADOC_DBG__
  let group = null
  dbg.scene.traverse(o => { if (o.name === 'assembly_linkers') group = o })
  if (!group) return { found: false }
  let arcs = 0, others = 0
  const arcLens = []
  group.traverse(o => {
    if (o === group) return
    if (o.name === 'assemblyDsConnectorArc') {
      arcs++
      o.geometry.computeBoundingBox?.()
      const bb = o.geometry.boundingBox
      if (bb) arcLens.push(+bb.min.distanceTo(bb.max).toFixed(2))
    } else if (o.isMesh || o.isInstancedMesh) {
      others++
    }
  })
  const asm = dbg.store.getState().currentAssembly
  const dsStrands = (asm?.assembly_strands ?? []).filter(s => /^__lnk__.+__(a|b)$/.test(s.id ?? ''))
  return { found: true, arcs, others, arcLens, dsStrandCount: dsStrands.length,
    connCount: (asm?.overhang_connections ?? []).length }
})()`

async function openFixtureWithLinker(page) {
  await page.goto('/')
  await page.waitForTimeout(800)
  const row = page.locator('.lib-row-name', { hasText: NASS }).first()
  await row.waitFor({ state: 'visible', timeout: 10_000 })
  await row.click()
  await expect(page.locator(MODE)).toContainText('ASSEMBLY', { timeout: 20_000 })
  await page.waitForFunction(
    () => !document.getElementById('file-load-progress')?.classList.contains('visible'),
    { timeout: 15_000 },
  )
  // Wait until the linker group has been built (bridge meshes present).
  await page.waitForFunction(() => {
    const dbg = window.__NADOC_DBG__
    if (!dbg) return false
    let group = null
    dbg.scene.traverse(o => { if (o.name === 'assembly_linkers') group = o })
    return group && group.children.length > 0
  }, { timeout: 15_000 })
  await page.waitForTimeout(500)
}

test('ds linker connector arcs render in the assembly view', async ({ page }) => {
  await openFixtureWithLinker(page)

  const p = await page.evaluate(PROBE)
  console.log('[linker probe]', JSON.stringify(p))
  expect(p.found, 'assembly_linkers group exists').toBe(true)
  expect(p.dsStrandCount, 'fixture has ds linker side strands').toBeGreaterThanOrEqual(1)
  // One connector arc per ds side strand that has a complement↔bridge gap.
  expect(p.arcs, 'at least one ds connector arc rendered').toBeGreaterThanOrEqual(1)
  expect(p.arcs, 'no more arcs than ds side strands').toBeLessThanOrEqual(p.dsStrandCount)
})

test('right-clicking any part of a linker opens a Relax menu', async ({ page }) => {
  await openFixtureWithLinker(page)

  // Project a linker nucleotide (a bridge/complement bead) to screen coords.
  const target = await page.evaluate(() => {
    const dbg = window.__NADOC_DBG__
    let group = null
    dbg.scene.traverse(o => { if (o.name === 'assembly_linkers') group = o })
    const nucs = group?.userData?.linkerNucs ?? []
    if (!nucs.length) return null
    const n = nucs[Math.floor(nucs.length / 2)]   // a mid-strand bead (on the bridge)
    const w = new dbg.THREE.Vector3(n.pos[0], n.pos[1], n.pos[2])
    const ndc = w.clone().project(dbg.camera)
    const rect = document.getElementById('canvas').getBoundingClientRect()
    return {
      connId: n.connId, ndcx: ndc.x, ndcy: ndc.y,
      sx: rect.left + (ndc.x * 0.5 + 0.5) * rect.width,
      sy: rect.top + (-ndc.y * 0.5 + 0.5) * rect.height,
    }
  })
  expect(target, 'a linker nucleotide is available to target').not.toBeNull()

  // pickLinker resolves the linker under the cursor to its connection.
  const picked = await page.evaluate(
    (t) => window.__NADOC_DBG__.assemblyRenderer.pickLinker({ x: t.ndcx, y: t.ndcy }, window.__NADOC_DBG__.camera),
    target,
  )
  console.log('[pickLinker]', picked, 'expected', target.connId)
  expect(picked, 'pickLinker returns the connection under the cursor').toBe(target.connId)

  // Real right-click → the Relax menu appears.
  await page.mouse.click(target.sx, target.sy, { button: 'right' })
  const menu = page.locator('.context-menu')
  await expect(menu, 'a context menu appears on linker right-click').toBeVisible({ timeout: 5_000 })
  await expect(menu, 'menu offers Relax linker').toContainText('Relax linker')
  await expect(menu, 'menu is the linker menu (header)').toContainText('Linker')
})

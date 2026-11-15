import { test, expect } from '@playwright/test'

// Persistence inventory: File > New creates __e2e__base-cluster-host.nadoc;
// global-teardown deletes that prefixed file and its project revision store.
// Autosave and the test server's session cache are off. Imported fixtures stay
// in memory. Bridge credentials and screenshots use standard global teardown.
for (const crossing of [false, true]) {
test(`S72-sized strand plus complementary bases forms an independently movable cluster (${crossing ? 'crossing' : 'window'} rectangle)`, async ({ page }) => {
  test.setTimeout(120000)
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.goto('/?doc=__e2e__base-cluster-assignment')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__base-cluster-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__base-cluster-host')
  // Same selection boundary as JJ_Hinge S72: 92..103 within a 90..119 scaffold
  // domain, followed by the unpaired 104..105 scaffold hinge. This is an authored
  // regression fixture imported through the real recorded scadnano operation.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const source = { name: '__e2e__base-cluster-fixture', version: '0.19.0', grid: 'square',
      helices: [{ grid_position: [0, 0], max_offset: 120 }],
      strands: [
        { is_scaffold: true, domains: [{ helix: 0, forward: false, start: 90, end: 120 }] },
        { name: 'S72', domains: [{ helix: 0, forward: true, start: 92, end: 104 }] },
        { domains: [{ helix: 0, forward: true, start: 90, end: 92 }] },
        { domains: [{ helix: 0, forward: true, start: 106, end: 120 }] },
      ] }
    await api.importScadnanoDesign(JSON.stringify(source), source.name)
    const s = window.__nadocTest.store.getState()
    const staple = s.currentDesign.strands.find(s => s.strand_type === 'staple' && s.domains[0].start_bp === 92)
    const hid = staple.domains[0].helix_id
    window.__nadocTest.selectRefsForTest([{ kind: 'strand', id: staple.id },
      ...Array.from({length:12},(_,i)=>({kind:'base',key:`${hid}:${92+i}:REVERSE`}))])
  })
  await page.locator('.right-tab-btn[data-tab="clustering"]').click()
  const create = page.locator('#cluster-new-btn')
  if (!await create.isVisible()) await page.locator('#cluster-panel-heading').click()
  await expect(create).toBeEnabled()
  // Exercise the real rectangle tool, including shader-rendered bead bounds.
  await selectS72Rectangle(page, crossing)
  expect(await page.evaluate(() => window.__nadocTest.getSelectedBaseKeys().length)).toBe(24)
  const before = await page.evaluate(() => {
    const s = window.__nadocTest.store.getState()
    return { strands: JSON.stringify(s.currentDesign.strands), n: s.currentDesign.cluster_transforms.length,
      positions: s.currentGeometry.map(n=>({key:`${n.helix_id}:${n.bp_index}:${n.direction}`,bp:n.bp_index,position:n.backbone_position})) }
  })
  await create.click()
  await page.waitForFunction(n => window.__nadocTest.store.getState().currentDesign.cluster_transforms.length === n+1, before.n)
  const grouped = await page.evaluate(() => {
    const s = window.__nadocTest.store.getState(), c = s.currentDesign.cluster_transforms.at(-1)
    return { cluster:c, strands:JSON.stringify(s.currentDesign.strands), features:s.currentDesign.feature_log.map(f=>f.feature_type) }
  })
  expect(grouped.cluster.base_ids).toHaveLength(24)
  expect(grouped.cluster.base_ids.every(n=>n.bp_index>=92&&n.bp_index<=103)).toBe(true)
  expect(grouped.strands).toBe(before.strands)
  expect(grouped.features.at(-1)).toBe('cluster_create')
  // Both the solid tint and the separate presentation halo must stay exact.
  await page.evaluate(() => window.__nadocTest.selectRefsForTest([]))
  await page.locator(`[data-cluster-id="${grouped.cluster.id}"]`).first().click({ position: { x: 8, y: 10 } })
  const fullHighlight = await page.evaluate(async () => {
    const t = window.__nadocTest
    const { capturePresentationSelection } = await import('/src/scene/presentation_selection.js')
    capturePresentationSelection(t.scene)
    const entries = t.getDesignRenderer().getBackboneEntries()
    const halo = t.scene.getObjectByName('Presenter selection'), p = halo.geometry.attributes.position
    const expected = new Set(entries.filter(e => e.nuc.bp_index >= 92 && e.nuc.bp_index <= 103)
      .map(e => e.pos.toArray().map(Math.fround).join(',')))
    return { haloCount: halo.geometry.drawRange.count,
      outside: Array.from({length:halo.geometry.drawRange.count}, (_,i) => [p.getX(i),p.getY(i),p.getZ(i)].join(','))
        .filter(key => !expected.has(key)),
      tintMismatch: entries.filter(e => !!e.instMesh.geometry.getAttribute('instanceSelection')?.getX(e.id) !==
        (e.nuc.bp_index >= 92 && e.nuc.bp_index <= 103)).length }
  })
  expect(fullHighlight).toEqual({haloCount:24,outside:[],tintMismatch:0})
  // Actual atom colors must not inherit the supporting helix's selection.
  await page.evaluate(async () => {
    window.__nadocTest.selectRefsForTest([])
    await window.__nadocTest.setRepresentation('ballstick')
  })
  await page.waitForFunction(() => window.__nadocTest.getAtomisticRenderer().selectionAtomEntries(
    window.__nadocTest.store.getState().currentGeometry).length > 0)
  const colorsBefore = await atomColors(page)
  await page.locator(`[data-cluster-id="${grouped.cluster.id}"]`).first().click({ position: { x: 8, y: 10 } })
  await page.waitForFunction(id => window.__nadocTest.getCanonicalSelection().items.some(r => r.kind==='cluster' && r.id===id), grouped.cluster.id)
  const colorsAfter = await atomColors(page)
  for (let i=0;i<colorsBefore.length;i++) {
    expect(colorsBefore[i].colors.length).toBeGreaterThan(0)
    const selected = colorsBefore[i].bp >= 92 && colorsBefore[i].bp <= 103
    expect(JSON.stringify(colorsAfter[i].colors) !== JSON.stringify(colorsBefore[i].colors), `base ${colorsBefore[i].key}`).toBe(selected)
  }
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ target:[0,0,35.5],position:[16,8,40] }))
  await page.screenshot({ path:test.info().outputPath('base-cluster-highlight.png') })
  await page.evaluate(async () => {
    window.__nadocTest.selectRefsForTest([])
    await window.__nadocTest.setRepresentation('full')
  })
  await page.evaluate(async cluster => {
    const api = await import('/src/api/client.js')
    const result = await api.commitClusterPoses([{cluster_id:cluster.id,fields:{translation:[3,0,0],rotation:cluster.rotation,pivot:cluster.pivot}}])
    if (!result) throw new Error(window.__nadocTest.store.getState().lastError?.message ?? 'Move failed')
  }, grouped.cluster)
  const positions = await page.evaluate(() => window.__nadocTest.store.getState().currentGeometry.map(n=>({key:`${n.helix_id}:${n.bp_index}:${n.direction}`,bp:n.bp_index,position:n.backbone_position})))
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ target:[1.5,0,35.5],position:[28,18,43] }))
  await page.screenshot({ path:test.info().outputPath('base-cluster-moved.png') })
  const original = new Map(before.positions.map(n=>[n.key,n]))
  expect(positions.map(n=>n.key).sort()).toEqual(before.positions.map(n=>n.key).sort())
  for (const n of positions) {
    const start=original.get(n.key), dx=n.bp>=92&&n.bp<=103?3:0
    expect(n.position[0]-start.position[0]).toBeCloseTo(dx,6)
    expect(n.position[1]).toBeCloseTo(start.position[1],6)
    expect(n.position[2]).toBeCloseTo(start.position[2],6)
  }
  await page.evaluate(async () => { const api=await import('/src/api/client.js'); await api.undo(); await api.undo() })
  await page.waitForFunction(n=>window.__nadocTest.store.getState().currentDesign.cluster_transforms.length===n,before.n)
})

}

async function atomColors(page) {
  return page.evaluate(async () => {
    const { Color } = await import('/node_modules/three/build/three.module.js')
    const api = window.__nadocTest, renderer = api.getAtomisticRenderer()
    return api.store.getState().currentGeometry.map(n => ({
      key:`${n.helix_id}:${n.bp_index}:${n.direction}`, bp:n.bp_index,
      colors:renderer.selectionAtomEntries([n]).map(e => {
        const color = new Color(); e.instMesh.getColorAt(e.id,color); return color.toArray()
      }),
    }))
  })
}


async function selectS72Rectangle(page, crossing) {
  await page.locator('#select-filter-trigger').click()
  await page.locator('#select-filter .sf-btn[data-key="base"]').click()
  const rect = await page.evaluate(async () => {
    const { Vector3, PerspectiveCamera } = await import('/node_modules/three/build/three.module.js')
    const t = window.__nadocTest
    const entries = t.getDesignRenderer().getBackboneEntries().filter(e => e.nuc.bp_index >= 91 && e.nuc.bp_index <= 104)
    const center = entries.reduce((p,e) => p.add(e.pos), new Vector3()).multiplyScalar(1/entries.length)
    const position = center.clone().add(new Vector3(0,-100,0))
    t.applyCameraPoseForTest({position:position.toArray(),target:center.toArray(),up:[0,0,1],fov:7})
    t.selectRefsForTest([])
    const canvas = document.getElementById('canvas').getBoundingClientRect()
    const camera = new PerspectiveCamera(7,canvas.width/canvas.height,.1,1000)
    camera.position.copy(position); camera.up.set(0,0,1); camera.lookAt(center); camera.updateMatrixWorld()
    const points = entries.map(e => e.pos.clone().project(camera))
    const padding = .12 * canvas.height/(200*Math.tan(7*Math.PI/360))
    const edges = entries.filter(e => e.nuc.bp_index === 91 || e.nuc.bp_index === 104).map(e => {
      const p = e.pos.clone().project(camera)
      return {x:canvas.left+(p.x+1)*canvas.width/2,y:canvas.top+(1-p.y)*canvas.height/2}
    })
    return { edges, x1:canvas.left+(Math.min(...points.map(p=>p.x))+1)*canvas.width/2-padding,
      x2:canvas.left+(Math.max(...points.map(p=>p.x))+1)*canvas.width/2+padding,
      y1:canvas.top+(1-Math.max(...points.map(p=>p.y)))*canvas.height/2-padding,
      y2:canvas.top+(1-Math.min(...points.map(p=>p.y)))*canvas.height/2+padding }
  })
  await page.mouse.move(crossing ? rect.x2 : rect.x1,rect.y1)
  await page.mouse.down()
  await page.mouse.move(crossing ? rect.x1 : rect.x2,rect.y2,{steps:12})
  await page.mouse.up()
  expect(await page.evaluate(() => window.__nadocTest.getSelectedBaseKeys().length)).toBe(27)
  await page.keyboard.down('Control')
  for (const edge of rect.edges) await page.mouse.click(edge.x,edge.y)
  await page.keyboard.up('Control')
}

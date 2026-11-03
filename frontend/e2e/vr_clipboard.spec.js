import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
let pid
test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})
for (const scenario of ['clusters', 'domains', 'rigid']) test(`copy ${scenario}, carry preview, paste and undo`, async ({ page, request }, info) => {
  test.setTimeout(180000)
  await page.goto('/?doc=__e2e__clipboard&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR Clipboard')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.evaluate(async scenario => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: [[0,0]], lengthBp: 21, plane: 'XY', name: '__e2e__Clipboard source' })
    for (const row of [3,6]) await api.addBundleSegment({ cells: [[row,0]], lengthBp: 21, plane: 'XY' })
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    const clusters = store.getState().currentDesign.cluster_transforms
    if (clusters.length !== 3) throw new Error(`Expected three fixture clusters, got ${clusters.length}`)
    let refs
    if (scenario === 'clusters') refs = clusters.slice(0,2).map(c => ({ kind: 'cluster', id: c.id }))
    else if (scenario === 'domains') {
      const d = structuredClone(store.getState().currentDesign)
      const strand = d.strands[0], domain = strand.domains[0]
      d.extensions = [{ id:'tail', strand_id:strand.id, end:'three_prime', sequence:'TT' }]
      await api.importDesign(JSON.stringify(d))
      const key = bp => `${domain.helix_id}:${bp}:${domain.direction}`
      refs = [{kind:'extension',id:'tail'}, {kind:'bond',fromKey:key(domain.start_bp),toKey:key(domain.start_bp+(domain.direction==='FORWARD'?1:-1)),strandId:strand.id},
        {kind:'base',key:key(domain.start_bp)}]
    } else {
      const d = structuredClone(store.getState().currentDesign)
      d.nanoparticles = [{id:'particle',diameter_nm:4}]
      d.protein_assets = [{id:'asset',name:'__e2e__Protein',atoms:[
        {serial:1,name:'CA',element:'C',res_name:'GLY',chain_id:'A',res_seq:1,x:5,y:0,z:0},
        {serial:2,name:'CA',element:'C',res_name:'GLY',chain_id:'A',res_seq:2,x:7,y:2,z:2}],bonds:[[0,1]]}]
      d.protein_attachments = [{id:'protein',asset_id:'asset',target:{kind:'free'}}]
      await api.importDesign(JSON.stringify(d))
      refs = [{kind:'protein',id:'protein'},{kind:'nanoparticle',id:'particle'}]
    }
    createSelectionController({ store }).replace(refs)
  }, scenario)
  const read = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  const before = await read()
  const sourceGeometry = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentGeometry)
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  execFileSync('uv', ['run','python','-m','tools.vr_workflows.clipboard_probe',status.scrywrite_socket,info.outputPath('clipboard')], {
    cwd: path.resolve(process.cwd(),'..'), env:{...process.env,NADOC_VR_CLIPBOARD_CASE:scenario}, timeout:120000, stdio:'inherit',
  })
  const after = await read()
  expect(before.cluster_transforms.length).toBe(3)
  expect(after.helices.length).toBe(before.helices.length+(scenario==='clusters'?2:scenario==='domains'?1:0))
  expect(after.helices.slice(0,before.helices.length)).toEqual(before.helices)
  expect(after.feature_log.at(-1).op_kind).toBe('element-paste')
  const event = await page.evaluate(async () => (await import('/src/api/client.js')).getVREvent())
  expect(event.ligation.action).toBe('paste')
  const matrix = event.ligation.matrix
  expect(after.feature_log.at(-1).params.matrix).toEqual(matrix)
  const geometry = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentGeometry)
  const selectedHelices = new Set(scenario==='clusters'?before.cluster_transforms.slice(0,2).flatMap(c => c.helix_ids):scenario==='domains'?[before.strands[0].domains[0].helix_id]:[])
  const sources = before.helices.filter(h => selectedHelices.has(h.id))
  const copied = after.helices.slice(before.helices.length)
  const ordered = (rows, id) => rows.filter(n => n.helix_id === id).sort((a,b) => a.bp_index-b.bp_index || a.direction.localeCompare(b.direction))
  for (let i=0;i<copied.length;i++) {
    const original = ordered(sourceGeometry,sources[i].id).filter(n => scenario!=='domains' || n.strand_id===before.strands[0].id), placed = ordered(geometry,copied[i].id)
    expect(placed).toHaveLength(original.length)
    for (let j=0;j<original.length;j++) for (let axis=0;axis<3;axis++) {
      const p = original[j].backbone_position
      const expected = matrix[axis]*p[0]+matrix[4+axis]*p[1]+matrix[8+axis]*p[2]+matrix[12+axis]
      expect(placed[j].backbone_position[axis]).toBeCloseTo(expected,3)
    }
  }
  if (scenario === 'domains') {
    expect(after.strands.length).toBe(before.strands.length+1)
    expect(after.extensions.length).toBe(2)
  }
  if (scenario === 'rigid') {
    expect(after.protein_attachments.length).toBe(2)
    expect(after.nanoparticles.length).toBe(2)
    const pose = after.nanoparticles[1].pose.values
    for (let row=0;row<4;row++) for(let col=0;col<4;col++) expect(pose[4*row+col]).toBeCloseTo(matrix[4*col+row],4)
  }
  await page.screenshot({path:info.outputPath('desktop-pasted.png')})
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect((await read()).helices).toEqual(before.helices)
})

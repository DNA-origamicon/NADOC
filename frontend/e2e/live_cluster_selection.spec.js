import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

// Read-only diagnosis: fetch an existing live document and inspect it in an
// isolated browser. No document mutation/save; autosave and session cache off.
// The diagnostic PNG under .development-artifacts is retained for visual review.
// Only the __e2e__ host is persisted, cleaned by global teardown along with
// bridge credentials, project history and managed Playwright output.
test('live exact cluster highlights only its member bases in Full', async ({ page, request }) => {
  test.skip(process.env.NADOC_CHECK_LIVE_CLUSTER !== '1', 'Opt-in read-only local document diagnosis')
  // Nine sidebar selections plus visual capture of a full origami in software WebGL.
  test.setTimeout(600000)
  let design
  if (process.env.NADOC_CHECK_CLUSTER_FILE) {
    design = JSON.parse(await readFile(process.env.NADOC_CHECK_CLUSTER_FILE, 'utf8'))
  } else {
    const registry = await request.get('http://127.0.0.1:8000/api/documents')
    const documents = (await registry.json()).documents
    const doc = documents.find(d => d.design?.name?.startsWith('JJ_Hinge'))
    test.skip(!doc, 'Local live user document')
    const response = await request.get('http://127.0.0.1:8000/api/design', {headers:{'X-NADOC-Doc':doc.doc_id}})
    const payload = await response.json()
    design = payload.design ?? payload
  }
  const cluster = design.cluster_transforms.find(c=>c.name==='Cluster 4')
  test.skip(!cluster?.base_ids?.length, 'Local exact cluster')
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({autosave:false})))
  await page.goto('/?doc=__e2e__live-cluster-highlight')
  await page.waitForFunction(()=>!!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name','__e2e__live-cluster-host')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.waitForFunction(()=>window.__nadocTest.store.getState().currentDesign?.metadata?.name==='__e2e__live-cluster-host')
  await page.evaluate(async design=>{
    const api=await import('/src/api/client.js')
    await api.importDesign(JSON.stringify(design))
    await window.__nadocTest.setRepresentation('full')
    window.__nadocTest.selectRefsForTest([])
  },design)
  await page.locator('.right-tab-btn[data-tab="clustering"]').click()
  for (const cluster of design.cluster_transforms) {
    const row=page.locator(`[data-cluster-id="${cluster.id}"]`).first()
    if(!await row.isVisible()) await page.locator('#cluster-panel-heading').click()
    await row.click({position:{x:8,y:10}})
    await page.waitForFunction(id=>window.__nadocTest.getCanonicalSelection().items.some(r=>r.kind==='cluster'&&r.id===id),cluster.id)
    await page.waitForFunction(()=>window.__nadocTest.scene.getObjectByName('Presenter selection')?.visible)
    const result=await page.evaluate(async cluster=>{
      const { clusterMemberFilter }=await import('/src/scene/cluster_entries.js')
      const { capturePresentationSelection }=await import('/src/scene/presentation_selection.js')
      capturePresentationSelection(window.__nadocTest.scene)
      const t=window.__nadocTest, renderer=t.getDesignRenderer(), matches=clusterMemberFilter(cluster,t.store.getState().currentDesign)
      const entries=renderer.getBackboneEntries(), members=entries.filter(e=>matches(e.nuc))
      const mismatches=[]
      for(const [name,source] of [['beads',entries],['plates',renderer.getSlabEntries()]]) {
        for(const e of source) if(!!e.instMesh.geometry.getAttribute('instanceSelection')?.getX(e.id)!==matches(e.nuc)) mismatches.push(name+':'+e.id)
      }
      const halo=t.scene.getObjectByName('Presenter selection'), positions=halo.geometry.attributes.position
      const expected=new Set(members.map(e=>e.pos.toArray().map(Math.fround).join(',')))
      const haloOutside=[]
      for(let i=0;i<halo.geometry.drawRange.count;i++) if(!expected.has([positions.getX(i),positions.getY(i),positions.getZ(i)].join(','))) haloOutside.push(i)
      return {name:cluster.name,members:members.length,halo:halo.geometry.drawRange.count,mismatches,haloOutside}
    },cluster)
    console.log(JSON.stringify(result))
    expect(result.mismatches).toEqual([])
    expect(result.haloOutside).toEqual([])
    expect(result.halo).toBe(result.members)
    if(cluster.base_ids?.length) expect(result.members).toBe(cluster.base_ids.length)
    if(cluster.name==='Cluster 4') {
      await page.evaluate(cluster=>{
        const t=window.__nadocTest,entries=t.getDesignRenderer().getBackboneEntries().filter(e=>cluster.helix_ids.includes(e.nuc.helix_id))
        const center=entries[0].pos.clone().set(0,0,0);entries.forEach(e=>center.add(e.pos));center.multiplyScalar(1/entries.length)
        t.applyCameraPoseForTest({target:center.toArray(),position:center.clone().add({x:28,y:-30,z:18}).toArray(),up:[0,0,1],fov:40})
      },cluster)
      await page.screenshot({path:'../.development-artifacts/jj-cluster-highlight-after.png'})
    }
  }
  await page.evaluate(()=>window.__nadocTest.selectRefsForTest([]))
  await page.waitForFunction(()=>!window.__nadocTest.scene.getObjectByName('Presenter selection').visible)
})

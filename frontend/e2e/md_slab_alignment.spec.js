import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'

// Read existing legacy design and recorded WebSocket frames only. No design/job saves.
const source = '/media/jojo/Archive/NADOC_archive/151b6da69fe5/design.json'
const recording = new URL('../../.development-artifacts/slab-audit/r1-live-transport.json', import.meta.url)
const hash = () => createHash('sha256').update(readFileSync(source)).digest('hex')
test('R1 Display MD slabs match atomic rings in the Full overlay', async ({ page }, info) => {
  test.skip(!process.env.NADOC_SLAB_AUDIT, 'Read-only local archived-run audit')
  const original = hash(), frames = JSON.parse(readFileSync(recording)), errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.routeWebSocket(/\/ws\/md-run(?:\?|$)/, ws => {
    let mode = 'nadoc'
    ws.onMessage(raw => {
      const m = JSON.parse(raw)
      if (m.action === 'load') {
        mode = m.mode
        ws.send(JSON.stringify({ type: 'ready', n_frames: frames[mode].n_frames }))
      } else if (['get_latest','seek'].includes(m.action)) ws.send(JSON.stringify(frames[mode]))
    })
  })
  try {
    await page.goto('/?test=1&doc=__e2e__md-slab-alignment')
    await page.evaluate(async source => {
      await (await import('/src/api/client.js')).loadDesign(source)
      document.getElementById('welcome-screen')?.classList.add('hidden')
    }, source)
    await expect.poll(() => page.evaluate(() => window.__nadocTest?.store.getState().currentGeometry?.length ?? 0)).toBeGreaterThan(0)
    await page.evaluate(() => window.__nadocTest.configureMultiOverlay({count: 2, representations: ['full','ballstick'], opacities: [.35,1], separation: 0}))
    await expect(page.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(2, {timeout:90000})
    await page.evaluate(() => window.__nadocMdDisplay.displayLatest('__e2e__recorded-r1.json', { live:false }))
    const expected = frames.nadoc.positions.map(p => ({center:[p.bx,p.by,p.bz], normal:[p.tx,p.ty,p.tz]}))
    const inspect = () => page.evaluate(async expected => {
      const THREE = await import('/node_modules/three/build/three.module.js')
      const layer = window.__nadocTest.comparisonScenesForTest().overlays.find(l => l.representation === 'full')
      const results=[]; const m=new THREE.Matrix4(),p=new THREE.Vector3(),q=new THREE.Quaternion(),s=new THREE.Vector3()
      layer?.renderScene?.traverseVisible(o => {
        if (!['baseSlabs','xoverExtraSlabs'].includes(o.name)) return
        for(let i=0;i<o.count;i++) {
          o.getMatrixAt(i,m);m.decompose(p,q,s);if(s.lengthSq()<1e-10) continue
          const distances=expected.map(e=>p.distanceTo(new THREE.Vector3(...e.center)))
          const distance=Math.min(...distances), index=distances.indexOf(distance)
          const normal=new THREE.Vector3(0,1,0).applyQuaternion(q).normalize()
          const angle=Math.acos(Math.min(1,Math.abs(normal.dot(new THREE.Vector3(...expected[index].normal).normalize()))))*180/Math.PI
          results.push({distance,angle,index})
        }
      });return results
    }, expected)
    await expect.poll(async () => {const r=await inspect();return r.length===expected.length && r.every(x=>x.distance<1e-5 && x.angle<.01)}, {timeout:90000}).toBe(true)
    const metrics=await inspect(); expect(new Set(metrics.map(x=>x.index)).size).toBe(expected.length)
    const center=[0,1,2].map(a=>expected.reduce((v,e)=>v+e.center[a],0)/expected.length)
    await page.evaluate(c=>window.__nadocTest.applyCameraPoseForTest({position:[c[0]+7,c[1]+5,c[2]+10],target:c}),center)
    await page.waitForTimeout(500)
    await page.locator('#canvas').screenshot({path:info.outputPath('r1-full-atomic.png')})
    await page.evaluate(c=>window.__nadocTest.applyCameraPoseForTest({position:[c[0]+2.5,c[1]+1.8,c[2]+3.5],target:c}), expected[35].center)
    await page.waitForTimeout(300)
    await page.locator('#canvas').screenshot({path:info.outputPath('r1-base-closeup.png')})
    await info.attach('rendered-slab-metrics',{body:JSON.stringify(metrics),contentType:'application/json'})
    expect(errors).toEqual([])
  } finally { expect(hash()).toBe(original) }
})

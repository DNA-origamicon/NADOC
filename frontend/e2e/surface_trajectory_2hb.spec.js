/** Read-only playback validation against an existing, completed 2hb simulation. */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const JOB = process.env.NADOC_SURFACE_JOB || '802f80ec405c'
const DOC = '__e2e__surface-trajectory-2hb'
const evidence = process.env.NADOC_SURFACE_EVIDENCE || path.join(ROOT, '.development-artifacts', `surface-trajectory-2hb-${Date.now()}`)

test('quick and detail surfaces follow real 2hb simulation frames and report playback costs', async ({ page, request }) => {
  test.skip(!existsSync(path.join(ROOT, `workspace/md_jobs/${JOB}/design.json`)))
  test.setTimeout(240000)
  mkdirSync(evidence, { recursive: true })
  const errors = [], requests = [], pending = [], trajectoryResponses = []
  const started = new Map()
  page.on('pageerror', e => errors.push(e.message))
  page.on('requestfailed', r => trajectoryResponses.push({url:r.url(),failure:r.failure()}))
  page.on('request', r => { if (r.url().includes('/frames-surface')) started.set(r, performance.now()) })
  page.on('response', r => {
    if (r.url().includes('/api/') && r.url().includes('/trajectory')) pending.push((async () => {
      const body = await r.body()
      trajectoryResponses.push({url:r.url(),status:r.status(),bytes:body.length,header:body.subarray(0,200).toString()})
    })())
    if (!r.url().includes('/frames-surface')) return
    pending.push((async () => {
      const data = await r.json()
      requests.push({ request: r.request().postDataJSON(), status: r.status(),
        ms: performance.now() - started.get(r.request()), bytes: (await r.body()).length,
        meshes: Object.entries(data).map(([frame,m]) => ({ frame, vertices: m.vertices.length / 3, faces: m.faces.length / 3 })) })
    })())
  })
  try {
    await page.goto(`/?doc=${DOC}`)
    await page.waitForFunction(() => window.__nadocTest && window.__nadocMdViz)
    await page.evaluate(async content => {
      const api = await import('/src/api/client.js')
      const design=JSON.parse(content)
      // Change only the isolated viewer copy, never the simulation snapshot.
      design.strands.forEach((s,i)=>{s.color=['#e33b39','#35c76f','#4488ff'][i%3]})
      await api.importDesign(JSON.stringify(design))
      window.__surfacePaletteAudit = () => {
        const mesh=window.__nadocTest.scene.getObjectByName('dna-surface')
        const colors=mesh?.geometry.getAttribute('color')?.array
        const unique=new Set()
        for(let i=0;i<(colors?.length??0);i+=3) unique.add([colors[i],colors[i+1],colors[i+2]].map(x=>Math.round(x*255)).join(','))
        return {enabled:!!mesh?.material.vertexColors, colors:[...unique].sort()}
      }
      document.getElementById('welcome-screen')?.classList.add('hidden')
      document.getElementById('right-tab-strip')?.classList.remove('locked-inactive')
      document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
    }, readFileSync(path.join(ROOT, `workspace/md_jobs/${JOB}/design.json`), 'utf8'))
    // Let the imported document finish rebuilding its timeline/preparation queue.
    // Starting playback during that reset cancels its pending download.
    await expect(page.locator('#animation-select option:enabled')).not.toHaveCount(0)
    const loaded = await page.evaluate(job => window.__nadocMdViz.loadTrajectory(job, true, 'lineage', 1, null, {frameStart:0,frameEnd:5}), JOB)
    await Promise.all(pending)
    expect(loaded.ok, JSON.stringify({loaded,trajectoryResponses})).toBe(true)
    await page.locator('.right-tab-btn[data-tab="visualization"]').click()
    const results = []
    for (const [name, target, detail] of [
      ['quick', 'menu-view-surface', 'coarse'], ['detail', 'menu-view-surface-detail', 'chimerax'],
    ]) {
      const start = performance.now()
      await page.locator(`#right-representation-modes [data-target="${target}"]`).click()
      await page.evaluate(() => window.__nadocMdViz.reapplyForRepr({strict:true,exact:true}))
      const selectMs = performance.now() - start
      const frames = []
      for (let i=0; i<6; ++i) {
        frames.push(await page.evaluate(async ({i,frameCamera}) => {
          const t=window.__nadocTest, c=window.__nadocMdViz
          const start=performance.now()
          c.showFrame(i,{heavy:false}); await c.reapplyForRepr({strict:true,exact:true})
          const applyMs=performance.now()-start
          const mesh=t.scene.getObjectByName('dna-surface')
          if(frameCamera) {
            mesh.geometry.computeBoundingBox()
            const box=mesh.geometry.boundingBox, center=box.getCenter(new (await import('/node_modules/three/build/three.module.js')).Vector3())
            const radius=box.max.distanceTo(box.min)
            t.applyCameraPoseForTest({position:[center.x+radius*.25,center.y+radius*.2,center.z+radius*1.35],target:center.toArray()})
          }
          const positions=mesh.geometry.attributes.position.array, faces=mesh.geometry.index.array
          let hash=2166136261
          for(const v of positions) hash=Math.imul(hash ^ Math.round(v*1e5),16777619)>>>0
          return {frame:i,applyMs,vertices:positions.length/3,faces:faces.length/3,positionHash:hash,
            palette:window.__surfacePaletteAudit(),census:t.renderedPixelCensus(),active:c.isActive(),mode:c.mode()}
        }, {i,frameCamera:name==='quick' && i===0}))
        if(i===0 || i===5) await page.locator('#canvas').screenshot({path:path.join(evidence,`${name}-${i}.png`)})
      }
      expect(frames.every(f=>f.census.visible>100 && f.active && f.mode==='trajectory')).toBe(true)
      for(const frame of frames) expect(frame.palette).toEqual({enabled:true,colors:['227,59,57','53,199,111','68,136,255']})
      expect(frames.every(f=>f.census.colorful>100)).toBe(true)
      expect(new Set(frames.map(f=>f.positionHash)).size).toBeGreaterThan(1)
      expect(new Set(frames.map(f=>f.census.pixelHash)).size).toBeGreaterThan(1)
      const replay = await page.evaluate(async () => {
        const c=window.__nadocMdViz,t=window.__nadocTest,ms=[]
        for(let k=0;k<30;++k) {
          const start=performance.now()
          c.showFrame(k%6,{heavy:false});await c.reapplyForRepr({strict:true,exact:true})
          ms.push(performance.now()-start)
        }
        const mesh=t.scene.getObjectByName('dna-surface')
        const visible=t.renderedPixelCensus()
        mesh.visible=false;const hidden=t.renderedPixelCensus();mesh.visible=true
        return {ms,visible,hidden}
      })
      expect(replay.visible.pixelHash).not.toBe(replay.hidden.pixelHash)
      const smooth = await page.evaluate(async () => {
        const c=window.__nadocMdViz,t=window.__nadocTest
        c.showFrame(0);await c.reapplyForRepr({strict:true,exact:true})
        const start=performance.now()
        if(!await c.ensureInterpolationFrames(0,1,{after:2})) throw new Error('Surface motion not prepared')
        const prepareMs=performance.now()-start
        c.setPlaying(true)
        const samples=[]
        for(const fraction of [.05,.25,.5,.75,.95]) {
          const begin=performance.now()
          c.showInterpolatedFrame(0,1,fraction,{after:2})
          const ms=performance.now()-begin
          const mesh=t.scene.getObjectByName('dna-surface')
          const visible=t.renderedPixelCensus()
          mesh.visible=false;const hidden=t.renderedPixelCensus();mesh.visible=true
          samples.push({fraction,ms,visible,hidden,palette:window.__surfacePaletteAudit()})
        }
        // Exercise the production render-clock path across a saved-frame boundary.
        const {initTrajectoryInterpolationClock}=await import('/src/ui/trajectory_interpolation_clock.js')
        let current=0, draws=0, failed=false
        const times=[]
        const clock=initTrajectoryInterpolationClock({current:()=>current,count:()=>6,fps:2,
          ensure:(a,b)=>c.ensureInterpolationFrames(a,b),
          draw:(a,b,f)=>{const begin=performance.now();c.showInterpolatedFrame(a,b,f);times.push(performance.now()-begin);draws++},
          commit:i=>{current=i;c.showFrame(i)},failed:()=>{failed=true}})
        clock.start()
        await new Promise(resolve=>setTimeout(resolve,1600))
        clock.stop()
        const playing=t.renderedPixelCensus()
        c.setPlaying(false);await c.reapplyForRepr({strict:true,exact:true})
        return {prepareMs,samples,draws,times,failed,current,playing,paused:t.renderedPixelCensus()}
      })
      for(const sample of smooth.samples) expect(sample.palette).toEqual({enabled:true,colors:['227,59,57','53,199,111','68,136,255']})
      expect(smooth.failed).toBe(false)
      expect(smooth.draws).toBeGreaterThan(10)
      expect(smooth.current).toBeGreaterThan(0)
      expect(new Set(smooth.samples.map(x=>x.visible.pixelHash)).size).toBe(5)
      expect(smooth.samples.every(x=>x.visible.visible>100 && x.hidden.visible < x.visible.visible*.05)).toBe(true)
      await page.locator('#canvas').screenshot({path:path.join(evidence,`${name}-paused.png`)})
      await page.evaluate(async () => {
        const c=window.__nadocMdViz
        await c.ensureInterpolationFrames(0,1,{after:2})
        c.setPlaying(true);c.showInterpolatedFrame(0,1,.5,{after:2})
      })
      await page.locator('#canvas').screenshot({path:path.join(evidence,`${name}-smooth.png`)})
      await page.evaluate(async () => {
        const c=window.__nadocMdViz;c.setPlaying(false);await c.reapplyForRepr({strict:true,exact:true})
      })
      results.push({name,detail,selectMs,frames,replay,smooth})
    }
    await Promise.all(pending)
    expect(requests.every(r=>r.status===200)).toBe(true)
    expect(new Set(requests.map(r=>r.request.detail))).toEqual(new Set(['coarse','chimerax']))
    expect(results[1].frames[0].vertices).toBeGreaterThan(results[0].frames[0].vertices)
    expect(errors).toEqual([])
    const report={job:JOB,design:'2hb_1-0xT',frameInterval:1,sampledFrames:6,results,requests,errors,trajectoryResponses,
      note:'Real saved NAMD coordinates; fixed fitted camera. Cached apply times exclude GPU draw/readback and are not display FPS.'}
    writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2))
    writeFileSync(path.join(evidence,'index.html'),`<!doctype html><title>2hb surface trajectory validation</title><style>body{background:#161b22;color:white;font:16px sans-serif}img{width:46%;margin:1%}pre{white-space:pre-wrap}</style><h1>2hb surface trajectory validation</h1><p>Job ${JOB}: actual 2 ns NAMD trajectory. First six saved frames, fixed camera. Quick surface then detail surface.</p><h2>Quick</h2><img src="quick-0.png"><img src="quick-5.png"><h2>Detail</h2><img src="detail-0.png"><img src="detail-5.png"><h2>Smooth subframes (Quick / Detail)</h2><img src="quick-smooth.png"><img src="detail-smooth.png"><p><a href="report.json">Timings and mesh statistics</a></p>`)
    console.log('SURFACE_TRAJECTORY_EVIDENCE',evidence)
    console.log('SURFACE_TRAJECTORY_RESULTS',JSON.stringify(results.map(r=>({name:r.name,selectMs:r.selectMs,frames:r.frames.map(f=>({frame:f.frame,ms:f.applyMs,vertices:f.vertices,faces:f.faces})),replayMs:r.replay.ms}))))
  } catch (error) {
    writeFileSync(path.join(evidence,'failure.json'),JSON.stringify({job:JOB,error:String(error),requests,errors,trajectoryResponses},null,2))
    await page.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{})
    throw error
  } finally {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${DOC}`).catch(()=>{})
    for(const relative of [`.session/${DOC}`,`.nadoc-projects/${DOC}`,`${DOC}.nadoc`]) rmSync(path.join(ROOT,'workspace',relative),{recursive:true,force:true})
  }
})

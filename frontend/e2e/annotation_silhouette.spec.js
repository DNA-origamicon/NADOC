import { writeFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'

test('protein silhouette follows trace and atom contours, only for the annotation target, including exports', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
  await page.route('**/annotation-silhouette?*', route => route.fulfill({ contentType: 'text/html',
    body: '<html><body style="margin:0"><div id="host" style="position:relative;width:640px;height:480px"></div></body></html>' }))
  await page.goto('/annotation-silhouette?impostors=1')
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { initProteinTraceRenderer } = await import('/src/scene/protein_trace_renderer.js')
    const { initAtomisticRenderer } = await import('/src/scene/atomistic_renderer.js')
    const { createAnnotationController } = await import('/src/scene/annotation_controller.js')
    const { initAnnotationOverlay } = await import('/src/scene/annotation_overlay.js')
    const { renderSilhouetteHighlights } = await import('/src/scene/silhouette_highlight.js')
    const { createPhotoMode } = await import('/src/scene/photo_mode.js')
    const host = document.getElementById('host'), scene = new THREE.Scene()
    scene.background = new THREE.Color('white')
    scene.add(new THREE.AmbientLight(0xffffff, 2))
    const camera = new THREE.PerspectiveCamera(45, 4/3, .1, 100)
    camera.position.z = 9
    const renderer = new THREE.WebGLRenderer({ preserveDrawingBuffer: true })
    renderer.setSize(640,480); host.append(renderer.domElement)
    // An open U: its concavity must remain empty, rather than a sphere outline.
    const points = [[-1,-1],[-1,-.5],[-1,0],[-1,.5],[-1,1],[-.5,1],[0,1],[.5,1],[.5,.5],[.5,0],[.5,-.5],[.5,-1]]
    const atoms = points.map(([x,y], i) => ({ serial: i+1, name:'CA', element:'C', chain_id:'A',
      helix_id:'__protein__p', x:x-1, y, z:0, residue_id:i+1 }))
    atoms.push(...points.map(([x,y],i) => ({ ...atoms[i], serial:100+i, helix_id:'__protein__other', x:x+2 })))
    const trace = initProteinTraceRenderer(scene)
    trace.setMode('trace'); trace.update({ atoms })
    const atomic = initAtomisticRenderer(scene)
    let active = trace
    const controller = createAnnotationController()
    controller.syncFromDesign({ id:'silhouette-test', annotations:[] })
    const overlay = initAnnotationOverlay({ container:host, scene, controller, getCamera:()=>camera,
      getViewport:()=>({width:640,height:480}), resolveExternal:()=>({x:-1,y:0,z:0,radius:1.5}),
      resolveSilhouette:()=>active.silhouetteEntries(a=>a.helix_id==='__protein__p') })
    const entry = controller.add({ text:'Protein contour', highlight:true, highlightType:'silhouette',
      glowColor:'#ff0000', glowIntensity:1, manual:true, screenPos:{x:.05,y:.05}, refs:[{kind:'protein',id:'p'}] })
    function pixels() {
      overlay.update(); renderer.render(scene,camera); renderSilhouetteHighlights(renderer,scene,camera)
      const canvas=document.createElement('canvas'); canvas.width=640; canvas.height=480
      const ctx=canvas.getContext('2d'); ctx.drawImage(renderer.domElement,0,0)
      return { data:ctx.getImageData(0,0,640,480).data, url:canvas.toDataURL() }
    }
    const count = data => {
      let left=0,right=0,center=0
      for(let y=100;y<380;y++) for(let x=0;x<640;x++) {
        const i=(y*640+x)*4
        if(data[i]>180 && data[i+1]<80 && data[i+2]<80) {
          if(x<320) left++; else right++
          if(x>220 && x<250 && y>235 && y<295) center++
        }
      }
      return {left,right,center}
    }
    const on = pixels(), traceCounts=count(on.data)
    controller.update(entry.id,{highlight:false}); const off=count(pixels().data)
    controller.update(entry.id,{highlight:true}); trace.setMode('off')
    atomic.setMode('vdw'); atomic.update({atoms,bonds:[]}); active=atomic
    const atomOn=pixels(), atomCounts=count(atomOn.data)
    // Source matrices must survive the extra render unchanged.
    const before=active.silhouetteEntries(()=>true).map(e=>Array.from(e.instMesh.instanceMatrix.array))
    pixels()
    const unchanged=JSON.stringify(before)===JSON.stringify(active.silhouetteEntries(()=>true).map(e=>Array.from(e.instMesh.instanceMatrix.array)))
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn(){},resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
    mode.activate()
    async function exportPixels(scale, intensity) {
      controller.update(entry.id,{glowIntensity:intensity}); overlay.update()
      const bitmap=await createImageBitmap(await mode.renderToBlob(640*scale,480*scale))
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480
      const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0,640,480);bitmap.close()
      const data=ctx.getImageData(0,0,640,480).data
      let energy=0
      for(let y=100;y<380;y++) for(let x=0;x<320;x++) {
        const i=(y*640+x)*4
        energy+=Math.max(0,data[i]-Math.max(data[i+1],data[i+2]))
      }
      return {counts:count(data),energy,url:canvas.toDataURL()}
    }
    const normal=await exportPixels(1,1), high=await exportPixels(4,1)
    const dim=await exportPixels(1,.35), highDim=await exportPixels(4,.35)
    const exported=normal.counts
    mode.deactivate(); overlay.dispose(); trace.dispose(); atomic.dispose(); renderer.dispose()
    return {traceCounts,off,atomCounts,unchanged,exported,normal,high,dim,highDim,traceUrl:on.url,atomUrl:atomOn.url}
  })
  if (process.env.NADOC_E2E_SHOT) {
    writeFileSync(process.env.NADOC_E2E_SHOT, Buffer.from(result.traceUrl.split(',')[1],'base64'))
    writeFileSync(process.env.NADOC_E2E_SHOT.replace('.png','-atoms.png'), Buffer.from(result.atomUrl.split(',')[1],'base64'))
  }
  if (process.env.NADOC_E2E_SHOT) {
    for (const key of ['normal','high','dim','highDim'])
      writeFileSync(process.env.NADOC_E2E_SHOT.replace('.png',`-${key}.png`), Buffer.from(result[key].url.split(',')[1],'base64'))
  }
  for (const [base, hi] of [[result.normal,result.high],[result.dim,result.highDim]]) {
    expect(base.energy).toBeGreaterThan(1000)
    expect(hi.energy/base.energy).toBeGreaterThan(.85)
    expect(hi.energy/base.energy).toBeLessThan(1.15)
  }
  expect(result.dim.energy/result.normal.energy).toBeLessThan(.6)
  expect(errors).toEqual([])
  expect(result.traceCounts.left).toBeGreaterThan(200)
  expect(result.traceCounts.right).toBe(0)
  expect(result.traceCounts.center).toBe(0)
  expect(result.off.left).toBe(0)
  expect(result.atomCounts.left).toBeGreaterThan(100)
  expect(result.atomCounts.right).toBe(0)
  expect(result.exported.left).toBeGreaterThan(100)
  expect(result.exported.right).toBe(0)
  expect(result.unchanged).toBe(true)
})

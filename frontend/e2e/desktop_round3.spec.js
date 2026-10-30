import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'

const root=fileURLToPath(new URL('../../',import.meta.url))
const doc='__e2e__desktop-round3'
const revision='2f3b962966b4917d9f626e486d56680306600363'
test.beforeAll(()=>{
  expect(process.env.NADOC_WORKSPACE).toBeTruthy()
  expect(existsSync(`${process.env.NADOC_WORKSPACE}/${doc}.nadoc`)).toBe(false)
})
test.afterEach(async({page,request})=>{
  await page.close()
  await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${doc}`)
})
test('selection, moving surface and solvent retain visible output',async({page,request})=>{
  test.setTimeout(90000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(()=>window.__nadocTest)
  const origin=new URL(page.url()).origin
  const transformed=async path=>(await request.get(origin+path)).text()
  const atomSource=await transformed('/src/scene/atomistic_renderer.js')
  const surfaceSource=await transformed('/src/scene/surface_renderer.js')
  const solventSource=await transformed('/src/scene/md_solvent_overlay.js')
  const threePath=solventSource.match(/from ["']([^"']*three[^"']*)["']/)[1]
  const old=(name)=>execFileSync('git',['show',`${revision}:frontend/src/scene/${name}.js`],{cwd:root,encoding:'utf8'})
    .replace(/from ['"]three['"]/g,`from '${threePath}'`)
  // Use the same transformed dependency URLs, isolating only each changed operation.
  const atomBaseline=atomSource.replace(/(["'])[^"']*atomistic_renderer\/color_resolver\.js[^"']*\1/g,"'/src/scene/atomistic_renderer/__round3_old_colour.js'")
  expect(atomBaseline).not.toBe(atomSource)
  const surfaceBaseline=surfaceSource.replace(/import\s*\{\s*computeSurfaceNormals\s*\}\s*from\s*["'][^"']+["'];?/, 'const computeSurfaceNormals = geometry => geometry.computeVertexNormals();')
  expect(surfaceBaseline).not.toBe(surfaceSource)
  for(const [path,body] of [
    ['/src/scene/__round3_old_atoms.js',atomBaseline],
    ['/src/scene/atomistic_renderer/__round3_old_colour.js',old('atomistic_renderer/color_resolver')],
    ['/src/scene/__round3_old_surface.js',surfaceBaseline],
    ['/src/scene/__round3_old_solvent.js',old('md_solvent_overlay')],
  ])await page.route('**'+path,route=>route.fulfill({contentType:'text/javascript',body}))
  const result=await page.evaluate(async()=>{
    const t=window.__nadocTest;t.pauseViewerRenderingForTest()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    t.applyCameraPoseForTest({position:[1.5,1.5,9],target:[1.5,1.5,0],up:[0,1,0]})
    const blank=t.renderedPixelCensus()
    const rows=[]
    const atoms=Array.from({length:144},(_,i)=>({serial:i+1,element:['C','N','O','P'][i%4],helix_id:'h',strand_id:`s${i%2}`,bp_index:i,direction:'FORWARD',x:(i%12)*.25,y:Math.floor(i/12)*.25,z:0}))
    const bonds=atoms.flatMap((a,i)=>i%12?[[atoms[i-1].serial,a.serial]]:[])
    const colours=new Map(atoms.map(a=>[`h:${a.bp_index}:FORWARD`,a.bp_index%2?0xaa22cc:0x22cc55]))
    const alphas=new Map(atoms.map(a=>[`h:${a.bp_index}:FORWARD`,a.bp_index%3?.5:1]))
    const atomModules=[await import('/src/scene/__round3_old_atoms.js'),await import('/src/scene/atomistic_renderer.js')]
    const selections=[null,{strandIds:['s0']},{bases:[{helix_id:'h',bp_index:15,direction:'FORWARD'}]},{domains:[{strandId:'s1',helixId:'h',direction:'FORWARD',lo:20,hi:50}]}]
    for(const colourMode of ['cpk','cluster','scalar']){
      const pair=[]
      for(const module of atomModules){
        const r=module.initAtomisticRenderer(t.scene,{independentColors:true})
        try{
          r.setMode('ballstick');r.update({atoms,bonds,sphereImpostors:true})
          if(colourMode==='cluster')r.setClusterDisplay(alphas,colours)
          if(colourMode==='scalar'){r.setClusterDisplay(alphas);r.applyScalarColors(colours)}
          const frames=[]
          for(const selection of selections){r.highlight(selection);frames.push(t.renderedPixelCensus())}
          pair.push(frames)
        }finally{r.dispose()}
      }
      rows.push({operation:'colour-'+colourMode,pair})
    }
    const vertices=[],faces=[]
    for(let y=0;y<20;y++)for(let x=0;x<20;x++){
      vertices.push(x*.15,y*.15,Math.sin(x*.2)*Math.cos(y*.2)*.2)
      if(x&&y){const i=y*20+x;faces.push(i,i-1,i-20,i-1,i-21,i-20)}
    }
    const data={vertices,faces,vertex_colors:vertices.map((v,i)=>i%3===0?.7:.2),scalar:true}
    const surfacePair=[]
    for(const module of [await import('/src/scene/__round3_old_surface.js'),await import('/src/scene/surface_renderer.js')]){
      const r=module.initSurfaceRenderer(t.scene)
      try{
        r.update(data);const frames=[t.renderedPixelCensus()]
        for(let k=0;k<3;k++){
          const d={...data,vertices:vertices.map((v,i)=>v+(i%3===2?Math.sin(i*.04+k)*.1:0))}
          r.applyPositionLerp(d,d,0);frames.push(t.renderedPixelCensus())
        }
        surfacePair.push(frames)
      }finally{r.dispose()}
    }
    rows.push({operation:'surface-motion',pair:surfacePair})
    const solventPair=[]
    for(const module of [await import('/src/scene/__round3_old_solvent.js'),await import('/src/scene/md_solvent_overlay.js')]){
      const r=module.initMdSolventOverlay(t.scene)
      try{
        r.setIonSpecies(new Uint8Array([0,1,2,3,4]));const frames=[]
        for(const mode of ['sphere','atomistic'])for(const count of [36,12,48]){
          r.setMode(mode,true)
          const water=[]
          for(let i=0;i<count;i++){
            const x=(i%6)*.4,y=Math.floor(i/6)*.35
            water.push(x,y,0)
            if(mode==='atomistic')water.push(x+.08,y+.03,0,x-.04,y+.07,0)
          }
          r.setFrame({nWater:count,water:new Float32Array(water),ions:new Float32Array([0,0,.3,.4,0,.3,.8,0,.3,1.2,0,.3,1.6,0,.3])})
          frames.push(t.renderedPixelCensus())
        }
        solventPair.push(frames)
      }finally{r.dispose()}
    }
    rows.push({operation:'solvent',pair:solventPair})
    return {blank,rows}
  })
  console.log('round3 visible comparison',JSON.stringify(result))
  for(const row of result.rows)for(let i=0;i<row.pair[0].length;i++){
    const a=row.pair[0][i],b=row.pair[1][i]
    expect(a.visible,`${row.operation}/${i} visible`).toBeGreaterThan(100)
    expect(a.pixelHash,`${row.operation}/${i} differs from blank`).not.toBe(result.blank.pixelHash)
    expect(b.pixelHash,`${row.operation}/${i} exact pixels`).toBe(a.pixelHash)
  }
  expect(errors).toEqual([])
})

import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'

const root=fileURLToPath(new URL('../../',import.meta.url))
const doc='__e2e__desktop-playback-round2'
// Only this doc can persist, in the explicitly isolated NADOC_WORKSPACE.
// afterEach closes the page/deletes the doc; global teardown removes prefixed
// stores and credentials. The caller removes its entire scratch workspace and
// custom Archive captures after servers stop, including on test failure.
test.beforeAll(()=>{
  expect(process.env.NADOC_WORKSPACE).toBeTruthy()
  expect(existsSync(`${process.env.NADOC_WORKSPACE}/${doc}.nadoc`)).toBe(false)
})
test.afterEach(async({page,request})=>{
  await page.close()
  await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${doc}`)
})
test('bond buffer writes preserve playback pixels and picking in the running desktop renderer',async({page})=>{
  test.setTimeout(90000)
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  const original=execFileSync('git',['show','2f3b962966b4917d9f626e486d56680306600363:frontend/src/scene/atomistic_renderer.js'],{cwd:root,encoding:'utf8'})
    .replace(/from ['"]three['"]/g,"from '/node_modules/three/build/three.module.js'")
    .replace('./atomistic_renderer/geometry_builder.js','./atomistic_renderer/__desktop_original_geometry_builder.js')
  const helperSource=execFileSync('git',['show','2f3b962966b4917d9f626e486d56680306600363:frontend/src/scene/atomistic_renderer/geometry_builder.js'],{cwd:root,encoding:'utf8'})
    .replace(/from ['"]three['"]/g,"from '/node_modules/three/build/three.module.js'")
  // Hold unchanged geometry constructors/material modules constant. Override
  // only the historical writer, which is self-contained and remains independent.
  const writer=helperSource.slice(helperSource.indexOf('export function writeBondMatrix('))
  expect(writer.trim().endsWith('}')).toBe(true)
  const helper="export * from './geometry_builder.js';\n"+writer
  await page.route('**/src/scene/atomistic_renderer/__desktop_original_geometry_builder.js',route=>route.fulfill({contentType:'text/javascript',body:helper}))
  await page.route('**/src/scene/__desktop_baseline_atomistic_renderer.js',route=>route.fulfill({contentType:'text/javascript',body:original}))
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(()=>window.__nadocTest)
  const result=await page.evaluate(async({control})=>{
    const THREE=await import('/node_modules/three/build/three.module.js')
    const old=await import('/src/scene/__desktop_baseline_atomistic_renderer.js')
    const current=await import('/src/scene/atomistic_renderer.js')
    const t=window.__nadocTest;t.pauseViewerRenderingForTest()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const atoms=Array.from({length:400},(_,i)=>({serial:i*8+3,element:['C','O','N','P'][i%4],
      x:(i%20)*.2,y:Math.floor(i/20)*.2,z:0,helix_id:'h',bp_index:i,direction:'FORWARD',strand_id:'s'}))
    const bonds=atoms.flatMap((a,i)=>i%20?[[atoms[i-1].serial,a.serial]]:[])
    t.applyCameraPoseForTest({position:[1.9,1.9,8],target:[1.9,1.9,0],up:[0,1,0]})
    const comparisons=[]
    const capture=()=>{
      const buffers=t.scene.children.filter(m=>m.isInstancedMesh).map(m=>{
        const hash=array=>{let h=2166136261;for(const byte of new Uint8Array(array.buffer,array.byteOffset,array.byteLength))h=Math.imul(h^byte,16777619)>>>0;return h}
        return {name:m.name,count:m.count,matrix:hash(m.instanceMatrix.array),color:m.instanceColor?hash(m.instanceColor.array):null}
      })
      return {...t.renderedPixelCensus(),buffers}
    }
    for(const mode of ['ballstick','stick','vdw']) for(const impostors of [false,true]){
      const paired=[]
      for(const init of [old.initAtomisticRenderer,control?old.initAtomisticRenderer:current.initAtomisticRenderer]){
        const r=init(t.scene,{independentColors:true})
        try{
          r.setMode(mode);r.update({atoms,bonds,sphereImpostors:impostors})
          const initial=capture()
          t.scene.updateMatrixWorld(true)
          const ray=new THREE.Raycaster(new THREE.Vector3(0,0,20),new THREE.Vector3(0,0,-1))
          const picked=r.raycastPick(ray)?.atom.serial
          r.highlight({strandIds:['s']})
          const selected=capture()
          r.updateFrame({atoms:atoms.map(a=>({...a,x:a.x+.1})),bonds})
          const updated=capture()
          const from=new Float64Array((atoms.at(-1).serial+1)*3),to=new Float64Array(from.length)
          for(const a of atoms){from.set([a.x,a.y,a.z],a.serial*3);to.set([a.x+.2,a.y-.1,a.z+.1],a.serial*3)}
          r.applyPositionLerp(from,to,.4)
          const interpolated=capture()
          r.applyPositionLerp(to,to,0)
          const snapshot=capture()
          paired.push({initial,selected,updated,interpolated,snapshot,picked})
        }finally{r.dispose()}
      }
      comparisons.push({mode,impostors,paired})
    }
    return {control,atoms:atoms.length,bonds:bonds.length,comparisons}
  },{control:process.env.NADOC_PLAYBACK_CONTROL==='1'})
  console.log('desktop playback diagnostic',JSON.stringify(result))
  for(const c of result.comparisons){
    expect(c.paired[0].picked).toBeDefined()
    expect(c.paired[1].picked).toBe(c.paired[0].picked)
    for(const state of ['initial','selected','updated','interpolated','snapshot']){
      expect(c.paired[0][state].visible).toBeGreaterThan(100)
      expect(c.paired[1][state].buffers,`${c.mode}/${c.impostors}/${state} buffers`).toEqual(c.paired[0][state].buffers)
      expect(c.paired[1][state].pixelHash,`${c.mode}/${c.impostors}/${state} pixels`).toBe(c.paired[0][state].pixelHash)
    }
  }
  expect(errors).toEqual([])
  console.log('desktop renderer verification',JSON.stringify(result))
})

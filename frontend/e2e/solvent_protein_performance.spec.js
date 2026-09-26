import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DOC = '__e2e__solvent-protein'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const ownedPaths = [`.session/${DOC}`, `.nadoc-projects/${DOC}`, `${DOC}.nadoc`]
  .map(path => `${ROOT}workspace/${path}`)
let content

test.beforeAll(() => {
  for (const path of ownedPaths) expect(existsSync(path), `Pre-existing test artifact: ${path}`).toBe(false)
  content = execFileSync('uv', ['run', 'python', '-c',
    `from tests.conftest import make_6hb_design; d=make_6hb_design(21); d.id='${DOC}'; d.metadata.name='${DOC}'; print(d.model_dump_json())`],
  { cwd: ROOT, encoding: 'utf8' })
})

test.afterEach(async ({ page, request }) => {
  try {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${DOC}`)
  } finally {
    for (const path of ownedPaths) rmSync(path, { recursive: true, force: true })
    for (const path of ownedPaths) expect(existsSync(path)).toBe(false)
  }
})

test('solvent and protein optimizations preserve rendered pixels and picking', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', m => { if (m.type() === 'error' && /WebGL|shader/i.test(m.text())) errors.push(m.text()) })
  for (const name of ['md_solvent_overlay','protein_trace_renderer','md_periodic_images']) {
    const body = execFileSync('git', ['show', `0dc8b857378b077a739289f413a23cfad3e234a3:frontend/src/scene/${name}.js`], { cwd: ROOT, encoding: 'utf8' })
      .replace(/from ['"]three['"]/g, "from '/node_modules/three/build/three.module.js'")
    await page.route(`**/src/scene/__original_${name}.js`, route => route.fulfill({ contentType: 'text/javascript', body }))
  }
  await page.goto(`/?doc=${DOC}`)
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js'); await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, content)
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const oldWater = await import('/src/scene/__original_md_solvent_overlay.js')
    const newWater = await import('/src/scene/md_solvent_overlay.js')
    const oldProtein = await import('/src/scene/__original_protein_trace_renderer.js')
    const newProtein = await import('/src/scene/protein_trace_renderer.js')
    const t = window.__nadocTest
    t.pauseViewerRenderingForTest()
    t.applyCameraPoseForTest({ position: [0,0,24], target: [0,0,0] })
    const checks = []
    for (const impostors of [false,true]) for (const mode of ['sphere','atomistic']) {
      window.NADOC_IMPOSTORS = impostors
      const paired = []
      for (const init of [oldWater.initMdSolventOverlay,newWater.initMdSolventOverlay]) {
        const r = init(t.scene), n=200, stride=mode==='sphere'?3:9
        r.setMode(mode,true);r.setIonSpecies(Uint8Array.from({length:25},(_,i)=>i%5))
        const frame={nWater:n,water:new Float32Array(n*stride),ions:Float32Array.from({length:75},(_,i)=>Math.sin(i)*3)}
        for(let i=0;i<n;i++)for(let k=0;k<stride/3;k++)frame.water.set([(i%20)*.4-4+k*.05,Math.floor(i/20)*.4-2+k*.06,k*.05],i*stride+k*3)
        r.setFrame(frame)
        const images=[t.renderedPixelCensus()]
        frame.nWater=80;frame.water[0]+=.25;r.setFrame(frame);images.push(t.renderedPixelCensus())
        paired.push(images);r.dispose()
      }
      checks.push({feature:'solvent',mode,impostors,paired})
    }
    delete window.NADOC_IMPOSTORS
    for(const mode of ['trace','ovoid','box']) {
      const paired=[]
      for(const init of [oldProtein.initProteinTraceRenderer,newProtein.initProteinTraceRenderer]) {
        const r=init(t.scene)
        let atoms=Array.from({length:150},(_,i)=>({helix_id:'__protein__p',name:'CA',chain_id:'A',serial:i,x:Math.cos(i*.1)*2,y:Math.sin(i*.1)*2,z:i*.02-1.5}))
        r.setMode(mode);r.update({atoms})
        const images=[t.renderedPixelCensus()]
        atoms=atoms.map(a=>({...a,serial:a.serial+1000}));r.update({atoms});images.push(t.renderedPixelCensus())
        r.highlight({data:{attachment_id:'p'}});r.update({atoms});images.push(t.renderedPixelCensus())
        t.scene.updateMatrixWorld(true)
        const pick=r.raycastPick(new THREE.Raycaster(new THREE.Vector3(2,0,10),new THREE.Vector3(0,0,-1)))?.atom.serial
        atoms[0].x+=.2;r.update({atoms});images.push(t.renderedPixelCensus())
        paired.push({images,pick,centroid:r.centroidOf().toArray()});r.dispose()
      }
      checks.push({feature:'protein',mode,paired})
    }
    const oldPeriodic = await import('/src/scene/__original_md_periodic_images.js')
    const newPeriodic = await import('/src/scene/md_periodic_images.js')
    const paired=[]
    for(const init of [oldPeriodic.initPeriodicImages,newPeriodic.initPeriodicImages]) {
      const group=new THREE.Group();t.scene.add(group)
      const entries=Array.from({length:20},(_,i)=>({pos:new THREE.Vector3(i*.15-1,.1,.2),defaultColor:0xff0000}))
      const r=init({scene:group,getEntries:()=>entries})
      window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail:{enabled:false,periodicImages:true,dimensions:[3,3,3]}}))
      const images=[t.renderedPixelCensus(),t.renderedPixelCensus()]
      entries[0].pos.y+=1;t.renderedPixelCensus();images.push(t.renderedPixelCensus())
      entries[1].defaultColor=0x00ff00;t.renderedPixelCensus();images.push(t.renderedPixelCensus())
      paired.push(images);r.dispose();t.scene.remove(group)
    }
    checks.push({feature:'periodic images',paired})
    return checks
  })
  for (const check of result) expect(check.paired[1],JSON.stringify(check)).toEqual(check.paired[0])
  expect(errors).toEqual([])
  console.log(JSON.stringify(result))
})

import { test, expect } from '@playwright/test'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const root=fileURLToPath(new URL('../../',import.meta.url))
const fixture=`${root}.development-artifacts/inset-coordinate-fixture.json`
const doc='__e2e__inset-exact-sources', source=`${root}workspace/24hb_2xT.nadoc`, session=`${root}workspace/.session/${doc}`
let original
// Read-only source and coordinate evidence; no design/save endpoints are called.
// Session cache disabled; afterEach cleans this exact session even on failure.
// Global teardown cleans the isolated credential; reporter removes screenshots.
test.beforeEach(()=>{test.skip(!existsSync(fixture),'Requires local P1 coordinate audit');original=readFileSync(source);expect(existsSync(session)).toBe(false)})
test.afterEach(async({page,request})=>{if(!original)return;try{await page.close();await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${doc}`)}finally{rmSync(session,{recursive:true,force:true});expect(readFileSync(source).equals(original)).toBe(true)}})
test('P1 inset uses exact means and trajectory atoms in Full and atomistic views',async({page},info)=>{
 test.setTimeout(180000)
 const evidence=JSON.parse(readFileSync(fixture)), errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 await page.route(/\/api\/design\/atomistic(?:\?|$)/,async route=>{
  const response=await route.fetch(), data=await response.json(), keys=new Set(evidence.keys)
  data.atoms=data.atoms.filter(a=>keys.has(a.crossover_id!=null?`__xb__:${a.crossover_id}:${a.extra_base_k}`:`${a.helix_id}:${a.bp_index}:${a.direction}${a.copy_k?':'+a.copy_k:''}`))
  const ids=new Set(data.atoms.map(a=>a.serial));data.bonds=data.bonds.filter(([a,b])=>ids.has(a)&&ids.has(b))
  await route.fulfill({response,json:data})
 })
 await page.setViewportSize({width:1400,height:1000})
 await page.goto(`/?debug=1&doc=${doc}`)
 await page.waitForFunction(()=>window.__nadocTest&&window.__NADOC_ZOOM_VOLUME__)
 await page.evaluate(async({source,evidence})=>{
  const api=await import('/src/api/client.js');await api.loadDesign(source)
  document.getElementById('welcome-screen')?.classList.add('hidden')
  const {initOxdnaDisplay}=await import('/src/ui/oxdna_display.js')
  const {mdVizApiAdapter}=await import('/src/ui/md_viz_adapter.js')
  const raw={getMdDisplayMeta:async()=>({ready:true}),getMdRmsf:async()=>evidence.rmsf,
   getMdRmsfAtomistic:async()=>({ready:true,model:evidence.model,atomistic:evidence.mean}),
   getMdAtomisticModel:async()=>evidence.model,getMdFramesAtomistic:async(_,ids)=>Object.fromEntries(ids.filter(i=>evidence.frames[i]).map(i=>[i,evidence.frames[i]])),
   getMdTrajectory:async()=>evidence.trajectory}
  window.__exactRepr='full'
  window.__exactCtrl=initOxdnaDisplay({api:mdVizApiAdapter(raw),designRenderer:window.__nadocTest.getDesignRenderer(),
   getAtomisticRenderer:()=>window.__nadocTest.getAtomisticRenderer(),getCurrentRepr:()=>window.__exactRepr})
  window.__exactEvidence=evidence
 },{source,evidence})
 await expect.poll(()=>page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.debug().ready),{timeout:60000}).toBe(true)
 const audit=async(frame)=>page.evaluate(async frame=>{
  const {canonicalAtomName}=await import('/src/scene/md_inset_atoms.js')
  const actual=new Map(window.__NADOC_ZOOM_VOLUME__.debugAtoms()), model=window.__exactEvidence.model
  let error=0,missing=0,relative=0
  const expected=new Map(model.atoms.map((a,i)=>[`${a.base_key}:${canonicalAtomName(a.name)}`,frame.dense.slice(i*3,i*3+3)]))
  const first=[...expected.keys()][0],anchor=actual.get(first),origin=expected.get(first)
  for(const [key,p] of expected){const q=actual.get(key);if(!q){missing++;continue}error=Math.max(error,Math.hypot(...p.map((v,i)=>v-q[i])));if(anchor)relative=Math.max(relative,Math.hypot(...p.map((v,i)=>(v-origin[i])-(q[i]-anchor[i]))))}
  return {missing,error,relative,count:actual.size}
 },frame)
 const check=async(frame)=>{await expect.poll(async()=>{const r=await audit(frame);return r.missing?Infinity:r.error},{timeout:30000}).toBeLessThan(1e-4);const r=await audit(frame);expect(r.relative).toBeLessThan(1e-4);expect(r.count).toBe(evidence.model.atoms.length);return r}
 const results={}
 for(const repr of ['full','ballstick']){
  await page.evaluate(async repr=>{window.__exactRepr=repr;window.__nadocTest.setRepresentation(repr)},repr)
  await page.evaluate(()=>window.__exactCtrl.displayRmsf('existing-P1',{awaitHeavy:true,refetch:true}))
  results[`flex_${repr}`]=await check(evidence.mean)
 }
 await page.evaluate(()=>window.__exactCtrl.stopAndRestore())
 for(const repr of ['full','ballstick']){
  await page.evaluate(async repr=>{window.__exactRepr=repr;window.__nadocTest.setRepresentation(repr);await window.__exactCtrl.loadTrajectory('existing-P1',true,'job',1)},repr)
  for(const i of [0,2,1]){
   await page.evaluate(index=>window.__exactCtrl.showFrame(index),evidence.indices[i])
   results[`frame_${i}_${repr}`]=await check(evidence.frames[evidence.indices[i]])
  }
  await page.evaluate(async indices=>{await window.__exactCtrl.ensureInterpolationFrames(indices[0],indices[1]);window.__exactCtrl.setPlaying(true);window.__exactCtrl.showInterpolatedFrame(indices[0],indices[1],.5)},evidence.indices)
  const a=evidence.frames[evidence.indices[0]],b=evidence.frames[evidence.indices[1]]
  results[`interpolated_${repr}`]=await check({...a,dense:a.dense.map((v,i)=>(v+b.dense[i])/2)})
  await page.evaluate(()=>window.__exactCtrl.setPlaying(false))
 }
 await expect(page.locator('.zoom-volume-inset')).toBeVisible()
 await page.locator('.zoom-volume-inset').screenshot({path:info.outputPath('exact-inset.png')})
 console.log('EXACT_INSET_COORDINATES',JSON.stringify(results))
 if(process.env.NADOC_INSET_REVIEW_MS)await page.waitForTimeout(Number(process.env.NADOC_INSET_REVIEW_MS))
 await page.evaluate(()=>window.__exactCtrl.stopAndRestore())
 expect(errors).toEqual([])
})

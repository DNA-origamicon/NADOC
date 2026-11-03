/** Paired first-open CPU measurements and exact renderer-state checks; no WebGL. */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { performance } from 'node:perf_hooks'
import { Session } from 'node:inspector/promises'
import * as THREE from 'three'
import { initAtomisticRenderer } from '../src/scene/atomistic_renderer.js'

const baseline = '2f3b962966b4917d9f626e486d56680306600363'
const path = 'frontend/src/scene/atomistic_renderer.js'
const url = new URL('../src/scene/atomistic_renderer.js', import.meta.url)
const source = execFileSync('git', ['show', `${baseline}:${path}`], { encoding: 'utf8' })
const original = source.replace(/from ['"]([^'"]+)['"]/g, (_, spec) => `from '${spec.startsWith('.') ? new URL(spec, url).href : import.meta.resolve(spec)}'`)
const oldInit = (await import(`data:text/javascript;base64,${Buffer.from(original).toString('base64')}`)).initAtomisticRenderer
function fixture(n, columnar) {
  const atoms = Array.from({length:n}, (_,i) => ({serial: i*8+3, element:['C','O','P','N'][i%4],
    helix_id:'h', bp_index:i, direction:'FORWARD', strand_id:'s', x:(i%100)*.15, y:Math.floor(i/100)*.2, z:.1*(i%2)}))
  const bonds = atoms.flatMap((a,i) => i%100 ? [[atoms[i-1].serial,a.serial]] : [])
  if (!columnar) return {atoms,bonds}
  return {columnar:true,count:n,serial:Uint32Array.from(atoms,a=>a.serial),
    x:Float64Array.from(atoms,a=>a.x),y:Float64Array.from(atoms,a=>a.y),z:Float64Array.from(atoms,a=>a.z),
    elementTable:['C','O','P','N'],elementIdx:Uint8Array.from(atoms,(_,i)=>i%4),
    strandTable:['s'],strandIdx:new Uint32Array(n),helixTable:['h'],helixIdx:new Uint32Array(n),
    dirTable:['FORWARD'],dirIdx:new Uint8Array(n),bpIndex:Int32Array.from(atoms,(_,i)=>i),
    auxHelixTable:[''],auxHelixIdx:new Uint8Array(n),auxT:new Float32Array(n),bonds:new Uint32Array(bonds.flat())}
}
function setup(init,data,mode='ballstick') {
  const scene=new THREE.Scene(),renderer=init(scene,{independentColors:true})
  renderer.setMode(mode);renderer.update(data)
  return {scene,renderer}
}
function equal(a,b) {
  assert.equal(a.scene.children.length,b.scene.children.length)
  a.scene.children.forEach((mesh,i)=>{
    const other=b.scene.children[i]
    assert.equal(mesh.name,other.name);assert.equal(mesh.count,other.count)
    assert.deepEqual(mesh.instanceMatrix.array,other.instanceMatrix.array)
    assert.equal(mesh.instanceMatrix.itemSize,other.instanceMatrix.itemSize)
    assert.equal(mesh.instanceMatrix.usage,other.instanceMatrix.usage)
    assert.deepEqual(mesh.instanceColor?.array,other.instanceColor?.array)
    assert.deepEqual(mesh._instanceAlpha?.array,other._instanceAlpha?.array)
    assert.equal(mesh.frustumCulled,other.frustumCulled)
  })
}
if(process.argv.includes('--profile')) {
  const data=fixture(150000,true),session=new Session();session.connect()
  const warm=setup(initAtomisticRenderer,data);warm.renderer.dispose()
  await session.post('Profiler.enable');await session.post('Profiler.start')
  for(let i=0;i<15;i++){const s=setup(initAtomisticRenderer,data);s.renderer.dispose()}
  const {profile}=await session.post('Profiler.stop');session.disconnect()
  const byId=new Map(profile.nodes.map(n=>[n.id,n])),self=new Map()
  for(let i=0;i<profile.samples.length;i++) self.set(profile.samples[i],(self.get(profile.samples[i])??0)+profile.timeDeltas[i])
  const rows=[...self].map(([id,us])=>({function:byId.get(id).callFrame.functionName,
    source:byId.get(id).callFrame.url.replace(/^.*\/NADOC\//,''),line:byId.get(id).callFrame.lineNumber+1,self_ms:us/1000})).sort((a,b)=>b.self_ms-a.self_ms)
  console.log(JSON.stringify({scope:'Sampled Node CPU profile, current renderer initialization + disposal; 15 x 150k columnar atoms, no GPU',top_self:rows.slice(0,25)},null,2))
} else {
  const checks=[]
  for(const mode of ['ballstick','vdw','stick']) for(const columnar of [false,true]) {
    const data=fixture(300,columnar),a=setup(oldInit,data,mode),b=setup(initAtomisticRenderer,data,mode)
    equal(a,b);a.renderer.dispose();b.renderer.dispose();checks.push({mode,columnar})
  }
  for (const serials of [[3,11,3,19], [3,2**40,3,19], ['3',3,'3',19]]) {
    const data={atoms:serials.map((serial,i)=>({serial,element:'C',x:i*.1,y:0,z:0})),
      bonds:[[serials[0],serials[1]],[serials[1],serials[3]],[serials[3],serials[3]],[serials[0],-999],[serials[0],3.5]]}
    const a=setup(oldInit,data),b=setup(initAtomisticRenderer,data)
    equal(a,b);a.renderer.dispose();b.renderer.dispose()
    checks.push({serials,duplicateAndMissingEndpoints:true})
  }
  const results=[]
  for(const n of [30000,150000]) for(const columnar of [false,true]) {
    const data=fixture(n,columnar),samples={before:[],after:[]}
    for(let i=-3;i<15;i++) {
      const pair={}
      for(const label of i%2?['before','after']:['after','before']) {
        const start=performance.now();pair[label]=setup(label==='before'?oldInit:initAtomisticRenderer,data)
        if(i>=0)samples[label].push(performance.now()-start)
      }
      equal(pair.before,pair.after);pair.before.renderer.dispose();pair.after.renderer.dispose()
    }
    const summary=Object.fromEntries(Object.entries(samples).map(([k,v])=>{const s=[...v].sort((a,b)=>a-b);return [k,{median_ms:s[7],p95_ms:s[14]}]}))
    results.push({atoms:n,columnar,samples_ms:samples,summary,speedup:summary.before.median_ms/summary.after.median_ms,exactBuffers:true})
  }
  console.log(JSON.stringify({scope:'Paired warm synthetic Node CPU first-open; no GPU, browser or network',baseline,
    baseline_sha256:createHash('sha256').update(source).digest('hex'),candidate_sha256:createHash('sha256').update(readFileSync(url)).digest('hex'),node:process.version,checks,results},null,2))
}

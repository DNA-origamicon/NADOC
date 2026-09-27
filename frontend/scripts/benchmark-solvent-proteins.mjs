import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { initMdSolventOverlay } from '../src/scene/md_solvent_overlay.js'
import { initProteinTraceRenderer } from '../src/scene/protein_trace_renderer.js'
const revision = '0dc8b857378b077a739289f413a23cfad3e234a3'
async function original(name) {
  const url = new URL(`../src/scene/${name}.js`, import.meta.url)
  const source = execFileSync('git', ['show', `${revision}:frontend/src/scene/${name}.js`], { encoding: 'utf8' })
    .replace(/from ['"]([^'"]+)['"]/g, (_, spec) => `from '${spec.startsWith('.') ? new URL(spec, url).href : import.meta.resolve(spec)}'`)
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
}
const oldSolvent = (await original('md_solvent_overlay')).initMdSolventOverlay
const oldProtein = (await original('protein_trace_renderer')).initProteinTraceRenderer
const median = a => a.sort((a,b) => a-b)[Math.floor(a.length/2)]
const results = []
for (const n of [20000, 100000]) for (const mode of ['sphere', 'atomistic']) {
  const stride = mode === 'sphere' ? 3 : 9
  const frame = { nWater: n, water: Float32Array.from({ length: n*stride }, (_,i) => Math.sin(i)*10), ions: Float32Array.from({ length: n/4*3 }, (_,i) => Math.cos(i)*10) }
  const pairs = [oldSolvent,initMdSolventOverlay].map(init => {
    const scene = new THREE.Scene(), r = init(scene)
    r.setMode(mode, true); r.setIonSpecies(Uint8Array.from({length:n/4},(_,i)=>i%5)); r.setFrame(frame)
    return {scene,r,times:[]}
  })
  for (let i=0;i<30;i++) for (const p of (i%2 ? [...pairs].reverse() : pairs)) {
    const start=performance.now(); p.r.setFrame(frame); if(i>=5)p.times.push(performance.now()-start)
  }
  pairs[0].scene.children.forEach((m,i)=>assert.deepEqual(m.instanceMatrix.array,pairs[1].scene.children[i].instanceMatrix.array))
  const beforeMs=median(pairs[0].times),afterMs=median(pairs[1].times)
  results.push({feature:'solvent',mode,waters:n,ions:n/4,beforeMs,afterMs,speedup:beforeMs/afterMs,exactMatrices:true})
  pairs.forEach(p=>p.r.dispose())
}
for (const n of [300,3000]) for (const mode of ['trace','ovoid','box']) {
  const atoms=Array.from({length:n},(_,i)=>({helix_id:'__protein__p',name:'CA',chain_id:'A',x:Math.cos(i*.1),y:Math.sin(i*.1),z:i*.01}))
  const pairs=[oldProtein,initProteinTraceRenderer].map(init=>{
    const scene=new THREE.Scene(),r=init(scene);r.setMode(mode);r.update({atoms});return {scene,r,times:[]}
  })
  for(let i=0;i<18;i++)for(const p of (i%2 ? [...pairs].reverse() : pairs)){
    const fresh={atoms:atoms.map(a=>({...a}))},start=performance.now();p.r.update(fresh);if(i>=3)p.times.push(performance.now()-start)
  }
  const geometry=p=>p.scene.children[0].children[0].children[0].geometry
  for(const key of ['position','normal','uv'])assert.deepEqual(geometry(pairs[0]).attributes[key].array,geometry(pairs[1]).attributes[key].array)
  assert.deepEqual(geometry(pairs[0]).index.array,geometry(pairs[1]).index.array)
  const beforeMs=median(pairs[0].times),afterMs=median(pairs[1].times)
  results.push({feature:'unchanged protein refresh',mode,atoms:n,beforeMs,afterMs,speedup:beforeMs/afterMs,exactGeometry:true})
  pairs.forEach(p=>p.r.dispose())
}
console.log(JSON.stringify({revision,results},null,2))

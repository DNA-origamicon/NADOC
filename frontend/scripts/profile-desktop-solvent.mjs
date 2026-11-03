import inspector from 'node:inspector'
import * as THREE from 'three'
import { initMdSolventOverlay } from '../src/scene/md_solvent_overlay.js'
if (process.env.NADOC_VALIDATION_SCOPE !== '1') throw new Error('Use validation_guard.sh')
const n=100000
const frame={nWater:n,water:Float32Array.from({length:n*9},(_,i)=>Math.sin(i)*10),ions:Float32Array.from({length:n/4*3},(_,i)=>Math.cos(i)*10)}
const r=initMdSolventOverlay(new THREE.Scene());r.setMode('atomistic',true);r.setIonSpecies(Uint8Array.from({length:n/4},(_,i)=>i%5))
for(let i=0;i<20;i++)r.setFrame(frame)
const s=new inspector.Session();s.connect()
const post=method=>new Promise((resolve,reject)=>s.post(method,(err,result)=>err?reject(err):resolve(result)))
try{
  await post('Profiler.enable');await post('Profiler.start')
  for(let i=0;i<100;i++)r.setFrame(frame)
  const {profile}=await post('Profiler.stop')
  const counts=new Map();for(const id of profile.samples)counts.set(id,(counts.get(id)||0)+1)
  const rows=profile.nodes.map(n=>({function:n.callFrame.functionName,source:n.callFrame.url,line:n.callFrame.lineNumber+1,selfSamples:counts.get(n.id)||0})).filter(r=>r.selfSamples).sort((a,b)=>b.selfSamples-a.selfSamples)
  console.log(JSON.stringify({scope:'Sampled current-only CPU attribution, 100 warmed atomistic solvent frames, 100k waters/25k ions; no GPU timing',samples:profile.samples.length,topSelf:rows.slice(0,25)},null,2))
}finally{s.disconnect();r.dispose()}

/** Pre-batch sources are preserved as inert audit fixtures, not production modules. */
import { readFileSync } from 'node:fs'
import { performance } from 'node:perf_hooks'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { initAtomisticRenderer } from '../src/scene/atomistic_renderer.js'
import { expandMdAtomFrame } from '../src/scene/md_atom_frames_bin.js'
import { initTrajectoryStream } from '../src/scene/trajectory_stream.js'
const audit = new URL('../../docs/audits/loading_open_20260926/', import.meta.url)
async function original(name) {
  const url = new URL(`../src/scene/${name}.js`, import.meta.url)
  const source = readFileSync(new URL(`baseline_${name}.js.txt`, audit), 'utf8')
    .replace(/from ['"]([^'"]+)['"]/g, (_, spec) => `from '${spec.startsWith('.') ? new URL(spec, url).href : import.meta.resolve(spec)}'`)
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
}
const oldAtoms = (await original('atomistic_renderer')).initAtomisticRenderer
const oldStream = (await original('trajectory_stream')).initTrajectoryStream
const median = a => [...a].sort((x,y) => x-y)[Math.floor(a.length/2)]
const results = []
function report(operation, scale, times, extra = {}) {
  const beforeMs = median(times[0]), afterMs = median(times[1])
  const row = { operation, ...scale, beforeMs, afterMs, speedup: beforeMs / afterMs, ...extra }
  results.push(row); console.error(JSON.stringify(row))
}
function setup(init, model, mode = 'ballstick') {
  const scene = new THREE.Scene(), r = init(scene, { independentColors: true })
  r.setMode(mode); r.update(model)
  return { scene, r }
}
function equal(a, b) {
  assert.equal(a.scene.children.length, b.scene.children.length)
  a.scene.children.forEach((m, i) => {
    const other = b.scene.children[i]
    assert.equal(m.count, other.count)
    assert.deepEqual(m.instanceMatrix.array, other.instanceMatrix.array)
    assert.deepEqual(m.instanceColor.array, other.instanceColor.array)
    assert.deepEqual(m._instanceAlpha?.array, other._instanceAlpha?.array)
  })
}
for (const n of [30000, 150000]) {
  const atoms = Array.from({ length: n }, (_, i) => ({ serial: i * 8 + 3,
    element: ['C','O','P','N'][i%4], helix_id: 'h', bp_index: i, direction: 'FORWARD', strand_id: 's',
    x: (i % 100) * .15, y: Math.floor(i / 100) * .2, z: .1 * (i % 2) }))
  const bonds = atoms.flatMap((a,i) => i%100 ? [[atoms[i-1].serial,a.serial]] : [])
  const columnar = { columnar: true, count: n, serial: Uint32Array.from(atoms,a=>a.serial),
    x: Float64Array.from(atoms,a=>a.x), y: Float64Array.from(atoms,a=>a.y), z: Float64Array.from(atoms,a=>a.z),
    elementTable: ['C','O','P','N'], elementIdx: Uint8Array.from(atoms,(_,i)=>i%4),
    strandTable: ['s'], strandIdx: new Uint32Array(n), helixTable: ['h'], helixIdx: new Uint32Array(n),
    dirTable: ['FORWARD'], dirIdx: new Uint8Array(n), bpIndex: Int32Array.from(atoms,(_,i)=>i),
    auxHelixTable: [''], auxHelixIdx: new Uint32Array(n), auxT: new Float32Array(n),
    bonds: new Uint32Array(bonds.flat()) }
  for (const [format, model] of [['object', {atoms,bonds}], ['columnar', columnar]]) {
    const times = [[],[]]
    for (let k = -3; k < 11; k++) {
      const pair = []
      for (const i of k%2 ? [1,0] : [0,1]) {
        const start = performance.now(); pair[i] = setup([oldAtoms,initAtomisticRenderer][i],model)
        if (k>=0) times[i].push(performance.now()-start)
      }
      equal(...pair); pair.forEach(s=>s.r.dispose())
    }
    report('first_open_cpu', { atoms:n, bonds:bonds.length, format }, times, {exactBuffers:true})
  }
  const pair = [oldAtoms,initAtomisticRenderer].map(init=>setup(init,columnar))
  const serialMap = columnar.serial
  const frames = [0,1].map(k=>({ serialMap, length:n*8*3,
    dense: Float64Array.from(atoms.flatMap(a=>[a.x+k*.01,a.y,a.z])) }))
  let scratch
  const times=[[],[]]
  for (let k=-10;k<21;k++) {
    for (const i of k%2 ? [1,0] : [0,1]) {
      const f=frames[Math.abs(k)%2], start=performance.now()
      if(i===0) { scratch=expandMdAtomFrame(f,scratch); pair[i].r.applyPositionLerp(scratch,scratch,0) }
      else assert.equal(pair[i].r.applyCompactFrame(f),true)
      if(k>=0)times[i].push(performance.now()-start)
    }
    equal(...pair)
  }
  report('cached_compact_frame', {atoms:n,serialSpan:n*8},times,
    {exactBuffers:true, eliminatedSparseScratchBytes:n*8*3*8})
  pair.forEach(s=>s.r.dispose())
}
for (const [name, init] of [['before',oldStream],['after',initTrajectoryStream]]) {
  let release
  const reads=[]
  const s=init({total:100,load:async start=>{ reads.push(start); if(start===0)await new Promise(r=>release=r) },apply(){},live:()=>true})
  const active=s.ensure(0)
  while(!release) await Promise.resolve()
  const requests=[8,16,24,32,40,48].map(i=>(s.seek ?? s.ensure)(i))
  release(); await Promise.all([active,...requests])
  results.push({operation:'rapid_scrub_reads',version:name,reads})
}
console.log(JSON.stringify({baseline:'pre-batch inert sources with SHA256 in audit directory',results},null,2))

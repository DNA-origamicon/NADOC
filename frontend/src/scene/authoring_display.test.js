import { it, expect } from 'vitest'
import * as THREE from 'three'
import { createAuthoringDisplay } from './authoring_display.js'
it('dims existing materials, composes live opacity changes and restores after the final tool closes', () => {
  let root = new THREE.Group()
  const mat = new THREE.MeshBasicMaterial({opacity:.6,transparent:true})
  root.add(new THREE.Mesh(new THREE.BoxGeometry(),mat))
  const frames = new Set()
  const begin = createAuthoringDisplay({getRoot:()=>root, addFrameCallback:fn=>frames.add(fn),removeFrameCallback:fn=>frames.delete(fn)})
  const end=begin(), other=begin()
  expect(mat.opacity).toBe(.6);
  const shader = { uniforms: {}, fragmentShader: '#include <opaque_fragment>' }
  mat.onBeforeCompile(shader)
  expect(shader.uniforms.nadocAuthoringOpacity.value).toBe(.15);
  expect(shader.fragmentShader).toContain('diffuseColor.a *= nadocAuthoringOpacity'); expect(mat.depthWrite).toBe(false)
  mat.opacity=.4; mat.transparent=false; mat.depthWrite=true
  expect(mat.opacity).toBe(.4); expect(mat.transparent).toBe(true)
  end(); expect(frames.size).toBe(1)
  const fresh = new THREE.MeshBasicMaterial()
  root = new THREE.Group(); root.add(new THREE.Mesh(new THREE.BoxGeometry(),fresh))
  frames.forEach(fn=>fn())
  expect(mat.opacity).toBe(.4); expect(mat.transparent).toBe(false); expect(mat.depthWrite).toBe(true)
  expect(fresh.opacity).toBe(1); expect(fresh.transparent).toBe(true)
  other(); other()
  expect(fresh.opacity).toBe(1); expect(fresh.transparent).toBe(false); expect(fresh.depthWrite).toBe(true)
  expect(frames.size).toBe(0)
})
it('composes shader hooks installed during authoring without recursion or leaving the model dimmed', () => {
  const material = new THREE.MeshBasicMaterial()
  const root = new THREE.Mesh(new THREE.BoxGeometry(), material)
  const begin = createAuthoringDisplay({getRoot:()=>root, addFrameCallback:()=>{},removeFrameCallback:()=>{}})
  const end = begin(), earlier = material.onBeforeCompile
  material.onBeforeCompile = function(shader, renderer) { earlier.call(this,shader,renderer); shader.uniforms.otherDisplayFactor={value:.8} }
  const shader = {uniforms:{},fragmentShader:'#include <opaque_fragment>'}
  material.onBeforeCompile(shader)
  expect(shader.uniforms.nadocAuthoringOpacity.value).toBe(.15)
  end(); expect(shader.uniforms.nadocAuthoringOpacity.value).toBe(1)
  expect(shader.uniforms.otherDisplayFactor.value).toBe(.8)
  const endAgain=begin(), next={uniforms:{},fragmentShader:'#include <opaque_fragment>'}
  material.onBeforeCompile(next)
  expect(next.uniforms.nadocAuthoringOpacity.value).toBe(.15)
  expect(next.fragmentShader.match(/uniform float nadocAuthoringOpacity;/g)).toHaveLength(1)
  endAgain(); expect(next.uniforms.nadocAuthoringOpacity.value).toBe(1)
})
it('includes separate crossover arc roots and preserves per-arc alpha through rebuild and close', async () => {
  const { buildNativeConnectionLines } = await import('./native_connection_lines.js')
  const geometry = new THREE.Group(), arcs = new THREE.Group(), frames = new Set()
  const makeArc = alpha => buildNativeConnectionLines([{color:0x00ff00}], 'scaffold', arc=>arc.color, ()=>alpha)
  let arc = makeArc(.4); arcs.add(arc.line)
  const begin = createAuthoringDisplay({getRoots:()=>[geometry, arcs, null],addFrameCallback:fn=>frames.add(fn),removeFrameCallback:fn=>frames.delete(fn)})
  const originalHook = arc.line.material.onBeforeCompile
  const end = begin()
  function checkFade(line) {
    const shader={uniforms:{},fragmentShader:THREE.ShaderLib.basic.fragmentShader}
    line.material.onBeforeCompile(shader)
    expect(shader.uniforms.nadocAuthoringOpacity.value).toBe(.15)
    expect(shader.fragmentShader).toContain('diffuseColor.a *= nadocAuthoringOpacity;')
    expect(line.material.opacity).toBe(.85)
    expect(line.material.depthWrite).toBe(false)
  }
  checkFade(arc.line)
  expect(arc.colors[3]).toBeCloseTo(.4)
  const old = arc; arcs.remove(old.line)
  arc=makeArc(.7); arcs.add(arc.line); frames.forEach(fn=>fn())
  expect(old.line.material.onBeforeCompile).toBe(originalHook)
  checkFade(arc.line); expect(arc.colors[3]).toBeCloseTo(.7)
  end()
  expect(arc.line.material.onBeforeCompile).toBe(originalHook)
  expect(arc.line.material.opacity).toBe(.85)
  expect(arc.line.material.transparent).toBe(true)
  expect(arc.line.material.depthWrite).toBe(true)
  expect(arc.colors[3]).toBeCloseTo(.7)
  for (const item of [old,arc]) { item.geo.dispose();item.line.material.dispose() }
})

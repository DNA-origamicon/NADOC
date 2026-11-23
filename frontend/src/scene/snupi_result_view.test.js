import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initSnupiResultView, snupiSiteColor } from './snupi_result_view.js'
const data = (kind = 'flex') => ({ meta: { kind, count: 2, min: 0, max: 1, helix_ids: ['a'], joints: 0 },
  positions: new Float32Array([1, 2, 3, 1, 2, 4]), scalars: new Float32Array([0, 1]),
  identities: new Int32Array([0, 0, 0, 0, 0, 1, 0, 2]) })
it('uses scalar colors when present and categorical colors for predicted/trajectory sites', () => {
  const d = data(); expect(snupiSiteColor(d, 0, 0, 1, 'viridis')).not.toBe(snupiSiteColor(d, 1, 0, 1, 'viridis'))
  d.meta.kind = 'deform'; expect(snupiSiteColor(d, 0, 0, 1)).toBe(snupiSiteColor(d, 1, 0, 1))
  d.identities[4] = 1; expect(snupiSiteColor(d, 0, 0, 1)).not.toBe(snupiSiteColor(d, 1, 0, 1))
})
it('renders lit opaque instances at exact saved sites and reuses them when scrubbing', () => {
  const scene = new THREE.Scene(), view = initSnupiResultView(scene), d = data()
  view.update(d, 'viridis'); const mesh = scene.children[0].children[0], m = new THREE.Matrix4()
  expect(mesh.isInstancedMesh).toBe(true); expect(mesh.material.isMeshStandardMaterial).toBe(true)
  expect(mesh.material.depthWrite).toBe(true); expect(mesh.material.transparent).toBe(false)
  mesh.getMatrixAt(0, m); expect(new THREE.Vector3().setFromMatrixPosition(m).toArray()).toEqual([1, 2, 3])
  const next = data(); next.positions[0] = 8; view.updatePositions(next)
  expect(scene.children[0].children[0]).toBe(mesh)
  mesh.getMatrixAt(0, m); expect(m.elements[12]).toBe(8)
  expect(view.getBoundingBox().max.x).toBeGreaterThan(8)
  const dispose = vi.spyOn(mesh, 'dispose'); view.clear(); expect(dispose).toHaveBeenCalled(); expect(scene.children).toHaveLength(0)
})
it('draws only recorded axis/joint pairs, with thinner crossover joints and live recoloring', () => {
  const scene = new THREE.Scene(), view = initSnupiResultView(scene), d = data('cando')
  d.meta.joints = 1; view.update(d)
  const mesh = scene.children[0].children[0], m = new THREE.Matrix4(); expect(mesh.count).toBe(1)
  mesh.getMatrixAt(0, m); expect(new THREE.Vector3().setFromMatrixScale(m).x).toBeCloseTo(.2)
  const before = mesh.instanceColor.array.slice(); view.recolor(0, 1, 'viridis')
  expect(mesh.instanceColor.array).not.toEqual(before); view.clear()
})
it('materializes exact nucleotide identities including loop copies and publishes new frames', () => {
  const scene = new THREE.Scene(), view = initSnupiResultView(scene)
  const renderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn() }
  view.update(data()); expect(view.materialize(renderer)).toBe(true)
  expect(scene.children[0].visible).toBe(false)
  expect(renderer.applyScalarColors.mock.calls[0][0]['a:1:FORWARD:2']).toBeDefined()
  expect(view.coloringInfo().values[1].copy).toBe(2)
  const next = data(); next.positions[0] = 5; view.updatePositions(next)
  expect(renderer.applyFemPositions.mock.lastCall[0][0].backbone_position[0]).toBe(5)
  view.clear()
})

it('bounds distant bead work, restores close-up detail, and retains every coordinate across frames', async () => {
  const { snupiGlyphCount } = await import('./snupi_result_view.js')
  expect(snupiGlyphCount(0, 4096)).toBe(32)
  expect(snupiGlyphCount(1000, 4096)).toBe(4096)
  const scene = new THREE.Scene(), view = initSnupiResultView(scene), n = 5000
  const d = { meta: {kind:'deform',count:n}, positions:new Float32Array(n*3), scalars:new Float32Array(n).fill(-1) }
  for(let i=0;i<n;i++) d.positions[3*i]=i
  view.update(d)
  const root=scene.children[0], mesh=root.children[0], camera=new THREE.PerspectiveCamera(45,1,.1,1e7)
  expect(root.children.reduce((n,m)=>n+m.instanceMatrix.count,0)).toBe(n)
  camera.position.set(0,0,1e6);mesh.onBeforeRender({domElement:{height:800}},scene,camera)
  expect(mesh.count).toBe(32)
  const next={...d,positions:d.positions.slice()};next.positions[3*(n-1)]=9999;view.updatePositions(next)
  expect(view.getBoundingBox().max.x).toBeGreaterThan(9999)
  camera.position.set(2048,0,100);mesh.onBeforeRender({domElement:{height:800}},scene,camera)
  expect(mesh.count).toBe(4096)
  view.clear()
})

it('keeps missing scalar data neutral instead of implying a measured RMSF or deviation', () => {
  const d=data();d.scalars[0]=-1;d.scalars[1]=NaN;d.identities[4]=1
  expect(snupiSiteColor(d,0,0,1)).toBe(0x94a3b8)
  expect(snupiSiteColor(d,1,0,1)).toBe(0x94a3b8)
})

import { describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { _createSharedInstancingRenderer } from './assembly_renderer_shared.js'

function fixture(options = {}) {
  let assembly = { instances: ['a', 'b', 'c'].map(id => ({
    id, source: { type: 'file', path: `${id}.nadoc` }, geometrySourceKey: `f:/${id}.nadoc:1:`,
    representation: 'full', visible: true, transform: { values: new THREE.Matrix4().elements },
  })) }
  const design = { helices: [], strands: [{ id: 's', strand_type: 'staple', domains: [] }], crossovers: [] }
  const nucleotides = [0, 1].map(i => ({ helix_id: 'h', bp_index: i, direction: 'FORWARD', copy: 0,
    strand_id: 's', strand_type: 'staple', domain_index: 0, backbone_position: [1, 0, i],
    placement_source: 'native-full-o5-v1', slab_position: [.67, 0, i], slab_quaternion: [-.5, .5, .5, .5],
    base_position: [.5, 0, i], base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1] }))
  const data = () => ({ design, nucleotides, helix_axes: {} })
  const api = {
    getAssemblyGeometry: vi.fn(async () => ({ instances: Object.fromEntries(assembly.instances.map(i => [i.id, data()])) })),
    getInstanceGeometry: vi.fn(async () => data()),
    getInstanceProteinGeometry: vi.fn(async () => ({ atoms: [] })),
    getLinkerGeometry: vi.fn(async () => ({ nucleotides: [], helix_axes: [] })),
  }
  const store = { getState: () => ({ currentAssembly: assembly }), subscribe: vi.fn() }
  const scene = new THREE.Scene()
  const renderer = _createSharedInstancingRenderer({ scene, store, api, ...options })
  const source = id => scene.children.find(o => o.userData.sharedSource?.startsWith(`file:${id}.nadoc:`))
  return { api, scene, renderer, source, assembly: () => assembly,
    update: fn => { assembly = { ...assembly, instances: assembly.instances.map(i => fn({ ...i })) }; return assembly } }
}

describe('shared assembly source reuse', () => {
  it('reports an existing failed source load to later waiters and clears the error on an explicit rebuild', async () => {
    const f = fixture()
    f.api.getAssemblyGeometry.mockResolvedValueOnce({ instances: {} })
    f.api.getInstanceGeometry.mockResolvedValueOnce(null).mockResolvedValueOnce(null).mockResolvedValueOnce(null)
    await expect(f.renderer.rebuild(f.assembly())).rejects.toThrow('Could not load assembly geometry')
    await expect(f.renderer.whenReady(f.assembly())).rejects.toThrow('Could not load assembly geometry')
    await expect(f.renderer.whenReady(f.assembly())).rejects.toThrow('Could not load assembly geometry')
    const retry = f.renderer.rebuild(f.assembly())
    const ready = f.renderer.whenReady(f.assembly())
    await retry
    await expect(ready).resolves.toBeUndefined()
    expect(f.renderer.getInstanceDesign('a')).not.toBeNull()
    f.renderer.dispose()
  })

  it('settles a pending Cylinders source wait when Full supersedes its deferred initial geometry build', async () => {
    const f = fixture()
    const cylinders = f.update(i => ({ ...i, representation: 'cylinders' }))
    let finishGeometry
    f.api.getAssemblyGeometry.mockImplementationOnce(() => new Promise(resolve => { finishGeometry = resolve }))
    const complete = vi.fn()
    const ready = f.renderer.whenReady(cylinders).then(complete)
    const firstBuild = f.renderer.rebuild(cylinders)
    await Promise.resolve()
    const full = f.update(i => ({ ...i, representation: 'full' }))
    const latestBuild = f.renderer.rebuild(full)
    expect(complete).not.toHaveBeenCalled()
    finishGeometry({ instances: {} })
    await Promise.all([firstBuild, latestBuild])
    await ready
    expect(complete).toHaveBeenCalledOnce()
    expect(f.renderer.probeLod().sources.every(source => Object.values(source.representations).every(rep => rep === 'full'))).toBe(true)
    await expect(f.renderer.whenReady(full)).resolves.toBeUndefined()
    f.renderer.dispose()
  })

  it('does not satisfy an old source version while a newer Full source completes', async () => {
    const f = fixture()
    const old = f.update(i => ({ ...i, representation: 'cylinders' }))
    let finishGeometry
    f.api.getAssemblyGeometry.mockImplementationOnce(() => new Promise(resolve => { finishGeometry = resolve }))
    const controller = new AbortController(), complete = vi.fn()
    const oldReady = f.renderer.whenReady(old, { signal: controller.signal }).then(complete)
    const rejected = expect(oldReady).rejects.toMatchObject({ name: 'AbortError' })
    const building = f.renderer.rebuild(old)
    await Promise.resolve()
    const latest = f.update(i => ({ ...i, representation: 'full', geometrySourceKey: `f:/${i.id}.nadoc:2:` }))
    const latestBuild = f.renderer.rebuild(latest)
    finishGeometry({ instances: {} })
    await Promise.all([building, latestBuild])
    await expect(f.renderer.whenReady(latest)).resolves.toBeUndefined()
    expect(complete).not.toHaveBeenCalled()
    controller.abort()
    await rejected
    f.renderer.dispose()
  })

  it.each(['unversioned snapshot', 'membership', 'mode'])('keeps strict readiness authority for changed %s', async change => {
    const f = fixture()
    if (change === 'unversioned snapshot') f.update(i => ({ ...i, geometrySourceKey: undefined }))
    await f.renderer.rebuild(f.assembly())
    const changed = f.update(i => ({ ...i, representation: 'beads',
      ...(change === 'membership' ? { id: `${i.id}-new` } : {}),
      ...(change === 'mode' ? { mode: 'articulated' } : {}),
    }))
    const complete = vi.fn(), controller = new AbortController()
    const pending = f.renderer.whenReady(changed, { signal: controller.signal }).then(complete)
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await Promise.resolve()
    expect(complete).not.toHaveBeenCalled()
    controller.abort()
    await rejected
    f.renderer.dispose()
  })

  it('lets readiness subscribe before a rebuild and rejects failed or disposed work', async () => {
    const f = fixture()
    const ready = f.renderer.whenReady(f.assembly())
    await f.renderer.rebuild(f.assembly())
    await expect(ready).resolves.toBeUndefined()
    const equivalent = f.update(i => i)
    await expect(f.renderer.whenReady(equivalent)).resolves.toBeUndefined()
    const changed = f.update(i => i.id === 'a' ? { ...i, geometrySourceKey: 'f:/a.nadoc:2:' } : i)
    const failed = f.renderer.whenReady(changed)
    const rejection = expect(failed).rejects.toThrow('Could not load assembly geometry')
    f.api.getInstanceGeometry.mockResolvedValueOnce(null)
    await expect(f.renderer.rebuild(changed)).rejects.toThrow('Could not load assembly geometry')
    await rejection
    const retry = f.renderer.rebuild(changed)
    const canceled = f.renderer.whenReady(changed)
    const aborted = expect(canceled).rejects.toMatchObject({ name: 'AbortError' })
    f.renderer.dispose()
    await aborted
    await retry
  })
  it('changes one source representation without refetching coordinates or replacing other meshes', async () => {
    const f = fixture()
    await f.renderer.rebuild(f.assembly())
    const before = ['a', 'b', 'c'].map(f.source)
    await f.renderer.rebuild(f.update(i => i.id === 'a' ? { ...i, representation: 'beads' } : i))
    expect(f.api.getAssemblyGeometry).toHaveBeenCalledOnce()
    expect(f.api.getInstanceGeometry).not.toHaveBeenCalled()
    expect(f.source('a')).toBe(before[0])
    expect(f.source('b')).toBe(before[1])
    expect(f.source('c')).toBe(before[2])
    expect(f.renderer.getBoundingBox().isEmpty()).toBe(false)
    f.renderer.dispose()
  })

  it('retains Full meshes across lower-detail switches, hiding slabs without changing poses', async () => {
    const f = fixture()
    await f.renderer.rebuild(f.assembly())
    const source = f.source('a'), slab = source.getObjectByName('baseSlabs')
    const poses = slab.userData.sharedBpXformData.slice()
    const shader = { uniforms: {}, vertexShader: THREE.ShaderLib.phong.vertexShader, fragmentShader: THREE.ShaderLib.phong.fragmentShader }
    slab.material.onBeforeCompile(shader)
    expect(shader.vertexShader).toContain('v_visible *= texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).g')
    const camera = new THREE.PerspectiveCamera(); camera.position.z = 20
    const gpu = { getContext: () => ({}), properties: { get: () => ({}) }, domElement: { height: 800 } }
    f.renderer.setSuppressLodDemotion(true)
    for (const representation of ['beads', 'cylinders', 'full']) {
      await f.renderer.rebuild(f.update(i => ({ ...i, representation })))
      source.getObjectByName('backboneSpheres').onBeforeRender(gpu, f.scene, camera)
      expect(f.source('a')).toBe(source)
      expect(slab.userData.sharedBpXformData).toEqual(poses)
      expect(shader.uniforms.u_visibilityTex.value.image.data[1]).toBe(representation === 'full' ? 1 : 0)
      expect(slab.count).toBe(representation === 'full' ? 2 : 0)
    }
    expect(f.api.getAssemblyGeometry).toHaveBeenCalledOnce()
    expect(f.api.getInstanceProteinGeometry).not.toHaveBeenCalled()
    f.renderer.dispose()
  })

  it('upgrades a cheap source once, then keeps the prepared Full source', async () => {
    const f = fixture({ prepareFull: false })
    f.update(i => ({ ...i, representation: 'cylinders' }))
    await f.renderer.rebuild(f.assembly())
    const cheap = f.source('a')
    await f.renderer.rebuild(f.update(i => ({ ...i, representation: 'full' })))
    const full = f.source('a')
    expect(full).not.toBe(cheap)
    await f.renderer.rebuild(f.update(i => ({ ...i, representation: 'cylinders' })))
    await f.renderer.rebuild(f.update(i => ({ ...i, representation: 'full' })))
    expect(f.source('a')).toBe(full)
    expect(f.api.getAssemblyGeometry).toHaveBeenCalledOnce()
    expect(f.api.getInstanceGeometry).not.toHaveBeenCalled()
    f.renderer.dispose()
  })

  it('prepares native Full on initial Cylinders load while drawing only the requested tier', async () => {
    const f = fixture()
    f.update(i => ({ ...i, representation: 'cylinders' }))
    await f.renderer.rebuild(f.assembly())
    const source = f.source('a'), slab = source.getObjectByName('baseSlabs')
    const camera = new THREE.PerspectiveCamera(); camera.position.z = 20
    const gpu = { getContext: () => ({}), properties: { get: () => ({}) }, domElement: { height: 800 } }
    f.renderer.setSuppressLodDemotion(true)
    source.getObjectByName('backboneSpheres').onBeforeRender(gpu, f.scene, camera)
    expect(slab.count).toBe(0)
    expect(f.renderer.probeLod().sources[0]).toMatchObject({ builtRepresentation: 'full', counts: { close: 0, mid: 1, hull: 0 } })
    await f.renderer.rebuild(f.update(i => ({ ...i, representation: 'full' })))
    source.getObjectByName('backboneSpheres').onBeforeRender(gpu, f.scene, camera)
    expect(f.source('a')).toBe(source)
    expect(slab.count).toBe(2)
    expect(f.api.getInstanceGeometry).not.toHaveBeenCalled()
    f.renderer.dispose()
  })

  it('retains meshes for no-op, transform and visibility-only snapshots', async () => {
    const f = fixture()
    await f.renderer.rebuild(f.assembly())
    const before = f.source('a')
    await f.renderer.rebuild(f.update(i => i))
    await f.renderer.rebuild(f.update(i => i.id === 'a' ? { ...i, visible: false } : i))
    expect(f.source('a')).toBe(before)
    expect(f.api.getAssemblyGeometry).toHaveBeenCalledOnce()
    expect(f.api.getInstanceGeometry).not.toHaveBeenCalled()
    expect(f.renderer.getInstanceCenters().map(i => i.id)).not.toContain('a')
    await f.renderer.rebuild(f.update(i => i.id === 'a' ? { ...i, visible: true } : i))
    expect(f.renderer.getInstanceCenters().map(i => i.id)).toContain('a')
    f.renderer.dispose()
  })

  it('refetches an edited source individually while preserving unchanged sources', async () => {
    const f = fixture()
    await f.renderer.rebuild(f.assembly())
    const before = f.source('b')
    await f.renderer.rebuild(f.update(i => i.id === 'a' ? { ...i, geometrySourceKey: 'f:/a.nadoc:2:' } : i))
    expect(f.api.getAssemblyGeometry).toHaveBeenCalledOnce()
    expect(f.api.getInstanceGeometry).toHaveBeenCalledExactlyOnceWith('a')
    expect(f.source('b')).toBe(before)
    f.renderer.dispose()
  })

  it('marks invalidated copies without starting requests and coalesces the eventual rebuild', async () => {
    const f = fixture()
    await f.renderer.rebuild(f.assembly())
    f.renderer.invalidateInstance('a')
    f.renderer.invalidateInstance('a')
    expect(f.api.getInstanceGeometry).not.toHaveBeenCalled()
    const first = f.renderer.rebuild(f.assembly())
    const second = f.renderer.rebuild(f.assembly())
    expect(second).toBe(first)
    await first
    expect(f.api.getInstanceGeometry).toHaveBeenCalledExactlyOnceWith('a')
    f.renderer.dispose()
  })

  it('refetches sources without an authoritative live version instead of trusting saved hashes', async () => {
    const f = fixture()
    f.update(i => ({ ...i, geometrySourceKey: `f:${i.id}.nadoc:saved-sha` }))
    await f.renderer.rebuild(f.assembly())
    await f.renderer.rebuild(f.update(i => i))
    expect(f.api.getAssemblyGeometry).toHaveBeenCalledTimes(2)
    f.renderer.dispose()
  })

  it('does not resurrect source meshes after disposal during a geometry request', async () => {
    const f = fixture()
    let resolve
    f.api.getAssemblyGeometry.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const building = f.renderer.rebuild(f.assembly())
    await Promise.resolve()
    f.renderer.dispose()
    resolve({ instances: {} })
    await building
    expect(f.scene.children.some(o => o.userData.sharedSource)).toBe(false)
    expect(f.api.getInstanceGeometry).not.toHaveBeenCalled()
  })

  it('refreshes linkers for the current transform-only snapshot without rebuilding sources', async () => {
    const f = fixture()
    await f.renderer.rebuild(f.assembly())
    const moved = f.update(i => i)
    moved.assembly_helices = [{ id: 'linker' }]
    await f.renderer.rebuildLinkers(moved)
    expect(f.api.getLinkerGeometry).toHaveBeenCalledOnce()
    expect(f.api.getAssemblyGeometry).toHaveBeenCalledOnce()
    f.renderer.dispose()
    await f.renderer.rebuildLinkers(moved)
    expect(f.api.getLinkerGeometry).toHaveBeenCalledOnce()
  })

  it('keeps existing meshes on fetch failure and retries the changed version', async () => {
    const f = fixture()
    await f.renderer.rebuild(f.assembly())
    const old = f.source('a')
    const changed = f.update(i => i.id === 'a' ? { ...i, geometrySourceKey: 'f:/a.nadoc:2:' } : i)
    f.api.getInstanceGeometry.mockResolvedValueOnce(null)
    await expect(f.renderer.rebuild(changed)).rejects.toThrow('Could not load assembly geometry for a')
    expect(f.source('a')).toBe(old)
    await f.renderer.rebuild(changed)
    expect(f.api.getInstanceGeometry).toHaveBeenCalledTimes(2)
    expect(f.source('a')).not.toBe(old)
    expect(f.renderer.getInstanceDesign('a', 'f:/a.nadoc:1:')).toBeNull()
    expect(f.renderer.getInstanceDesign('a', 'f:/a.nadoc:2:')).not.toBeNull()
    f.renderer.dispose()
  })
})

// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { captureEMParticles, initEMAnalysis } from './em_analysis.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const sphere = { id: 'a', kind: 'gold_nanosphere', diameter_nm: 20, visible: false, pos: new THREE.Vector3(1, 2, 3) }
const np = { getQuenchingParticles: () => [sphere] }
let feature
const result = { origin_nm:[0,0,0], basis:[[1,0,0],[0,1,0],[0,0,1]], shape: [25, 25, 25], gap_nm: null, peak_intensity: 3, elapsed_seconds: .5,
  multipole_order: 6, probe_relative_error: .001, upper_nm: [20,20,20], lower_nm: [-20,-20,-20],
  polarization_world: [1,0,0], propagation_world: [0,0,1] }
afterEach(() => { feature?.dispose(); document.body.innerHTML = ''; localStorage.clear(); vi.restoreAllMocks() })

describe('EM analysis snapshot and lifecycle', () => {
  it('includes hidden gold with live coordinates and applies assembly transforms', () => {
    expect(captureEMParticles({ state: {}, nanoparticleSubsystem: np })).toEqual([{ id:'a', diameter_nm:20, center_nm:[1,2,3] }])
    const particles = captureEMParticles({ state: { assemblyActive:true, currentAssembly:{instances:[{id:'part'}]} },
      assemblyRenderer: { getInstanceDesign: () => ({nanoparticles:[sphere]}), getLiveTransform: () => new THREE.Matrix4().makeTranslation(10,20,30) } })
    expect(particles[0].center_nm).toEqual([10,20,30])
    expect(particles[0].id).toBe('part:a')
  })
  it('rejects unknown optical materials', () => {
    expect(() => captureEMParticles({ state:{}, nanoparticleSubsystem:{getQuenchingParticles:()=>[{...sphere,kind:'quantum_dot'}]} })).toThrow(/materials/)
  })
  it('renders results, supports slices, and removes the scene overlay on close', async () => {
    const store = createMockStore({ currentDesign:{id:'d'} }), original = store.getState()
    const overlay = { show:vi.fn(), clear:vi.fn(), dispose:vi.fn() }, remove = vi.fn()
    feature = initEMAnalysis({ scene:{}, store, nanoparticleSubsystem:np, api:{_request:vi.fn().mockResolvedValue(result)},
      overlayFactory:()=>overlay, addFrameCallback:vi.fn(), removeFrameCallback:remove })
    feature.open(); document.querySelector('[data-run]').click()
    await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
    expect(document.querySelector('[data-status]').textContent).toContain('3.00×')
    const select = document.querySelector('[data-mode]'); select.value='xy'; select.dispatchEvent(new Event('input'))
    expect(overlay.show.mock.lastCall[1].mode).toBe('xy')
    feature.close(); expect(overlay.dispose).toHaveBeenCalled(); expect(remove).toHaveBeenCalled()
    expect(store.getState()).toBe(original)
    expect(document.querySelector('#em-analysis-panel')).toBeNull()
  })
  it('discards a result arriving after cancellation', async () => {
    let resolve
    const overlay = { show:vi.fn(), clear:vi.fn(), dispose:vi.fn() }
    feature = initEMAnalysis({ scene:{}, store:createMockStore({}), nanoparticleSubsystem:np,
      api:{_request:()=>new Promise(r=>{resolve=r})}, overlayFactory:()=>overlay })
    feature.open(); document.querySelector('[data-run]').click(); document.querySelector('[data-cancel]').click()
    resolve(result); await Promise.resolve(); expect(overlay.show).not.toHaveBeenCalled()
    expect(document.querySelector('[data-status]').textContent).toBe('Cancelled.')
  })
})

it('invalidates a completed map when a live particle moves', async () => {
  let frame
  const moving = {...sphere, pos:sphere.pos.clone()}
  const overlay = {show:vi.fn(),clear:vi.fn(),dispose:vi.fn()}
  feature = initEMAnalysis({scene:{},store:createMockStore({}),nanoparticleSubsystem:{getQuenchingParticles:()=>[moving]},
    api:{_request:vi.fn().mockResolvedValue(result)},overlayFactory:()=>overlay,
    addFrameCallback:fn=>{frame=fn},removeFrameCallback:vi.fn()})
  feature.open();document.querySelector('[data-run]').click()
  await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
  moving.pos.x += 1
  vi.spyOn(performance,'now').mockReturnValue(100000)
  frame()
  expect(document.querySelector('[data-status]').textContent).toContain('configuration changed')
  expect(document.querySelector('[data-download]').disabled).toBe(true)
  expect(overlay.clear).toHaveBeenCalledTimes(2)
})

it('uses full optical coverage independent of conjugate count and invalidates shell/solver edits', async () => {
  const request = vi.fn().mockResolvedValue(result)
  feature = initEMAnalysis({ scene:{}, store:createMockStore({}), nanoparticleSubsystem:np,
    api:{_request:request}, overlayFactory:()=>({show:vi.fn(),clear:vi.fn(),dispose:vi.fn()}) })
  feature.open(); document.querySelector('[data-run]').click()
  await vi.waitFor(()=>expect(request).toHaveBeenCalled())
  expect(request.mock.calls[0][2]).toMatchObject({ sampling:'field_adaptive', solver:'multipole', shell:{model:'ssdna_wlc',oligo_length_nt:20,refractive_index:1.7} })
  await vi.waitFor(()=>expect(document.querySelector('[data-download]').disabled).toBe(false))
  const sampling = document.querySelector('[data-sampling]')
  sampling.value='uniform'; sampling.dispatchEvent(new Event('change'))
  expect(document.querySelector('[data-download]').disabled).toBe(true)
  const shell = document.querySelector('[data-shell]')
  shell.value='manual'; shell.dispatchEvent(new Event('change'))
  expect(document.querySelector('[data-download]').disabled).toBe(true)
  expect(document.querySelector('[data-thickness]').disabled).toBe(false)
  expect(document.querySelector('[data-oligo-length]').disabled).toBe(true)
  document.querySelector('[data-thickness]').value='0.5'
  const solver = document.querySelector('[data-solver]')
  solver.value='multipole_reference'; solver.dispatchEvent(new Event('change'))
  document.querySelector('[data-run]').click()
  await vi.waitFor(()=>expect(request).toHaveBeenCalledTimes(2))
  expect(request.mock.calls[1][2]).toMatchObject({sampling:'uniform',solver:'multipole_reference',shell:{model:'manual',thickness_nm:.5}})
})

it('preserves solver rejection details and only removes the coating on explicit recovery', async () => {
  const message = 'DNA dielectric shells overlap or touch. This pair has a 4.55 nm metal gap, but its shells require 13.65 nm.'
  const overlay = {show:vi.fn(),clear:vi.fn(),dispose:vi.fn()}
  const request = vi.fn().mockImplementationOnce(async (_method, _path, _body, options) => {
    options.onError(422, message)
    return null
  }).mockResolvedValue(result)
  feature = initEMAnalysis({scene:{},store:createMockStore({}),nanoparticleSubsystem:np,
    api:{_request:request},overlayFactory:()=>overlay})
  feature.open(); document.querySelector('[data-run]').click()
  await vi.waitFor(()=>expect(document.querySelector('[data-status]').textContent).toBe(message))
  expect(document.querySelector('[data-shell]').value).toBe('ssdna_wlc')
  expect(document.querySelector('[data-download]').disabled).toBe(true)
  expect(overlay.show).not.toHaveBeenCalled()
  expect(request).toHaveBeenCalledTimes(1)
  const recovery = document.querySelector('[data-bare-retry]')
  expect(recovery.hidden).toBe(false)
  recovery.click()
  await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
  expect(request.mock.calls[1][2].shell.model).toBe('none')
  expect(document.querySelector('[data-shell]').value).toBe('none')
  expect(recovery.hidden).toBe(true)
})

it('shows other API errors without offering an unrelated coating workaround', async () => {
  feature = initEMAnalysis({scene:{},store:createMockStore({}),nanoparticleSubsystem:np,
    api:{_request:async (_m,_p,_b,options)=>{options.onError(504,'EM analysis exceeded the time limit.');return null}},
    overlayFactory:()=>({show:vi.fn(),clear:vi.fn(),dispose:vi.fn()})})
  feature.open(); document.querySelector('[data-run]').click()
  await vi.waitFor(()=>expect(document.querySelector('[data-status]').textContent).toBe('EM analysis exceeded the time limit.'))
  expect(document.querySelector('[data-bare-retry]').hidden).toBe(true)
  expect(document.querySelector('[data-run]').disabled).toBe(false)
})
it('resizes sampling dots immediately without recalculating or invalidating the map', async () => {
 const request = vi.fn().mockResolvedValue(result)
 const overlay = {show:vi.fn(), clear:vi.fn(), dispose:vi.fn()}
 feature = initEMAnalysis({scene:{},store:createMockStore({}),nanoparticleSubsystem:np,
  api:{_request:request},overlayFactory:()=>overlay})
 feature.open(); document.querySelector('[data-run]').click()
 await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
 const slider = document.querySelector('[data-dot-size]')
 slider.value='6.5'; slider.dispatchEvent(new Event('input'))
 expect(overlay.show.mock.lastCall[1].dotSize).toBe(6.5)
 expect(document.querySelector('[data-dot-size-value]').textContent).toBe('6.5 px')
 expect(document.querySelector('[data-download]').disabled).toBe(false)
 expect(request).toHaveBeenCalledTimes(1)
})

it('retains optical and display settings after closing and reopening the popup', () => {
  feature = initEMAnalysis({scene:{},store:createMockStore({}),nanoparticleSubsystem:np,api:{},
    overlayFactory:()=>({clear:vi.fn(),dispose:vi.fn(),show:vi.fn()})})
  feature.open()
  document.querySelector('[data-shell]').value = 'none'
  document.querySelector('[data-resolution]').value = '49'
  document.querySelector('[data-dot-size]').value = '6'
  feature.close(); feature.open()
  expect(document.querySelector('[data-shell]').value).toBe('none')
  expect(document.querySelector('[data-resolution]').value).toBe('49')
  expect(document.querySelector('[data-dot-size]').value).toBe('6')
})

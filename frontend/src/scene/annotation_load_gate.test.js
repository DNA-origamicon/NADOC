import { afterEach, expect, it, vi } from 'vitest'
import { createAnnotationLoadGate } from './annotation_load_gate.js'
let gate
const setup = () => {
  let state = { currentDesign: { id: 'a', strands: [{ domains: [{}] }] }, currentGeometry: null }
  const frames = []
  gate = createAnnotationLoadGate({ store: { getState: () => state }, document,
    requestFrame: fn => { frames.push(fn); return frames.length }, cancelFrame: vi.fn() })
  return { state, frame: () => frames.shift()?.(), switchTo: value => { state = value } }
}
afterEach(() => { gate?.dispose(); document.body.replaceChildren() })
it('hides notes until geometry, opening UI, and a model paint have completed', () => {
  const f = setup()
  expect(gate.isReady()).toBe(false)
  document.body.innerHTML = '<div id="welcome-screen"></div><div id="file-load-progress" class="visible"></div>'
  f.state.currentGeometry = [{}]
  expect(gate.isReady()).toBe(false)
  document.getElementById('welcome-screen').classList.add('hidden')
  expect(gate.isReady()).toBe(false)
  document.getElementById('file-load-progress').classList.remove('visible')
  expect(gate.isReady()).toBe(false)
  f.frame(); expect(gate.isReady()).toBe(false)
  f.frame(); expect(gate.isReady()).toBe(true)
})
it('a stale frame cannot reveal notes from a newly opened document', () => {
  const f = setup(); f.state.currentGeometry = [{}]
  gate.isReady(); f.frame()
  f.switchTo({ currentDesign: { id: 'b', strands: [{ domains: [{}] }] }, currentGeometry: null })
  expect(gate.isReady()).toBe(false)
  f.frame(); expect(gate.isReady()).toBe(false)
})
it('waits for the actual assembly renderer and ignores a stale completion', async () => {
  const frames = []; let resolve
  let state = { assemblyActive: true, currentAssembly: { id: 'assembly', instances: [{}] } }
  const renderer = { whenReady: vi.fn(() => new Promise(done => { resolve = done })) }
  gate = createAnnotationLoadGate({ store: { getState: () => state }, document, getAssemblyRenderer: () => renderer,
    requestFrame: fn => { frames.push(fn); return frames.length }, cancelFrame: vi.fn() })
  expect(gate.isReady()).toBe(false)
  resolve(); await Promise.resolve()
  expect(gate.isReady()).toBe(false)
  frames.shift()(); frames.shift()(); expect(gate.isReady()).toBe(true)
  state = { ...state, currentAssembly: { id: 'other', instances: [{}] } }
  expect(gate.isReady()).toBe(false)
  gate.dispose(); resolve(); await Promise.resolve()
  expect(gate.isReady()).toBe(false)
})

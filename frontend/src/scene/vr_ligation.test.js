import { describe, it, expect, vi } from 'vitest'
import { createVRLigation } from './vr_ligation.js'

function fixture() {
  const end = (id, role, bp) => ({ strand_id: id, helix_id: 'h', domain_index: 0,
    direction: 'FORWARD', bp_index: bp, is_three_prime: role === 3, is_five_prime: role === 5,
    backbone_position: [0,0,bp], axis_tangent: [0,0,1] })
  let state = { currentDesign: { id: 'd', helices: [], strands: [
    { id: 'a', domains: [{ helix_id: 'h', direction: 'FORWARD', start_bp: 0, end_bp: 5 }] },
    { id: 'b', domains: [{ helix_id: 'h', direction: 'FORWARD', start_bp: 6, end_bp: 10 }] },
  ] }, currentGeometry: [end('a', 3, 5), end('b', 5, 6), end('a', 5, 0), end('b', 3, 10)] }
  const api = { sendVRLigationEnds: vi.fn(async () => ({})), forcedLigation: vi.fn(async () => ({})),
    refreshNativeVRScene: vi.fn(async () => ({ published: true })), currentRevisionWatermark: () => 8 }
  const tool = createVRLigation({ getState: () => state, api })
  return { tool, api, get state() { return state }, setState: s => { state = s } }
}

describe('VR forced ligation', () => {
  it('maps either pickup polarity onto one canonical forced-ligation request and refresh', async () => {
    for (const [source, target] of [[0,1],[1,0]]) {
      const h = fixture(), version = h.tool.catalog().version
      expect(await h.tool.commit({ version, source, target })).toBe(true)
      expect(h.api.forcedLigation).toHaveBeenCalledExactlyOnceWith('a', 'b', false, { onCommitted: expect.any(Function), deferGeometry: true })
      expect(h.api.refreshNativeVRScene).toHaveBeenCalledExactlyOnceWith({ expected_design_id: 'd', expected_revision: 8 })
      expect(await h.tool.commit({ version, source, target })).toBe(false)
      expect(h.api.forcedLigation).toHaveBeenCalledTimes(1)
    }
  })
  it('refuses same strand, same polarity, stale topology, ambiguous and nonterminal picks', async () => {
    const h = fixture(), version = h.tool.catalog().version
    for (const [source,target] of [[0,2],[0,3],[0,0],[0,99]]) {
      expect(await h.tool.commit({ version: h.tool.catalog().version, source, target })).toBe(false)
    }
    h.setState({ ...h.state, currentDesign: { ...h.state.currentDesign } })
    expect(await h.tool.commit({ version, source: 0, target: 1 })).toBe(false)
    h.setState({ ...h.state, currentGeometry: h.state.currentGeometry.map(n => ({ ...n, is_five_prime: true, is_three_prime: true })) })
    expect(h.tool.catalog().ends).toEqual([])
    expect(h.api.forcedLigation).not.toHaveBeenCalled()
  })
  it('serializes held releases and publishes fresh terminal state after failure', async () => {
    const h = fixture()
    let finish
    h.api.forcedLigation.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const event = { version: h.tool.catalog().version, source: 0, target: 1 }
    const pending = h.tool.commit(event)
    expect(await h.tool.commit(event)).toBe(false)
    finish(null)
    expect(await pending).toBe(false)
    expect(h.api.sendVRLigationEnds.mock.calls.at(-1)[0].status).toBe('failed')
    expect(h.api.refreshNativeVRScene).not.toHaveBeenCalled()
  })
})


describe('wheel nick and history', () => {
  it('uses ordered backbone neighbors, ignores existing breaks, and sends the 3-prime-side coordinate', async () => {
    const h=fixture(), n=h.state.currentGeometry[0]
    h.setState({...h.state,currentGeometry:[{...n,bp_index:3,is_three_prime:false},{...n,bp_index:4,is_three_prime:false},n]})
    h.api.addNick=vi.fn(async()=>({}))
    const c=h.tool.catalog()
    expect(c.bonds).toHaveLength(2)
    expect(await h.tool.commit({action:'nick',version:c.version,source:0,target:0})).toBe(true)
    expect(h.api.addNick).toHaveBeenCalledExactlyOnceWith({helixId:'h',bpIndex:3,direction:'FORWARD'}, { onCommitted: expect.any(Function), deferGeometry: true })
    expect(await h.tool.commit({action:'nick',version:c.version,source:0,target:0})).toBe(false)
  })
  it('orders reverse bonds toward decreasing bp and excludes loop-copy and ambiguous coordinates', () => {
    const h=fixture(), template=h.state.currentGeometry[0]
    const n=bp=>({...template,bp_index:bp,direction:'REVERSE',is_three_prime:bp===0,is_five_prime:bp===2})
    h.setState({...h.state,currentGeometry:[n(0),n(2),n(1)]})
    expect(h.tool.catalog().nickArgs.map(n=>n.bpIndex)).toEqual([2,1])
    h.setState({...h.state,currentGeometry:[n(2),{...n(2),copy_k:1},n(1)]})
    expect(h.tool.catalog().nickArgs.map(n=>n.bpIndex)).toEqual([2])
    h.setState({...h.state,currentGeometry:[n(2),n(1),{...n(2),strand_id:'b'}]})
    expect(h.tool.catalog().bonds).toHaveLength(0)
  })
  it('serializes undo/redo, refreshes scene, rejects stale and assembly requests', async () => {
    const h=fixture();h.api.undo=vi.fn(async()=>({}));h.api.redo=vi.fn(async()=>({}))
    for(const action of ['undo','redo']) {
      const version=h.tool.catalog().version
      expect(await h.tool.commit({action,version,source:0,target:0})).toBe(true)
      expect(h.api[action]).toHaveBeenCalledTimes(1)
      expect(await h.tool.commit({action,version,source:0,target:0})).toBe(false)
    }
    h.setState({...h.state,assemblyActive:true})
    expect(await h.tool.commit({action:'undo',version:h.tool.catalog().version})).toBe(false)
    expect(h.api.undo).toHaveBeenCalledTimes(1)
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledTimes(2)
  })
})

it('exports the committed revision while desktop synchronization is still pending', async () => {
  const h = fixture()
  let finishSync
  h.api.forcedLigation.mockImplementation(async (a, b, seam, { onCommitted }) => {
    onCommitted({ design: { id: 'committed' }, revision: 9 })
    return new Promise(resolve => { finishSync = resolve })
  })
  const done = h.tool.commit({ version: h.tool.catalog().version, source: 0, target: 1 })
  expect(h.api.refreshNativeVRScene).toHaveBeenCalledExactlyOnceWith({ expected_design_id: 'committed', expected_revision: 9 })
  expect(h.tool.busy).toBe(true)
  finishSync({})
  expect(await done).toBe(true)
  expect(h.api.refreshNativeVRScene).toHaveBeenCalledOnce()
})

it('retries a failed acknowledgement publication without repeating the edit', async () => {
  const h = fixture()
  h.api.sendVRLigationEnds.mockResolvedValueOnce(null)
  const event = { version: h.tool.catalog().version, source: 0, target: 1 }
  expect(await h.tool.commit(event)).toBe(true)
  const feedback = h.api.sendVRLigationEnds.mock.calls[0][0]
  await h.tool.publish()
  expect(h.api.sendVRLigationEnds).toHaveBeenCalledTimes(2)
  expect(h.api.sendVRLigationEnds.mock.calls[1][0]).toEqual(feedback)
  await h.tool.publish()
  expect(h.api.sendVRLigationEnds).toHaveBeenCalledTimes(2)
  expect(h.api.forcedLigation).toHaveBeenCalledOnce()
})

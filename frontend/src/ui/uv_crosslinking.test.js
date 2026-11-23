// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { filterUvPairs, uvColorPayload, initUvCrosslinking } from './uv_crosslinking.js'

const result = {
  ready: true, complete: true, n_sampled_frames: 10, n_total_frames: 10,
  sites: [0,1,2].map(i=>({ id:`D:${i}`,label:`Base ${i}`,display_key:`h:${i}:FORWARD` })),
  pairs: [
    { a:0,b:1,same_strand:false,chemistry:'TC',opportunity:.2,min_distance_ang:3.5 },
    { a:0,b:2,same_strand:true,chemistry:'TT',opportunity:.1,min_distance_ang:4 },
  ], note: 'Geometric opportunity, not yield.',
}
afterEach(()=>{ vi.useRealTimers();document.body.replaceChildren() })
describe('UV pair filtering and colors',()=>{
  it('defaults to both strand classes and all pyrimidines',()=>{
    expect(filterUvPairs(result)).toHaveLength(2)
    expect(filterUvPairs(result,{ttOnly:true})).toEqual([result.pairs[1]])
    expect(filterUvPairs(result,{intrastrand:false})).toEqual([result.pairs[0]])
    expect(filterUvPairs(result,{interstrand:false,intrastrand:false})).toEqual([])
  })
  it('shows strongest incident opportunity without renormalizing filters',()=>{
    expect(uvColorPayload(result,{}).base_likelihoods.map(b=>b.relative_likelihood)).toEqual([.2,.2,.1])
    expect(uvColorPayload(result,{ttOnly:true}).base_likelihoods.map(b=>b.relative_likelihood)).toEqual([.1,0,.1])
  })
})

function setup(fetchResult = async()=>result) {
  document.body.innerHTML = ['photoproduct-toggle','uv-interstrand','uv-intrastrand','uv-tt-only'].map(id=>`<input id="md-jobs-${id}" type="checkbox">`).join('')
    + ['uv-options','photoproduct-status','photoproduct-progress','photoproduct-progress-fill','photoproduct-progress-label'].map(id=>`<div id="md-jobs-${id}"></div>`).join('')
  for (const id of ['uv-interstrand','uv-intrastrand']) document.getElementById(`md-jobs-${id}`).checked=true
  const api={getMdPhotoproductLikelihood:vi.fn(fetchResult),getMdPhotoproductProgress:vi.fn(async()=>({})),cancelMdAnalysis:vi.fn(async()=>({}))}
  const display={displayPhotoproduct:vi.fn(()=>({ok:true})),recolorPhotoproduct:vi.fn(),mode:()=> 'photoproduct',stopAndRestore:vi.fn()}
  const scale={show:vi.fn(),hide:vi.fn()}
  const c=initUvCrosslinking({api,getJobId:()=> 'job',getDisplay:()=>display,getScale:()=>scale,activate:()=>true})
  const toggle=document.getElementById('md-jobs-photoproduct-toggle')
  toggle.checked=true
  return {c,api,display,scale,toggle}
}
it('filters and scale edits recolor locally, retaining zero-valued sites',async()=>{
  const {c,api,display,scale}=setup()
  await c.refresh()
  document.getElementById('md-jobs-uv-tt-only').click()
  expect(api.getMdPhotoproductLikelihood).toHaveBeenCalledTimes(1)
  expect(display.displayPhotoproduct.mock.lastCall[1].n_candidates).toBe(1)
  scale.show.mock.lastCall[0].onRecolor(0,.3,'turbo')
  expect(display.recolorPhotoproduct).toHaveBeenLastCalledWith(0,.3,'turbo')
  document.getElementById('md-jobs-uv-interstrand').click()
  expect(display.recolorPhotoproduct).toHaveBeenLastCalledWith(0,.3,'turbo')
  c.dispose()
})
it('pauses on off and ignores stale responses after rapid reactivation',async()=>{
  let resolve
  const {c,api,toggle,display}=setup(()=>new Promise(r=>{resolve=r}))
  const pending=c.refresh()
  await Promise.resolve()
  c.off()
  resolve(result)
  await pending
  expect(display.displayPhotoproduct).not.toHaveBeenCalled()
  expect(api.cancelMdAnalysis).toHaveBeenCalledWith('job','photoproduct')
  api.getMdPhotoproductLikelihood.mockResolvedValue(result)
  toggle.checked=true
  await c.refresh()
  expect(display.displayPhotoproduct).toHaveBeenCalledTimes(1)
  c.dispose()
})

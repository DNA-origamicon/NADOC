import { describe, expect, it } from 'vitest'
import { discoverConnectivity, graphProjection, nanoparticleSites } from './connectivity_graph.js'
const sites = xyz => xyz.map((center, i) => ({ id: `p${i}`, label: `NP ${i+1}`, center, radius: 5 }))
const psi = sites([[55.793852,.829224,24.664174],[15,0,0],[73.711817,1.455097,-33.809933],[24.412518,0,22.657096]])
function checkTree(c, particles) {
  expect(c.edges).toHaveLength(c.nodes.length-1)
  const reached = new Set([c.nodes[0].id])
  for(let i=0;i<c.nodes.length;i++) for(const e of c.edges) if(reached.has(e.source)||reached.has(e.target)){reached.add(e.source);reached.add(e.target)}
  expect(reached.size).toBe(c.nodes.length)
  expect(c.nodes.filter(n=>n.kind==='particle').map(n=>n.particleId).sort()).toEqual(particles.map(p=>p.id).sort())
  for(const n of c.nodes.filter(n=>n.kind==='split')) {
    expect(n.motif).toBe('shared-section-split'); expect(n.daughterHB).toHaveLength(2)
    expect(n.daughterHB.reduce((a,b)=>a+b,0)).toBe(n.sectionHB)
    expect(c.edges.filter(e=>e.source===n.id||e.target===n.id)).toHaveLength(3)
  }
  for(const e of c.edges){expect(e.controlPoints.flat().every(Number.isFinite)).toBe(true);expect(e.lengthNm).toBeGreaterThan(0)}
}
describe('bundle connectivity grammar',()=>{
  it('discovers the distant stem in NP_gen_tests without mutating particle positions',()=>{
    const before=structuredClone(psi), r=discoverConnectivity(psi), best=r.candidates[0]
    expect(best.rootId).toBe('p2');expect(best.warnings).toEqual([])
    expect(best.nodes.filter(n=>n.kind==='split').map(n=>n.sectionHB)).toEqual([18,12])
    expect(best.estimatedNt).toBeLessThan(7249)
    expect(new Set(r.candidates.map(c=>c.topology)).size).toBeGreaterThan(1)
    r.candidates.forEach(c=>checkTree(c,psi));expect(psi).toEqual(before)
  })
  it('discovers a common 12HB stem splitting at both ends for a tall rectangle',()=>{
    const ps=sites([[-20,0,-40],[20,0,-40],[-20,0,40],[20,0,40]]), c=discoverConnectivity(ps).candidates[0]
    expect(c.family).toBe('opposed-splits');expect(c.edges.map(e=>e.hb).sort((a,b)=>a-b)).toEqual([6,6,6,6,12])
    expect(c.warnings).toEqual([]);checkTree(c,ps)
  })
  it('connects pairs, triangles, and nonplanar arrangements as trees',()=>{
    for(const xyz of [[[0,0,0],[50,0,0]],[[0,0,0],[50,0,0],[25,0,45]],[[0,0,0],[50,0,0],[25,40,0],[25,10,50]]]){
      const ps=sites(xyz),r=discoverConnectivity(ps);expect(r.candidates.length).toBeGreaterThan(0);r.candidates.forEach(c=>checkTree(c,ps))
    }
  })
  it('flags obstructed and over-budget paths',()=>{
    expect(discoverConnectivity(sites([[0,0,0],[30,0,0],[60,0,0]])).candidates[0].warnings.join(' ')).toContain('intersects')
    const c=discoverConnectivity(sites([[0,0,0],[1000,0,0]])).candidates[0]
    expect(c.budget).toBeNull();expect(c.warnings.join(' ')).toContain('8064')
  })
  it('is invariant under rigid transforms and projects collinear sites',()=>{
    const moved=psi.map(p=>({...p,center:[p.center[2]+100,p.center[0]-400,p.center[1]+37]}))
    expect(discoverConnectivity(moved).candidates[0].estimatedNt).toBe(discoverConnectivity(psi).candidates[0].estimatedNt)
    const ps=sites([[0,0,0],[50,0,0]]);expect(ps.map(p=>graphProjection(ps)(p.center)).flat().every(Number.isFinite)).toBe(true)
  })
  it('handles missing, invalid, overlapping and excessive inputs',()=>{
    for(const ps of [[],sites([[0,0,0]]),sites([[0,0,0],[1,0,0]]),sites([[0,0,0],[NaN,0,0]]),sites(Array.from({length:9},(_,i)=>[i*30,0,0]))])expect(discoverConnectivity(ps).candidates).toEqual([])
    expect(nanoparticleSites(null)).toEqual([])
  })
})

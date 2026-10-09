import { describe, expect, it } from 'vitest'
import { discoverConnectivity } from './connectivity_graph.js'
import { buildOrigamiPathPreview, previewSection } from './origami_path_preview.js'
const sites = xyz => xyz.map((center,i)=>({id:String(i),label:String(i),center,radius:5}))
const psi = sites([[55.793852,.829224,24.664174],[15,0,0],[73.711817,1.455097,-33.809933],[24.412518,0,22.657096]])
const tallI = sites([[-20,0,-40],[20,0,-40],[-20,0,40],[20,0,40]])
const distance=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i]))
function checkJoins(preview,candidate) {
  for(const j of preview.junctions) {
    const trunk=preview.paths.filter(p=>p.edgeId===j.trunkEdgeId && (p.kind==='bundle'||p.junctionId===j.id)).map(p=>j.atStart?p.points[0]:p.points.at(-1))
    const branches=j.childEdgeIds.flatMap(id=>{
      const edge=candidate.edges.find(e=>e.id===id)
      return preview.paths.filter(p=>p.edgeId===id&&p.kind==='bundle').map(p=>edge.source===j.id?p.points[0]:p.points.at(-1))
    })
    expect(trunk).toHaveLength(preview.hb*2);expect(branches).toHaveLength(preview.hb*2)
    // Compare actual lane endpoints, not just bundle centerlines.
    for(const p of trunk) expect(Math.min(...branches.map(q=>distance(p,q)))).toBeLessThan(1e-5)
  }
}
describe('origami helix path preview',()=>{
  it.each([6,12,18,24])('uses uniform %iHB bodies and twice that count only at splits',hb=>{
    for(const ps of [psi,tallI]) {
      const candidate=discoverConnectivity(ps).candidates[0],before=JSON.stringify(candidate)
      const p=buildOrigamiPathPreview(candidate,{hb})
      expect(p.edges.every(e=>e.hb===hb)).toBe(true)
      expect(p.paths.filter(p=>p.kind==='bundle')).toHaveLength(candidate.edges.length*hb)
      expect(p.paths.filter(p=>p.kind==='junction-extension')).toHaveLength(p.junctions.length*hb)
      expect(p.junctions.every(j=>j.hb===hb*2)).toBe(true)
      expect(p.paths.flatMap(p=>p.points.flat()).every(Number.isFinite)).toBe(true)
      expect(p.estimatedNt).toBe(p.paths.reduce((s,p)=>s+Math.ceil(p.lengthNm/.34),0))
      expect(p.routed).toBe(false);expect(JSON.stringify(candidate)).toBe(before)
      checkJoins(p,candidate)
    }
  })
  it('keeps a two-particle path uniform and handles nonplanar branches',()=>{
    const pair=discoverConnectivity(sites([[0,0,0],[50,0,0]])).candidates[0],p=buildOrigamiPathPreview(pair)
    expect(p.paths).toHaveLength(6);expect(p.junctions).toHaveLength(0)
    const spatial=discoverConnectivity(sites([[0,0,0],[50,0,0],[20,45,0],[10,10,60]])).candidates[0]
    checkJoins(buildOrigamiPathPreview(spatial),spatial)
  })
  it('uses honeycomb spacing and includes local reinforcement in its estimate',()=>{
    const s=previewSection(6)
    expect(Math.min(...s.cells.flatMap((p,i)=>s.cells.slice(i+1).map(q=>Math.hypot(p.x-q.x,p.y-q.y))))).toBeCloseTo(2.25)
    const c=discoverConnectivity(psi).candidates[0],p=buildOrigamiPathPreview(c)
    expect(p.estimatedNt).toBeGreaterThan(p.paths.filter(p=>p.kind==='bundle').reduce((s,p)=>s+p.estimatedNt,0))
    const huge=buildOrigamiPathPreview(discoverConnectivity(sites([[0,0,0],[1000,0,0]])).candidates[0])
    expect(huge.warnings.join(' ')).toContain('8064')
    expect(()=>previewSection(7)).toThrow()
  })
})

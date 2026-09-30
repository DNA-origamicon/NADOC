import { describe,it,expect } from 'vitest'
import { bindSurfaceMotion } from './surface_motion.js'
const keys=[['h',0,'FORWARD'],['h',1,'FORWARD']]
const rest=[0,0,0,1,0,0,0,0,1, 2,0,0,1,0,0,0,0,1]
const mesh={vertices:[0,1,0, 2,1,0, 1,0,1],faces:[0,1,2]}
describe('surface motion',()=>{
  it('preserves the reference and follows rigid translation without mutating saved meshes',()=>{
    const binding=bindSurfaceMotion(mesh,keys,rest)
    const original=structuredClone(mesh)
    Array.from(binding.deform(rest)).forEach((v,i)=>expect(v).toBeCloseTo(mesh.vertices[i],5))
    const moved=rest.map((v,i)=>i%9<3?v+3:v)
    Array.from(binding.deform(moved)).forEach((v,i)=>expect(v).toBeCloseTo(mesh.vertices[i]+3,5))
    expect(mesh).toEqual(original)
  })
  it('rotates local detail with nucleotide frames',()=>{
    const binding=bindSurfaceMotion(mesh,keys,rest)
    const rotated=[]
    for(let i=0;i<rest.length;i+=3) rotated.push(-rest[i+1],rest[i],rest[i+2])
    const out=binding.deform(rotated)
    for(let i=0;i<out.length;i+=3) {
      expect(out[i]).toBeCloseTo(-mesh.vertices[i+1],5)
      expect(out[i+1]).toBeCloseTo(mesh.vertices[i],5)
      expect(out[i+2]).toBeCloseTo(mesh.vertices[i+2],5)
    }
  })
  it('does not drag an independent strand along with its nearby neighbour',()=>{
    const source={...mesh,vertex_strand_index_table:['A','B'],vertex_strand_index:[0,1,0],
      vertex_nuc_index_table:['h:0:FORWARD','h:1:FORWARD'],vertex_nuc_index:[0,1,0]}
    const binding=bindSurfaceMotion(source,keys,rest)
    const moved=[...rest];moved[9]+=10
    const out=binding.deform(moved)
    expect(out[0]).toBeCloseTo(mesh.vertices[0],5)
    expect(out[3]).toBeCloseTo(mesh.vertices[3]+10,5)
  })
  it('rejects absent trajectory anchors',()=>{
    expect(bindSurfaceMotion(mesh,[],[])).toBeNull()
  })
})

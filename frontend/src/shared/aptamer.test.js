import { describe, it, expect } from 'vitest'
import { nativeCorePaired, quadruplexMarkers } from './aptamer.js'
const helix = { id: 'g4', native_residues: Array.from({length:15},(_,bp_index)=>({bp_index})) }
const domain = (direction,start_bp,end_bp) => ({helix_id:'g4',direction,start_bp,end_bp})
const owner = {id:'aptamer',domains:[domain('FORWARD',-4,18)]}

describe('quadruplex annotation and authored pairing',()=>{
  it('marks the native core of an ordinary strand, including after ligation',()=>{
    const design = {helices:[helix],strands:[{...owner,id:'merged-staple',domains:[{helix_id:'normal'},...owner.domains]}]}
    expect(quadruplexMarkers(design)).toEqual([{helixId:'g4',strandId:'merged-staple',bp:7,paired:false}])
  })
  it('tail pairing preserves the fold; core pairing selects duplex and undo restores it',()=>{
    const design = {helices:[helix],strands:[owner,{id:'tail',domains:[domain('REVERSE',18,15)]}]}
    expect(nativeCorePaired(helix,design)).toBe(false)
    const partner = {id:'complement',domains:[domain('REVERSE',14,0)]}
    design.strands.push(partner)
    expect(quadruplexMarkers(design)[0].paired).toBe(true)
    partner.is_reference = true
    expect(nativeCorePaired(helix,design)).toBe(false)
    design.strands.pop()
    expect(quadruplexMarkers(design)[0].paired).toBe(false)
  })
  it('does not label a deleted core or an ordinary helix',()=>{
    expect(quadruplexMarkers({helices:[helix],strands:[]})).toEqual([])
    expect(quadruplexMarkers({helices:[{id:'ordinary'}],strands:[owner]})).toEqual([])
  })
})

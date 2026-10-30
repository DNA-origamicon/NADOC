import { describe, expect, it } from 'vitest'
import { buildAtomSerialIndex } from './atom_serial_index.js'

function check(serials, probes = []) {
  const expected = new Map(serials.map((s, i) => [s, i]))
  const actual = buildAtomSerialIndex({count:serials.length,serial:i=>serials[i]})
  for (const id of [...serials,...probes]) expect(actual.get(id)).toBe(expected.get(id))
  return actual
}

describe('atom serial identity lookup', () => {
  it('preserves sparse/reordered IDs, holes, duplicate precedence and row zero', () => {
    check([19,3,27,11,3], [0,4,18,28,'3',3.5,NaN,undefined,null])
  })
  it('handles negative IDs, signed zero and large numeric offsets without allocating by maximum ID', () => {
    check([-3,0,-0,-1], [-2,1,'0'])
    check([Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER-8], [0,Number.MAX_SAFE_INTEGER-4])
  })
  it('keeps arbitrary key types and SameValueZero behavior', () => {
    const object = {}, other = {}
    expect(check([NaN,Infinity,'3',3,object,null,undefined,NaN], [other,-Infinity])).toBeInstanceOf(Map)
  })
  it('uses bounded fallback for extremely sparse IDs and empty input', () => {
    expect(check([0,2**40], [1,2**40-1])).toBeInstanceOf(Map)
    expect(check([], [0,undefined])).toBeInstanceOf(Map)
  })
  it('matches Map across deterministic shuffled signed integer inputs', () => {
    let state=42
    const random=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state}
    const ids=Array.from({length:2000},()=>random()%3000-1500)
    check(ids,Array.from({length:4000},(_,i)=>i-2000))
  })
})

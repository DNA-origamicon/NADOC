import { describe, it, expect } from 'vitest'
import { resolveExtrudeSourcePlane } from './extrude_source_plane.js'
const h = (id, end) => ({ id, axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: end[0], y: end[1], z: end[2] } })
describe('canonical extrusion source plane', () => {
  it('recognizes imported axes and gives source metadata precedence over placement', () => {
    for (const [plane, axis] of [['XY', [0,0,7]], ['XZ', [0,-7,0]], ['YZ', [7,0,0]]]) {
      expect(resolveExtrudeSourcePlane({ helices: [h('imported',axis)] })).toEqual({plane,reason:'geometry'})
      expect(resolveExtrudeSourcePlane({ helices: [h(`h_${plane}_0_0`,[1,2,3])] })).toEqual({plane,reason:'geometry'})
    }
  })
  it('does not invent alignment for mixed or oblique geometry', () => {
    expect(resolveExtrudeSourcePlane({helices:[h('a',[0,0,7]),h('b',[7,0,0])]},'XZ')).toEqual({plane:'XZ',reason:'mixed'})
    expect(resolveExtrudeSourcePlane({helices:[h('a',[1,2,3])]})).toEqual({plane:'XY',reason:'unknown'})
    expect(resolveExtrudeSourcePlane(null,'invalid')).toEqual({plane:'XY',reason:'empty'})
  })
})

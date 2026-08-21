import { describe, expect, it } from 'vitest'

import {
  DEFAULT_EXPANDED_HELIX_SPACING_NM,
  expandedHelixOffsetFrame,
} from './expanded_helix_offsets.js'

const point = (x, y, z) => ({ x, y, z })

describe('authoritative Expanded Quick View helix offsets', () => {
  it('expands about the all-helix centroid at the native 5 nm spacing', () => {
    const frame = expandedHelixOffsetFrame({ helices: [
      { id: 'a', axis_start: point(-1, 0, 0), axis_end: point(-1, 0, 10) },
      { id: 'b', axis_start: point(1, 0, 0), axis_end: point(1, 0, 10) },
    ] })
    const delta = DEFAULT_EXPANDED_HELIX_SPACING_NM / 2.25 - 1
    expect(frame.axis).toBe('Z')
    expect(frame.offsets.get('a')).toEqual([-delta, 0, 0])
    expect(frame.offsets.get('b')).toEqual([delta, 0, 0])
  })

  it('preserves desktop Z/Y/X tie priority and rejects malformed inputs', () => {
    expect(expandedHelixOffsetFrame({ helices: [
      { id: 'diag', axis_start: point(0, 0, 0), axis_end: point(1, 1, 1) },
    ] }).axis).toBe('Z')
    expect(expandedHelixOffsetFrame({ helices: [] })).toBeNull()
    expect(expandedHelixOffsetFrame({ helices: [
      { id: 'bad', axis_start: point(0, 0, 0), axis_end: point(0, 0, NaN) },
    ] })).toBeNull()
  })
})

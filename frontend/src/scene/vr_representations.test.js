import { describe, it, expect } from 'vitest'
import { VR_REPRESENTATIONS, nativeRepresentation } from './vr_representations.js'

describe('native representation dispatch', () => {
  it.each(['hull-prism', 'cylinders', 'beads', 'full', 'surface', 'surface-detail', 'vdw', 'ballstick', 'stick', 'mrdna-coarse', 'mrdna-fine', 'oxdna'])('preserves desktop %s without substituting another style', rep => {
    expect(nativeRepresentation(rep)).toBe(rep)
    expect(VR_REPRESENTATIONS).toContain(rep)
  })
  it('falls back for invalid persisted values', () => {
    expect(nativeRepresentation(null)).toBe('full')
    expect(nativeRepresentation('unknown')).toBe('full')
  })
})

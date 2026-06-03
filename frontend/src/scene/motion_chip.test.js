import { describe, it, expect } from 'vitest'
import { motionChipStyle } from './motion_chip.js'

describe('motionChipStyle', () => {
  it('returns the palette for each known severity', () => {
    expect(motionChipStyle('ok')).toEqual({ fg: '#3fb950', bd: '#238636', bg: '#0d2316' })
    expect(motionChipStyle('warn').fg).toBe('#d29922')
    expect(motionChipStyle('locked').fg).toBe('#f85149')
    expect(motionChipStyle('info').fg).toBe('#8b949e')
  })
  it('falls back to info for unknown / missing severity', () => {
    expect(motionChipStyle('bogus')).toEqual(motionChipStyle('info'))
    expect(motionChipStyle()).toEqual(motionChipStyle('info'))
  })
})

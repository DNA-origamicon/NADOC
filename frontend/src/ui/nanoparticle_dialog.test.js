// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { parseNanoparticleDiameter } from './nanoparticle_dialog.js'

describe('parseNanoparticleDiameter', () => {
  it('accepts a positive finite diameter in nm', () => {
    expect(parseNanoparticleDiameter('12.5')).toBe(12.5)
  })
  it.each(['', '0', '-1', '1001', 'not-a-number'])(`rejects %s`, value => {
    expect(parseNanoparticleDiameter(value)).toBeNull()
  })
})

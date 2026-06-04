import { describe, it, expect } from 'vitest'
import { clientToNdc } from './ndc.js'

const rect = { left: 100, top: 50, width: 800, height: 400 }

describe('clientToNdc', () => {
  it('maps the rect centre to the origin', () => {
    expect(clientToNdc(500, 250, rect)).toEqual({ x: 0, y: 0 })
  })
  it('maps the top-left corner to (-1, +1) and bottom-right to (+1, -1)', () => {
    expect(clientToNdc(100, 50, rect)).toEqual({ x: -1, y: 1 })
    expect(clientToNdc(900, 450, rect)).toEqual({ x: 1, y: -1 })
  })
})

import { describe, it, expect } from 'vitest'
import {
  GUTTER, RULER_H, TOP_PAD, BP_W, LABEL_R,
  CELL_H, PAIR_Y, ROW_H, GROUP_GAP,
} from './layout.js'

// These constants were lifted verbatim out of pathview.js (TD-03/TD-14) so the
// 3D app's Domain Designer fork can share them without importing the 4977-LOC
// drawing module. They are geometry shared by TWO apps — this pins the values
// so a silent tweak in one app can't move the other.
describe('pathview layout constants', () => {
  it('pins the world-space drawing grid', () => {
    expect(GUTTER).toBe(40)
    expect(RULER_H).toBe(26)
    expect(TOP_PAD).toBe(18)
    expect(BP_W).toBe(10)
    expect(LABEL_R).toBe(16)
    expect(CELL_H).toBe(12)
    expect(ROW_H).toBe(40)
    expect(GROUP_GAP).toBe(28)
  })

  it('keeps PAIR_Y equal to CELL_H — fwd/rev cells are adjacent, not spaced', () => {
    expect(PAIR_Y).toBe(CELL_H)
  })

  it('leaves room for the ruler above the first helix row', () => {
    expect(RULER_H + TOP_PAD).toBeGreaterThan(LABEL_R * 2)
  })

  it('fits both track cells plus a gap inside one row', () => {
    expect(ROW_H).toBeGreaterThan(CELL_H + PAIR_Y)
  })
})

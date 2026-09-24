import { describe, it, expect, vi } from 'vitest'

import {
  HD_MARKER_COLOR,
  HD_MARKER_PX,
  drawHairpinDimerMarkers,
  hitHairpinDimerMarker,
  placeHairpinDimerMarkers,
} from './hairpin_dimer_markers.js'
import { BP_W, CELL_H, GUTTER } from './layout.js'

const rowMap = new Map([['h1', { fwdY: 100, revY: 112 }]])
const markers = [
  { strandId: 'fwd', label: 'OH-F', tooltip: 't1', level: 'critical', domains: [{ helix_id: 'h1', start_bp: 10, end_bp: 19, direction: 'FORWARD' }] },
  { strandId: 'rev', label: 'OH-R', tooltip: 't2', domains: [{ helix_id: 'h1', start_bp: 39, end_bp: 30, direction: 'REVERSE' }] },
  { strandId: 'lnk', label: 'L', tooltip: 't3', domains: [
    { helix_id: '__lnk__c1', start_bp: 0, end_bp: 5, direction: 'FORWARD' },      // not laid out
    { helix_id: 'h1', start_bp: 50, end_bp: 55, direction: 'REVERSE' }] },
  { strandId: 'gone', label: 'x', tooltip: 't4', domains: [{ helix_id: 'nope', start_bp: 0, end_bp: 1, direction: 'FORWARD' }] },
]

describe('cadnano path-view hairpin/dimer markers', () => {
  it('sits above a forward domain, below a reverse one, at the domain midpoint', () => {
    const placed = placeHairpinDimerMarkers(markers, rowMap)
    expect(placed.map(p => p.strandId)).toEqual(['fwd', 'rev', 'lnk'])   // unlaid-out helix skipped
    expect(placed[0]).toMatchObject({ x: GUTTER + 15 * BP_W, y: 100 - CELL_H, below: false })
    expect(placed[1]).toMatchObject({ x: GUTTER + 35 * BP_W, y: 112 + CELL_H, below: true })
    expect(placed[2].x).toBe(GUTTER + 53 * BP_W)                         // first laid-out linker domain
  })

  it('hit-tests in screen pixels at any zoom', () => {
    const placed = placeHairpinDimerMarkers(markers, rowMap)
    const [p] = placed
    for (const zoom of [0.5, 1, 4]) {
      expect(hitHairpinDimerMarker(placed, p.x + 6 / zoom, p.y, zoom)?.strandId).toBe('fwd')
      expect(hitHairpinDimerMarker(placed, p.x + 14 / zoom, p.y, zoom)).toBeNull()
    }
  })

  it('draws an outlined ⚠ glyph of constant screen size, red when critical', () => {
    const fills = []
    const ctx = { save: vi.fn(), restore: vi.fn(), strokeText: vi.fn(),
      fillText: vi.fn(function () { fills.push(this.fillStyle) }) }
    drawHairpinDimerMarkers(ctx, placeHairpinDimerMarkers(markers, rowMap), 2)
    expect(fills).toEqual([HD_MARKER_COLOR.critical, HD_MARKER_COLOR.warning, HD_MARKER_COLOR.warning])
    expect(ctx.fillText).toHaveBeenCalledTimes(3)
    expect(ctx.fillText.mock.calls[0][0]).toBe('⚠')
    expect(ctx.font).toBe(`bold ${HD_MARKER_PX / 2}px sans-serif`)
  })
})

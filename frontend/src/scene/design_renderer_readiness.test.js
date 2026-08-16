import { describe, expect, it } from 'vitest'
import { designRebuildAwaitingGeometry } from './design_render_readiness.js'

describe('initial design render readiness', () => {
  it('waits when populated topology arrives before geometry', () => {
    const design = { strands: [{ domains: [{ helix_id: 'h0', start_bp: 0, end_bp: 9 }] }] }
    expect(designRebuildAwaitingGeometry(design, null)).toBe(true)
    expect(designRebuildAwaitingGeometry(design, [])).toBe(true)
    expect(designRebuildAwaitingGeometry(design, [{ helix_id: 'h0' }])).toBe(false)
  })

  it('does not strand genuinely empty designs', () => {
    expect(designRebuildAwaitingGeometry({ strands: [] }, [])).toBe(false)
    expect(designRebuildAwaitingGeometry({ strands: [{ domains: [] }] }, null)).toBe(false)
    expect(designRebuildAwaitingGeometry(null, null)).toBe(false)
  })
})

import { describe, it, expect, vi } from 'vitest'
import { mdVizApiAdapter } from './md_viz_adapter.js'

describe('mdVizApiAdapter', () => {
  it('maps the oxDNA-named controller methods to the MD endpoints', () => {
    const api = {
      getMdTrajectory: vi.fn((id) => `traj:${id}`),
      getMdRmsf: vi.fn((id) => `rmsf:${id}`),
    }
    const a = mdVizApiAdapter(api)
    expect(a.getOxdnaTrajectory('J1')).toBe('traj:J1')
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', undefined)
    expect(a.getOxdnaRmsf('J2')).toBe('rmsf:J2')
    expect(api.getMdRmsf).toHaveBeenCalledWith('J2', undefined)
  })

  it('forwards an AbortSignal through to the MD endpoints', () => {
    const api = {
      getMdTrajectory: vi.fn((id) => `traj:${id}`),
      getMdRmsf: vi.fn((id) => `rmsf:${id}`),
    }
    const sig = new AbortController().signal
    const a = mdVizApiAdapter(api)
    a.getOxdnaTrajectory('J1', sig)
    a.getOxdnaRmsf('J2', sig)
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', sig)
    expect(api.getMdRmsf).toHaveBeenCalledWith('J2', sig)
  })

  it('does NOT expose heavy-rep methods (CG-only scope — heavy fails closed)', () => {
    const a = mdVizApiAdapter({})
    expect(a.getOxdnaFramesAtomistic).toBeUndefined()
    expect(a.getOxdnaRmsfAtomistic).toBeUndefined()
  })
})

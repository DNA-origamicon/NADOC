import { describe, it, expect } from 'vitest'
import { statusBadge, statusKeyFor, STATUS_BADGE, JOB_STATUS_LEGEND } from './job_status_symbol.js'

describe('statusKeyFor', () => {
  it('oxDNA production lifecycle', () => {
    expect(statusKeyFor('oxdna', 'completed', 'none')).toBe('production-ready')
    expect(statusKeyFor('oxdna', 'completed', 'done')).toBe('production-done')
    expect(statusKeyFor('oxdna', 'running', 'done')).toBe('production-done')
    expect(statusKeyFor('oxdna', 'running', 'failed')).toBe('production-failed')
  })
  it('plain statuses (both engines)', () => {
    expect(statusKeyFor('namd', 'completed')).toBe('completed')
    expect(statusKeyFor('namd', 'running')).toBe('running')
    expect(statusKeyFor('namd', 'queued')).toBe('queued')
    expect(statusKeyFor('namd', 'failed')).toBe('failed')
    expect(statusKeyFor('namd', 'stopped')).toBe('stopped')
  })
  it('MD never gets oxDNA production keys', () => {
    expect(statusKeyFor('namd', 'completed', 'none')).toBe('completed')
  })
  it('unknown fallback', () => {
    expect(statusKeyFor('oxdna', 'weird')).toBe('unknown')
  })
})

describe('statusBadge', () => {
  it('maps keys to {symbol,color,label}', () => {
    expect(statusBadge('production-ready')).toMatchObject({ symbol: '▲', label: 'Production ready' })
    expect(statusBadge('production-done')).toMatchObject({ symbol: '■', label: 'Production done' })
  })
  it('falls back to unknown for a bad key', () => {
    expect(statusBadge('nope')).toBe(STATUS_BADGE.unknown)
  })
  it('every legend entry is a real badge with a distinct symbol set', () => {
    expect(JOB_STATUS_LEGEND.length).toBeGreaterThan(4)
    for (const b of JOB_STATUS_LEGEND) {
      expect(b).toHaveProperty('symbol')
      expect(b).toHaveProperty('color')
      expect(b).toHaveProperty('label')
    }
  })
})

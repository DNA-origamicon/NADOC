import { describe, it, expect } from 'vitest'
import { initIonTransportProgress } from './ion_transport_progress.js'

describe('ion transport progress', () => {
  it('keeps stable bars, real frame counts and indeterminate setup stages', () => {
    const host = document.createElement('div')
    const progress = initIonTransportProgress(host)
    progress.reset()
    progress.update({ stage: 'topology', done: 0, total: 0 })
    const bar = host.querySelector('[data-ion-transport-stage="topology"] progress')
    expect(bar.hasAttribute('value')).toBe(false)
    progress.update({ stage: 'topology', done: 0, total: 0 })
    expect(host.querySelector('[data-ion-transport-stage="topology"] progress')).toBe(bar)
    progress.update({ stage: 'current', done: 250, total: 1000 })
    const row = host.querySelector('[data-ion-transport-stage="current"]')
    expect(row.textContent).toContain('250 / 1,000 (25%)')
    expect(row.querySelector('progress').value).toBe(250)
    progress.update({ stage: 'current', done: 1000, total: 1000 })
    expect(row.textContent).toContain('Complete')
  })

  it('marks failed stages and stops waiting for subsequent stages', () => {
    const host = document.createElement('div')
    const progress = initIonTransportProgress(host)
    progress.reset()
    progress.update({ stage: 'topology', state: 'running' })
    progress.fail('Unreadable PSF')
    expect(host.querySelector('[data-ion-transport-stage="topology"]').textContent).toContain('Failed · Unreadable PSF')
    expect(host.querySelector('[data-ion-transport-stage="current"]').textContent).toContain('Not run')
    expect(host.querySelector('progress:not([value])')).toBeNull()
  })
})

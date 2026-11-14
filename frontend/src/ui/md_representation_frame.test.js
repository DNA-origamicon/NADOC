import { it, expect, vi } from 'vitest'
import { scheduleMdRepresentationFrame } from './md_representation_frame.js'
const emit = (state, jobId = 'job') => window.dispatchEvent(new CustomEvent('nadoc:md-display-state', { detail: { state, jobId } }))
it('waits past topology readiness and other jobs until actual coordinates are displayed', async () => {
  vi.useFakeTimers()
  try {
    let finished = false
    const ready = scheduleMdRepresentationFrame(() => emit('topology-ready'), 'job').then(() => { finished = true })
    await vi.advanceTimersByTimeAsync(20)
    emit('frame', 'other'); await Promise.resolve()
    expect(finished).toBe(false)
    emit('frame'); await ready
    expect(finished).toBe(true)
  } finally { vi.useRealTimers() }
})
it('reports frame-load errors instead of accepting a stale mesh', async () => {
  vi.useFakeTimers()
  try {
    const ready = scheduleMdRepresentationFrame(() => emit('error'), 'job')
    const failure = expect(ready).rejects.toThrow('MD display stopped')
    await vi.advanceTimersByTimeAsync(20)
    await failure
  } finally { vi.useRealTimers() }
})

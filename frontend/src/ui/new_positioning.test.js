import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  __resetForTests,
  geometryQuerySuffix,
  isNewPositioningOn,
  onNewPositioningChange,
  setNewPositioning,
} from './new_positioning.js'

beforeEach(() => {
  __resetForTests(false)
  localStorage.clear()
})

describe('the flag', () => {
  it('is off after an explicit opt-out', () => {
    expect(isNewPositioningOn()).toBe(false)
  })

  it('reports whether the value actually changed', () => {
    expect(setNewPositioning(true)).toBe(true)
    expect(setNewPositioning(true)).toBe(false)   // no-op: skip the refetch
    expect(setNewPositioning(false)).toBe(true)
  })

  it('notifies subscribers with the new value and can unsubscribe', () => {
    const seen = []
    const off = onNewPositioningChange(v => seen.push(v))
    setNewPositioning(true)
    setNewPositioning(false)
    off()
    setNewPositioning(true)
    expect(seen).toEqual([true, false])
  })

  it('persists across a reload', () => {
    setNewPositioning(true)
    expect(localStorage.getItem('nadoc.newPositioning.v2')).toBe('true')
    setNewPositioning(false)
    expect(localStorage.getItem('nadoc.newPositioning.v2')).toBe('false')
  })

  it('is ON when nothing was ever chosen — measured placement is native', () => {
    localStorage.removeItem('nadoc.newPositioning.v2')
    __resetForTests(undefined)
    expect(isNewPositioningOn()).toBe(true)
  })

  it('survives localStorage being unavailable', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(() => setNewPositioning(true)).not.toThrow()
    expect(isNewPositioningOn()).toBe(true)
    spy.mockRestore()
  })
})

describe('geometryQuerySuffix', () => {
  it('states the mode explicitly when off, never relying on a default', () => {
    // The two endpoints this feeds do NOT default alike — atomistic is measured
    // natively, CG geometry is still opt-in — so an empty suffix would mean two
    // different things depending on which URL it was appended to.
    expect(geometryQuerySuffix(false)).toBe('?measured_positioning=false')
    expect(geometryQuerySuffix(true)).toBe('&measured_positioning=false')
  })

  it('picks the right separator for the URL it is appended to', () => {
    setNewPositioning(true)
    expect(geometryQuerySuffix(false)).toBe('?measured_positioning=true')
    expect(geometryQuerySuffix(true)).toBe('&measured_positioning=true')
  })
})

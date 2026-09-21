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
  it('selects baseline after an explicit choice', () => {
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
    expect(localStorage.getItem('nadoc.newPositioning.v3')).toBe('true')
    setNewPositioning(false)
    expect(localStorage.getItem('nadoc.newPositioning.v3')).toBe('false')
  })

  it('starts on the candidate slot when nothing was chosen', () => {
    localStorage.removeItem('nadoc.newPositioning.v3')
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
    expect(geometryQuerySuffix(false)).toBe('?measured_positioning=false')
    expect(geometryQuerySuffix(true)).toBe('&measured_positioning=false')
  })

  it('picks the right separator for the URL it is appended to', () => {
    setNewPositioning(true)
    expect(geometryQuerySuffix(false)).toBe('?measured_positioning=true')
    expect(geometryQuerySuffix(true)).toBe('&measured_positioning=true')
  })
})

it('clears the retired comparison preference instead of restoring legacy mode', () => {
  localStorage.setItem('nadoc.newPositioning.v1', 'false')
  localStorage.setItem('nadoc.newPositioning.v2', 'false')
  __resetForTests()
  expect(isNewPositioningOn()).toBe(true)
  expect(localStorage.getItem('nadoc.newPositioning.v1')).toBeNull()
  expect(localStorage.getItem('nadoc.newPositioning.v2')).toBeNull()
})

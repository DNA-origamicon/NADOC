import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import {
  MEASURED_SLAB_EXTENT,
  __resetForTests,
  geometryQuerySuffix,
  isNewPositioningOn,
  onNewPositioningChange,
  setNewPositioning,
  slabCenterInto,
  slabExtent,
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

describe('slabCenterInto', () => {
  const bb = new THREE.Vector3(1, 0, 0)
  const bn = new THREE.Vector3(-1, 0, 0)

  it('keeps the legacy construction when off, even if a base position exists', () => {
    const out = slabCenterInto(bb, bn, 0.45, [9, 9, 9], new THREE.Vector3())
    expect([out.x, out.y, out.z]).toEqual([0.55, 0, 0])
  })

  it('uses the measured base centroid when on', () => {
    setNewPositioning(true)
    const out = slabCenterInto(bb, bn, 0.45, [0.3, 0.1, 0.2], new THREE.Vector3())
    expect([out.x, out.y, out.z]).toEqual([0.3, 0.1, 0.2])
  })

  it('falls back to the legacy offset when the payload carries no base position', () => {
    setNewPositioning(true)
    const out = slabCenterInto(bb, bn, 0.45, null, new THREE.Vector3())
    expect([out.x, out.y, out.z]).toEqual([0.55, 0, 0])
  })
})

describe('slabExtent', () => {
  it('passes the legacy extent through when off', () => {
    expect(slabExtent(0.7)).toBe(0.7)
  })

  it('spans only the base itself when on', () => {
    setNewPositioning(true)
    expect(slabExtent(0.7)).toBe(MEASURED_SLAB_EXTENT)
  })
})

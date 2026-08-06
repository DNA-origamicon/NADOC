import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import {
  MEASURED_SLAB_EXTENT,
  __resetForTests,
  geometryQuerySuffix,
  isNewPositioningOn,
  onNewPositioningChange,
  setNewPositioning,
  slabAxisInto,
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

  it('puts the slab OUTER FACE on the bead when on, so the two connect', () => {
    setNewPositioning(true)
    // base 1 nm inward along -x from a bead at x=1: the centre must sit half an extent
    // in from the bead, i.e. the near face lands exactly on the bead.
    const out = slabCenterInto(bb, bn, 0.45, [0, 0, 0], new THREE.Vector3())
    expect(out.x).toBeCloseTo(1 - MEASURED_SLAB_EXTENT / 2, 9)
    expect(out.y).toBeCloseTo(0, 9)
    expect(out.z).toBeCloseTo(0, 9)
    // the face itself, reconstructed the way the renderer scales the plate
    const axis = slabAxisInto(bb, bn, [0, 0, 0], new THREE.Vector3())
    const face = out.clone().addScaledVector(axis, -MEASURED_SLAB_EXTENT / 2)
    expect(face.distanceTo(bb)).toBeCloseTo(0, 9)
  })

  it('aims the slab at its own bead, not along the cross-strand direction', () => {
    setNewPositioning(true)
    // A base offset sideways from the bead: measured, the C3' sits 0.29 nm off the
    // base's cross-strand line, so a slab laid along bnDir would miss the bead.
    const base = [0.5, 0.5, 0]
    const axis = slabAxisInto(bb, bn, base, new THREE.Vector3())
    expect(axis.dot(bn)).toBeLessThan(0.99)          // genuinely not bnDir
    expect(axis.length()).toBeCloseTo(1, 9)
    const out = slabCenterInto(bb, bn, 0.45, base, new THREE.Vector3())
    const face = out.clone().addScaledVector(axis, -MEASURED_SLAB_EXTENT / 2)
    expect(face.distanceTo(bb)).toBeCloseTo(0, 9)    // still lands on the bead
  })

  it('falls back to the cross-strand axis with no base position', () => {
    setNewPositioning(true)
    const axis = slabAxisInto(bb, bn, null, new THREE.Vector3())
    expect([axis.x, axis.y, axis.z]).toEqual([-1, 0, 0])
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

  it('spans from the bead to past the Watson-Crick atom when on', () => {
    setNewPositioning(true)
    expect(slabExtent(0.7)).toBe(MEASURED_SLAB_EXTENT)
  })
})

import { describe, it, expect } from 'vitest'
import {
  ANNOTATION_COLORS, annotationFromWire, annotationHasContent, annotationIsRenderable, annotationToWire,
  deserializeAnnotations, legacyStorageKeyFor, normalizeAnnotation,
} from './annotation_model.js'

describe('normalizeAnnotation', () => {
  it('fills defaults and clamps out-of-range values', () => {
    const a = normalizeAnnotation({ size: 99, transparency: 5, color: 'nope', calloutType: 'bogus', icon: 'bogus' }, { index: 1 })
    expect(a.size).toBe(2.5)
    expect(a.transparency).toBe(0.8)
    expect(a.color).toBe(ANNOTATION_COLORS[1])
    expect(a.calloutType).toBe('elbow')
    expect(a.icon).toBeNull()
    expect(a.manual).toBe(false)
    expect(a.visible).toBe(true)
    expect(a.id).toMatch(/^anno-/)
  })
  it('keeps valid refs and drops invalid ones', () => {
    const a = normalizeAnnotation({ refs: [{ kind: 'strand', id: 's1' }, { kind: 'nope' }, { kind: 'strand', id: 's1' }] })
    expect(a.refs).toEqual([{ kind: 'strand', id: 's1' }])
  })
  it('clamps a manual screen position to the unit square', () => {
    expect(normalizeAnnotation({ screenPos: { x: -2, y: 4 } }).screenPos).toEqual({ x: 0, y: 1 })
    expect(normalizeAnnotation({ screenPos: { x: NaN, y: 1 } }).screenPos).toBeNull()
  })
})

describe('renderability', () => {
  it('needs text or an icon', () => {
    expect(annotationHasContent({ text: '', icon: null })).toBe(false)
    expect(annotationHasContent({ text: '   ', icon: null })).toBe(false)
    expect(annotationHasContent({ text: 'hi', icon: null })).toBe(true)
    expect(annotationHasContent({ text: '', icon: 'check' })).toBe(true)
  })
  it('a hidden entry never renders even with content', () => {
    expect(annotationIsRenderable({ text: 'hi', visible: false })).toBe(false)
    expect(annotationIsRenderable({ text: 'hi', visible: true })).toBe(true)
  })
})

describe('file wire format', () => {
  it('maps to the snake_case .nadoc shape and back without loss', () => {
    const entry = normalizeAnnotation({
      id: 'a', text: 't', icon: 'check', calloutType: 'rounded', color: '#123456', transparency: 0.3, size: 1.4,
      manual: true, screenPos: { x: 0.2, y: 0.7 }, visible: false, refs: [{ kind: 'domain', strandId: 's', domainIndex: 1 }],
    })
    const wire = annotationToWire(entry)
    expect(wire).toMatchObject({ callout_type: 'rounded', screen_pos: [0.2, 0.7], visible: false })
    expect(Object.keys(wire).some(k => /[A-Z]/.test(k))).toBe(false)
    expect(annotationFromWire(wire)).toEqual(entry)
    expect(annotationToWire(normalizeAnnotation({ text: 'x' })).screen_pos).toBeNull()
  })
  it('tolerates missing and foreign fields', () => {
    const e = annotationFromWire({ id: 'z', callout_type: 'nope', screen_pos: 'x', color: 5 }, { index: 2 })
    expect(e).toMatchObject({ id: 'z', calloutType: 'elbow', screenPos: null, color: ANNOTATION_COLORS[2] })
    expect(annotationFromWire(null).id).toMatch(/^anno-/)
  })
})

describe('legacy browser-storage payload', () => {
  it('parses old localStorage payloads and survives corrupt input', () => {
    const raw = JSON.stringify({ version: 1, entries: [normalizeAnnotation({ text: 'a', icon: 'star' })] })
    expect(deserializeAnnotations(raw)).toHaveLength(1)
    expect(deserializeAnnotations('{not json')).toEqual([])
    expect(deserializeAnnotations(null)).toEqual([])
    expect(deserializeAnnotations('{"entries":[1,null,{"id":"x"},{"id":"x"}]}')).toHaveLength(1)
    expect(legacyStorageKeyFor('d')).toBe('nadoc.annotations.v1:d')
  })
})

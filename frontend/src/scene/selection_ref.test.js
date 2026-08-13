import { describe, expect, it } from 'vitest'
import {
  STABLE_SELECTION_KINDS,
  normalizeSelectionRef, selectionRefKey, selectionRefsEqual,
  dedupeSelectionRefs, reconcileSelectionRefs,
  serializeSelectionRefs, deserializeSelectionRefs, isSelectionRefLive,
} from './selection_ref.js'

describe('selection_ref — decision-independent Phase 1 identity contract', () => {
  it('lists only the stable kinds ratified independently of pending semantic decisions', () => {
    expect(STABLE_SELECTION_KINDS).toEqual([
      'cluster', 'strand', 'domain', 'base', 'end', 'bond', 'crossover',
      'overhang', 'extension', 'protein',
    ])
    expect(STABLE_SELECTION_KINDS).not.toContain('forced_ligation') // classification gate
  })

  it.each(['cluster', 'strand', 'overhang', 'extension', 'protein'])(
    'normalizes a minimal %s ref and strips mutable payload',
    (kind) => {
      expect(normalizeSelectionRef({ kind, id: `${kind}:1`, data: { stale: true }, mesh: {} }))
        .toEqual({ kind, id: `${kind}:1` })
    },
  )

  it('normalizes domain aliases to one canonical field spelling', () => {
    expect(normalizeSelectionRef({ kind: 'domain', strand_id: 's1', domain_index: 2 }))
      .toEqual({ kind: 'domain', strandId: 's1', domainIndex: 2 })
    expect(normalizeSelectionRef({ kind: 'domain', strandId: 's1', domainIndex: 2, helixId: 'stale' }))
      .toEqual({ kind: 'domain', strandId: 's1', domainIndex: 2 })
  })

  it('accepts every app-wide base-key family', () => {
    for (const key of [
      'h1:3:FORWARD', 'h1:3:REVERSE:2', '__xb__:xo:0',
      '__ext_e1:4:FORWARD', '__lnk__c1:2:FORWARD',
    ]) {
      expect(normalizeSelectionRef({ kind: 'base', key })).toEqual({ kind: 'base', key })
      expect(normalizeSelectionRef({ kind: 'end', key })).toEqual({ kind: 'end', key })
    }
  })

  it('models forced ligation as a crossover subtype', () => {
    expect(normalizeSelectionRef({ kind: 'crossover', id: 'x1' }))
      .toEqual({ kind: 'crossover', id: 'x1', subtype: 'crossover' })
    expect(normalizeSelectionRef({ kind: 'crossover', id: 'f1', subtype: 'forced_ligation' }))
      .toEqual({ kind: 'crossover', id: 'f1', subtype: 'forced_ligation' })
    expect(normalizeSelectionRef({ kind: 'forced_ligation', id: 'f1' })).toBeNull()
    expect(normalizeSelectionRef({ kind: 'crossover', id: 'x', subtype: 'other' })).toBeNull()
  })

  it('normalizes a renderer-independent backbone bond identity', () => {
    expect(normalizeSelectionRef({
      kind: 'bond', fromKey: 'h1:3:FORWARD', toKey: 'h1:4:FORWARD', strand_id: 's1', mesh: {},
    })).toEqual({
      kind: 'bond', fromKey: 'h1:3:FORWARD', toKey: 'h1:4:FORWARD', strandId: 's1',
    })
  })

  it.each([
    null, {}, { kind: 'unknown', id: 'x' }, { kind: 'strand', id: '' },
    { kind: 'domain', strandId: 's', domainIndex: -1 },
    { kind: 'domain', strandId: 's', domainIndex: 1.5 },
    { kind: 'base', key: 'garbage' },
    { kind: 'end', key: 'garbage' },
    { kind: 'bond', fromKey: 'garbage', toKey: 'h1:2:FORWARD' },
  ])('rejects unstable identity %#', (input) => {
    expect(normalizeSelectionRef(input)).toBeNull()
  })

  it('uses collision-safe structural keys', () => {
    expect(selectionRefKey({ kind: 'strand', id: 'a:b' })).toBe('["strand","a:b"]')
    expect(selectionRefKey({ kind: 'domain', strandId: 'a:b', domainIndex: 4 }))
      .toBe('["domain","a:b",4]')
    expect(selectionRefKey({ kind: 'base', key: '__xb__:a:b:2' }))
      .toBe('["base","__xb__:a:b:2"]')
    expect(selectionRefKey({ kind: 'crossover', id: 'a:b', subtype: 'forced_ligation' }))
      .toBe('["crossover","forced_ligation","a:b"]')
  })

  it('compares normalized structural identity rather than object identity', () => {
    expect(selectionRefsEqual(
      { kind: 'domain', strand_id: 's1', domain_index: 0 },
      { kind: 'domain', strandId: 's1', domainIndex: 0 },
    )).toBe(true)
    expect(selectionRefsEqual({ kind: 'strand', id: 's1' }, { kind: 'strand', id: 's2' })).toBe(false)
    expect(selectionRefsEqual(null, null)).toBe(false)
  })

  it('deduplicates in first-seen order and returns fresh canonical objects', () => {
    const original = { kind: 'strand', id: 's1', data: { mutable: true } }
    const out = dedupeSelectionRefs([
      original,
      { kind: 'domain', strand_id: 's1', domain_index: 0 },
      { kind: 'strand', id: 's1' },
      { kind: 'base', key: 'h1:3:FORWARD' },
      { nope: true },
    ])
    expect(out).toEqual([
      { kind: 'strand', id: 's1' },
      { kind: 'domain', strandId: 's1', domainIndex: 0 },
      { kind: 'base', key: 'h1:3:FORWARD' },
    ])
    expect(out[0]).not.toBe(original)
  })

  it('reconciles only positively live refs and is idempotent', () => {
    const refs = [
      { kind: 'strand', id: 'live' },
      { kind: 'strand', id: 'gone' },
      { kind: 'domain', strandId: 'live', domainIndex: 0 },
    ]
    const isLive = ref => ref.id === 'live' || ref.strandId === 'live'
    const once = reconcileSelectionRefs(refs, isLive)
    expect(once).toEqual([
      { kind: 'strand', id: 'live' },
      { kind: 'domain', strandId: 'live', domainIndex: 0 },
    ])
    expect(reconcileSelectionRefs(once, isLive)).toEqual(once)
  })

  it('round-trips JSON with stable order and drops invalid/corrupt input', () => {
    const refs = [
      { kind: 'overhang', id: 'oh1' },
      { kind: 'base', key: 'h1:2:REVERSE' },
    ]
    expect(deserializeSelectionRefs(serializeSelectionRefs(refs))).toEqual(refs)
    expect(deserializeSelectionRefs('{bad')).toEqual([])
    expect(deserializeSelectionRefs('{"not":"array"}')).toEqual([])
    expect(deserializeSelectionRefs(JSON.stringify([...refs, { kind: 'base', key: 'bad' }])))
      .toEqual(refs)
  })

  it('never mutates caller arrays or refs', () => {
    const ref = { kind: 'strand', id: 's1' }
    const inputs = [ref, ref]
    dedupeSelectionRefs(inputs)
    reconcileSelectionRefs(inputs, () => true)
    serializeSelectionRefs(inputs)
    expect(inputs).toEqual([ref, ref])
  })
})

describe('selection ref design liveness', () => {
  const design = {
    helices: [{ id: 'h1' }], strands: [{ id: 's1', domains: [{}] }],
    crossovers: [{ id: 'x1' }], forced_ligations: [{ id: 'f1' }],
    overhangs: [{ id: 'o1' }], extensions: [{ id: 'e1' }],
    overhang_connections: [{ id: 'l1' }], cluster_transforms: [{ id: 'c1' }],
    protein_attachments: [{ id: 'p1' }],
  }
  it('keeps every live owner and rejects deleted identities', () => {
    for (const ref of [
      { kind: 'strand', id: 's1' }, { kind: 'domain', strandId: 's1', domainIndex: 0 },
      { kind: 'base', key: 'h1:4:FORWARD' }, { kind: 'base', key: '__xb__:x1:0' },
      { kind: 'base', key: '__ext_e1:0:FORWARD' }, { kind: 'base', key: '__lnk__l1:0:FORWARD' },
      { kind: 'crossover', id: 'f1', subtype: 'forced_ligation' },
      { kind: 'bond', fromKey: 'h1:3:FORWARD', toKey: 'h1:4:FORWARD', strandId: 's1' },
      { kind: 'overhang', id: 'o1' }, { kind: 'cluster', id: 'c1' }, { kind: 'protein', id: 'p1' },
    ]) expect(isSelectionRefLive(ref, design)).toBe(true)
    expect(isSelectionRefLive({ kind: 'strand', id: 'gone' }, design)).toBe(false)
    expect(isSelectionRefLive({ kind: 'base', key: 'gone:1:FORWARD' }, design)).toBe(false)
  })
})

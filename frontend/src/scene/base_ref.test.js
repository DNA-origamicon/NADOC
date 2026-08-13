import { describe, it, expect } from 'vitest'
import {
  XB_HELIX, baseKey, xbKey, atomBaseKey, parseBaseKey, baseFamily,
  toggleBaseKey, dedupeBaseKeys, mergeBaseKeys, pruneBaseKeys,
} from './base_ref.js'

const nuc = (helix_id, bp_index, direction = 'FORWARD') => ({ helix_id, bp_index, direction })

describe('baseKey', () => {
  it('emits the 3-part form for an ordinary bead (copy 0 omitted)', () => {
    expect(baseKey(nuc('h1', 12))).toBe('h1:12:FORWARD')
    expect(baseKey(nuc('h1', 12), 0)).toBe('h1:12:FORWARD')
  })

  it('emits the 4-part form only for a loop copy', () => {
    expect(baseKey(nuc('h1', 12), 1)).toBe('h1:12:FORWARD:1')
    expect(baseKey(nuc('h1', 12, 'REVERSE'), 2)).toBe('h1:12:REVERSE:2')
  })

  it('returns null without a helix id', () => {
    expect(baseKey(null)).toBeNull()
    expect(baseKey({ bp_index: 3, direction: 'FORWARD' })).toBeNull()
  })
})

describe('xbKey', () => {
  it('uses the repo-existing 3-part __xb__ form verbatim', () => {
    expect(xbKey('xo-7', 2)).toBe('__xb__:xo-7:2')
    expect(XB_HELIX).toBe('__xb__')
  })
  it('returns null without a crossover id', () => {
    expect(xbKey(null, 0)).toBeNull()
    expect(xbKey(undefined, 1)).toBeNull()
  })
})

describe('atomBaseKey', () => {
  it('does not collapse an extension-tail atom onto its anchor nucleotide', () => {
    expect(atomBaseKey({
      helix_id: 'anchor', bp_index: 9, direction: 'REVERSE',
      extension_id: 'tail7', ext_k: 2,
    })).toBe('__ext_tail7:2:REVERSE')
  })

  it('preserves crossover-insert and loop-copy identity', () => {
    expect(atomBaseKey({ crossover_id: 'xo1', extra_base_k: 3 })).toBe('__xb__:xo1:3')
    expect(atomBaseKey({ helix_id: 'h1', bp_index: 4, direction: 'FORWARD', copy_k: 1 }))
      .toBe('h1:4:FORWARD:1')
  })
})

describe('parseBaseKey — splits from the RIGHT', () => {
  it('round-trips an ordinary bead', () => {
    expect(parseBaseKey('h1:12:FORWARD'))
      .toEqual({ helix_id: 'h1', bp_index: 12, direction: 'FORWARD', copy: 0 })
  })

  it('round-trips a loop copy', () => {
    expect(parseBaseKey('h1:12:REVERSE:3'))
      .toEqual({ helix_id: 'h1', bp_index: 12, direction: 'REVERSE', copy: 3 })
  })

  // The whole reason for splitting from the right: synthetic helix ids carry
  // underscores and (for __xb__) an arbitrary crossover-id string.
  it('survives an __ext_<uuid> helix id', () => {
    const k = baseKey(nuc('__ext_9f3a-2b_11', 4))
    expect(parseBaseKey(k)).toEqual({
      helix_id: '__ext_9f3a-2b_11', bp_index: 4, direction: 'FORWARD', copy: 0,
    })
  })

  it('survives a __lnk__<connId> helix id', () => {
    const k = baseKey(nuc('__lnk__conn_42', 0))
    expect(parseBaseKey(k).helix_id).toBe('__lnk__conn_42')
    expect(parseBaseKey(k).bp_index).toBe(0)
  })

  it('survives a helix id containing a colon', () => {
    const k = baseKey(nuc('h:weird:1', 7, 'REVERSE'))
    expect(parseBaseKey(k)).toEqual({
      helix_id: 'h:weird:1', bp_index: 7, direction: 'REVERSE', copy: 0,
    })
  })

  it('parses the __xb__ form into crossover_id + k, not helix/bp/dir', () => {
    expect(parseBaseKey('__xb__:xo-7:2'))
      .toEqual({ helix_id: '__xb__', crossover_id: 'xo-7', k: 2 })
  })

  it('keeps a crossover id containing colons intact', () => {
    expect(parseBaseKey('__xb__:a:b:c:5'))
      .toEqual({ helix_id: '__xb__', crossover_id: 'a:b:c', k: 5 })
  })

  it('rejects junk', () => {
    expect(parseBaseKey('')).toBeNull()
    expect(parseBaseKey(null)).toBeNull()
    expect(parseBaseKey('h1:12')).toBeNull()
    expect(parseBaseKey('__xb__:nope')).toBeNull()
    expect(parseBaseKey('h1:notanumber:FORWARD')).toBeNull()
  })
})

describe('baseFamily', () => {
  it('routes each synthetic helix to its renderer family', () => {
    expect(baseFamily('h1:12:FORWARD')).toBe('backbone')
    expect(baseFamily('__xb__:xo-7:2')).toBe('xover')
    expect(baseFamily('__lnk__c9:0:FORWARD')).toBe('sslink')
    expect(baseFamily('__ext_abc:3:FORWARD')).toBe('extension')
  })
  it('returns null for an unparseable key', () => {
    expect(baseFamily('garbage')).toBeNull()
  })
})

describe('toggleBaseKey', () => {
  it('adds when absent, removes when present', () => {
    expect(toggleBaseKey([], 'a:1:F')).toEqual(['a:1:F'])
    expect(toggleBaseKey(['a:1:F'], 'a:1:F')).toEqual([])
    expect(toggleBaseKey(['a:1:F', 'b:2:F'], 'a:1:F')).toEqual(['b:2:F'])
  })

  it('is its own inverse', () => {
    const pool = ['a:1:F', 'b:2:F']
    expect(toggleBaseKey(toggleBaseKey(pool, 'c:3:F'), 'c:3:F')).toEqual(pool)
  })

  it('never mutates the input, and a null key is a no-op copy', () => {
    const pool = ['a:1:F']
    const out = toggleBaseKey(pool, null)
    expect(out).toEqual(pool)
    expect(out).not.toBe(pool)
  })
})

describe('pruneBaseKeys — drops only what is positively gone', () => {
  const S = (...v) => new Set(v)

  it('drops a key whose helix was deleted, keeps the rest', () => {
    const keys = ['h1:3:FORWARD', 'gone:4:FORWARD', 'h2:5:REVERSE']
    expect(pruneBaseKeys(keys, { helixIds: S('h1', 'h2') }))
      .toEqual(['h1:3:FORWARD', 'h2:5:REVERSE'])
  })

  it('drops an extra base whose crossover was deleted', () => {
    const keys = ['__xb__:xo1:0', '__xb__:xoGone:1']
    expect(pruneBaseKeys(keys, { crossoverIds: S('xo1') })).toEqual(['__xb__:xo1:0'])
  })

  it('drops an extension base whose extension was deleted', () => {
    const keys = ['__ext_e1:0:FORWARD', '__ext_eGone:0:FORWARD']
    expect(pruneBaseKeys(keys, { extensionIds: S('e1') })).toEqual(['__ext_e1:0:FORWARD'])
  })

  it('drops a linker base whose connection was deleted', () => {
    const keys = ['__lnk__c1:0:FORWARD', '__lnk__cGone:2:FORWARD']
    expect(pruneBaseKeys(keys, { connectionIds: S('c1') })).toEqual(['__lnk__c1:0:FORWARD'])
  })

  // The conservative half: an omitted id set means "can't tell", never "delete it".
  it('keeps every family whose id set was not supplied', () => {
    const keys = ['h1:3:FORWARD', '__xb__:xo1:0', '__ext_e1:0:FORWARD', '__lnk__c1:0:FORWARD']
    expect(pruneBaseKeys(keys, {})).toEqual(keys)
  })

  it('supplying only helixIds does not prune the synthetic families', () => {
    const keys = ['__xb__:xo1:0', '__ext_e1:0:FORWARD', '__lnk__c1:0:FORWARD']
    expect(pruneBaseKeys(keys, { helixIds: S() })).toEqual(keys)
  })

  it('drops unparseable keys — they can never resolve', () => {
    expect(pruneBaseKeys(['garbage', 'h1:3:FORWARD'], { helixIds: S('h1') }))
      .toEqual(['h1:3:FORWARD'])
  })

  it('an empty pool stays empty', () => {
    expect(pruneBaseKeys([], { helixIds: S('h1') })).toEqual([])
  })
})

describe('dedupeBaseKeys / mergeBaseKeys', () => {
  it('dedupes preserving first-seen order and drops nulls', () => {
    expect(dedupeBaseKeys(['a', 'b', 'a', null, 'c', 'b'])).toEqual(['a', 'b', 'c'])
  })

  it('merge is an additive union (lasso semantics)', () => {
    expect(mergeBaseKeys(['a', 'b'], ['b', 'c'])).toEqual(['a', 'b', 'c'])
    expect(mergeBaseKeys([], ['x'])).toEqual(['x'])
    expect(mergeBaseKeys(['x'], [])).toEqual(['x'])
  })
})

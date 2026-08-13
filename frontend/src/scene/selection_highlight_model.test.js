import { describe, expect, it } from 'vitest'
import { selectionHighlightDescriptor, highlightDescriptorIsEmpty } from './selection_highlight_model.js'

describe('selection highlight descriptor', () => {
  it('compiles every canonical kind without renderer objects or mutable payloads', () => {
    const state = { selection: {
      context: 'design', level: 'end',
      items: [
        { kind: 'cluster', id: 'c1' },
        { kind: 'strand', id: 's1' },
        { kind: 'domain', strandId: 's1', domainIndex: 2 },
        { kind: 'base', key: 'h1:3:FORWARD' },
        { kind: 'end', key: 'h1:4:FORWARD' },
        { kind: 'bond', fromKey: 'h1:3:FORWARD', toKey: 'h1:4:FORWARD', strandId: 's1' },
        { kind: 'crossover', id: 'x1', subtype: 'forced_ligation' },
        { kind: 'overhang', id: 'o1' }, { kind: 'extension', id: 'e1' },
        { kind: 'protein', id: 'p1' },
      ],
      primary: { kind: 'protein', id: 'p1' },
    } }
    expect(selectionHighlightDescriptor(state)).toEqual({
      context: 'design', primary: { kind: 'protein', id: 'p1' },
      clusterIds: ['c1'], strandIds: ['s1'], domains: [{ strandId: 's1', domainIndex: 2 }],
      baseKeys: ['h1:3:FORWARD'], endKeys: ['h1:4:FORWARD'],
      bonds: [{ fromKey: 'h1:3:FORWARD', toKey: 'h1:4:FORWARD', strandId: 's1' }],
      crossovers: [{ id: 'x1', subtype: 'forced_ligation' }],
      overhangIds: ['o1'], extensionIds: ['e1'], proteinIds: ['p1'],
    })
  })

  it('normalizes malformed input to an empty descriptor', () => {
    const descriptor = selectionHighlightDescriptor({ selection: { items: [{ mesh: {} }] } })
    expect(highlightDescriptorIsEmpty(descriptor)).toBe(true)
    expect(descriptor.primary).toBeNull()
  })
})

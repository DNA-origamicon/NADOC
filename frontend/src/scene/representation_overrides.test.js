import { describe, expect, it } from 'vitest'
import { editOverridesForProteins, proteinRepsByAttachment } from './representation_overrides.js'

describe('protein representation overrides', () => {
  it('assigns proteins independently and preserves DNA segments', () => {
    const original = [{ representation: 'cylinders', segments: [{ helix_id: 'h1', bp_start: 0, bp_end: 4 }] }]
    const next = editOverridesForProteins(original, ['p1'], 'stick')
    expect(next[0].segments).toEqual(original[0].segments)
    expect(proteinRepsByAttachment({ representation_overrides: next }).get('p1')).toBe('stick')
  })

  it('moves only the selected protein and reset removes empty overrides', () => {
    const original = [{ representation: 'vdw', segments: [], protein_attachment_ids: ['p1', 'p2'] }]
    const moved = editOverridesForProteins(original, ['p1'], 'full')
    expect(proteinRepsByAttachment({ representation_overrides: moved })).toEqual(
      new Map([['p2', 'vdw'], ['p1', 'full']]),
    )
    expect(editOverridesForProteins(moved, ['p1'], null)).toEqual([
      expect.objectContaining({ representation: 'vdw', protein_attachment_ids: ['p2'] }),
    ])
  })
})

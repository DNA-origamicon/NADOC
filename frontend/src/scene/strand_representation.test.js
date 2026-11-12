import { describe, it, expect } from 'vitest'
import { editStrandRepresentation, strandRepresentationLayers } from './strand_representation.js'
import { resolveRepOverrides, editOverridesForSegments, editOverridesForProteins } from './representation_overrides.js'

describe('independent strand representation', () => {
  it('preserves domain and protein overrides while cycling only the selected strand', () => {
    const domain = { representation: 'full', segments: [{ helix_id: 'h', bp_start: 0, bp_end: 1 }] }
    let design = { representation_overrides: [domain, { protein_attachment_ids: ['p'], representation: 'vdw' }] }
    for (const coloring of ['strand', 'base', 'cluster', 'cpk', 'strand']) {
      design = { ...design, representation_overrides: editStrandRepresentation(design, ['s'], 'ballstick', { cycle: true }) }
      expect(design.representation_overrides.at(-1)).toMatchObject({ strand_ids: ['s'], representation: 'ballstick', coloring, segments: [] })
      expect(design.representation_overrides[0]).toMatchObject(domain)
      expect(design.representation_overrides[1].protein_attachment_ids).toEqual(['p'])
    }
    expect(resolveRepOverrides(design).columnRep.get('h:0')).toBe('full')
    expect(editOverridesForSegments(design.representation_overrides, domain.segments, 'vdw').some(r => r.strand_ids?.includes('s'))).toBe(true)
    expect(editOverridesForProteins(design.representation_overrides, ['p'], null).some(r => r.strand_ids?.includes('s'))).toBe(true)
  })

  it('cycles Full locally even when Full is already the global representation', () => {
    expect(editStrandRepresentation({}, ['s'], 'full', { cycle: true })[0].coloring).toBe('base')
  })

  it('excludes the complementary strand at the same columns and retains insertion copies', () => {
    const state = { currentDesign: { representation_overrides: [{ strand_ids: ['s'], representation: 'ballstick', coloring: 'cpk' }] },
      currentGeometry: [
        { strand_id: 's', helix_id: 'h', bp_index: 0, direction: 'FORWARD' },
        { strand_id: 's', helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy_k: 1 },
        { strand_id: 'other', helix_id: 'h', bp_index: 0, direction: 'REVERSE' },
      ] }
    expect(strandRepresentationLayers(state)).toEqual([expect.objectContaining({
      strandId: 's', coloring: 'cpk', keys: ['h:0'], baseKeys: ['h:0:FORWARD', 'h:0:FORWARD:1'],
    })])
  })
})

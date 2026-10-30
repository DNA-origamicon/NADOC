import { describe, expect, it, vi } from 'vitest'
import { applyComparisonRepresentation, oxdnaPreviewInputsChanged } from './comparison_representations.js'

describe('comparison representations', () => {
  it.each([
    ['mrdna-coarse', 'coarse'],
    ['mrdna-fine', 'fine'],
  ])('routes %s through the current design input preview', async (representation, resolution) => {
    const geometry = [{ helix_id: 'h', bp_index: 1, axis_position: [0, 0, 0] }]
    const mrdnaDisplay = { stopAndRestore: vi.fn(), showInputPreview: vi.fn(() => ({ ok: true })) }
    const result = await applyComparisonRepresentation(representation, {
      setRepresentation: vi.fn(), mrdnaDisplay, getCurrentGeometry: () => geometry,
    })
    expect(result).toBe(true)
    expect(mrdnaDisplay.showInputPreview).toHaveBeenCalledWith(geometry, resolution)
  })

  it('restores mrDNA geometry before applying a native representation', async () => {
    const setRepresentation = vi.fn()
    const mrdnaDisplay = { stopAndRestore: vi.fn() }
    expect(await applyComparisonRepresentation('surface', { setRepresentation, mrdnaDisplay })).toBe(true)
    expect(mrdnaDisplay.stopAndRestore).toHaveBeenCalled()
    expect(setRepresentation).toHaveBeenCalledWith('surface')
  })

  it('routes oxDNA through the current design rigid-nucleotide preview', async () => {
    const geometry = [{ helix_id: 'h', bp_index: 1, backbone_position: [0, 0, 0] }]
    const mrdnaDisplay = { stopAndRestore: vi.fn(), showOxdnaInputPreview: vi.fn(() => ({ ok: true })) }
    expect(await applyComparisonRepresentation('oxdna', {
      setRepresentation: vi.fn(), mrdnaDisplay, getCurrentGeometry: () => geometry,
    })).toBe(true)
    expect(mrdnaDisplay.showOxdnaInputPreview).toHaveBeenCalledWith(geometry, undefined, undefined, undefined, undefined)
  })

  it('does not capture stale geometry when the current design has no geometry', async () => {
    const onUnavailable = vi.fn()
    expect(await applyComparisonRepresentation('mrdna-coarse', {
      setRepresentation: vi.fn(), mrdnaDisplay: {}, getCurrentGeometry: () => [], onUnavailable,
    })).toBe(false)
    expect(onUnavailable).toHaveBeenCalled()
  })
})

it('keeps oxDNA geometry through annotation edits and cloned autosave acknowledgements', () => {
  const state = { currentGeometry: [], currentDesign: { id: 'd', strands: [{ id: 's', sequence: 'AT' }],
    cluster_transforms: [], annotations: [], metadata: { name: 'd' }, loadouts: [] } }
  const saved = { ...state, currentDesign: JSON.parse(JSON.stringify(state.currentDesign)) }
  saved.currentDesign.annotations = [{ id: 'note', highlight: true }]
  saved.currentDesign.annotations_enabled = false
  saved.currentDesign.metadata.modified = 'now'
  saved.currentDesign.loadouts = [{ id: 'saved' }]
  saved.currentDesign.active_loadout_id = 'saved'
  expect(oxdnaPreviewInputsChanged(saved, state)).toBe(false)
  expect(oxdnaPreviewInputsChanged({ ...saved, currentGeometry: [{}] }, state)).toBe(true)
  expect(oxdnaPreviewInputsChanged({ ...saved, showReferenceGeometry: false }, state)).toBe(true)
  saved.currentDesign.strands[0].sequence = 'GC'
  expect(oxdnaPreviewInputsChanged(saved, state)).toBe(true)
})

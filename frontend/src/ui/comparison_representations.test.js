import { describe, expect, it, vi } from 'vitest'
import { applyComparisonRepresentation } from './comparison_representations.js'

describe('comparison representations', () => {
  it.each([
    ['mrdna-coarse', 'showBeads'],
    ['mrdna-fine', 'showDeform'],
  ])('routes %s through the selected mrDNA job', async (representation, method) => {
    const mrdnaDisplay = { stopAndRestore: vi.fn(), showBeads: vi.fn(), showDeform: vi.fn() }
    mrdnaDisplay[method].mockResolvedValue({ ok: true })
    const result = await applyComparisonRepresentation(representation, {
      setRepresentation: vi.fn(), mrdnaDisplay, getMrdnaJob: () => ({ job_id: 'job-7' }),
    })
    expect(result).toBe(true)
    expect(mrdnaDisplay[method]).toHaveBeenCalledWith('job-7')
  })

  it('restores mrDNA geometry before applying a native representation', async () => {
    const setRepresentation = vi.fn()
    const mrdnaDisplay = { stopAndRestore: vi.fn() }
    expect(await applyComparisonRepresentation('surface', { setRepresentation, mrdnaDisplay })).toBe(true)
    expect(mrdnaDisplay.stopAndRestore).toHaveBeenCalled()
    expect(setRepresentation).toHaveBeenCalledWith('surface')
  })

  it('does not capture stale geometry when no mrDNA job is selected', async () => {
    const onUnavailable = vi.fn()
    expect(await applyComparisonRepresentation('mrdna-coarse', {
      setRepresentation: vi.fn(), mrdnaDisplay: {}, getMrdnaJob: () => null, onUnavailable,
    })).toBe(false)
    expect(onUnavailable).toHaveBeenCalled()
  })
})

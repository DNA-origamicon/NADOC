import { beforeEach, describe, expect, it, vi } from 'vitest'
vi.mock('../api/client.js', () => ({ previewNucleotideReclassification: vi.fn() }))
vi.mock('../ui/primitives/confirm.js', () => ({ showConfirm: vi.fn() }))
import { previewNucleotideReclassification as preview } from '../api/client.js'
import { showConfirm } from '../ui/primitives/confirm.js'
import { confirmMoveReclassification } from './move_unpair_confirmation.js'

describe('Move unpair confirmation', () => {
  beforeEach(() => vi.resetAllMocks())
  it('does not prompt when both strands retain a common pose', async () => {
    preview.mockResolvedValue({ overhang_count: 0, confirmation_token: 'source' })
    expect(await confirmMoveReclassification([{ kind: 'base' }])).toEqual({ accepted: true, token: 'source' })
    expect(showConfirm).not.toHaveBeenCalled()
  })
  it.each([true, false])('only Continue returns authority to apply: %s', async accepted => {
    preview.mockResolvedValue({ overhang_count: 1, confirmation_token: 'source' })
    showConfirm.mockResolvedValue(accepted)
    expect(await confirmMoveReclassification([{ kind: 'base' }])).toEqual({
      accepted, token: accepted ? 'source' : null,
    })
    expect(showConfirm).toHaveBeenCalledWith(expect.objectContaining({
      confirmLabel: 'Continue', cancelLabel: 'Cancel',
      message: expect.stringContaining('3D geometry will be preserved'),
    }))
  })
  it('refuses an absent check response', async () => {
    preview.mockResolvedValue(null)
    await expect(confirmMoveReclassification([{ kind: 'base' }])).rejects.toThrow('Could not check')
    expect(showConfirm).not.toHaveBeenCalled()
  })
  it('describes an entirely detached staple as free ssDNA', async () => {
    preview.mockResolvedValue({ overhang_count: 0, free_strand_count: 1, confirmation_token: 'source' })
    showConfirm.mockResolvedValue(true)
    await confirmMoveReclassification([{ kind: 'base' }])
    expect(showConfirm).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Reclassify separated ssDNA', message: expect.stringContaining('become free ssDNA'),
    }))
  })
})

import { previewNucleotideReclassification } from '../api/client.js'
import { showConfirm } from '../ui/primitives/confirm.js'

/** Preview and consent are read-only; the caller owns Apply/Cancel and undo. */
export async function confirmMoveReclassification(transforms, { vr = false } = {}) {
  if (!transforms.some(t => t.kind === 'base')) return { accepted: true, token: null }
  const result = await previewNucleotideReclassification(transforms)
  if (!result?.confirmation_token) throw new Error('Could not check strand separation.')
  if (result.overhang_count > 0 || result.free_strand_count > 0) {
    const outcome = result.free_strand_count > 0
      ? (result.overhang_count > 0 ? 'overhangs or free ssDNA, depending on their remaining attachment' : 'free ssDNA')
      : 'an overhang'
    const accepted = await showConfirm({
      title: result.free_strand_count > 0 ? 'Reclassify separated ssDNA' : 'Convert separated segment to overhang',
      message: `The separated staple segments will become ${outcome} on new rows in the cadnano editor, with the same bp indices. The scaffold stays on its original helix. Your moved 3D geometry will be preserved.`,
      confirmLabel: 'Continue', cancelLabel: 'Cancel', vr,
    })
    if (!accepted) return { accepted: false, token: null }
  }
  return { accepted: true, token: result.confirmation_token }
}

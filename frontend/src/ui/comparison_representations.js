export const MRDNA_COARSE_REPRESENTATION = 'mrdna-coarse'
export const MRDNA_FINE_REPRESENTATION = 'mrdna-fine'

export function isMrdnaRepresentation(representation) {
  return representation === MRDNA_COARSE_REPRESENTATION || representation === MRDNA_FINE_REPRESENTATION
}

/** Apply a representation for the comparison tools, including mrDNA result geometry. */
export async function applyComparisonRepresentation(representation, {
  setRepresentation, mrdnaDisplay, getMrdnaJob, onUnavailable,
}) {
  if (!isMrdnaRepresentation(representation)) {
    mrdnaDisplay?.stopAndRestore?.()
    await setRepresentation(representation)
    return true
  }

  const job = getMrdnaJob?.()
  const jobId = job?.job_id ?? job?.id
  if (!jobId) {
    onUnavailable?.('Select a completed mrDNA job before using an mrDNA representation')
    return false
  }

  mrdnaDisplay?.stopAndRestore?.()
  const result = representation === MRDNA_COARSE_REPRESENTATION
    ? await mrdnaDisplay?.showBeads?.(jobId)
    : await mrdnaDisplay?.showDeform?.(jobId)
  if (!result?.ok) {
    onUnavailable?.(`${representation === MRDNA_COARSE_REPRESENTATION ? 'Coarse' : 'Fine'} mrDNA geometry is not ready for the selected job`)
    return false
  }
  return true
}

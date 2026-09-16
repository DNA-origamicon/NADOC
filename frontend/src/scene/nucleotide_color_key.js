// Shared by the Full-letter map and atomistic resolver. bp indices are local to
// a helix; loop copies at one site also have distinct sequence identities.
export function nucleotideColorKey(nuc, copy = nuc.copy_k ?? nuc.copy ?? 0) {
  return JSON.stringify([nuc.strand_id ?? '', nuc.helix_id ?? '', nuc.bp_index,
    nuc.direction, Number(copy)])
}

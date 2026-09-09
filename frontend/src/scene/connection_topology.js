// Pure signatures used by renderer rebuild guards. Every rendered connection
// field belongs here; omitting one can misclassify a topology edit as display-only.

const crossoverSignature = crossover => [
  crossover.id,
  crossover.half_a?.helix_id, crossover.half_a?.index, crossover.half_a?.strand,
  crossover.half_b?.helix_id, crossover.half_b?.index, crossover.half_b?.strand,
  crossover.extra_bases ?? null,
]

const forcedLigationSignature = ligation => [
  ligation.id,
  ligation.three_prime_helix_id, ligation.three_prime_bp, ligation.three_prime_direction,
  ligation.five_prime_helix_id, ligation.five_prime_bp, ligation.five_prime_direction,
  ligation.extra_bases ?? null, !!ligation.is_periodic_seam,
]

const sameSignatures = (left, right, signature) =>
  JSON.stringify((left ?? []).map(signature)) === JSON.stringify((right ?? []).map(signature))

export const sameCrossoverTopology = (leftDesign, rightDesign) =>
  sameSignatures(leftDesign?.crossovers, rightDesign?.crossovers, crossoverSignature)

export const sameForcedLigationTopology = (leftDesign, rightDesign) =>
  sameSignatures(leftDesign?.forced_ligations, rightDesign?.forced_ligations, forcedLigationSignature)

export const sameConnectionTopology = (leftDesign, rightDesign) =>
  sameCrossoverTopology(leftDesign, rightDesign) &&
  sameForcedLigationTopology(leftDesign, rightDesign)

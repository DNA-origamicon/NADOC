/** Crossover arcs belong to the full representation at both endpoints. */
export function crossoverArcHiddenForRepresentations(fromRepresentation, toRepresentation) {
  return fromRepresentation !== 'full' || toRepresentation !== 'full'
}

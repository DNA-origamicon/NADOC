// Canonical caDNAno staple-crossover lookup. Mirrors
// backend/core/constants.py and backend/core/crossover_positions.py.

const HC = {
  '1_0':[0,-1], '1_6':[0,1], '1_7':[0,1], '1_13':[-1,0], '1_14':[-1,0], '1_20':[0,-1],
  '0_0':[0,1],  '0_6':[0,-1], '0_7':[0,-1], '0_13':[1,0], '0_14':[1,0], '0_20':[0,1],
}

const SQ = {
  '1_0':[0,1], '1_31':[0,1], '1_23':[1,0], '1_24':[1,0],
  '1_15':[0,-1], '1_16':[0,-1], '1_7':[-1,0], '1_8':[-1,0],
  '0_0':[0,-1], '0_31':[0,-1], '0_23':[-1,0], '0_24':[-1,0],
  '0_15':[0,1], '0_16':[0,1], '0_7':[1,0], '0_8':[1,0],
}

/** Return the one lattice cell addressed by a staple crossover at bp, or null. */
export function stapleCrossoverNeighbor(latticeType, row, col, bp) {
  const square = String(latticeType).toUpperCase() === 'SQUARE'
  const period = square ? 32 : 21
  const table = square ? SQ : HC
  const forward = (((row + col) % 2) + 2) % 2 === 0
  const mod = ((bp % period) + period) % period
  const delta = table[`${forward ? 1 : 0}_${mod}`]
  return delta ? [row + delta[0], col + delta[1]] : null
}

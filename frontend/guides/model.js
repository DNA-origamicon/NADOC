// User-selected guide convention: three rows × six columns, square lattice.
// Length is a lesson parameter, not part of the shared footprint convention.
export const DEFAULT_GUIDE_MODEL = Object.freeze({ lattice: 'SQUARE', rows: 3, columns: 6 })
export const guideCells = (row = 0, column = 1) => Array.from(
  { length: DEFAULT_GUIDE_MODEL.rows * DEFAULT_GUIDE_MODEL.columns },
  (_, index) => [row + Math.floor(index / DEFAULT_GUIDE_MODEL.columns), column + index % DEFAULT_GUIDE_MODEL.columns],
)

// All lessons use Full; only the representations lesson may demonstrate other modes.
export const DEFAULT_GUIDE_REPRESENTATION = 'full'

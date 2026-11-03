/** Cell coordinates are local to a lattice frame, including Sweep segments. */
export function crossoverCellKey(helix, row, col) {
  return JSON.stringify([helix?.lattice_frame_id ?? null, row, col])
}

import { isAtomSelected } from './color_resolver.js'
import { atomBondSelection } from './selection_bonds.js'

/** Instance identities only: the outline samples their live matrices every frame. */
export function atomisticSelectionEntries(state) {
  const selection = state.lastSel
  if (!selection || state.mode === 'off') return []
  const bonds = atomBondSelection(state.atoms, state.topologyBonds, selection.bonds, state.mode === 'vdw')
  const rows = new Set(), entries = []
  for (const [element, group] of Object.entries(state.elementAtoms)) {
    const mesh = state.elementMeshes[element]
    for (let i = 0; i < group.length; i++) {
      const row = group[i]
      if (!bonds.atomRows.has(row) && !isAtomSelected(state.atoms.get(row), selection)) continue
      rows.add(row)
      if (state.mode !== 'stick') entries.push({ instMesh: mesh, id: i })
    }
  }
  const indices = state.bondAtomIdx
  if (state.bondMesh) for (let i = 0; i < (indices?.length ?? 0) / 2; i++) {
    const a = indices[i * 2], b = indices[i * 2 + 1]
    if ((rows.has(a) && rows.has(b)) || bonds.has(a, b)) entries.push({ instMesh: state.bondMesh, id: i })
  }
  return entries
}

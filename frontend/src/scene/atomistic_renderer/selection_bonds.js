import { atomBaseKey } from '../base_ref.js'
import { atomSelectionBondKey } from '../atom_selection_connections.js'
import { buildAtomSerialIndex } from '../atom_serial_index.js'

/** Select real covalent bonds; VDW exposes their endpoint atoms instead of cylinders. */
export function atomBondSelection(table, topology, pairs, selectEndpointAtoms = false) {
  const wanted = new Set((pairs ?? []).map(([a, b]) => atomSelectionBondKey(a, b)))
  const atomRows = new Set()
  if (!wanted.size) return { has: () => false, atomRows }
  const keys = Array.from({ length: table.count }, (_, r) => atomBaseKey(table.get(r)))
  const has = (a, b) => wanted.has(atomSelectionBondKey(keys[a], keys[b]))
  if (selectEndpointAtoms && topology) {
    const rows = buildAtomSerialIndex(table)
    const flat = ArrayBuffer.isView(topology)
    const count = flat ? topology.length / 2 : topology.length
    for (let i = 0; i < count; i++) {
      const a = rows.get(flat ? topology[i * 2] : topology[i][0])
      const b = rows.get(flat ? topology[i * 2 + 1] : topology[i][1])
      if (a !== undefined && b !== undefined && has(a, b)) { atomRows.add(a); atomRows.add(b) }
    }
  }
  return { has, atomRows }
}

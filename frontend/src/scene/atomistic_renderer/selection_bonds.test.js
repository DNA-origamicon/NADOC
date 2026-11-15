import { it, expect } from 'vitest'
import { makeAtomTable } from '../atom_table.js'
import { atomBondSelection } from './selection_bonds.js'

it('resolves sparse serials and flat bonds without widening an endpoint residue', () => {
  const table = makeAtomTable({ atoms: [
    { serial: 8, helix_id: 'h', bp_index: 0, direction: 'FORWARD' },
    { serial: 50, helix_id: 'h', bp_index: 1, direction: 'FORWARD' },
    { serial: 2, helix_id: 'h', bp_index: 0, direction: 'FORWARD' },
  ] })
  const topology = new Int32Array([8, 50, 8, 2, 8, 999])
  const pairs = [['h:0:FORWARD', 'h:1:FORWARD']]
  const selected = atomBondSelection(table, topology, pairs, true)
  expect([...selected.atomRows]).toEqual([0, 1])
  expect(selected.has(1, 0)).toBe(true)
  expect(selected.has(0, 2)).toBe(false)
  expect(atomBondSelection(table, topology, pairs).atomRows.size).toBe(0)
  expect(atomBondSelection(table, topology, []).has(0, 1)).toBe(false)
})

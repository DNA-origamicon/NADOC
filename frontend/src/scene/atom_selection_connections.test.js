import { it, expect } from 'vitest'
import { atomSelectionConnections, atomSelectionBondKey } from './atom_selection_connections.js'
import { atomSelectionForState } from './atom_surface_display.js'
import { colorForAtom } from './atomistic_renderer/color_resolver.js'

it('selects exactly the recorded connection path, including inserted bases and forced ligations', () => {
  const design = { crossovers: [{ id: 'x', half_a: { helix_id: 'a', index: 3, strand: 'FORWARD' }, half_b: { helix_id: 'b', index: 7, strand: 'REVERSE' }, extra_bases: 'T' }],
    forced_ligations: [{ id: 'f', three_prime_helix_id: 'c', three_prime_bp: 8, three_prime_direction: 'REVERSE', five_prime_helix_id: 'd', five_prime_bp: 2, five_prime_direction: 'FORWARD' }] }
  const result = atomSelectionConnections({ crossovers: [{ id: 'x' }, { id: 'f', subtype: 'forced_ligation' }] }, design)
  expect(result.bonds).toEqual([['a:3:FORWARD', '__xb__:x:0'], ['__xb__:x:0', 'b:7:REVERSE'], ['c:8:REVERSE', 'd:2:FORWARD']])
  expect(result.bases).toEqual([{ helix_id: '__xb__', crossover_id: 'x', k: 0 }])
  expect(atomSelectionBondKey('a', 'b')).toBe(atomSelectionBondKey('b', 'a'))
})

it('bond selection does not widen to the strand or its endpoint residues', () => {
  const result = atomSelectionForState({ selection: { items: [{ kind: 'bond', fromKey: 'h:1:FORWARD', toKey: 'h:2:FORWARD', strandId: 's' }] } })
  expect(result.strandIds).toEqual([])
  expect(result.bases).toEqual([])
  expect(result.bonds).toEqual([['h:1:FORWARD', 'h:2:FORWARD']])
})

it('base and End colors honor insertion copies and extra-base identities', () => {
  const ctx = { colorMode: 'cpk' }
  const atom = { element: 'O', helix_id: 'h', bp_index: 1, direction: 'FORWARD', copy_k: 1 }
  const selection = atomSelectionForState({ selection: { items: [{ kind: 'end', key: 'h:1:FORWARD:1' }, { kind: 'base', key: '__xb__:x:2' }] } })
  expect(colorForAtom(ctx, atom, selection)).toBe(0xffffff)
  expect(colorForAtom(ctx, { ...atom, copy_k: 0 }, selection)).not.toBe(0xffffff)
  expect(colorForAtom(ctx, { ...atom, crossover_id: 'x', extra_base_k: 2 }, selection)).toBe(0xffffff)
  expect(colorForAtom(ctx, { ...atom, crossover_id: 'x', extra_base_k: 1 }, selection)).not.toBe(0xffffff)
})

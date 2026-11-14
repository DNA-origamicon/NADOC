import { expect, it, vi } from 'vitest'
import { createMdInsetAtomHub, canonicalAtomName } from './md_inset_atoms.js'

it('requests the union of inset residues only when it changes', () => {
  const hub = createMdInsetAtomHub(), listener = vi.fn()
  hub.onRequest(listener)
  hub.setResidues('a', ['h:1:FORWARD', 'h:2:FORWARD'])
  hub.setResidues('b', ['h:2:FORWARD', '__xb__:xo:0'])
  hub.setResidues('b', ['__xb__:xo:0', 'h:2:FORWARD'])
  expect(listener).toHaveBeenCalledTimes(2)
  expect(hub.residueKeys()).toEqual(['__xb__:xo:0', 'h:1:FORWARD', 'h:2:FORWARD'])
  hub.setResidues('a', null); hub.setResidues('b', [])
  expect(listener).toHaveBeenLastCalledWith([])
})

it('publishes frame atoms under canonical design names and clears them', () => {
  const hub = createMdInsetAtomHub(), start = hub.version()
  hub.publish([['h:1:FORWARD', 'O1P', 1, 2, 3], ['__xb__:xo:0', 'C5M', 4, 5, 6], ['h:1:FORWARD', "O3'", 7, 8, 9]])
  expect([...hub.atoms()]).toEqual([['h:1:FORWARD:OP1', [1, 2, 3]], ['__xb__:xo:0:C7', [4, 5, 6]], ["h:1:FORWARD:O3'", [7, 8, 9]]])
  expect(hub.version()).toBe(start + 1)
  hub.clear(); expect(hub.atoms()).toBeNull()
  expect(canonicalAtomName('O2P')).toBe('OP2'); expect(canonicalAtomName('P')).toBe('P')
})

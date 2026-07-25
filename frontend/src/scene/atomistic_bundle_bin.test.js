import { describe, expect, it } from 'vitest'

import { parseAtomisticBundleBin } from './atomistic_bundle_bin.js'
import { makeAtomTable } from './atom_table.js'

/**
 * The blob below was produced by the REAL backend encoder
 * (backend/core/atomistic.pack_bundle_bin) — regenerate with:
 *
 *   uv run python -c "from backend.core.atomistic import pack_bundle_bin; ..."
 *
 * for these three atoms:
 *   0  P  (1.5, -2.25, 3.0)     sc   h_a  bp 7    FORWARD
 *   1  C  (0.0,  0.5,  0.0)     st1  h_b  bp 231  REVERSE  aux h_a @ 0.25
 *   2  O  (-9.75, 4.5, 0.125)   sc   h_a  bp 8    REVERSE
 *   bonds [[0,1],[1,2]]  atom_nuc [0,-1,1]  atom_local 0..8  nonrigid [1]  n_nuc 2
 *
 * Pinning a real encoder output (rather than a hand-rolled one) is the point: the wire
 * layout is a contract between two languages and nothing else checks both ends at once.
 */
const FIXTURE_B64 =
  'MUJBTgEAAAADAAAAAgAAAAMBAAB7InN0cmFuZF90YWJsZSI6IFsic2MiLCAic3QxIl0sICJoZWxpeF90YWJsZSI6IFsi' +
  'aF9hIiwgImhfYiJdLCAiYXV4X2hlbGl4X3RhYmxlIjogWyIiLCAiaF9hIl0sICJlbGVtZW50X3RhYmxlIjogWyJQIiwg' +
  'IkMiLCAiTyJdLCAiZGlyX3RhYmxlIjogWyJGT1JXQVJEIiwgIlJFVkVSU0UiXSwgImVsZW1lbnRfbWV0YSI6IHsiUCI6' +
  'IHsidmR3X3JhZGl1cyI6IDAuMTksICJjcGtfY29sb3IiOiAxNjc0NzUyMH19LCAidG9wb2xvZ3lfaGFzaCI6ICJUSEFT' +
  'SCJ9AAAAwD8AAAAAAAAcwQAAEMAAAAA/AACQQAAAQEAAAAAAAAAAPgcAAADnAAAACAAAAAAAAAAAAIA+AAAAAAAAAQAA' +
  'AAAAAQAAAAAAAQAAAAABAgABAQAAAAABAAAAAQAAAAIAAAACAAAAAQAAAAAAAAD/////AQAAAAAAAAAAAIA/AAAAQAAA' +
  'QEAAAIBAAACgQAAAwEAAAOBAAAAAQQEAAAA='

function fixture() {
  const bin = atob(FIXTURE_B64)
  const u8 = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
  return u8.buffer
}

describe('parseAtomisticBundleBin', () => {
  it('decodes a real backend-encoded bundle', () => {
    const c = parseAtomisticBundleBin(fixture())
    expect(c).toBeTruthy()
    expect(c.columnar).toBe(true)
    expect(c.count).toBe(3)
    expect(Array.from(c.x)).toEqual([1.5, 0, -9.75])
    expect(Array.from(c.y)).toEqual([-2.25, 0.5, 4.5])
    expect(Array.from(c.z)).toEqual([3, 0, 0.125])
    expect(Array.from(c.bpIndex)).toEqual([7, 231, 8])
    expect(Array.from(c.auxT)).toEqual([0, 0.25, 0])
    expect(c.strandTable).toEqual(['sc', 'st1'])
    expect(c.dirTable).toEqual(['FORWARD', 'REVERSE'])
    expect(Array.from(c.bonds)).toEqual([0, 1, 1, 2])
    expect(c.topology_hash).toBe('THASH')
    expect(c.element_meta.P.cpk_color).toBe(16747520)
  })

  it('carries the stamp descriptor with its NEGATIVE non-rigid sentinel intact', () => {
    // atom_nuc must be signed: as u32 the -1 becomes 4294967295 and expandStampFrames
    // would index frames[] wildly out of range instead of skipping the atom.
    const c = parseAtomisticBundleBin(fixture())
    expect(Array.from(c.atom_nuc)).toEqual([0, -1, 1])
    expect(Array.from(c.atom_local)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8])
    expect(Array.from(c.nonrigid_serials)).toEqual([1])
    expect(c.n_nuc).toBe(2)
    expect(c.n_atoms).toBe(3)
  })

  it('returns null for junk, a bad magic, an unknown version, and an empty payload', () => {
    expect(parseAtomisticBundleBin(null)).toBeNull()
    expect(parseAtomisticBundleBin(new ArrayBuffer(4))).toBeNull()
    const bad = new Uint8Array(fixture().slice(0))
    bad[0] ^= 0xff                                   // corrupt the magic
    expect(parseAtomisticBundleBin(bad.buffer)).toBeNull()
    const wrongVer = new Uint8Array(fixture().slice(0))
    new DataView(wrongVer.buffer).setUint32(4, 99, true)
    expect(parseAtomisticBundleBin(wrongVer.buffer)).toBeNull()
    const empty = new Uint8Array(fixture().slice(0))
    new DataView(empty.buffer).setUint32(8, 0, true)  // nAtoms = 0
    expect(parseAtomisticBundleBin(empty.buffer)).toBeNull()
  })
})

describe('makeAtomTable over a decoded columnar bundle', () => {
  const c = parseAtomisticBundleBin(fixture())

  it('reads back every field the renderer and colour resolver use', () => {
    const t = makeAtomTable(c)
    expect(t.columnar).toBe(true)
    expect(t.count).toBe(3)
    const a1 = t.get(1)
    expect(a1.serial).toBe(1)
    expect(a1.element).toBe('C')
    expect(a1.x).toBe(0)
    expect(a1.y).toBe(0.5)
    expect(a1.strand_id).toBe('st1')
    expect(a1.helix_id).toBe('h_b')
    expect(a1.bp_index).toBe(231)
    expect(a1.direction).toBe('REVERSE')
    expect(a1.aux_helix_id).toBe('h_a')
    expect(a1.aux_t).toBe(0.25)
    // Atoms with no aux helix must read as falsy — colour_resolver and atomOffset both
    // branch on `!atom.aux_helix_id`, so a stray placeholder would mis-colour every atom.
    expect(t.get(0).aux_helix_id).toBe('')
    expect(t.get(0).aux_t).toBe(0)
  })

  it('scalar accessors agree with the object view', () => {
    const t = makeAtomTable(c)
    for (let i = 0; i < t.count; i++) {
      const a = t.get(i)
      expect([t.x(i), t.y(i), t.z(i)]).toEqual([a.x, a.y, a.z])
      expect(t.element(i)).toBe(a.element)
      expect(t.helixId(i)).toBe(a.helix_id)
      expect(t.serial(i)).toBe(a.serial)
    }
  })

  it('get() returns a SHARED flyweight; materialize() returns an owned copy', () => {
    const t = makeAtomTable(c)
    const first = t.get(0)
    expect(first.element).toBe('P')
    t.get(2)                                  // re-point the flyweight
    expect(first.element).toBe('O')           // …the old handle followed it — by design
    const owned = t.materialize(0)
    t.get(2)
    expect(owned.element).toBe('P')           // a materialized atom does NOT follow
    expect(owned.strand_id).toBe('sc')
    expect(owned.bp_index).toBe(7)
  })
})

describe('makeAtomTable over a legacy object array', () => {
  const atoms = [
    { serial: 5, element: 'N', x: 1, y: 2, z: 3, strand_id: 's', helix_id: 'h',
      bp_index: 4, direction: 'FORWARD', aux_helix_id: '', aux_t: 0 },
  ]

  it('passes the real records straight through (no copy, no flyweight)', () => {
    const t = makeAtomTable({ atoms })
    expect(t.columnar).toBe(false)
    expect(t.count).toBe(1)
    expect(t.get(0)).toBe(atoms[0])
    expect(t.materialize(0)).toBe(atoms[0])
    expect(t.serial(0)).toBe(5)              // NOT the row index on this path
    expect(t.element(0)).toBe('N')
    expect(t.helixId(0)).toBe('h')
  })

  it('tolerates the empty/clear idioms the other producers use', () => {
    expect(makeAtomTable(null).count).toBe(0)
    expect(makeAtomTable({}).count).toBe(0)
    expect(makeAtomTable({ atoms: [] }).count).toBe(0)
  })
})

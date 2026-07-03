import { describe, it, expect } from 'vitest'
import { orderStrandNucleotides } from './helix_renderer.js'

// A nucleotide with just the fields orderStrandNucleotides reads. `z` stands in for
// the axial coordinate so we can assert monotone backbone threading through a loop.
const nuc = (bp, dir, z, copyHint = 0) => ({
  helix_id: 'h0', bp_index: bp, direction: dir, domain_index: 0, z, _copyHint: copyHint,
})

// A loop insertion at bp5 emits copies in ascending-axial (emission) order: copy0 low,
// copy1 high. The geometry list yields them in that order regardless of strand direction.
const loopCopiesAscending = (dir, z0, z1) => [nuc(5, dir, z0, 0), nuc(5, dir, z1, 1)]

describe('orderStrandNucleotides', () => {
  it('threads a FORWARD strand up the axis through a loop (copies 0→1)', () => {
    // built out of order on purpose; emission order of the loop copies is ascending
    const nucs = [nuc(4, 'FORWARD', 1.34), ...loopCopiesAscending('FORWARD', 1.50, 1.84), nuc(6, 'FORWARD', 2.00)]
    orderStrandNucleotides(nucs)
    const zs = nucs.map(n => n.z)
    expect(zs).toEqual([...zs].sort((a, b) => a - b))         // strictly ascending
  })

  it('threads a REVERSE strand down the axis through a loop (copies 1→0)', () => {
    // REVERSE strand descends bp (6→5→4); the loop copies must be visited high→low
    const nucs = [nuc(6, 'REVERSE', 2.00), ...loopCopiesAscending('REVERSE', 1.50, 1.84), nuc(4, 'REVERSE', 1.34)]
    orderStrandNucleotides(nucs)
    const zs = nucs.map(n => n.z)
    expect(zs).toEqual([...zs].sort((a, b) => b - a))         // strictly descending — no zig-zag
    // the high copy (copy 1) is threaded before the low copy (copy 0)
    const copies = nucs.filter(n => n.bp_index === 5)
    expect(copies.map(n => n._copyHint)).toEqual([1, 0])
  })

  it('is a no-op ordering for a strand without loops (plain ascending FORWARD)', () => {
    const nucs = [nuc(2, 'FORWARD', 0.7), nuc(0, 'FORWARD', 0.0), nuc(1, 'FORWARD', 0.34)]
    orderStrandNucleotides(nucs)
    expect(nucs.map(n => n.bp_index)).toEqual([0, 1, 2])
  })
})

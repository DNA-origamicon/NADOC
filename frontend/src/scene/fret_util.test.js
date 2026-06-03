import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { fretQuenchedDonors } from './fret_util.js'

const entry = (modification, pos) => ({ nuc: { modification }, pos: new THREE.Vector3(...pos) })
const donorMap = new Map([['Cy3', ['Cy5']]])
const r0Map = new Map([['Cy3:Cy5', 6]])

describe('fretQuenchedDonors', () => {
  it('quenches a donor within r0 of a compatible acceptor', () => {
    const donor = entry('Cy3', [0, 0, 0])
    const acceptor = entry('Cy5', [3, 0, 0]) // 3 nm < r0 6
    const q = fretQuenchedDonors([donor, acceptor], donorMap, r0Map)
    expect(q.has(donor)).toBe(true)
    expect(q.has(acceptor)).toBe(false) // Cy5 is not a donor
  })

  it('does NOT quench when the acceptor is beyond r0', () => {
    const donor = entry('Cy3', [0, 0, 0])
    const acceptor = entry('Cy5', [10, 0, 0]) // 10 nm > r0 6
    expect(fretQuenchedDonors([donor, acceptor], donorMap, r0Map).size).toBe(0)
  })

  it('ignores entries without a modification or not registered as a donor', () => {
    const plain = entry(undefined, [0, 0, 0])
    const nonDonor = entry('FAM', [0, 0, 0])
    const acceptor = entry('Cy5', [1, 0, 0])
    expect(fretQuenchedDonors([plain, nonDonor, acceptor], donorMap, r0Map).size).toBe(0)
  })

  it('does not quench a lone donor with no acceptor present', () => {
    const donor = entry('Cy3', [0, 0, 0])
    expect(fretQuenchedDonors([donor], donorMap, r0Map).size).toBe(0)
  })

  it('skips pairs with no r0 entry for the donor:acceptor combo', () => {
    const donor = entry('Cy3', [0, 0, 0])
    const acceptor = entry('Cy5', [1, 0, 0])
    const emptyR0 = new Map()
    expect(fretQuenchedDonors([donor, acceptor], donorMap, emptyR0).size).toBe(0)
  })
})

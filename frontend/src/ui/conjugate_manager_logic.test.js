import { describe, it, expect } from 'vitest'
import {
  CHEMISTRY_META,
  chemistryColor,
  chemistryCss,
  candidateLabel,
  summarizeCandidates,
  reverseComplement,
  overhangLabel,
  radialOutward,
  ssdnaBackbonePoints,
  ssdnaHelixFrames,
  SSDNA_PREVIEW_RADIUS_NM,
  SSDNA_PREVIEW_RISE_NM,
  SSDNA_PREVIEW_TWIST_RAD,
  perpendicular,
} from './conjugate_manager_logic.js'

describe('chemistryColor / chemistryCss', () => {
  it('returns the configured color per chemistry', () => {
    expect(chemistryColor('lys')).toBe(CHEMISTRY_META.lys.color)
    expect(chemistryColor('cys')).toBe(CHEMISTRY_META.cys.color)
    expect(chemistryColor('nterm')).toBe(CHEMISTRY_META.nterm.color)
  })
  it('falls back to grey for an unknown chemistry', () => {
    expect(chemistryColor('zzz')).toBe(0x999999)
  })
  it('formats css as a 6-digit hex string', () => {
    expect(chemistryCss('lys')).toBe('#39ff14')
    expect(chemistryCss('nterm')).toBe('#ff2fd0')
  })
})

describe('candidateLabel', () => {
  it('renders residue, chain:seq and the reactive site', () => {
    expect(candidateLabel({ res_name: 'LYS', chain_id: 'A', res_seq: 142, chemistry: 'lys' }))
      .toBe('LYS A:142 — ε-amine')
    expect(candidateLabel({ res_name: 'CYS', chain_id: 'B', res_seq: 7, chemistry: 'cys' }))
      .toBe('CYS B:7 — thiol')
  })
})

describe('summarizeCandidates', () => {
  it('counts per chemistry in stable lys→cys→nterm order, omitting empties', () => {
    const cands = [
      { chemistry: 'cys' }, { chemistry: 'lys' }, { chemistry: 'lys' }, { chemistry: 'nterm' }, { chemistry: 'lys' },
    ]
    const summary = summarizeCandidates(cands)
    expect(summary.map(s => s.chemistry)).toEqual(['lys', 'cys', 'nterm'])
    expect(summary.map(s => s.count)).toEqual([3, 1, 1])
    // cys absent → omitted
    expect(summarizeCandidates([{ chemistry: 'lys' }]).map(s => s.chemistry)).toEqual(['lys'])
  })
  it('returns [] for no candidates', () => {
    expect(summarizeCandidates([])).toEqual([])
    expect(summarizeCandidates()).toEqual([])
  })
})

describe('reverseComplement', () => {
  it('reverse-complements a DNA sequence', () => {
    expect(reverseComplement('ATGC')).toBe('GCAT')
    expect(reverseComplement('AAAA')).toBe('TTTT')
    expect(reverseComplement('GATTACA')).toBe('TGTAATC')
  })
  it('lowercases and maps unknown bases to N; empty/nullish → ""', () => {
    expect(reverseComplement('atgc')).toBe('GCAT')
    expect(reverseComplement('ANXG')).toBe('CNNT')   // X→N, then reversed+complemented
    expect(reverseComplement('')).toBe('')
    expect(reverseComplement(null)).toBe('')
    expect(reverseComplement(undefined)).toBe('')
  })
})

describe('overhangLabel', () => {
  it('uses label or id and shows nt count', () => {
    expect(overhangLabel({ label: 'A1', sequence: 'ATGC' })).toBe('A1 (4 nt)')
    expect(overhangLabel({ id: 'ovhg_x', sequence: '' })).toBe('ovhg_x (no seq)')
    expect(overhangLabel({ id: 'ovhg_y' })).toBe('ovhg_y (no seq)')
  })
})

describe('radialOutward', () => {
  it('returns the unit vector from centroid to point', () => {
    const v = radialOutward({ x: 3, y: 0, z: 0 }, { x: 0, y: 0, z: 0 })
    expect(v).toEqual({ x: 1, y: 0, z: 0 })
    const d = radialOutward({ x: 0, y: 0, z: 5 }, { x: 0, y: 0, z: 2 })
    expect(d).toEqual({ x: 0, y: 0, z: 1 })
  })
  it('falls back to +Z when point equals centroid', () => {
    expect(radialOutward({ x: 1, y: 1, z: 1 }, { x: 1, y: 1, z: 1 })).toEqual({ x: 0, y: 0, z: 1 })
  })
})

describe('ssdnaBackbonePoints', () => {
  it('steps `count` beads of `rise` nm along the direction from the start', () => {
    const pts = ssdnaBackbonePoints({ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }, 3, 0.5)
    expect(pts).toEqual([
      { x: 0, y: 0, z: 0 },
      { x: 0.5, y: 0, z: 0 },
      { x: 1, y: 0, z: 0 },
    ])
  })
  it('clamps to at least one bead', () => {
    expect(ssdnaBackbonePoints({ x: 0, y: 0, z: 0 }, { x: 0, y: 1, z: 0 }, 0).length).toBe(1)
  })
})

describe('ssdnaHelixFrames', () => {
  const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z
  it('uses the same B-form rise, radius, and twist as overhang previews', () => {
    const axis = { x: 0, y: 0, z: 1 }
    const frames = ssdnaHelixFrames({ x: 0, y: 0, z: 0 }, axis, 5)
    expect(frames).toHaveLength(5)
    frames.forEach((frame, i) => {
      expect(frame.position.z).toBeCloseTo(i * SSDNA_PREVIEW_RISE_NM, 9)
      expect(Math.hypot(frame.position.x, frame.position.y)).toBeCloseTo(SSDNA_PREVIEW_RADIUS_NM, 9)
      expect(dot(frame.baseNormal, axis)).toBeCloseTo(0, 9)
    })
    const a = frames[0].position, b = frames[1].position
    const angle = Math.acos((a.x * b.x + a.y * b.y) / (SSDNA_PREVIEW_RADIUS_NM ** 2))
    expect(angle).toBeCloseTo(SSDNA_PREVIEW_TWIST_RAD, 9)
  })
  it('returns a frame even for an empty requested sequence', () => {
    expect(ssdnaHelixFrames({ x: 1, y: 2, z: 3 }, { x: 1, y: 0, z: 0 }, 0)).toHaveLength(1)
  })
})

describe('perpendicular', () => {
  const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z
  const mag = (v) => Math.sqrt(dot(v, v))
  it('returns a unit vector orthogonal to dir', () => {
    for (const dir of [{ x: 1, y: 0, z: 0 }, { x: 0, y: 0, z: 1 }, { x: 0.6, y: 0.8, z: 0 }]) {
      const p = perpendicular(dir)
      expect(Math.abs(dot(p, dir))).toBeLessThan(1e-9)
      expect(mag(p)).toBeCloseTo(1, 9)
    }
  })
})

import { describe, it, expect } from 'vitest'
import { cylinderSegments, jetRGB } from './cando_cylinders.js'

describe('cylinderSegments', () => {
  it('emits consecutive-node tube segments per helix (mean-RMSF) + the joints, no spheres', () => {
    const data = {
      helices: [
        { helix_id: 'h0', points: [[0, 0, 0], [1, 0, 0], [2, 0, 0]], rmsf: [2, 6, 10] },
        { helix_id: 'h1', points: [[0, 1, 0], [0, 2, 0]], rmsf: [4, 8] },
      ],
      joints: [[[0, 0, 0], [0, 1, 0]]],
      joint_rmsf: [6],
    }
    const { tubes, joints } = cylinderSegments(data)
    expect(tubes).toEqual([
      { a: [0, 0, 0], b: [1, 0, 0], rmsf: 4 },     // mean(2,6)
      { a: [1, 0, 0], b: [2, 0, 0], rmsf: 8 },     // mean(6,10)
      { a: [0, 1, 0], b: [0, 2, 0], rmsf: 6 },     // mean(4,8)
    ])
    expect(joints).toEqual([{ a: [0, 0, 0], b: [0, 1, 0], rmsf: 6 }])
  })

  it('rmsf is null when a node has no value; single-node helix yields no segment', () => {
    const { tubes } = cylinderSegments({ helices: [{ helix_id: 'h', points: [[0, 0, 0], [1, 0, 0]], rmsf: [] }] })
    expect(tubes).toEqual([{ a: [0, 0, 0], b: [1, 0, 0], rmsf: null }])
    expect(cylinderSegments({ helices: [{ helix_id: 'h', points: [[0, 0, 0]] }] }).tubes).toEqual([])
  })

  it('handles empty/missing input', () => {
    expect(cylinderSegments({})).toEqual({ tubes: [], joints: [] })
    expect(cylinderSegments(null)).toEqual({ tubes: [], joints: [] })
  })
})

describe('jetRGB (CanDo heat map)', () => {
  it('sweeps the vivid jet: blue → cyan → green → yellow → red', () => {
    expect(jetRGB(0)).toEqual([0, 0, 1])       // blue (low RMSF)
    expect(jetRGB(0.25)).toEqual([0, 1, 1])    // cyan
    expect(jetRGB(0.5)).toEqual([0, 1, 0])     // green
    expect(jetRGB(0.75)).toEqual([1, 1, 0])    // yellow
    expect(jetRGB(1)).toEqual([1, 0, 0])       // red (high RMSF)
  })
  it('clamps out-of-range t', () => {
    expect(jetRGB(-1)).toEqual(jetRGB(0))
    expect(jetRGB(2)).toEqual(jetRGB(1))
    expect(jetRGB(NaN)).toEqual(jetRGB(0))
  })
})

describe('cylinder GPU lifecycle', () => {
  it('recolors existing instances and releases cached geometry on Off', async () => {
    const THREE = await import('three')
    const { initCandoCylinders } = await import('./cando_cylinders.js')
    const scene = new THREE.Scene(), overlay = initCandoCylinders(scene)
    overlay.update({ helices: [{ points: [[0,0,0],[0,2,0]], rmsf: [1,2] }], has_rmsf: true, rmsf_min: 0, rmsf_p95: 2 })
    const mesh = scene.children[0], matrix = [...mesh.instanceMatrix.array]
    overlay.recolor(0, 8, 'viridis')
    expect(scene.children[0]).toBe(mesh)
    expect([...mesh.instanceMatrix.array]).toEqual(matrix)
    overlay.clear()
    overlay.recolor(0, 1)
    expect(scene.children).toHaveLength(0)
  })
})

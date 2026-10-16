// @vitest-environment node
import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { ARC_SEGS, buildNativeConnectionLines, writeNativeConnectionArc } from './native_connection_lines.js'

describe('shared native ordinary connection buffers', () => {
  it.each([0, .3, 1])('preserves every original Float32 quadratic sample at unfold fraction %s', t => {
    const from = new THREE.Vector3(-2, 3, 1), to = new THREE.Vector3(8, -4, 2)
    const control = from.clone().add(to).multiplyScalar(.5)
    control.z += from.distanceTo(to) * .15 * t
    const actual = new Float32Array(126), original = new Float32Array(126), base = 21
    // Frozen pre-extraction loop is the numerical oracle, including operation
    // order and Float32 writes; not a separately inferred line definition.
    for (let j = 0; j <= 20; j++) {
      const u = j / 20, u2 = 1 - u
      const w0 = u2 * u2, w1 = 2 * u2 * u, w2 = u * u
      const bi = (base + j) * 3
      original[bi] = w0 * from.x + w1 * control.x + w2 * to.x
      original[bi + 1] = w0 * from.y + w1 * control.y + w2 * to.y
      original[bi + 2] = w0 * from.z + w1 * control.z + w2 * to.z
    }
    writeNativeConnectionArc(actual, base, from, control, to)
    expect(ARC_SEGS).toBe(20)
    expect(actual).toEqual(original)
    expect(actual.slice(0, 63)).toEqual(new Float32Array(63))
  })

  it('preserves merged RGBA, index buffers, native material and per-arc offsets', () => {
    const arcs = [{ color: 0xff0000, crossover_id: 'x' }, { color: 0x00ff00 }]
    const result = buildNativeConnectionLines(arcs, 'scaffold', arc => arc.color, arc => arc.crossover_id ? .25 : 1)
    try {
      expect(arcs.map(a => a.vertIdx)).toEqual([0, 21])
      expect(result.geo.attributes.color.itemSize).toBe(4)
      expect(result.geo.attributes.position.itemSize).toBe(3)
      expect(result.colors.length).toBe(42 * 4)
      expect(result.positions.length).toBe(42 * 3)
      expect(result.geo.index.array).toBeInstanceOf(Uint16Array)
      expect([...result.geo.index.array.slice(0, 4)]).toEqual([0, 1, 1, 2])
      expect([...result.geo.index.array.slice(-4)]).toEqual([39, 40, 40, 41])
      expect([...result.colors.slice(0, 4)]).toEqual([1, 0, 0, .25])
      expect([...result.colors.slice(84, 88)]).toEqual([0, 1, 0, 1])
      for (let vertex = 0; vertex < 42; vertex++) {
        expect([...result.colors.slice(vertex * 4, vertex * 4 + 4)])
          .toEqual(vertex < 21 ? [1, 0, 0, .25] : [0, 1, 0, 1])
      }
      expect(result.line.material).toMatchObject({ vertexColors: true, transparent: true, opacity: .85 })
      expect(result.line.frustumCulled).toBe(false)
      expect(result.line.userData.arcXoverIds).toEqual(['x'])
      expect(buildNativeConnectionLines([])).toBeNull()
    } finally { result.geo.dispose(); result.line.material.dispose() }
  })
})

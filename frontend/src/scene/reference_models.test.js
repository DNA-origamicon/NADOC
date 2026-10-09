import { describe, expect, it } from 'vitest'
import { Vector3 } from 'three'
import { parseReferenceSTL, uniformReferenceScale } from './reference_models.js'

const ascii = `solid fixture
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 60 0 0
vertex 0 30 0
endloop
endfacet
endsolid fixture`

describe('temporary STL reference geometry', () => {
  it('maps millimeter values to nanometers and centers the transform pivot', () => {
    const geometry = parseReferenceSTL(new TextEncoder().encode(ascii).buffer)
    geometry.computeBoundingBox()
    expect(geometry.boundingBox.getSize(new Vector3()).toArray()).toEqual([60, 30, 0])
    expect(geometry.boundingBox.getCenter(new Vector3()).toArray()).toEqual([0, 0, 0])
    expect(geometry.attributes.normal.array.every(Number.isFinite)).toBe(true)
  })
  it('accepts binary STL even when its header starts with solid', () => {
    const bytes = new ArrayBuffer(134), view = new DataView(bytes)
    new Uint8Array(bytes).set(new TextEncoder().encode('solid binary'))
    view.setUint32(80, 1, true)
    view.setFloat32(112, 60, true)
    view.setFloat32(128, 30, true)
    const geometry = parseReferenceSTL(bytes)
    expect(geometry.attributes.position.count).toBe(3)
  })
  it('rejects empty, nonfinite and degenerate geometry', () => {
    expect(() => parseReferenceSTL(new TextEncoder().encode('solid empty\nendsolid empty').buffer)).toThrow()
    expect(() => parseReferenceSTL(new TextEncoder().encode(ascii.replaceAll('60', '0').replaceAll('30', '0')).buffer)).toThrow()
    const bytes = new ArrayBuffer(134), view = new DataView(bytes)
    view.setUint32(80, 1, true); view.setFloat32(96, Infinity, true)
    expect(() => parseReferenceSTL(bytes)).toThrow()
  })
})


it('axis and plane scale handles preserve proportions and cannot become singular', () => {
  expect(uniformReferenceScale(new Vector3(4, 1, 1), 'X')).toBe(4)
  expect(uniformReferenceScale(new Vector3(1, 4, 1), 'XY')).toBe(2)
  expect(uniformReferenceScale(new Vector3(3, 3, 3), 'XYZ')).toBe(3)
  expect(uniformReferenceScale(new Vector3(NaN, 1, 1), 'X', 2)).toBe(2)
  expect(uniformReferenceScale(new Vector3(0, 0, 0), 'XYZ')).toBeGreaterThan(0)
})

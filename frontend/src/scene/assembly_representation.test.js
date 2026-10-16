import { expect, it } from 'vitest'
import { assemblyMemberSignature, canReuseAssemblyRepresentation, applyAssemblyRepresentation } from './assembly_representation.js'

it('reuses prepared detail only for unchanged membership and compatible CG representations', () => {
  const instances = [{ id: 'a', representation: 'beads' }, { id: 'b', representation: 'full' }]
  const source = { rep: 'full', cgRepresentationReusable: true, memberSignature: assemblyMemberSignature(instances) }
  expect(canReuseAssemblyRepresentation(source, instances)).toBe(true)
  expect(canReuseAssemblyRepresentation({ ...source, rep: 'beads' }, instances)).toBe(false)
  expect(canReuseAssemblyRepresentation(source, [{ ...instances[0], mode: 'other' }, instances[1]])).toBe(false)
  expect(canReuseAssemblyRepresentation(source, [{ ...instances[0], representation: 'surface' }, instances[1]])).toBe(false)
  expect(canReuseAssemblyRepresentation({ ...source, cgRepresentationReusable: false }, instances)).toBe(false)
})

it('updates current permuted rows while preserving visibility and every transform field', () => {
  const source = { rep: 'full', instanceIndex: new Map([['b', 0], ['a', 1]]),
    instanceLodCap: new Int8Array(2), visData: new Float32Array(32), dirtyVisRows: new Set(), hullLod: {} }
  source.visData[0] = .3; source.visData[16] = 1
  source.visData[3] = 19; source.visData[19] = 27
  applyAssemblyRepresentation(source, [{ id: 'a', representation: 'beads' }, { id: 'b', representation: 'full' }])
  expect(source.visData[0]).toBeCloseTo(.3)
  expect(source.visData[16]).toBe(1)
  expect(source.visData[1]).toBe(1)
  expect(source.visData[17]).toBe(0)
  expect(source.visData[3]).toBe(19)
  expect(source.visData[19]).toBe(27)
  expect(source.hasFullRepresentation).toBe(true)
  expect([...source.dirtyVisRows].sort()).toEqual([0, 1])
})

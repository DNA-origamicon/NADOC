import { expect, it } from 'vitest'
import { isPegJob, wholePegCoordinates, pegRmsf, pegWaterIndices } from './namd_peg_visualization.js'
const data = { coordinates_nm: [[.1, 1, .4], [.2, 1, .4], [4.7, 1, .4], [2, 2, 2]],
  elements: ['C', 'H', 'O', 'O'], peg_indices: [0, 1], anchor_indices: [0], bonds: [[0, 1]], slit: { box_nm: [4.8, 4.8, 4.8] } }
it('routes PEG job kinds only', () => {
  expect(isPegJob({ run_kind: 'peg_fast_relax' })).toBe(true)
  expect(isPegJob({ run_kind: 'peg_wall_qualification' })).toBe(true)
  expect(isPegJob({ run_kind: 'production' })).toBe(false)
  expect(isPegJob(null)).toBe(false)
})
it('reconstructs a boundary-crossing chain without mutating the frame or saved positions', () => {
  const xyz = [[4.75, 1, .4], [.05, 1, .4], ...data.coordinates_nm.slice(2)]
  const before = JSON.stringify({ data, xyz })
  const result = wholePegCoordinates(data, xyz)
  expect(result[0][0]).toBeCloseTo(-.05)
  expect(result[1][0]-result[0][0]).toBeCloseTo(.1)
  expect(JSON.stringify({ data, xyz })).toBe(before)
})
it('retains a rigid 0.2 nm graft displacement as 1 Å population RMSF', () => {
  const frames = [data.coordinates_nm, data.coordinates_nm.map(p => [p[0]+.2, ...p.slice(1)])].map(coordinates_nm => ({ coordinates_nm }))
  const result = pegRmsf(data, frames)
  expect(result.mean[0][0]).toBeCloseTo(.2)
  expect(result.angstrom[0]).toBeCloseTo(1)
  expect(result.max).toBeCloseTo(1)
  expect(() => pegRmsf(data, frames.slice(0, 1))).toThrow('two')
})
it('selects water oxygens using periodic PEG distances', () => {
  expect(pegWaterIndices(data, data.coordinates_nm)).toEqual([2, 3])
  expect(pegWaterIndices(data, data.coordinates_nm, 3)).toEqual([2])
})

import { expect, it } from 'vitest'
import { withSkippedColumnPoints } from './view_volume_points.js'
import { resolveViewVolumeLayers } from './view_volumes.js'
import { clippedCylinderRuns } from './helix_renderer.js'

it('suppresses isolated cylinder slices at deleted columns inside a volume', () => {
  const points = [24, 25, 26, 28, 29, 30, 31].flatMap(bp => [-1, 1].map(x => ({ key: `h:${bp}`, position: [x, 0, bp * .334] })))
  const helices = [{ id: 'h', loop_skips: [{ bp_index: 27, delta: -1 }] }]
  const volume = { min_corner: [-2, -2, 7], max_corner: [2, 2, 11] }
  const oldKeys = resolveViewVolumeLayers([volume], points)[0].keys
  expect(clippedCylinderRuns(24, 31, bp => !oldKeys.has(`h:${bp}`))).toEqual([[27, 27]])
  const [{ keys }] = resolveViewVolumeLayers([volume], withSkippedColumnPoints(points, helices))
  expect(clippedCylinderRuns(24, 31, bp => !keys.has(`h:${bp}`))).toEqual([])
  expect(points).toHaveLength(14)
})

it('fills consecutive skips using live positions without filling ordinary gaps or occupied columns', () => {
  const points = [{ key: 'h:1', position: [4, 2, 10] }, { key: 'h:4', position: [10, 2, 16] }]
  const helices = [{ id: 'h', loop_skips: [0, 1, 2, 3, 5].map(bp_index => ({ bp_index, delta: -1 })) }]
  expect(withSkippedColumnPoints(points, helices).slice(2)).toEqual([
    { key: 'h:2', position: [6, 2, 12] }, { key: 'h:3', position: [8, 2, 14] },
  ])
  expect(withSkippedColumnPoints(points, [])).toEqual(points)
  const volume = { min_corner: [5, 1, 11], max_corner: [7, 3, 13] }
  expect([...resolveViewVolumeLayers([volume], withSkippedColumnPoints(points, helices))[0].keys]).toEqual(['h:2'])
})

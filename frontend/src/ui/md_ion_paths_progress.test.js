import { it, expect } from 'vitest'
import { ION_PATH_STAGES, ionPathsProgress } from './md_ion_paths_progress.js'
it('counts all analysis, atomistic and surface stages while reserving completion for rendering', () => {
  expect(ionPathsProgress(null).percentage).toBe(0)
  const stages = ION_PATH_STAGES.map(([stage]) => ({ stage, done: 1, total: 1 }))
  expect(ionPathsProgress({ stages }).percentage).toBe(70)
  const coordinates = stages.find(s => s.stage === 'coordinates')
  coordinates.done = 5; coordinates.total = 10
  expect(ionPathsProgress({ stages }).percentage).toBe(63)
  expect(ionPathsProgress({ stages: [{ stage: 'rmsf', done: 50, total: 150 }] }).label).toContain('50 / 150')
})

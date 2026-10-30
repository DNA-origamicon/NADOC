import { expect, it } from 'vitest'
import { projectMatch } from './image_sequence_overlay.js'
it('projects reverse domains through stretched columns and clips to calibrated evidence', () => {
  const m = { helix_id: 'h', start_bp: 19, end_bp: 5 }
  expect(projectMatch(m, [100, 200, 500], [0, 7, 14], [300], ['h'])).toEqual({ x1: 100 + 500 / 7, x2: 500, y: 300, row: 0, clipped: true })
  expect(projectMatch(m, [100, 200], [7, 0], [300], ['h'])).toBeNull()
  expect(projectMatch(m, [100, 200], [0, 7], [300], ['other'])).toBeNull()
  expect(projectMatch({ ...m, end_bp: 15 }, [100, 200], [0, 7], [300], ['h'])).toBeNull()
})

import { describe, expect, it } from 'vitest'
import { hasEffectiveDisplayPose } from './deform_view.js'

describe('effective display pose', () => {
  it('ignores the automatic identity cluster', () => {
    expect(hasEffectiveDisplayPose({
      deformations: [],
      cluster_transforms: [{ translation: [0, 0, 0], rotation: [0, 0, 0, 1] }],
    })).toBe(false)
  })

  it('detects deformations, translations, and rotations', () => {
    expect(hasEffectiveDisplayPose({ deformations: [{}], cluster_transforms: [] })).toBe(true)
    expect(hasEffectiveDisplayPose({
      deformations: [], cluster_transforms: [{ translation: [0, 0.01, 0], rotation: [0, 0, 0, 1] }],
    })).toBe(true)
    expect(hasEffectiveDisplayPose({
      deformations: [], cluster_transforms: [{ translation: [0, 0, 0], rotation: [0, 0.1, 0, 0.995] }],
    })).toBe(true)
  })
})

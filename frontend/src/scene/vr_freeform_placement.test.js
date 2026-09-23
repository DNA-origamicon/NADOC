import { it, expect } from 'vitest'
import { normalizeFreeformPlacement } from './vr_freeform_placement.js'

it('copies a bounded rigid placement and rejects scale-like/nonfinite poses', () => {
  const pose = { translation_nm:[12,-4,8],rotation_xyzw:[0,0.6,0,0.8] }
  expect(normalizeFreeformPlacement(pose)).toEqual(pose)
  expect(normalizeFreeformPlacement(pose).translation_nm).not.toBe(pose.translation_nm)
  expect(normalizeFreeformPlacement(undefined)).toBeUndefined()
  for (const bad of [null, {...pose,scale:2}, {...pose,translation_nm:[NaN,0,0]},
    {...pose,translation_nm:[1e7,0,0]}, {...pose,rotation_xyzw:[0,0,0,0]},
    {...pose,rotation_xyzw:[0,0,0,2]}]) expect(normalizeFreeformPlacement(bad)).toBeNull()
})

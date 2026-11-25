import { it, expect, vi } from 'vitest'
import { normalizeGrade, initColorGrade } from './color_grade.js'
it('bounds grading and rejects non-finite values', () => {
  expect(normalizeGrade({ exposure: Infinity, contrast: 9, saturation: -2 })).toEqual({ exposure: 1, contrast: 1.5, saturation: 0 })
})
it('keeps live and export passes synchronized, neutral grading bypassed, and inactive renderer untouched', () => {
  const settings = normalizeGrade(), renderer = { toneMappingExposure: 2 }
  let active = false
  const grade = initColorGrade({ settings, renderer, isActive: () => active })
  const preview = grade.create(), exported = grade.create()
  expect(preview.enabled).toBe(false)
  grade.set({ exposure: 1.3, saturation: 0 })
  expect(renderer.toneMappingExposure).toBe(2)
  for (const pass of [preview, exported]) {
    expect(pass.enabled).toBe(true)
    expect(pass.uniforms.saturation.value).toBe(0)
  }
  active = true; grade.set({ contrast: 1.2 })
  expect(renderer.toneMappingExposure).toBe(1.3)
  exported.dispose(); exported.setParams = vi.fn()
  grade.set({ saturation: 1 })
  expect(exported.setParams).not.toHaveBeenCalled()
  preview.dispose()
})

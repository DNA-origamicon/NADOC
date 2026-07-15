import { describe, it, expect } from 'vitest'
import {
  DISPLAY_HOME_TAB,
  preservesDisplays,
  shouldTearDownDisplays,
  shouldResumeDisplays,
  displayTabIds,
} from './display_tab_policy.js'

describe('display_tab_policy', () => {
  it('keeps a simulation display alive when the user opens the Photo tab', () => {
    expect(preservesDisplays('photo')).toBe(true)
    expect(shouldTearDownDisplays('photo')).toBe(false)
  })

  it('tears the display down on the editing tabs', () => {
    for (const tab of ['design', 'scene', 'view', 'features', 'assembly']) {
      expect(shouldTearDownDisplays(tab)).toBe(true)
    }
  })

  it('never tears down on the tab that owns the engine panels', () => {
    expect(shouldTearDownDisplays(DISPLAY_HOME_TAB)).toBe(false)
    expect(shouldResumeDisplays(DISPLAY_HOME_TAB)).toBe(true)
  })

  it('only resumes polling on the home tab, not on a view-only tab', () => {
    expect(shouldResumeDisplays('photo')).toBe(false)
    expect(shouldResumeDisplays('design')).toBe(false)
  })

  it('treats an undefined tab as a teardown (missing detail must not preserve)', () => {
    expect(shouldTearDownDisplays(undefined)).toBe(true)
  })

  it('lists every tab a display may be shown on', () => {
    expect(displayTabIds()).toEqual(['dynamics', 'photo'])
  })
})

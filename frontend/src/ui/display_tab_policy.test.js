import { describe, it, expect } from 'vitest'
import {
  DISPLAY_HOME_TAB,
  preservesDisplays,
  shouldTearDownDisplays,
  shouldStopLiveSession,
  shouldResumeDisplays,
  displayTabIds,
  liveTabIds,
} from './display_tab_policy.js'

describe('display_tab_policy', () => {
  it('keeps a simulation display alive when the user opens the Photo tab', () => {
    expect(preservesDisplays('photo')).toBe(true)
    expect(shouldTearDownDisplays('photo')).toBe(false)
  })

  it('keeps a display alive on the ANIMATIONS tab — trajectory keyframes paint there', () => {
    // Regression: Animations → Photo → Animations reverted the model to native
    // positions, because the return trip tore down the very controller the
    // animation was playing through.
    expect(preservesDisplays('scene')).toBe(true)
    expect(shouldTearDownDisplays('scene')).toBe(false)
  })

  it('tears the display down on the editing tabs', () => {
    for (const tab of ['design', 'view', 'features', 'assembly', 'feature-log', 'plates']) {
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
    // Photo mode preserves displays: you photograph what is on screen, which
    // includes an oxDNA/NAMD frame. Animations preserves them because a trajectory
    // keyframe paints through the same controller.
    expect(displayTabIds()).toEqual(['dynamics', 'photo', 'scene'])
  })

  describe('live sessions are stricter than painted displays', () => {
    it('stops a live stream on Animations even though a painted frame survives there', () => {
      // A stream writes bead positions every frame; animation playback writes the
      // same beads. One of them has to yield, and it is the stream.
      expect(shouldStopLiveSession('scene')).toBe(true)
      expect(shouldTearDownDisplays('scene')).toBe(false)
    })

    it('still exempts Photo and the home tab', () => {
      expect(shouldStopLiveSession('photo')).toBe(false)
      expect(shouldStopLiveSession(DISPLAY_HOME_TAB)).toBe(false)
    })

    it('stops on the editing tabs and on a missing tab id', () => {
      for (const tab of ['feature-log', 'plates', 'design', undefined]) {
        expect(shouldStopLiveSession(tab)).toBe(true)
      }
    })

    it('lists every tab a live session may run on', () => {
      expect(liveTabIds()).toEqual(['dynamics', 'photo'])
    })
  })

  it('does not resume polling on the photo tab — it only preserves', () => {
    expect(shouldTearDownDisplays('photo')).toBe(false)
    expect(shouldResumeDisplays('photo')).toBe(false)
  })
})

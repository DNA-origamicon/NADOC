import { describe, expect, it } from 'vitest'
import { createDesignRevisionTracker } from './design_revisions.js'

const snapshot = (revision, fields = {}, id = 'part') => ({ revision, design: { id, ...fields } })

describe('design and metadata response ordering', () => {
  it('accepts needed topology after newer metadata and preserves the metadata', () => {
    const tracker = createDesignRevisionTracker()
    tracker.acceptDesign(snapshot(9))
    tracker.acceptMetadata({ revision: 11, annotations: ['new'], annotations_enabled: false },
      ['annotations', 'annotations_enabled'], 'part')
    const geometry = snapshot(10, { helices: ['edited'], annotations: ['old'], annotations_enabled: true })
    expect(tracker.acceptDesign(geometry)).toBe(true)
    expect(geometry.design).toMatchObject({ helices: ['edited'], annotations: ['new'], annotations_enabled: false })
    expect(tracker.current()).toBe(11)
    expect(tracker.acceptDesign(snapshot(9))).toBe(false)
  })

  it('orders metadata per field, rather than losing an independent earlier save', () => {
    const tracker = createDesignRevisionTracker()
    expect(tracker.acceptMetadata(snapshot(12, { camera_poses: ['camera'] }), ['camera_poses'], 'part')).toBe(true)
    expect(tracker.acceptMetadata({ revision: 11, view_volumes: ['volume'] }, ['view_volumes'], 'part')).toBe(true)
    expect(tracker.acceptMetadata({ revision: 10, view_volumes: [] }, ['view_volumes'], 'part')).toBe(false)
    const design = snapshot(9)
    tracker.acceptDesign(design)
    expect(design.design).toMatchObject({ camera_poses: ['camera'], view_volumes: ['volume'] })
  })

  it('retires acknowledged overlays and rejects metadata older than a full snapshot', () => {
    const tracker = createDesignRevisionTracker()
    tracker.acceptMetadata({ revision: 11, annotations: ['old'] }, ['annotations'], 'part')
    const fresh = snapshot(12, { annotations: ['fresh'] })
    tracker.acceptDesign(fresh)
    expect(fresh.design.annotations).toEqual(['fresh'])
    expect(tracker.acceptMetadata({ revision: 11, annotations: [] }, ['annotations'], 'part')).toBe(false)
  })

  it('does not carry metadata between designs or across a server restart', () => {
    const tracker = createDesignRevisionTracker()
    tracker.acceptMetadata({ revision: 11, annotations: ['old'] }, ['annotations'], 'part')
    const other = snapshot(10, { annotations: [] }, 'other')
    tracker.acceptDesign(other)
    expect(other.design.annotations).toEqual([])
    tracker.reset()
    expect(tracker.current()).toBeNull()
    expect(tracker.acceptDesign(snapshot(1))).toBe(true)
  })
})

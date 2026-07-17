import { describe, expect, it } from 'vitest'
import { leftWidthStorageKey } from './sidebar_resize.js'

describe('leftWidthStorageKey', () => {
  it('keeps a separate width for each workspace file', () => {
    expect(leftWidthStorageKey('parts/a.nadoc'))
      .not.toBe(leftWidthStorageKey('parts/b.nadoc'))
    expect(leftWidthStorageKey('parts/a.nadoc'))
      .toBe('nadoc.leftPanel.width.file:parts%2Fa.nadoc')
  })

  it('uses the legacy global key for an unsaved design', () => {
    expect(leftWidthStorageKey(null)).toBe('nadoc.leftPanel.width')
  })
})

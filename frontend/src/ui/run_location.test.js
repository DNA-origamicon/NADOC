import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the interactive deps so the pure/factory logic is testable headless.
vi.mock('./folder_picker.js', () => ({ pickSystemFolder: vi.fn() }))
vi.mock('./primitives/choice.js', () => ({ showChoice: vi.fn() }))
vi.mock('./primitives/button.js', () => ({
  createButton: ({ label }) => { const b = { textContent: label, addEventListener: () => {} }; return b },
}))

import { runDirLabel, archiveRecommendation, initRunLocation } from './run_location.js'
import { showChoice } from './primitives/choice.js'

function memStore() {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) }
}

describe('runDirLabel', () => {
  it('shows the last path component, or a default', () => {
    expect(runDirLabel('/media/jojo/Archive')).toBe('Archive')
    expect(runDirLabel('/media/jojo/Archive/')).toBe('Archive')
    expect(runDirLabel(null)).toMatch(/Default/)
  })
})

describe('archiveRecommendation', () => {
  it('recommends only when the forecast warns AND has a suggestion', () => {
    expect(archiveRecommendation({ warn: false, suggested_archive: { path: '/x', free_bytes: 9 } }).show).toBe(false)
    expect(archiveRecommendation({ warn: true, suggested_archive: null }).show).toBe(false)
    const r = archiveRecommendation({ warn: true, suggested_archive: { path: '/media/jojo/Archive', free_bytes: 42 } })
    expect(r).toEqual({ show: true, path: '/media/jojo/Archive', freeBytes: 42 })
  })
})

describe('initRunLocation', () => {
  let store
  beforeEach(() => { store = memStore(); showChoice.mockReset() })

  it('defaults from storage, persists setDir, clears', () => {
    store.setItem('nadoc.md.runDir', '/media/jojo/Archive')
    const rl = initRunLocation({ api: {}, storage: store })
    expect(rl.getRunDir()).toBe('/media/jojo/Archive')
    rl.setDir('/mnt/big'); expect(rl.getRunDir()).toBe('/mnt/big')
    expect(store.getItem('nadoc.md.runDir')).toBe('/mnt/big')
    rl.clear(); expect(rl.getRunDir()).toBe(null)
    expect(store.getItem('nadoc.md.runDir')).toBe(null)
  })

  it('recommendArchive: no suggestion → proceed with current dir, no dialog', async () => {
    const rl = initRunLocation({ api: {}, storage: store })
    rl.setDir('/keep')
    const r = await rl.recommendArchive({ warn: false })
    expect(r).toEqual({ proceed: true, runDir: '/keep' })
    expect(showChoice).not.toHaveBeenCalled()
  })

  it('recommendArchive: "archive" sets + returns the suggested dir', async () => {
    showChoice.mockResolvedValue('archive')
    const rl = initRunLocation({ api: {}, storage: store })
    const r = await rl.recommendArchive({ warn: true, suggested_archive: { path: '/media/jojo/Archive', free_bytes: 99 } })
    expect(r).toEqual({ proceed: true, runDir: '/media/jojo/Archive' })
    expect(rl.getRunDir()).toBe('/media/jojo/Archive')
  })

  it('recommendArchive: "here" keeps current, cancel stops', async () => {
    const rl = initRunLocation({ api: {}, storage: store })
    rl.setDir('/cur')
    showChoice.mockResolvedValue('here')
    expect(await rl.recommendArchive({ warn: true, suggested_archive: { path: '/a', free_bytes: 9 } }))
      .toEqual({ proceed: true, runDir: '/cur' })
    showChoice.mockResolvedValue(null)
    expect(await rl.recommendArchive({ warn: true, suggested_archive: { path: '/a', free_bytes: 9 } }))
      .toEqual({ proceed: false })
  })
})

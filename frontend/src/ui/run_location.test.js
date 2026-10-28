// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./folder_picker.js', () => ({ pickSystemFolder: vi.fn() }))
vi.mock('./primitives/choice.js', () => ({ showChoice: vi.fn() }))
vi.mock('./primitives/button.js', () => ({
  createButton: (opts) => {
    const btn = document.createElement('button')
    btn.textContent = opts.label
    btn.onClick = opts.onClick
    return btn
  },
}))

import {
  runDirLabel, archiveRecommendation, getRunDir, setRunDir, recommendArchive, mountDirectoryButton,
} from './run_location.js'
import { showChoice } from './primitives/choice.js'
import { pickSystemFolder } from './folder_picker.js'

beforeEach(() => { localStorage.clear(); showChoice.mockReset(); pickSystemFolder.mockReset() })

describe('runDirLabel', () => {
  it('shows the last path component, or a default', () => {
    expect(runDirLabel('/media/jojo/Archive')).toBe('Archive')
    expect(runDirLabel('/media/jojo/Archive/')).toBe('Archive')
    expect(runDirLabel(null)).toMatch(/Default/)
  })
})

describe('shared preference (getRunDir/setRunDir)', () => {
  it('persists an engine-specific key and reads back fresh', () => {
    expect(getRunDir()).toBe(null)
    setRunDir('/media/jojo/Archive')
    expect(getRunDir()).toBe('/media/jojo/Archive')
    expect(localStorage.getItem('nadoc.runDir.namd')).toBe('/media/jojo/Archive')
    setRunDir(null)
    expect(getRunDir()).toBe(null)
  })
})

describe('archiveRecommendation', () => {
  it('recommends only when the forecast warns AND has a suggestion', () => {
    expect(archiveRecommendation({ warn: false, suggested_archive: { path: '/x', free_bytes: 9 } }).show).toBe(false)
    expect(archiveRecommendation({ warn: true, suggested_archive: null }).show).toBe(false)
    expect(archiveRecommendation({ warn: true, suggested_archive: { path: '/media/jojo/Archive', free_bytes: 42 } }))
      .toEqual({ show: true, path: '/media/jojo/Archive', freeBytes: 42 })
  })
})

describe('recommendArchive', () => {
  it('no suggestion → proceed with current dir, no dialog', async () => {
    setRunDir('/keep')
    expect(await recommendArchive({ warn: false })).toEqual({ proceed: true, runDir: '/keep' })
    expect(showChoice).not.toHaveBeenCalled()
  })
  it('"archive" sets + returns the suggested dir', async () => {
    showChoice.mockResolvedValue('archive')
    const r = await recommendArchive({ warn: true, suggested_archive: { path: '/media/jojo/Archive', free_bytes: 99 } })
    expect(r).toEqual({ proceed: true, runDir: '/media/jojo/Archive' })
    expect(getRunDir()).toBe('/media/jojo/Archive')
  })
  it('"here" keeps current; cancel stops', async () => {
    setRunDir('/cur')
    showChoice.mockResolvedValue('here')
    expect(await recommendArchive({ warn: true, suggested_archive: { path: '/a', free_bytes: 9 } }))
      .toEqual({ proceed: true, runDir: '/cur' })
    showChoice.mockResolvedValue(null)
    expect(await recommendArchive({ warn: true, suggested_archive: { path: '/a', free_bytes: 9 } }))
      .toEqual({ proceed: false })
  })
})

describe('mountDirectoryButton', () => {
  it('renders into a container and picks a folder into the shared preference', async () => {
    pickSystemFolder.mockResolvedValue('/mnt/big')
    const container = { appendChild: vi.fn() }
    const btn = mountDirectoryButton(container, { api: {} })
    expect(container.appendChild).toHaveBeenCalledWith(btn)
    await btn.onClick()     // opens the folder browser → stores the pick in the shared preference
    expect(getRunDir()).toBe('/mnt/big')
  })

  it('checks and displays NADOC\'s workspace default on mount', async () => {
    const container = document.createElement('div')
    const api = { getMdRunDirStatus: vi.fn(async () => ({
      ok: true, default: true, path: '/repo/workspace/md_jobs', detail: '',
    })) }
    const btn = mountDirectoryButton(container, { api })

    expect(btn.textContent).toMatch(/checking/)
    await vi.waitFor(() => expect(btn.dataset.runDirState).toBe('ok'))
    expect(api.getMdRunDirStatus).toHaveBeenCalledWith(null, 'namd')
    expect(btn.textContent).toContain('md_jobs')
    expect(btn.textContent).not.toContain('⚠')
  })

  it('shows an error icon when a remembered folder belongs to another computer', async () => {
    setRunDir('/media/other-machine/nadoc_jobs')
    const container = document.createElement('div')
    const api = { getMdRunDirStatus: vi.fn(async path => ({
      ok: false, path, detail: 'Folder does not exist on this computer.',
    })) }
    const btn = mountDirectoryButton(container, { api })

    await vi.waitFor(() => expect(btn.dataset.runDirState).toBe('error'))
    expect(api.getMdRunDirStatus).toHaveBeenCalledWith('/media/other-machine/nadoc_jobs', 'namd')
    expect(btn.textContent).toContain('⚠')
    expect(btn.title).toMatch(/does not exist/)
  })
})

it('keeps legacy choices initially, then changes and resets each engine independently', () => {
  localStorage.setItem('nadoc.runDir', '/legacy')
  expect(getRunDir('oxdna')).toBe('/legacy')
  expect(getRunDir('namd')).toBe('/legacy')
  setRunDir('/oxdna', 'oxdna')
  expect(getRunDir('namd')).toBe('/legacy')
  setRunDir('/namd', 'namd')
  expect(getRunDir('oxdna')).toBe('/oxdna')
  setRunDir(null, 'oxdna')
  expect(getRunDir('oxdna')).toBeNull()
  expect(getRunDir('namd')).toBe('/namd')
})
it('updates on engine switches and preserves the engine of an open picker', async () => {
  setRunDir('/dna', 'oxdna'); setRunDir('/atoms', 'namd')
  let finish
  pickSystemFolder.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const btn = mountDirectoryButton(document.createElement('div'), { engine: 'oxdna' })
  expect(btn.textContent).toContain('dna')
  const pending = btn.onClick()
  btn.setEngine('namd')
  expect(btn.textContent).toContain('atoms')
  finish('/new-dna'); await pending
  expect(getRunDir('oxdna')).toBe('/new-dna')
  expect(getRunDir('namd')).toBe('/atoms')
  expect(btn.textContent).toContain('atoms')
  btn.dispatchEvent(new MouseEvent('contextmenu'))
  expect(getRunDir('namd')).toBeNull()
  expect(getRunDir('oxdna')).toBe('/new-dna')
})

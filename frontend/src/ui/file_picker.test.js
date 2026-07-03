import { describe, it, expect, vi, afterEach } from 'vitest'
import { formatSize, formatMtime, openFilePicker } from './file_picker.js'

afterEach(() => { document.body.querySelectorAll('.modal__overlay').forEach(n => n.remove()) })

describe('formatSize', () => {
  it('blank for empty/zero', () => {
    expect(formatSize(0)).toBe('')
    expect(formatSize(undefined)).toBe('')
  })
  it('scales units', () => {
    expect(formatSize(500)).toBe('500 B')
    expect(formatSize(2048)).toBe('2 KB')
    expect(formatSize(1_500_000)).toMatch(/MB$/)
  })
})

describe('formatMtime', () => {
  const now = 1_000_000_000_000  // fixed "now" in ms
  it('blank when missing', () => expect(formatMtime(0, now)).toBe(''))
  it('yesterday / N days ago / date', () => {
    const day = 86400
    const nowS = now / 1000
    expect(formatMtime(nowS - day, now)).toBe('yesterday')
    expect(formatMtime(nowS - 3 * day, now)).toBe('3 days ago')
    expect(formatMtime(nowS - 30 * day, now)).toMatch(/\d/)   // a date string
  })
})

describe('openFilePicker', () => {
  function api(listing) { return { browseFiles: vi.fn().mockResolvedValue(listing) } }
  const listing = {
    cwd: '/mnt/c/Users/joshu/Downloads', parent: '/mnt/c/Users/joshu', error: '',
    entries: [
      { name: 'sub', path: '/d/sub', is_dir: true, size: 0, mtime: 1, matches: false },
      { name: 'arbd-may24-beta.tar.gz', path: '/d/arbd-may24-beta.tar.gz', is_dir: false, size: 386754, mtime: 2, matches: true },
    ],
  }

  it('opens at Downloads (browseFiles(null)) and renders entries', async () => {
    const a = api(listing)
    openFilePicker({ api: a, kind: 'arbd', title: 'Pick', onPick: () => {} })
    await Promise.resolve(); await Promise.resolve()
    expect(a.browseFiles).toHaveBeenCalledWith(null, 'arbd')
    const modal = document.querySelector('.modal__overlay')
    expect(modal.textContent).toMatch(/arbd-may24-beta/)
    expect(modal.textContent).toMatch(/sub/)
  })

  it('clicking a directory navigates into it', async () => {
    const a = api(listing)
    openFilePicker({ api: a, onPick: () => {} })
    await Promise.resolve(); await Promise.resolve()
    const modal = document.querySelector('.modal__overlay')
    const dirRow = [...modal.querySelectorAll('div')].find(d => /sub/.test(d.textContent) && (d.getAttribute('style') || '').includes('cursor:pointer'))
    dirRow.click()
    await Promise.resolve()
    expect(a.browseFiles).toHaveBeenLastCalledWith('/d/sub', undefined)
  })

  it('clicking a file calls onPick with its path and closes', async () => {
    const a = api(listing)
    const onPick = vi.fn()
    openFilePicker({ api: a, onPick })
    await Promise.resolve(); await Promise.resolve()
    const modal = document.querySelector('.modal__overlay')
    const fileRow = [...modal.querySelectorAll('div')].find(d => /arbd-may24-beta/.test(d.textContent) && (d.getAttribute('style') || '').includes('cursor:pointer'))
    fileRow.click()
    expect(onPick).toHaveBeenCalledWith('/d/arbd-may24-beta.tar.gz')
  })
})

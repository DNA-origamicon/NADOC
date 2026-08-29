// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  hasLargeSimulationData,
  mergeLibraryDiskUsage,
  readLibraryCache,
  writeLibraryCache,
  initLibraryPanel,
} from './library_panel.js'

afterEach(() => { document.body.replaceChildren(); localStorage.clear(); vi.restoreAllMocks() })

describe('hasLargeSimulationData', () => {
  const halfGb = 0.5 * 1024 ** 3

  it('only flags NAMD/oxDNA data strictly larger than 0.5 GB', () => {
    expect(hasLargeSimulationData(halfGb - 1)).toBe(false)
    expect(hasLargeSimulationData(halfGb)).toBe(false)
    expect(hasLargeSimulationData(halfGb + 1)).toBe(true)
  })

  it('uses a selector specific enough to beat the later accessibility size rule', () => {
    const html = readFileSync(`${process.cwd()}/index.html`, 'utf8')
    expect(html).toContain('.lib-row-size.lib-row-size-sim')
  })
})

describe('mergeLibraryDiskUsage', () => {
  it('enriches parts without changing assemblies or folders', () => {
    const entries = [
      { type: 'part', path: 'Parts/a.nadoc', size_bytes: 100 },
      { type: 'assembly', path: 'asm.nass', size_bytes: 50 },
      { type: 'folder', path: 'Parts', size_bytes: 0 },
    ]
    const out = mergeLibraryDiskUsage(entries, { 'Parts/a.nadoc': 900 })
    expect(out[0]).toMatchObject({ sim_bytes: 900, disk_bytes: 1000 })
    expect(out[1]).toBe(entries[1])
    expect(out[2]).toBe(entries[2])
  })

  it('treats a part with no jobs as file-only disk usage', () => {
    const out = mergeLibraryDiskUsage(
      [{ type: 'part', path: 'a.nadoc', size_bytes: 123 }],
      {},
    )
    expect(out[0]).toMatchObject({ sim_bytes: 0, disk_bytes: 123 })
  })
})

describe('library cache', () => {
  it('round-trips the last file list for immediate reload rendering', () => {
    const storage = new Map()
    const adapter = {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    }
    const entries = [{ type: 'part', path: 'cached.nadoc' }]
    expect(writeLibraryCache(entries, adapter)).toBe(true)
    expect(readLibraryCache(adapter)).toEqual(entries)
  })

  it('ignores corrupt cached data', () => {
    expect(readLibraryCache({ getItem: () => '{bad json' })).toEqual([])
  })
})

describe('welcome workspace server tabs', () => {
  it('browses and checks out an online peer directly from the welcome library', async () => {
    document.body.innerHTML = '<div id="library-panel-mount"></div>'
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([]),
      libraryDiskUsage: vi.fn().mockResolvedValue({}),
      getCollaborationPeerStatuses: vi.fn().mockResolvedValue({ peers: [
        { id: 'remote', name: 'Laptop', online: true },
      ] }),
      listPeerLibraryFiles: vi.fn().mockResolvedValue([
        { path: 'Voltron.nadoc', name: 'Voltron', type: 'part', size_bytes: 100, mtime_iso: new Date().toISOString() },
      ]),
      checkoutPeerLibraryFile: vi.fn().mockResolvedValue({ path: 'Voltron.nadoc', name: 'Voltron' }),
    }
    const onOpenPart = vi.fn()
    initLibraryPanel({ api, onOpenPart, onOpenAssembly: vi.fn(), onNewPart: vi.fn(), onNewAssembly: vi.fn() })
    await new Promise(resolve => setTimeout(resolve, 0))
    const tab = [...document.querySelectorAll('button')].find(item => item.textContent.includes('Laptop'))
    expect(tab).toBeTruthy()
    tab.click()
    await new Promise(resolve => setTimeout(resolve, 0))
    document.querySelector('.lib-file-row').click()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(api.checkoutPeerLibraryFile).toHaveBeenCalledWith('remote', 'Voltron.nadoc')
    expect(onOpenPart).toHaveBeenCalledWith('Voltron.nadoc', 'Voltron')
  })
})

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
  it('expands and collapses every folder from one button', async () => {
    document.body.innerHTML = '<div id="library-panel-mount"></div>'
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([
        { path: 'Alpha', name: 'Alpha', type: 'folder', size_bytes: 0 },
        { path: 'Alpha/Nested', name: 'Nested', type: 'folder', size_bytes: 0 },
        { path: 'Alpha/Nested/a.nadoc', name: 'a', type: 'part', size_bytes: 10 },
        { path: 'Beta', name: 'Beta', type: 'folder', size_bytes: 0 },
        { path: 'Beta/b.nadoc', name: 'b', type: 'part', size_bytes: 10 },
      ]),
      libraryDiskUsage: vi.fn().mockResolvedValue({}),
    }
    initLibraryPanel({
      api,
      onOpenPart: vi.fn(), onOpenAssembly: vi.fn(),
      onNewPart: vi.fn(), onNewAssembly: vi.fn(),
    })
    await new Promise(resolve => setTimeout(resolve, 0))

    const button = document.querySelector('.lib-expand-all-btn')
    expect(button.title).toBe('Expand all folders')
    expect(button.classList.contains('lib-trash-icon-btn')).toBe(true)
    expect(button.querySelector('svg')).toBeTruthy()
    const toolbarItems = [...document.querySelector('.lib-sort-bar').children]
    expect(toolbarItems[0].className).toBe('lib-sort-leading-actions')
    expect(toolbarItems[0].children[0].getAttribute('aria-label')).toBe('Open Trash')
    expect(toolbarItems[0].children[1]).toBe(button)
    expect(toolbarItems[1].textContent).toBe('Sort:')
    expect(document.querySelectorAll('.lib-folder-row')).toHaveLength(2)

    button.click()
    expect(button.title).toBe('Collapse all folders')
    expect(document.querySelectorAll('.lib-folder-row')).toHaveLength(3)
    expect(document.querySelectorAll('.lib-file-row')).toHaveLength(2)

    button.click()
    expect(button.title).toBe('Expand all folders')
    expect(document.querySelectorAll('.lib-folder-row')).toHaveLength(2)
    expect(document.querySelectorAll('.lib-file-row')).toHaveLength(0)
  })

  it('keeps local files usable while a configured peer is offline', async () => {
    document.body.innerHTML = '<div id="library-panel-mount"></div>'
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([
        { path: 'Local.nadoc', name: 'Local', type: 'part', size_bytes: 10, mtime_iso: new Date().toISOString() },
      ]),
      libraryDiskUsage: vi.fn().mockResolvedValue({}),
      getCollaborationPeerStatuses: vi.fn().mockResolvedValue({ peers: [
        { id: 'remote', name: 'Laptop', online: false },
      ] }),
    }
    const onOpenPart = vi.fn()
    initLibraryPanel({
      api, onOpenPart, onOpenAssembly: vi.fn(),
      onNewPart: vi.fn(), onNewAssembly: vi.fn(),
    })
    await new Promise(resolve => setTimeout(resolve, 0))

    const localTab = [...document.querySelectorAll('button')]
      .find(item => item.textContent.includes('This computer'))
    const remoteTab = [...document.querySelectorAll('button')]
      .find(item => item.textContent.includes('Laptop'))
    expect(localTab.disabled).toBe(false)
    expect(remoteTab.disabled).toBe(true)
    document.querySelector('.lib-file-row').click()
    expect(onOpenPart).toHaveBeenCalledWith('Local.nadoc', 'Local')
  })

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
    expect(tab.className).toBe('lib-server-tab')
    expect(tab.getAttribute('role')).toBe('tab')
    expect(tab.getAttribute('aria-selected')).toBe('false')
    expect(document.querySelector('.lib-show-sim-folders').textContent).toContain('Show sim folders')
    tab.click()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect([...document.querySelectorAll('.lib-server-tab')].find(item => item.textContent.includes('Laptop')).getAttribute('aria-selected')).toBe('true')
    document.querySelector('.lib-file-row').click()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(api.checkoutPeerLibraryFile).toHaveBeenCalledWith('remote', 'Voltron.nadoc')
    expect(onOpenPart).toHaveBeenCalledWith('Voltron.nadoc', 'Voltron')
  })

  it('updates a stale offline tab when peer reachability changes', async () => {
    document.body.innerHTML = '<div id="library-panel-mount"></div>'
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([]),
      libraryDiskUsage: vi.fn().mockResolvedValue({}),
      getCollaborationPeerStatuses: vi.fn()
        .mockResolvedValueOnce({ peers: [{ id: 'remote', name: 'Compy5000', online: false }] })
        .mockResolvedValueOnce({ peers: [{ id: 'remote', name: 'Compy5000', online: true }] }),
    }
    initLibraryPanel({
      api,
      onOpenPart: vi.fn(), onOpenAssembly: vi.fn(),
      onNewPart: vi.fn(), onNewAssembly: vi.fn(),
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    let tab = [...document.querySelectorAll('button')].find(item => item.textContent.includes('Compy5000'))
    expect(tab.disabled).toBe(true)

    window.dispatchEvent(new Event('nadoc:collaboration-peers-changed'))
    await new Promise(resolve => setTimeout(resolve, 0))
    tab = [...document.querySelectorAll('button')].find(item => item.textContent.includes('Compy5000'))
    expect(tab.disabled).toBe(false)
    expect(tab.querySelector('.lib-server-status').classList.contains('online')).toBe(true)
  })
})

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

describe('hidden direct-open library startup', () => {
  const mountHidden = () => {
    document.body.innerHTML = '<div id="welcome-screen" class="hidden"><div id="library-panel-mount"></div></div>'
    return {
      listLibraryFiles: vi.fn().mockResolvedValue([]),
      libraryDiskUsage: vi.fn().mockResolvedValue({}),
    }
  }

  it('defers the initial listing until the hidden welcome screen becomes visible', async () => {
    const api = mountHidden()
    initLibraryPanel({ api })
    await Promise.resolve()
    expect(api.listLibraryFiles).not.toHaveBeenCalled()
    expect(api.libraryDiskUsage).not.toHaveBeenCalled()
    document.getElementById('welcome-screen').classList.remove('hidden')
    await vi.waitFor(() => expect(api.listLibraryFiles).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(api.libraryDiskUsage).toHaveBeenCalledOnce())
    document.getElementById('welcome-screen').classList.add('hidden')
    document.getElementById('welcome-screen').classList.remove('hidden')
    await Promise.resolve()
    expect(api.listLibraryFiles).toHaveBeenCalledOnce()
  })

  it('keeps an explicit hidden refresh immediate and does not repeat it on first show', async () => {
    const api = mountHidden()
    const panel = initLibraryPanel({ api })
    await panel.refresh()
    expect(api.listLibraryFiles).toHaveBeenCalledOnce()
    document.getElementById('welcome-screen').classList.remove('hidden')
    await Promise.resolve(); await Promise.resolve()
    expect(api.listLibraryFiles).toHaveBeenCalledOnce()
  })
})

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

it('preserves cached sizes while pending and marks completion explicitly', () => {
  const entries = [{ type: 'part', path: 'a.nadoc', size_bytes: 10, sim_bytes: 40, disk_bytes: 50 }]
  const pending = mergeLibraryDiskUsage(entries, { 'a.nadoc': null })
  expect(pending[0]).toMatchObject({ disk_bytes: 50, disk_usage_pending: true })
  const ready = mergeLibraryDiskUsage(pending, { 'a.nadoc': 90 })
  expect(ready[0]).toMatchObject({ disk_bytes: 100, disk_usage_pending: false })
})

describe('inline library rename', () => {
  async function setup(rename = vi.fn().mockResolvedValue({ new_path: 'new.nadoc' })) {
    document.body.innerHTML = '<div id="welcome-screen"><div id="library-panel-mount"></div></div>'
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([
        { path: 'old.nadoc', name: 'old', type: 'part', mtime_iso: new Date().toISOString() },
        { path: 'taken.nadoc', name: 'taken', type: 'part', mtime_iso: new Date().toISOString() },
      ]),
      renameLibrary: rename,
    }
    const onOpenPart = vi.fn()
    const panel = initLibraryPanel({ api, onOpenPart })
    await panel.refresh()
    document.querySelector('[data-library-path="old.nadoc"] [title="Rename"]').click()
    await new Promise(resolve => setTimeout(resolve, 30))
    return { api, panel, onOpenPart, input: document.querySelector('.lib-inline-input') }
  }
  const key = (input, value, options = {}) => input.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true, ...options }))

  it('keeps focus, draft and selection through refresh and editing shortcuts', async () => {
    const { panel, input, onOpenPart } = await setup()
    expect(input.value).toBe('old')
    input.value = 'new name'
    input.setSelectionRange(2, 5)
    input.click()
    key(input, ' ')
    key(input, 'a', { ctrlKey: true })
    await panel.refresh()
    expect(document.querySelector('.lib-inline-input')).toBe(input)
    expect(document.activeElement).toBe(input)
    expect(input.value).toBe('new name')
    expect(input.selectionStart).toBe(2)
    expect(onOpenPart).not.toHaveBeenCalled()
    key(input, 'Escape')
    expect(document.querySelector('.lib-inline-input')).toBeNull()
  })

  it('submits Enter once without opening the file and retains failed drafts for retry', async () => {
    let resolve
    const rename = vi.fn().mockImplementation(() => new Promise(r => { resolve = r }))
    const { input, onOpenPart } = await setup(rename)
    expect(input.value).toBe('old')
    input.value = 'new name'
    key(input, 'Enter'); key(input, 'Enter')
    expect(rename).toHaveBeenCalledTimes(1)
    expect(rename.mock.calls[0].slice(0, 2)).toEqual(['old.nadoc', 'new name.nadoc'])
    expect(onOpenPart).not.toHaveBeenCalled()
    rename.mock.calls[0][2].onError(403, 'Workspace is read-only')
    resolve(null)
    await vi.waitFor(() => expect(input.disabled).toBe(false))
    expect(document.body.textContent).toContain('Workspace is read-only')
    expect(document.body.textContent).not.toContain('already exist')
    expect(document.activeElement).toBe(input)
    expect(input.value).toBe('new name')
    rename.mockResolvedValue({ new_path: 'new name.nadoc' })
    const confirm = document.querySelector('[title="Confirm rename"]')
    key(confirm, 'Enter')
    expect(onOpenPart).not.toHaveBeenCalled()
    confirm.click()
    expect(onOpenPart).not.toHaveBeenCalled()
    await vi.waitFor(() => expect(document.querySelector('.lib-inline-input')).toBeNull())
  })

  it.each(['Enter', 'blur'])('finishes %s without waiting for the next listing', async action => {
    const rename = vi.fn().mockResolvedValue({ new_path: 'saved.nadoc' })
    const { input, api } = await setup(rename)
    let resolveListing
    api.listLibraryFiles.mockImplementation(() => new Promise(resolve => { resolveListing = resolve }))
    input.value = 'saved'
    if (action === 'Enter') key(input, 'Enter')
    else input.blur()
    await vi.waitFor(() => expect(document.querySelector('.lib-inline-input')).toBeNull())
    expect(document.querySelector('[data-library-path="saved.nadoc"] .lib-row-name').textContent).toBe('saved')
    expect(rename).toHaveBeenCalledTimes(1)
    resolveListing([{ path: 'saved.nadoc', name: 'saved', type: 'part', mtime_iso: new Date().toISOString() }])
  })

  it('cancels without saving when focus moves to Cancel', async () => {
    const { input, api } = await setup()
    input.value = 'discard'
    const cancel = document.querySelector('[title="Cancel"]')
    cancel.focus()
    expect(api.renameLibrary).not.toHaveBeenCalled()
    cancel.click()
    expect(document.querySelector('.lib-inline-input')).toBeNull()
    expect(api.renameLibrary).not.toHaveBeenCalled()
  })

  it('rejects a real collision locally while keeping the editor open', async () => {
    const { input, api } = await setup()
    input.value = 'taken'
    key(input, 'Enter')
    expect(api.renameLibrary).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('already exists')
    expect(document.querySelector('.lib-inline-input')).toBe(input)
  })
})

describe('workspace move destinations and stable refresh space', () => {
  it('offers only fresh server-validated destinations, not cached folders', async () => {
    document.body.innerHTML = '<div id="library-panel-mount"></div>'
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([
        { path: 'Stale', name: 'Stale', type: 'folder' },
        { path: 'sample.nadoc', name: 'sample', type: 'part', mtime_iso: new Date().toISOString() },
      ]),
      listLibraryMoveDestinations: vi.fn().mockResolvedValue(['Fresh']),
      moveLibrary: vi.fn().mockResolvedValue({}),
    }
    const panel = initLibraryPanel({ api })
    await panel.refresh()
    document.querySelector('[data-library-path="sample.nadoc"] [title="Move"]').click()
    await vi.waitFor(() => expect(document.querySelector('.lib-move-picker')).not.toBeNull())
    expect(api.listLibraryMoveDestinations).toHaveBeenCalledWith(['sample.nadoc'])
    expect([...document.querySelectorAll('[data-move-destination]')].map(el => el.dataset.moveDestination)).toEqual(['Fresh'])
    document.querySelector('[data-move-destination="Fresh"]').click()
    await vi.waitFor(() => expect(api.moveLibrary).toHaveBeenCalledWith('sample.nadoc', 'Fresh'))
  })

  it('shows an empty destination list rather than offering invalid folders', async () => {
    document.body.innerHTML = '<div id="library-panel-mount"></div>'
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([
        { path: 'sample.nadoc', name: 'sample', type: 'part', mtime_iso: new Date().toISOString() },
      ]),
      listLibraryMoveDestinations: vi.fn().mockResolvedValue([]),
    }
    const panel = initLibraryPanel({ api })
    await panel.refresh()
    document.querySelector('[title="Move"]').click()
    await vi.waitFor(() => expect(document.querySelector('.lib-move-picker')?.textContent).toContain('No valid workspace destinations'))
    expect(document.querySelectorAll('[data-move-destination]')).toHaveLength(0)
  })

  it('keeps the refresh status row in layout when its contents disappear', async () => {
    document.body.innerHTML = '<div id="library-panel-mount"></div>'
    let finishUsage
    const api = {
      listLibraryFiles: vi.fn().mockResolvedValue([]),
      libraryDiskUsage: vi.fn().mockImplementation(() => new Promise(resolve => { finishUsage = resolve })),
    }
    const panel = initLibraryPanel({ api })
    await panel.refresh()
    const status = document.querySelector('.lib-simulation-refresh-status')
    expect(status.style.visibility).toBe('visible')
    const reservedHeight = status.style.height
    finishUsage({})
    await vi.waitFor(() => expect(status.style.visibility).toBe('hidden'))
    expect(status.style.display).toBe('flex')
    expect(status.style.height).toBe(reservedHeight)
    expect(status.getAttribute('aria-hidden')).toBe('true')
  })
})

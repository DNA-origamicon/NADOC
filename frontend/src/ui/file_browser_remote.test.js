import { afterEach, describe, expect, it, vi } from 'vitest'
import { openFileBrowser } from './file_browser.js'

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

const tick = () => new Promise(resolve => setTimeout(resolve, 0))

describe('remote workspace tabs', () => {
  it('shows configured online and offline servers and returns remote identity', async () => {
    const api = {
      getCollaborationPeerStatuses: vi.fn().mockResolvedValue({ peers: [
        { id: 'online', name: 'Laptop', online: true },
        { id: 'offline', name: 'Lab PC', online: false },
      ] }),
      listLibraryFiles: vi.fn().mockResolvedValue([]),
      listPeerLibraryFiles: vi.fn().mockResolvedValue([
        { path: 'parts/Shared.nadoc', name: 'Shared', type: 'part', mtime_iso: new Date().toISOString() },
      ]),
    }
    const pending = openFileBrowser({ title: 'Open', mode: 'open', api })
    await tick(); await tick()
    const buttons = [...document.querySelectorAll('button')]
    const laptop = buttons.find(item => item.textContent.includes('Laptop'))
    const offline = buttons.find(item => item.textContent.includes('Lab PC'))
    expect(laptop).toBeTruthy()
    expect(offline.disabled).toBe(true)
    laptop.click()
    await tick(); await tick()
    expect(api.listPeerLibraryFiles).toHaveBeenCalledWith('online')
    const folder = [...document.querySelectorAll('span')].find(item => item.textContent === 'parts')
    folder.parentElement.click()
    await tick()
    const file = [...document.querySelectorAll('span')].find(item => item.textContent === 'Shared.nadoc')
    file.parentElement.click()
    await expect(pending).resolves.toEqual({ path: 'parts/Shared.nadoc', name: 'Shared', peer_id: 'online' })
  })
})

// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { pickSystemFolder } from './folder_picker.js'

const listing = (path = '/home/user') => ({ path, parent: '/', entries: [], wsl: true,
  locations: [{ name: 'Home', path: '/home/user' }, { name: 'Windows drive (F:)', path: '/mnt/f', free_bytes: 1024 ** 3 }] })
const button = text => [...document.querySelectorAll('button')].find(b => b.textContent.includes(text))
const flush = async () => { await new Promise(resolve => setTimeout(resolve, 0)) }

describe('system folder navigation', () => {
  it('navigates directly to a mounted drive and returns its validated path', async () => {
    const api = { fsListDir: vi.fn(async path => listing(path || '/home/user')) }
    const result = pickSystemFolder({ api })
    await flush()
    expect(button('Windows drive (F:)').textContent).toContain('free')
    button('Windows drive (F:)').click()
    expect(button('Select this folder').disabled).toBe(true)
    await flush()
    expect(api.fsListDir).toHaveBeenLastCalledWith('/mnt/f')
    button('Select this folder').click()
    expect(await result).toBe('/mnt/f')
  })

  it('accepts pasted Windows paths via Enter and selects the normalized result', async () => {
    const api = { fsListDir: vi.fn().mockResolvedValueOnce(listing()).mockResolvedValueOnce(listing('/mnt/f/My simulations')) }
    const result = pickSystemFolder({ api })
    await flush()
    const input = document.querySelector('[aria-label="Folder path"]')
    input.value = 'F:\\My simulations'
    input.dispatchEvent(new Event('input'))
    expect(button('Select this folder').disabled).toBe(true)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(api.fsListDir).toHaveBeenLastCalledWith('F:\\My simulations')
    button('Select this folder').click()
    expect(await result).toBe('/mnt/f/My simulations')
  })

  it('recovers to Home if the remembered drive is disconnected', async () => {
    const api = { fsListDir: vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce(listing()),
      lastErrorMessage: () => 'Drive unavailable' }
    const result = pickSystemFolder({ api, initialPath: '/mnt/f/missing' })
    await flush()
    expect(api.fsListDir).toHaveBeenLastCalledWith(null)
    expect(document.body.textContent).toContain('Drive unavailable')
    expect(button('Select this folder').disabled).toBe(false)
    button('Cancel').click()
    expect(await result).toBeNull()
  })

  it('ignores stale responses after a newer navigation', async () => {
    let resolveSlow
    const api = { fsListDir: vi.fn().mockResolvedValueOnce(listing())
      .mockImplementationOnce(() => new Promise(resolve => { resolveSlow = resolve }))
      .mockResolvedValueOnce(listing('/home/user')) }
    const result = pickSystemFolder({ api })
    await flush()
    button('Windows drive (F:)').click()
    button('Home').click()
    await flush()
    resolveSlow(listing('/mnt/f'))
    await flush()
    button('Select this folder').click()
    expect(await result).toBe('/home/user')
  })
})

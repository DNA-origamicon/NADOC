import { afterEach, describe, expect, it, vi } from 'vitest'
import { initTailscaleSetup } from './tailscale_setup.js'
import * as api from '../api/client.js'

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
const tick = () => new Promise(resolve => setTimeout(resolve, 0))

describe('Tailscale setup', () => {
  it('opens from Help and displays a one-time pairing code', async () => {
    document.body.innerHTML = '<button id="menu-help-tailscale-setup"></button>'
    vi.spyOn(api, 'getCollaborationIdentity').mockResolvedValue({ sync_enabled: true, public_url: 'http://100.1.2.3:5173', server_name: 'Desktop' })
    vi.spyOn(api, 'getCollaborationPeerStatuses').mockResolvedValue({ peers: [] })
    vi.spyOn(api, 'startCollaborationPairing').mockResolvedValue({ code: '123456' })
    initTailscaleSetup()
    document.getElementById('menu-help-tailscale-setup').click()
    await tick(); await tick()
    const show = [...document.querySelectorAll('button')].find(item => item.textContent === 'Show one-time pairing code')
    show.click()
    await tick(); await tick()
    expect(document.body.textContent).toContain('123456')
    expect(document.body.textContent).toContain('expires in five minutes')
  })

  it('notifies the welcome library after pairing succeeds', async () => {
    document.body.innerHTML = '<button id="menu-help-tailscale-setup"></button>'
    vi.spyOn(api, 'getCollaborationIdentity').mockResolvedValue({ sync_enabled: true, public_url: 'http://100.1.2.3:5173', server_name: 'Desktop' })
    vi.spyOn(api, 'getCollaborationPeerStatuses').mockResolvedValue({ peers: [] })
    vi.spyOn(api, 'connectCollaborationPeer').mockResolvedValue({ id: 'compy', name: 'Compy5000' })
    const changed = vi.fn()
    window.addEventListener('nadoc:collaboration-peers-changed', changed, { once: true })
    initTailscaleSetup()
    document.getElementById('menu-help-tailscale-setup').click()
    await tick(); await tick()
    const inputs = document.querySelectorAll('input')
    inputs[0].value = 'http://100.1.2.4:5173'
    inputs[1].value = '123456'
    ;[...document.querySelectorAll('button')].find(item => item.textContent === 'Pair both servers').click()
    await tick(); await tick(); await tick()
    expect(changed).toHaveBeenCalledOnce()
  })
})

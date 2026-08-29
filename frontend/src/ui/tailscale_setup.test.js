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
})

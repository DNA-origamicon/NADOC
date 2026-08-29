import * as api from '../api/client.js'

function node(tag, text, css = '') {
  const item = document.createElement(tag)
  if (text != null) item.textContent = text
  item.style.cssText = css
  return item
}

export function initTailscaleSetup() {
  const overlay = node('div', null, 'display:none;position:fixed;inset:0;z-index:10020;background:#000b;align-items:center;justify-content:center')
  const panel = node('section', null, 'width:min(680px,94vw);max-height:86vh;overflow:auto;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:20px;font:13px system-ui')
  overlay.append(panel); document.body.append(overlay)
  overlay.addEventListener('click', event => { if (event.target === overlay) close() })

  const button = (label, action) => {
    const item = node('button', label, 'padding:7px 11px;background:#21262d;color:#f0f6fc;border:1px solid #484f58;border-radius:5px;cursor:pointer')
    item.addEventListener('click', async () => { item.disabled = true; try { await action() } finally { item.disabled = false } })
    return item
  }
  const input = placeholder => {
    const item = node('input', null, 'padding:8px;background:#010409;color:#f0f6fc;border:1px solid #30363d;border-radius:4px;flex:1;min-width:180px')
    item.placeholder = placeholder
    return item
  }
  const row = (...items) => { const item = node('div', null, 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:9px 0'); item.append(...items); return item }
  let message = ''
  let pairing = null

  function close() { overlay.style.display = 'none' }
  async function render() {
    panel.replaceChildren()
    const identity = await api.getCollaborationIdentity()
    const statuses = await api.getCollaborationPeerStatuses()
    panel.append(row(node('h2', 'Tailscale Workspace Setup', 'margin:0;flex:1'), button('Close', close)))
    panel.append(node('p', 'Pair NADOC servers once. Their workspaces then appear as live tabs whenever you open the file browser.'))
    if (!identity?.sync_enabled || !identity?.public_url) {
      panel.append(node('p', 'Remote access is not active. Restart NADOC with: ./start.sh --tailscale', 'color:#f0883e'))
      return
    }
    panel.append(node('p', `${identity.server_name} · ${identity.public_url}`, 'color:#8b949e'))
    if (message) panel.append(node('p', message, 'color:#58a6ff'))
    if (pairing) {
      panel.append(node('div', pairing.code, 'font:700 30px ui-monospace;text-align:center;letter-spacing:8px;padding:14px;border:1px solid #30363d;border-radius:6px'))
      panel.append(node('p', 'On the other computer, open this setup panel and enter this computer’s URL plus the code. It expires in five minutes.', 'color:#8b949e'))
    } else {
      panel.append(button('Show one-time pairing code', async () => { pairing = await api.startCollaborationPairing(); await render() }))
    }
    panel.append(node('h3', 'Connect to another computer'))
    const url = input('Other server URL, e.g. http://100.x.y.z:5173')
    const code = input('6-digit code')
    code.maxLength = 6
    panel.append(row(url, code, button('Pair both servers', async () => {
      message = 'Pairing…'; await render()
      const peer = await api.connectCollaborationPeer(url.value.trim(), code.value.trim())
      message = peer ? `Connected to ${peer.name}.` : 'Pairing failed. Check the URL, code, and server status.'
      pairing = null
      await render()
    })))
    panel.append(node('h3', 'Configured servers'))
    const peers = statuses?.peers || []
    if (!peers.length) panel.append(node('p', 'No other servers paired yet.', 'color:#8b949e'))
    for (const peer of peers) panel.append(row(
      node('span', peer.online ? '●' : '○', `color:${peer.online ? '#3fb950' : '#8b949e'}`),
      node('strong', peer.name), node('span', peer.base_url, 'color:#8b949e'),
      node('span', peer.online ? 'online' : 'offline', `color:${peer.online ? '#3fb950' : '#8b949e'}`),
    ))
  }
  async function open() {
    overlay.style.display = 'flex'
    try { await render() } catch (error) { panel.replaceChildren(node('p', `Setup unavailable: ${error.message || error}`), button('Close', close)) }
  }
  document.getElementById('menu-help-tailscale-setup')?.addEventListener('click', open)
  return { open, close }
}

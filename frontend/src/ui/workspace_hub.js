import { store } from '../state/store.js'
import * as api from '../api/client.js'

export function activeProjectContext(state = store.getState()) {
  const design = state.currentDesign
  if (!design?.id) return null
  const loadout = design.loadouts?.find(item => item.id === design.active_loadout_id)
  return { projectId: design.id, loadoutId: loadout?.id || design.active_loadout_id || 'main' }
}

/** Stable per-browser identity that cannot make the optional hub abort app boot. */
export function collaborationClientId(storage = globalThis.localStorage, cryptoApi = globalThis.crypto) {
  const key = 'nadoc.collaboration.clientId'
  try {
    const saved = storage?.getItem(key)
    if (saved) return saved
  } catch { /* private/blocked storage — continue with an in-memory id */ }

  let id
  if (typeof cryptoApi?.randomUUID === 'function') {
    id = cryptoApi.randomUUID()
  } else if (typeof cryptoApi?.getRandomValues === 'function') {
    const bytes = cryptoApi.getRandomValues(new Uint8Array(16))
    id = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('')
  } else {
    id = `${Date.now()}-${Math.random().toString(16).slice(2)}`
  }

  try { storage?.setItem(key, id) } catch { /* identity remains valid for this page */ }
  return id
}

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag)
  if (text != null) node.textContent = text
  Object.assign(node, attrs)
  return node
}

function button(text, run, danger = false) {
  const node = el('button', text)
  node.style.cssText = `padding:6px 10px;border:1px solid ${danger ? '#f85149' : '#484f58'};border-radius:5px;background:#21262d;color:#f0f6fc;cursor:pointer`
  node.addEventListener('click', async () => {
    node.disabled = true
    try { await run() } finally { node.disabled = false }
  })
  return node
}

export function initWorkspaceHub() {
  const overlay = el('div')
  overlay.id = 'workspace-hub'
  overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:10000;background:#000a;align-items:center;justify-content:center'
  const panel = el('section')
  panel.style.cssText = 'width:min(920px,94vw);max-height:88vh;overflow:auto;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:18px;font:13px system-ui'
  overlay.append(panel)
  document.body.append(overlay)
  overlay.addEventListener('click', e => { if (e.target === overlay) close() })

  const clientId = collaborationClientId()
  let identity = null
  let notice = ''

  function close() { overlay.style.display = 'none' }
  function row(...nodes) {
    const r = el('div'); r.style.cssText = 'display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:7px 0'; r.append(...nodes); return r
  }
  function input(placeholder, type = 'text') {
    const n = el('input'); n.placeholder = placeholder; n.type = type
    n.style.cssText = 'padding:7px;background:#010409;color:#f0f6fc;border:1px solid #30363d;border-radius:4px;min-width:150px;flex:1'
    return n
  }
  async function act(label, fn) {
    notice = `${label}…`; await render()
    try { const result = await fn(); notice = `${label} complete${result?.relation ? ` (${result.relation})` : ''}.` }
    catch (error) { notice = `${label} failed: ${error.message || error}` }
    await render()
  }

  async function render() {
    panel.replaceChildren()
    const heading = row(el('h2', 'Workspace Hub'), button('Close', close))
    heading.style.justifyContent = 'space-between'; panel.append(heading)
    const ctx = activeProjectContext()
    const [id, peers, projects] = await Promise.all([
      api.getCollaborationIdentity(), api.listCollaborationPeers(), api.listCollaborationProjects(),
    ])
    identity = id || identity
    if (!identity || !peers || !projects) {
      panel.append(el('p', 'Collaboration service is unavailable.')); return
    }
    panel.append(el('p', `This server: ${identity.server_name} · ${identity.server_id}${identity.sync_enabled ? '' : ' · peer sync token not configured'}`))
    if (notice) panel.append(el('p', notice, { style: 'color:#58a6ff' }))

    const peerTitle = el('h3', 'Servers')
    panel.append(peerTitle)
    for (const peer of peers.peers) {
      const open = button('Open frontend', () => { window.open(peer.base_url, '_blank', 'noopener,noreferrer') })
      const controls = [el('strong', peer.name), el('span', peer.base_url), open]
      if (ctx) {
        for (const direction of ['pull', 'push', 'sync']) controls.push(button(direction, () => act(`${direction} ${peer.name}`, () => api.syncCollaborationPeer(peer.id, ctx.projectId, direction))))
      }
      controls.push(button('Remove', () => act('Remove peer', () => api.removeCollaborationPeer(peer.id)), true))
      panel.append(row(...controls))
    }
    const peerId = input('server ID'), peerName = input('server name'), peerUrl = input('https://machine.tailnet.ts.net:5173'), peerToken = input('peer token', 'password')
    panel.append(row(peerId, peerName, peerUrl, peerToken, button('Register server', () => act('Register peer', () => api.registerCollaborationPeer({ id: peerId.value, name: peerName.value, base_url: peerUrl.value, token: peerToken.value })))))

    panel.append(el('h3', 'Active project'))
    if (!ctx) {
      panel.append(el('p', `No design is open. Known projects: ${projects.projects.join(', ') || 'none'}.`)); return
    }
    const overview = await api.getProjectOverview(ctx.projectId)
    if (!overview) { panel.append(el('p', `Project ${ctx.projectId} has not been revisioned yet. Save or edit it once, then reopen this hub.`)); return }
    panel.append(el('p', `Project ${ctx.projectId} · active branch ${ctx.loadoutId}`))
    const refs = Object.values(overview.refs || {})
    for (const ref of refs) {
      const head = ref.head_revision_id || ref.revision_id
      const controls = [el('strong', ref.name || ref.loadout_id), el('code', head?.slice(0, 12) || '—')]
      if (head) controls.push(button('History', () => act('Load history', async () => {
        const result = await api.getLoadoutHistory(ctx.projectId, ref.loadout_id)
        notice = result.history.map(item => `${item.revision_id.slice(0, 10)} ${item.message || ''}`).join(' ← ')
        return result
      })))
      if (head) controls.push(button('Name version', async () => {
        const name = window.prompt('Immutable version name')
        if (name) await act('Create version', () => api.createProjectVersion(ctx.projectId, { revision_id: head, name, source_loadout_id: ref.loadout_id }))
      }))
      if (ref.loadout_id !== ctx.loadoutId) controls.push(button('Promote here', async () => {
        if (!window.confirm(`Replace ${ctx.loadoutId} with ${ref.name || ref.loadout_id}? The current head will be preserved as a recovery version.`)) return
        const target = overview.refs[ctx.loadoutId]
        await act('Promote branch', () => api.promoteProjectBranch(ctx.projectId, { source_loadout_id: ref.loadout_id, target_loadout_id: ctx.loadoutId, expected_target_head: target?.head_revision_id || null }))
      }))
      panel.append(row(...controls))
    }
    const activeRef = overview.refs?.[ctx.loadoutId]
    if (activeRef) {
      panel.append(row(
        button('Acquire edit lease', () => act('Acquire lease', () => api.acquireProjectLease(ctx.projectId, ctx.loadoutId, { server_id: identity.server_id, server_name: identity.server_name, client_id: clientId }))),
        button('Auto-fork if busy', () => act('Acquire/fork', () => api.acquireProjectLease(ctx.projectId, ctx.loadoutId, { server_id: identity.server_id, server_name: identity.server_name, client_id: clientId, auto_fork: true }))),
        button('Release lease', () => act('Release lease', () => api.releaseProjectLease(ctx.projectId, ctx.loadoutId, identity.server_id, clientId))),
      ))
    }
    const jobs = overview.jobs || []
    panel.append(el('h3', `Simulation data (${jobs.length})`))
    for (const job of jobs) panel.append(row(el('span', `${job.engine}/${job.job_id}`), el('span', (job.locations || []).map(x => x.server_name || x.server_id).join(', ') || 'location unknown')))
  }

  async function open() {
    overlay.style.display = 'flex'
    try { await render() } catch (error) { panel.replaceChildren(el('h2', 'Workspace Hub'), el('p', `Unable to load: ${error.message || error}`), button('Close', close)) }
  }
  document.getElementById('menu-workspace-hub')?.addEventListener('click', open)
  return { open, close }
}

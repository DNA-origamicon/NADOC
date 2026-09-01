/**
 * Library panel — tree-view file manager mounted on the welcome screen.
 *
 * Shows the workspace as a navigable folder tree.  Supports inline rename,
 * new-folder creation, file deletion, and move-to-folder operations.
 * Import uses the file browser to pick a destination on the server.
 */

import { openFileBrowser } from './file_browser.js'
import { showToast } from './toast.js'
import { confirmAndDeleteFile } from './file_deletion.js'
import { formatBytes } from './format_bytes.js'
import { fetchActiveJobs, activeJobForPath, jobActivityTooltip, jobLocationTag, normPath } from './job_activity.js'
import { visibleWorkspaceEntries } from './sim_folders.js'
import { showConfirm } from './primitives/confirm.js'

const _JOB_POLL_MS = 4000   // welcome-screen activity-spinner refresh cadence
const _PEER_POLL_MS = 4000  // keep remote tabs in sync with current reachability
const _LIBRARY_CACHE_KEY = 'nadoc:library-files:v1'
const _LARGE_SIM_DATA_BYTES = 0.5 * 1024 ** 3

export function hasLargeSimulationData(simBytes) {
  return Number(simBytes) > _LARGE_SIM_DATA_BYTES
}

export function readLibraryCache(storage = localStorage) {
  try {
    const cached = JSON.parse(storage.getItem(_LIBRARY_CACHE_KEY) || 'null')
    return Array.isArray(cached) ? cached : []
  } catch { return [] }
}

export function writeLibraryCache(entries, storage = localStorage) {
  try { storage.setItem(_LIBRARY_CACHE_KEY, JSON.stringify(entries)); return true } catch { return false }
}

export function mergeLibraryDiskUsage(entries, usage) {
  if (!usage || typeof usage !== 'object') return entries
  return entries.map(entry => {
    if (entry.type !== 'part') return entry
    const simBytes = Number(usage[normPath(entry.path)] ?? 0)
    return { ...entry, sim_bytes: simBytes, disk_bytes: (entry.size_bytes ?? 0) + simBytes }
  })
}

function _relativeTime(isoString) {
  const ms  = Date.now() - new Date(isoString).getTime()
  const sec = Math.floor(ms / 1000)
  const min = Math.floor(sec / 60)
  const hr  = Math.floor(min / 60)
  const day = Math.floor(hr  / 24)
  if (sec < 60)  return 'just now'
  if (min < 60)  return `${min}m ago`
  if (hr  < 24)  return `${hr}h ago`
  if (day < 7)   return `${day}d ago`
  return new Date(isoString).toLocaleDateString()
}

// ── Sort helpers ──────────────────────────────────────────────────────────────

const _SORT_COLS = [
  { key: 'name',     label: 'Name',     defaultDir: 'asc'  },
  { key: 'modified', label: 'Modified', defaultDir: 'desc' },
  { key: 'size',     label: 'Size',     defaultDir: 'desc' },
  { key: 'type',     label: 'Type',     defaultDir: 'asc'  },
]

// Total on-disk footprint of an entry: the .nadoc file + its simulation jobs.
function _entryDiskBytes(e) {
  return e.disk_bytes ?? e.size_bytes ?? 0
}

function _sortFiles(files, key, dir) {
  const d = dir === 'asc' ? 1 : -1
  if (key === 'name') {
    files.sort((a, b) => d * a.name.localeCompare(b.name))
  } else if (key === 'modified') {
    files.sort((a, b) => d * (new Date(a.mtime_iso) - new Date(b.mtime_iso)))
  } else if (key === 'size') {
    files.sort((a, b) => d * (_entryDiskBytes(a) - _entryDiskBytes(b)) || a.name.localeCompare(b.name))
  } else if (key === 'type') {
    files.sort((a, b) => {
      const t = (a.type === b.type ? 0 : a.type === 'part' ? -1 : 1) * d
      return t !== 0 ? t : a.name.localeCompare(b.name)
    })
  }
}

// ── Tree builder ──────────────────────────────────────────────────────────────

function _buildTree(entries, { sortKey = 'modified', sortDir = 'desc' } = {}) {
  const folderMap = new Map()
  const root = { name: '', path: '', type: 'root', children: [], files: [], mtime_iso: '' }
  folderMap.set('', root)

  // Explicit folder entries
  for (const e of entries) {
    if (e.type === 'folder') {
      folderMap.set(e.path, { ...e, children: [], files: [] })
    }
  }
  // Infer intermediate folders from file paths
  for (const e of entries) {
    if (e.type === 'folder') continue
    const parts = e.path.split('/')
    let acc = ''
    for (let i = 0; i < parts.length - 1; i++) {
      acc = acc ? `${acc}/${parts[i]}` : parts[i]
      if (!folderMap.has(acc)) {
        folderMap.set(acc, { name: parts[i], path: acc, type: 'folder', children: [], files: [], mtime_iso: e.mtime_iso })
      }
    }
  }
  // Wire children to parents
  for (const [path, node] of folderMap) {
    if (!path) continue
    const parentPath = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
    const parent = folderMap.get(parentPath) ?? root
    parent.children.push(node)
  }
  // Place files in their immediate parent
  for (const e of entries) {
    if (e.type === 'folder') continue
    const parentPath = e.path.includes('/') ? e.path.slice(0, e.path.lastIndexOf('/')) : ''
    const parent = folderMap.get(parentPath) ?? root
    parent.files.push(e)
  }
  // Sort each level: folders alpha, files per sort config
  const sortNode = (n) => {
    n.children.sort((a, b) => a.name.localeCompare(b.name))
    _sortFiles(n.files, sortKey, sortDir)
    n.children.forEach(sortNode)
  }
  sortNode(root)
  return root
}

// ── Component ─────────────────────────────────────────────────────────────────

export function initLibraryPanel({ api, onOpenPart, onOpenAssembly, onNewPart, onNewAssembly, onImportCadnano, onImportScadnano }) {
  const mount = document.getElementById('library-panel-mount')
  if (!mount) return { refresh() {} }

  let _allEntries = []
  const _expanded = new Set()
  let _sortKey = 'modified'
  let _sortDir = 'desc'
  let _query   = ''
  let _showSimFolders = false
  let _refreshGeneration = 0
  let _activePeerId = null
  const _selectedPaths = new Set()
  let _lastSelectedPath = null
  let _servers = [{ id: null, name: 'This computer', online: true }]

  // Per-design simulation activity: active MD/oxDNA jobs (polled) + a map from
  // workspace file path → the row's status <span>, so the spinner can be updated
  // in place without rebuilding rows (which would restart its CSS animation).
  let _activeJobs = []
  const _statusEls = new Map()
  let _jobPollTimer = null
  let _peerPollTimer = null

  // ── Action buttons ──────────────────────────────────────────────────────────

  const actionsEl = document.createElement('div')
  actionsEl.className = 'lib-actions'

  function _mkBtn(text, cls) {
    const b = document.createElement('button'); b.textContent = text; b.className = cls; return b
  }
  const newPartBtn    = _mkBtn('New Part',     'lib-btn-primary')
  const newAsmBtn     = _mkBtn('New Assembly', 'lib-btn-secondary')
  const importBtn     = _mkBtn('Import…',      'lib-btn-secondary')
  const newFolderBtn  = _mkBtn('+ Folder',     'lib-btn-secondary')
  const trashBtn      = _mkBtn('',              'lib-trash-icon-btn')
  trashBtn.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
    </svg>`
  trashBtn.title = 'Trash'
  trashBtn.setAttribute('aria-label', 'Open Trash')

  newPartBtn.addEventListener('click', () => onNewPart())
  newAsmBtn.addEventListener('click', () => onNewAssembly())
  importBtn.addEventListener('click', _handleImport)
  newFolderBtn.addEventListener('click', () => _showNewFolderInput(treeEl, '', 0))
  trashBtn.addEventListener('click', _showTrash)

  const simToggleLabel = document.createElement('label')
  simToggleLabel.className = 'lib-show-sim-folders'
  const simToggle = document.createElement('input')
  simToggle.type = 'checkbox'
  simToggle.checked = false
  simToggle.dataset.role = 'show-sim-folders'
  simToggle.addEventListener('change', () => {
    _showSimFolders = simToggle.checked
    _render()
  })
  simToggleLabel.append(simToggle, document.createTextNode('Show sim folders'))

  actionsEl.append(newPartBtn, newAsmBtn, importBtn, newFolderBtn)
  mount.appendChild(actionsEl)

  const libraryNavEl = document.createElement('div')
  libraryNavEl.className = 'lib-library-nav'

  const serverTabsEl = document.createElement('div')
  serverTabsEl.className = 'lib-server-tabs'
  serverTabsEl.setAttribute('role', 'tablist')
  serverTabsEl.setAttribute('aria-label', 'Workspace location')
  libraryNavEl.append(serverTabsEl)
  mount.appendChild(libraryNavEl)

  const bulkEl = document.createElement('div')
  bulkEl.className = 'lib-bulk-actions'
  bulkEl.hidden = true
  mount.appendChild(bulkEl)

  function _updateActionVisibility() {
    const remote = _activePeerId !== null
    for (const item of [newPartBtn, newAsmBtn, importBtn, newFolderBtn, simToggleLabel]) {
      item.style.display = remote ? 'none' : ''
    }
  }

  function _renderServerTabs() {
    serverTabsEl.replaceChildren()
    for (const server of _servers) {
      const active = server.id === _activePeerId
      const tab = document.createElement('button')
      tab.className = 'lib-server-tab'
      tab.setAttribute('role', 'tab')
      tab.setAttribute('aria-selected', String(active))
      const statusDot = document.createElement('span')
      statusDot.className = `lib-server-status ${server.online ? 'online' : 'offline'}`
      statusDot.setAttribute('aria-hidden', 'true')
      const name = document.createElement('span')
      name.textContent = server.name
      tab.append(statusDot, name)
      tab.title = server.online ? `View files on ${server.name}` : `${server.name} is offline`
      tab.disabled = !server.online
      tab.addEventListener('click', async () => {
        _activePeerId = server.id
        _query = ''
        searchEl.value = ''
        _expanded.clear()
        _renderServerTabs()
        _updateActionVisibility()
        await refresh()
      })
      serverTabsEl.appendChild(tab)
    }
  }

  async function _refreshServerStatuses() {
    if (typeof api.getCollaborationPeerStatuses !== 'function') return
    try {
      const status = await api.getCollaborationPeerStatuses()
      _servers = [
        _servers[0],
        ...((status?.peers || []).map(peer => ({
          id: peer.id, name: peer.name, online: !!peer.online,
        }))),
      ]
      _renderServerTabs()
    } catch {
      // A failed status probe must not hide the cached workspace or break refresh.
    }
  }

  function _startPeerPolling() {
    if (_peerPollTimer != null || typeof api.getCollaborationPeerStatuses !== 'function') return
    void _refreshServerStatuses()
    _peerPollTimer = setInterval(_refreshServerStatuses, _PEER_POLL_MS)
  }

  // ── Search bar ──────────────────────────────────────────────────────────────
  // Simple filename filter. Files matching the query (case-insensitive substring
  // on name or path) are kept; folders containing matches are kept and expanded.
  const searchEl = document.createElement('input')
  searchEl.type = 'search'
  searchEl.placeholder = 'Search files…'
  searchEl.className = 'lib-search-input'
  searchEl.style.cssText = [
    'width:100%', 'box-sizing:border-box',
    'padding:4px 8px', 'margin:6px 0',
    'background:var(--color-bg-canvas)',
    'border:1px solid var(--color-border-default)',
    'border-radius:var(--radius-sm)',
    'color:var(--color-text-primary)',
    'font-family:var(--font-ui)', 'font-size:var(--text-sm)',
  ].join(';')
  mount.appendChild(searchEl)
  searchEl.addEventListener('input', () => {
    _query = searchEl.value.trim().toLowerCase()
    _render()
  })

  // ── Sort bar ────────────────────────────────────────────────────────────────

  const sortBarEl = document.createElement('div')
  sortBarEl.className = 'lib-sort-bar'
  mount.appendChild(sortBarEl)

  function _renderSortBar() {
    sortBarEl.innerHTML = ''
    const prefix = document.createElement('span')
    prefix.className = 'lib-sort-label'
    prefix.textContent = 'Sort:'
    sortBarEl.appendChild(prefix)

    for (const col of _SORT_COLS) {
      const el = document.createElement('span')
      const isActive = _sortKey === col.key
      el.className = 'lib-sort-col' + (isActive ? ' active' : '')
      el.textContent = col.label + (isActive ? (_sortDir === 'asc' ? ' ↑' : ' ↓') : '')
      el.addEventListener('click', () => {
        if (_sortKey === col.key) {
          _sortDir = _sortDir === 'asc' ? 'desc' : 'asc'
        } else {
          _sortKey = col.key
          _sortDir = col.defaultDir
        }
        _renderSortBar()
        _render()
      })
      sortBarEl.appendChild(el)
    }
    const libraryOptionsEl = document.createElement('span')
    libraryOptionsEl.className = 'lib-library-options'
    libraryOptionsEl.append(simToggleLabel, trashBtn)
    sortBarEl.appendChild(libraryOptionsEl)
  }
  _renderSortBar()

  // ── Tree container ──────────────────────────────────────────────────────────

  const treeEl = document.createElement('div')
  treeEl.className = 'lib-tree'
  treeEl.setAttribute('role', 'tree')
  treeEl.setAttribute('aria-label', 'Workspace files')
  mount.appendChild(treeEl)

  // ── Refresh ─────────────────────────────────────────────────────────────────

  function _saveCachedEntries() {
    writeLibraryCache(_allEntries)
  }

  function _loadCachedEntries() {
    _allEntries = readLibraryCache()
  }

  async function _refreshDiskUsage(generation) {
    if (typeof api.libraryDiskUsage !== 'function') return
    const usage = await api.libraryDiskUsage()
    if (generation !== _refreshGeneration || !usage) return
    _allEntries = mergeLibraryDiskUsage(_allEntries, usage)
    _saveCachedEntries()
    _render()
  }

  async function refresh() {
    const generation = ++_refreshGeneration
    if (!_allEntries.length) treeEl.innerHTML = '<div class="lib-loading">Loading…</div>'
    try {
      const files = _activePeerId
        ? await api.listPeerLibraryFiles(_activePeerId)
        : await api.listLibraryFiles()
      if (generation !== _refreshGeneration) return
      _allEntries = Array.isArray(files) ? files : []
    } catch {
      if (!_allEntries.length) treeEl.innerHTML = '<div class="lib-empty">Could not reach server.</div>'
      return
    }
    if (!_activePeerId) _saveCachedEntries()
    _render()
    if (!_activePeerId) void _refreshDiskUsage(generation)
  }

  function _render() {
    treeEl.innerHTML = ''
    _statusEls.clear()   // rows are rebuilt below; re-registered in _renderFileRow
    // Apply search filter: include files matching the query, plus every folder
    // explicitly. _buildTree will only create folders for ancestors of kept files.
    const visibleEntries = visibleWorkspaceEntries(_allEntries, _showSimFolders)
    const matchesQuery = entry => (entry.name?.toLowerCase().includes(_query)) ||
      (entry.path?.toLowerCase().includes(_query))
    const matchingFiles = _query
      ? visibleEntries.filter(entry => entry.type !== 'folder' && matchesQuery(entry))
      : []
    const entries = !_query ? visibleEntries : visibleEntries.filter(entry => {
      if (entry.type !== 'folder') return matchesQuery(entry)
      return matchesQuery(entry) || matchingFiles.some(file => file.path.startsWith(entry.path + '/'))
    })
    const tree = _buildTree(entries, { sortKey: _sortKey, sortDir: _sortDir })
    if (!tree.children.length && !tree.files.length) {
      const empty = document.createElement('div')
      empty.className = 'lib-empty'
      empty.textContent = _query
        ? `No files match "${_query}".`
        : 'No files yet — create your first part above.'
      treeEl.appendChild(empty)
      return
    }
    // When searching, auto-expand any folder that has surviving descendants.
    if (_query) {
      const collect = (n) => {
        if (n.path) _expanded.add(n.path)
        for (const c of n.children) collect(c)
      }
      for (const c of tree.children) {
        if (c.children.length || c.files.length) collect(c)
      }
    }
    _renderLevel(tree, treeEl, 0)
    _renderBulkActions()
  }

  function _renderBulkActions() {
    bulkEl.replaceChildren()
    const selected = _allEntries.filter(entry => _selectedPaths.has(entry.path))
    bulkEl.hidden = selected.length === 0
    if (!selected.length) return
    const count = document.createElement('span')
    count.textContent = `${selected.length} selected`
    const move = _mkBtn('Move to…', 'lib-bulk-btn')
    move.addEventListener('click', async () => {
      const dest = await _pickFolderModal(`Move ${selected.length} selected item${selected.length === 1 ? '' : 's'} to…`, null, selected.map(item => item.path))
      if (dest === null) return
      for (const item of selected) await api.moveLibrary(item.path, dest)
      _selectedPaths.clear()
      await refresh()
    })
    const trash = _mkBtn('Trash', 'lib-bulk-btn lib-trash-delete')
    trash.addEventListener('click', async () => {
      const ok = await showConfirm({ title: 'Move selected items to Trash', message: `Move ${selected.length} selected item${selected.length === 1 ? '' : 's'} to Trash?`, confirmLabel: 'Move to Trash', danger: true })
      if (!ok) return
      for (const item of selected) await api.trashLibraryItem(item.path)
      _selectedPaths.clear()
      await refresh()
    })
    const clear = _mkBtn('Clear', 'lib-bulk-btn')
    clear.addEventListener('click', () => { _selectedPaths.clear(); _render() })
    bulkEl.append(count, move, trash, clear)
  }

  function _toggleSelection(entry, additive = true) {
    if (!additive) _selectedPaths.clear()
    if (additive && _selectedPaths.has(entry.path)) _selectedPaths.delete(entry.path)
    else _selectedPaths.add(entry.path)
    _lastSelectedPath = entry.path
    _render()
    treeEl.querySelector(`[data-library-path="${CSS.escape(entry.path)}"]`)?.focus()
  }

  function _renderLevel(node, container, depth) {
    for (const folder of node.children) _renderFolderRow(folder, container, depth)
    for (const file   of node.files)   _renderFileRow(file, container, depth)
  }

  // ── Folder row ──────────────────────────────────────────────────────────────

  function _renderFolderRow(folder, container, depth) {
    const expanded  = _expanded.has(folder.path)

    const rowEl = document.createElement('div')
    rowEl.className = 'lib-tree-row lib-folder-row'
    rowEl.dataset.libraryPath = folder.path
    rowEl.tabIndex = 0
    rowEl.setAttribute('role', 'treeitem')
    rowEl.setAttribute('aria-selected', String(_selectedPaths.has(folder.path)))
    rowEl.style.paddingLeft = `${depth * 16 + 4}px`

    const toggleEl = document.createElement('span')
    toggleEl.className   = 'lib-folder-toggle'
    toggleEl.textContent = expanded ? '▼' : '▶'

    const iconEl = document.createElement('span')
    iconEl.textContent = '📁'
    iconEl.style.cssText = 'font-size:12px;margin-right:6px;flex-shrink:0'

    const nameEl = document.createElement('span')
    nameEl.className   = 'lib-row-name'
    nameEl.textContent = folder.name

    const actEl = _makeActionsEl(_activePeerId ? [] : [
      { label: '+', title: 'New subfolder', fn: (e) => { e.stopPropagation(); childrenEl.style.display = ''; _expanded.add(folder.path); toggleEl.textContent = '▼'; _showNewFolderInput(childrenEl, folder.path, depth + 1) } },
      { label: '✎', title: 'Rename', fn: (e) => { e.stopPropagation(); _startRename(rowEl, nameEl, folder) } },
      { label: '↗', title: 'Move', fn: async (e) => { e.stopPropagation(); await _moveItem(folder) } },
      { label: '×', title: 'Move to Trash', danger: true, fn: async (e) => {
        e.stopPropagation()
        await _trashItem(folder)
      }},
    ])

    rowEl.append(toggleEl, iconEl, nameEl, actEl)

    const childrenEl = document.createElement('div')
    childrenEl.style.display = expanded ? '' : 'none'
    if (expanded) _renderLevel(folder, childrenEl, depth + 1)

    rowEl.addEventListener('click', (e) => {
      if (e.ctrlKey || e.metaKey) { _toggleSelection(folder, true); return }
      const isExpanded = _expanded.has(folder.path)
      if (isExpanded) { _expanded.delete(folder.path); childrenEl.style.display = 'none'; toggleEl.textContent = '▶' }
      else            { _expanded.add(folder.path);    childrenEl.style.display = '';     toggleEl.textContent = '▼'; if (!childrenEl.children.length) _renderLevel(folder, childrenEl, depth + 1) }
    })
    rowEl.addEventListener('contextmenu', e => { e.preventDefault(); _showContextMenu(e, folder) })
    rowEl.addEventListener('keydown', e => _onRowKeydown(e, folder, () => rowEl.click()))

    container.appendChild(rowEl)
    container.appendChild(childrenEl)
  }

  // ── File row ─────────────────────────────────────────────────────────────────

  function _renderFileRow(file, container, depth) {
    const rowEl = document.createElement('div')
    rowEl.className = `lib-tree-row lib-file-row${file.type === 'assembly' ? ' lib-file-assembly' : ''}`
    rowEl.dataset.libraryPath = file.path
    rowEl.tabIndex = 0
    rowEl.setAttribute('role', 'treeitem')
    rowEl.setAttribute('aria-selected', String(_selectedPaths.has(file.path)))
    rowEl.style.paddingLeft = `${depth * 16 + 4}px`
    rowEl.title = file.path

    const iconEl = document.createElement('span')
    iconEl.textContent = file.type === 'assembly' ? '⬡' : '◈'
    iconEl.style.cssText = 'font-size:11px;margin-right:6px;flex-shrink:0;color:' + (file.type === 'assembly' ? '#388bfd' : '#3fb950')

    const nameEl = document.createElement('span')
    nameEl.className   = 'lib-row-name'
    nameEl.textContent = file.name

    // Simulation-activity spinner (shown only while this design has a running/
    // preparing MD or oxDNA job). Registered by path so polling updates it in place.
    const statusEl = document.createElement('span')
    statusEl.className = 'lib-row-status'
    _statusEls.set(normPath(file.path), statusEl)
    _applyJobStatus(statusEl, file.path)

    const pathEl = document.createElement('span')
    pathEl.className = 'lib-row-path'
    const parentFolder = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/')) : ''
    pathEl.textContent = depth === 0 && parentFolder ? parentFolder + '/' : ''

    const mtimeEl = document.createElement('span')
    mtimeEl.className   = 'lib-row-mtime'
    mtimeEl.textContent = _relativeTime(file.mtime_iso)

    const sizeEl = document.createElement('span')
    sizeEl.className = 'lib-row-size'
    const diskBytes = _entryDiskBytes(file)
    sizeEl.textContent = diskBytes ? formatBytes(diskBytes) : ''
    const simBytes = file.sim_bytes ?? 0
    if (simBytes > 0) {
      if (hasLargeSimulationData(simBytes)) sizeEl.classList.add('lib-row-size-sim')
      sizeEl.title = `File ${formatBytes(file.size_bytes ?? 0)} + simulation data ${formatBytes(simBytes)}`
    } else if (diskBytes) {
      sizeEl.title = `File ${formatBytes(diskBytes)}`
    }

    const actEl = _makeActionsEl(_activePeerId ? [] : [
      { label: '✎', title: 'Rename', fn: (e) => { e.stopPropagation(); _startRename(rowEl, nameEl, file) } },
      { label: '↗', title: 'Move',   fn: async (e) => { e.stopPropagation(); await _moveItem(file) } },
      { label: '×', title: 'Move to Trash', danger: true, fn: async (e) => {
        e.stopPropagation()
        await _trashItem(file)
      }},
    ])

    rowEl.append(iconEl, nameEl, statusEl, mtimeEl, sizeEl, actEl)
    rowEl.addEventListener('click', async (e) => {
      if (e.ctrlKey || e.metaKey) { _toggleSelection(file, true); return }
      let path = file.path
      let name = file.name
      if (_activePeerId) {
        const server = _servers.find(item => item.id === _activePeerId)
        showToast(`Copying ${file.name} from ${server?.name || 'remote server'}…`)
        const checkout = await api.checkoutPeerLibraryFile(_activePeerId, file.path)
        if (!checkout?.path) {
          showToast('Remote file could not be opened. The server may have gone offline.', { severity: 'error' })
          return
        }
        path = checkout.path
        name = checkout.name
      }
      if (file.type === 'assembly') onOpenAssembly(path, name)
      else                          onOpenPart(path, name)
    })
    rowEl.addEventListener('contextmenu', e => { e.preventDefault(); _showContextMenu(e, file) })
    rowEl.addEventListener('keydown', e => _onRowKeydown(e, file, () => rowEl.click()))
    container.appendChild(rowEl)
  }

  function _onRowKeydown(e, entry, open) {
    if (e.key === ' ' || (e.key.toLowerCase() === 'a' && (e.ctrlKey || e.metaKey))) {
      e.preventDefault()
      if (e.key.toLowerCase() === 'a') {
        for (const item of _allEntries) _selectedPaths.add(item.path)
        _render()
      } else _toggleSelection(entry, e.ctrlKey || e.metaKey)
      return
    }
    if (e.key === 'Enter') { e.preventDefault(); open(); return }
    if (e.key === 'F2' && !_activePeerId) { e.preventDefault(); _startRename(e.currentTarget, e.currentTarget.querySelector('.lib-row-name'), entry); return }
    if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {
      e.preventDefault(); const box = e.currentTarget.getBoundingClientRect(); _showContextMenu({ clientX: box.left + 24, clientY: box.bottom }, entry)
      return
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const rows = [...treeEl.querySelectorAll('.lib-tree-row[tabindex="0"]')]
      const next = rows[rows.indexOf(e.currentTarget) + (e.key === 'ArrowDown' ? 1 : -1)]
      next?.focus()
    }
  }

  async function _duplicateFile(entry) {
    if (entry.type === 'folder') return
    const result = await api.getLibraryFileContent(entry.path)
    if (!result?.content) return
    const slash = entry.path.lastIndexOf('/')
    const dir = slash >= 0 ? entry.path.slice(0, slash + 1) : ''
    const filename = entry.path.slice(slash + 1)
    const dot = filename.lastIndexOf('.')
    const stem = dot >= 0 ? filename.slice(0, dot) : filename
    const ext = dot >= 0 ? filename.slice(dot) : ''
    let n = 1
    let dest
    do { dest = `${dir}${stem} copy${n > 1 ? ` ${n}` : ''}${ext}`; n++ } while (_allEntries.some(item => item.path === dest))
    await api.uploadLibraryFile(result.content, filename, { destPath: dest, overwrite: false })
    showToast(`Created ${dest}`)
    await refresh()
  }

  async function _downloadFile(entry) {
    const result = await api.getLibraryFileContent(entry.path)
    if (!result?.content) return
    const url = URL.createObjectURL(new Blob([result.content], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = entry.path.split('/').pop(); link.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  function _showContextMenu(e, entry) {
    document.querySelector('.lib-context-menu')?.remove()
    const menu = document.createElement('div')
    menu.className = 'lib-context-menu'
    menu.setAttribute('role', 'menu')
    const add = (label, fn, danger = false) => {
      const button = document.createElement('button')
      button.textContent = label; button.setAttribute('role', 'menuitem')
      if (danger) button.className = 'danger'
      button.addEventListener('click', async () => { menu.remove(); await fn() })
      menu.append(button)
    }
    add(entry.type === 'folder' ? 'Open folder' : 'Open', () => treeEl.querySelector(`[data-library-path="${CSS.escape(entry.path)}"]`)?.click())
    if (!_activePeerId) {
      add('Rename', () => { const row = treeEl.querySelector(`[data-library-path="${CSS.escape(entry.path)}"]`); _startRename(row, row.querySelector('.lib-row-name'), entry) })
      add('Move to…', () => _moveItem(entry))
      if (entry.type !== 'folder') {
        add('Duplicate', () => _duplicateFile(entry))
        add('Download', () => _downloadFile(entry))
        if (entry.type === 'part' && typeof api.downloadNativePartPackage === 'function') add('Download with simulations', () => api.downloadNativePartPackage(entry.path))
      }
      add('Move to Trash…', () => _trashItem(entry), true)
    }
    menu.style.left = `${Math.min(e.clientX, innerWidth - 210)}px`
    menu.style.top = `${Math.min(e.clientY, innerHeight - menu.childElementCount * 34 - 12)}px`
    document.body.append(menu)
    const close = event => { if (!menu.contains(event.target)) { menu.remove(); document.removeEventListener('pointerdown', close) } }
    setTimeout(() => document.addEventListener('pointerdown', close), 0)
    menu.querySelector('button')?.focus()
  }

  async function _trashItem(entry) {
    if (typeof api.trashLibraryItem !== 'function') {
      const deleted = await confirmAndDeleteFile({ api, path: entry.path, name: entry.name, isDir: entry.type === 'folder' })
      if (deleted) await refresh()
      return
    }
    const ok = await showConfirm({
      title: 'Move to Trash',
      message: `Move "${entry.name}" to Trash? You can restore it from the welcome screen.`,
      confirmLabel: 'Move to Trash',
      danger: true,
    })
    if (!ok) return
    if (await api.trashLibraryItem(entry.path)) {
      _selectedPaths.delete(entry.path)
      showToast(`${entry.name} moved to Trash.`)
      await refresh()
    }
  }

  async function _showTrash() {
    if (typeof api.listLibraryTrash !== 'function') return
    const response = await api.listLibraryTrash()
    const overlay = document.createElement('div')
    overlay.className = 'lib-trash-overlay'
    const dialog = document.createElement('div')
    dialog.className = 'lib-trash-dialog'
    dialog.setAttribute('role', 'dialog')
    dialog.setAttribute('aria-label', 'Trash')
    const header = document.createElement('div')
    header.className = 'lib-trash-header'
    const title = document.createElement('strong'); title.textContent = 'Trash'
    const close = _mkBtn('Close', 'lib-bulk-btn')
    const finish = () => overlay.remove()
    close.addEventListener('click', finish)
    header.append(title, close); dialog.append(header)
    const items = response?.items || []
    if (!items.length) {
      const empty = document.createElement('div'); empty.className = 'lib-empty'; empty.textContent = 'Trash is empty.'; dialog.append(empty)
    }
    for (const item of items) {
      const row = document.createElement('div'); row.className = 'lib-trash-row'
      const label = document.createElement('span'); label.textContent = item.original_path
      const restore = _mkBtn('Restore', 'lib-bulk-btn')
      restore.addEventListener('click', async () => { if (await api.restoreLibraryTrashItem(item.id)) { finish(); await refresh() } })
      const remove = _mkBtn('Delete permanently', 'lib-bulk-btn lib-trash-delete')
      remove.addEventListener('click', async () => {
        const ok = await showConfirm({ title: 'Delete permanently', message: `Permanently delete "${item.name}"? This cannot be undone.`, confirmLabel: 'Delete permanently', danger: true })
        if (ok && await api.deleteLibraryItem(`.nadoc-trash/${item.id}`)) { row.remove(); if (!dialog.querySelector('.lib-trash-row')) finish() }
      })
      row.append(label, restore, remove); dialog.append(row)
    }
    overlay.append(dialog)
    overlay.addEventListener('click', e => { if (e.target === overlay) finish() })
    document.body.append(overlay)
    close.focus()
  }

  // ── Actions helper ────────────────────────────────────────────────────────────

  function _makeActionsEl(actions) {
    const el = document.createElement('span')
    el.className = 'lib-row-actions'
    for (const { label, title, danger, fn } of actions) {
      const b = document.createElement('button')
      b.className   = 'lib-row-btn' + (danger ? ' lib-row-btn-danger' : '')
      b.textContent = label
      b.title       = title
      b.setAttribute('aria-label', title)
      b.addEventListener('click', fn)
      el.appendChild(b)
    }
    return el
  }

  // ── Simulation-activity spinner ───────────────────────────────────────────────

  // Fill (or clear) a row's status span from the current _activeJobs snapshot.
  // Reuses the global .nadoc-spinner CSS class for the rotating indicator.
  function _applyJobStatus(statusEl, path) {
    const job = activeJobForPath(_activeJobs, path)
    if (!job) {
      if (statusEl.firstChild) statusEl.replaceChildren()
      statusEl.title = ''
      return
    }
    if (!statusEl.querySelector('.nadoc-spinner')) {
      const spin = document.createElement('span')
      spin.className = 'nadoc-spinner'
      spin.setAttribute('aria-hidden', 'true')
      const tag = document.createElement('span')
      tag.className = 'lib-row-location-tag'
      statusEl.replaceChildren(spin, tag)
    }
    statusEl.querySelector('.lib-row-location-tag').textContent = jobLocationTag(job)
    statusEl.title = jobActivityTooltip(job)
  }

  async function _refreshJobStatuses() {
    // Skip work while the welcome screen is hidden (editor open).
    if (mount.offsetParent === null) return
    _activeJobs = await fetchActiveJobs()
    for (const [path, el] of _statusEls) _applyJobStatus(el, path)
  }

  function _startJobPolling() {
    if (_jobPollTimer != null) return
    _refreshJobStatuses()
    _jobPollTimer = setInterval(_refreshJobStatuses, _JOB_POLL_MS)
  }

  // ── New folder input ──────────────────────────────────────────────────────────

  function _showNewFolderInput(container, parentPath, depth) {
    const rowEl = document.createElement('div')
    rowEl.className = 'lib-tree-row lib-new-folder-row'
    rowEl.style.paddingLeft = `${depth * 16 + 4}px`

    const iconEl = document.createElement('span')
    iconEl.textContent = '📁'
    iconEl.style.cssText = 'font-size:12px;margin-right:6px;flex-shrink:0'

    const inp = document.createElement('input')
    inp.type = 'text'; inp.placeholder = 'folder name'
    inp.className = 'lib-inline-input'

    const okBtn  = document.createElement('button'); okBtn.textContent  = '✓'; okBtn.className = 'lib-row-btn lib-row-btn-ok'
    const canBtn = document.createElement('button'); canBtn.textContent = '×'; canBtn.className = 'lib-row-btn'

    const doCreate = async () => {
      const n = inp.value.trim()
      if (!n) { inp.focus(); return }
      if (n.includes('/') || n.includes('\\')) { showToast('Folder name cannot contain path separators.', { severity: 'error' }); inp.focus(); return }
      const folderPath = parentPath ? `${parentPath}/${n}` : n
      await api.mkdirLibrary(folderPath)
      _expanded.add(folderPath)
      await refresh()
    }
    const doCancel = () => { rowEl.remove(); _render() }
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') doCreate(); if (e.key === 'Escape') doCancel() })
    okBtn.addEventListener('click', doCreate)
    canBtn.addEventListener('click', doCancel)

    rowEl.append(iconEl, inp, okBtn, canBtn)
    container.prepend(rowEl)
    setTimeout(() => inp.focus(), 30)
  }

  // ── Inline rename ─────────────────────────────────────────────────────────────

  function _startRename(rowEl, nameEl, entry) {
    const oldName = entry.path.split('/').pop()
    const inp     = document.createElement('input')
    inp.type = 'text'; inp.value = oldName; inp.className = 'lib-inline-input'
    inp.style.cssText += ';flex:1'

    const okBtn  = document.createElement('button'); okBtn.textContent  = '✓'; okBtn.className = 'lib-row-btn lib-row-btn-ok'
    const canBtn = document.createElement('button'); canBtn.textContent = '×'; canBtn.className = 'lib-row-btn'

    nameEl.replaceWith(inp)

    const doRename = async () => {
      const newName = inp.value.trim()
      if (!newName || newName === oldName) { await refresh(); return }
      if (newName.includes('/') || newName.includes('\\')) { showToast('Name cannot contain path separators.', { severity: 'error' }); inp.focus(); return }
      const dir = entry.path.includes('/') ? entry.path.slice(0, entry.path.lastIndexOf('/')) : ''
      const newPath = dir ? `${dir}/${newName}` : newName
      const conflict = _allEntries.some(e => e.path === newPath) ||
        (entry.type === 'folder' && _allEntries.some(e => e.path.startsWith(newPath + '/')))
      if (conflict) { showToast(`"${newName}" already exists in this folder.`, { severity: 'error' }); inp.focus(); return }
      const result = await api.renameLibrary(entry.path, newName)
      if (result) await refresh()
      else { showToast('Rename failed — a file with that name may already exist.', { severity: 'error' }); await refresh() }
    }
    const doCancel = () => refresh()
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') doRename(); if (e.key === 'Escape') doCancel() })
    okBtn.addEventListener('click', doRename)
    canBtn.addEventListener('click', doCancel)

    rowEl.querySelector('.lib-row-actions')?.replaceWith(_makeActionsEl([
      { label: '✓', title: 'Confirm rename', fn: doRename },
      { label: '×', title: 'Cancel',         fn: doCancel },
    ]))

    setTimeout(() => { inp.focus(); inp.select() }, 20)
  }

  // ── Move ──────────────────────────────────────────────────────────────────────

  async function _moveItem(entry) {
    const destFolder = await _pickFolderModal(`Move "${entry.path.split('/').pop()}" to folder…`, entry.path)
    if (destFolder === null) return
    const result = await api.moveLibrary(entry.path, destFolder)
    if (result) await refresh()
  }

  function _pickFolderModal(title, excludePath, excludePaths = []) {
    return new Promise(resolve => {
      const seen = new Set([''])
      for (const e of _allEntries) {
        if (e.type === 'folder') seen.add(e.path)
        const parts = e.path.split('/')
        for (let i = 1; i < parts.length; i++) seen.add(parts.slice(0, i).join('/'))
      }
      const currentParent = excludePath?.includes('/') ? excludePath.slice(0, excludePath.lastIndexOf('/')) : ''
      const folders = [...seen].filter(fp =>
        fp !== currentParent &&
        fp !== excludePath &&
        !(excludePath && fp.startsWith(excludePath + '/')) &&
        !excludePaths.some(path => fp === path || fp.startsWith(path + '/'))
      ).sort()

      const overlay = document.createElement('div')
      overlay.style.cssText = 'position:fixed;inset:0;z-index:300;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center'

      const modal = document.createElement('div')
      modal.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:8px;width:320px;max-height:50vh;display:flex;flex-direction:column;overflow:hidden;font-family:var(--font-ui);font-size:12px'

      const hdr = document.createElement('div')
      hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #21262d'
      const hdrT = document.createElement('span'); hdrT.textContent = title; hdrT.style.cssText = 'color:#c9d1d9;font-size:12px'
      const hdrX = document.createElement('button'); hdrX.innerHTML = '&times;'; hdrX.style.cssText = 'background:none;border:none;color:#6e7681;font-size:16px;cursor:pointer'
      hdrX.addEventListener('click', () => { document.body.removeChild(overlay); resolve(null) })
      hdr.append(hdrT, hdrX)

      const list = document.createElement('div')
      list.style.cssText = 'flex:1;overflow-y:auto;padding:3px 8px'

      for (const fp of folders) {
        const row = document.createElement('div')
        row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:4px;cursor:pointer'
        row.addEventListener('mouseenter', () => { row.style.background = '#21262d' })
        row.addEventListener('mouseleave', () => { row.style.background = '' })
        const icon = document.createElement('span'); icon.textContent = fp === '' ? '🏠' : '📁'; icon.style.cssText = 'font-size:12px;flex-shrink:0'
        const name = document.createElement('span'); name.textContent = fp === '' ? 'workspace root' : fp; name.style.cssText = 'color:#c9d1d9;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
        row.append(icon, name)
        row.addEventListener('click', () => { document.body.removeChild(overlay); resolve(fp) })
        list.appendChild(row)
      }

      modal.append(hdr, list)
      overlay.appendChild(modal)
      overlay.addEventListener('click', (e) => { if (e.target === overlay) { document.body.removeChild(overlay); resolve(null) } })
      document.body.appendChild(overlay)
    })
  }

  // ── Import from disk → file browser for destination ───────────────────────────

  function _handleNadocImport() {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.nadoc,.nass,application/json'; input.multiple = true
    input.onchange = async (e) => {
      const files = Array.from(e.target.files ?? [])
      if (!files.length) return
      for (const file of files) {
        const content = await file.text()
        const ext     = file.name.endsWith('.nass') ? '.nass' : '.nadoc'
        const stem    = file.name.replace(/\.(nadoc|nass)$/i, '')
        const dest    = await openFileBrowser({
          title: `Import "${file.name}" — choose destination`,
          mode: 'save',
          fileType: ext === '.nass' ? 'assembly' : 'part',
          suggestedName: stem,
          suggestedExt: ext,
          api,
        })
        if (!dest) continue
        await api.uploadLibraryFile(content, file.name, { destPath: dest.path, overwrite: dest.overwrite ?? false })
        await refresh()
      }
    }
    input.click()
  }

  function _handleImport() {
    const SB = {
      bg: '#161b22', border: '#30363d', text: '#c9d1d9', muted: '#8b949e',
      hover: '#21262d', accent: '#58a6ff',
    }

    const overlay = document.createElement('div')
    overlay.style.cssText = 'position:fixed;inset:0;z-index:400;background:rgba(0,0,0,0.72);display:flex;align-items:center;justify-content:center'

    const modal = document.createElement('div')
    modal.style.cssText = [
      `background:${SB.bg};border:1px solid ${SB.border};border-radius:8px`,
      'padding:20px 24px 16px;font-family:var(--font-ui);font-size:13px',
      `color:${SB.text};display:flex;flex-direction:column;gap:12px;min-width:260px`,
    ].join(';')

    const titleEl = document.createElement('div')
    titleEl.textContent = 'Choose import format'
    titleEl.style.cssText = `font-size:13px;font-weight:600;color:#e6edf3;margin-bottom:2px`

    function _close() { document.body.removeChild(overlay) }
    overlay.addEventListener('click', e => { if (e.target === overlay) _close() })

    function _makeFormatBtn(label, sub, action) {
      const b = document.createElement('button')
      b.style.cssText = [
        `background:${SB.bg};border:1px solid ${SB.border};border-radius:5px`,
        `color:${SB.text};cursor:pointer;padding:10px 14px;text-align:left`,
        'display:flex;flex-direction:column;gap:2px;width:100%',
      ].join(';')
      const nameEl = document.createElement('span')
      nameEl.textContent = label
      nameEl.style.cssText = 'font-size:12px;font-weight:500'
      const subEl = document.createElement('span')
      subEl.textContent = sub
      subEl.style.cssText = `font-size:var(--text-xs);color:${SB.muted}`
      b.append(nameEl, subEl)
      b.addEventListener('mouseenter', () => { b.style.borderColor = SB.accent; b.style.background = SB.hover })
      b.addEventListener('mouseleave', () => { b.style.borderColor = SB.border; b.style.background = SB.bg })
      b.addEventListener('click', () => { _close(); action() })
      return b
    }

    modal.append(
      titleEl,
      _makeFormatBtn('NADOC',    '.nadoc / .nass — native format',     () => _handleNadocImport()),
      _makeFormatBtn('caDNAno',  '.json — parses with autodetection',  () => onImportCadnano?.()),
      _makeFormatBtn('scadnano', '.sc — parses with autodetection',    () => onImportScadnano?.()),
    )
    overlay.appendChild(modal)
    document.body.appendChild(overlay)
  }

  _loadCachedEntries()
  _renderServerTabs()
  _updateActionVisibility()
  if (_allEntries.length) _render()
  refresh()
  _startPeerPolling()
  window.addEventListener('nadoc:collaboration-peers-changed', _refreshServerStatuses)
  _startJobPolling()
  return { refresh, refreshJobStatuses: _refreshJobStatuses }
}

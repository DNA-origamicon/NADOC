/**
 * Library panel — tree-view file manager mounted on the welcome screen.
 *
 * Shows the workspace as a navigable folder tree.  Supports inline rename,
 * new-folder creation, file deletion, and move-to-folder operations.
 * Import uses the file browser to pick a destination on the server.
 */

import { openFileBrowser } from './file_browser.js'

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
  { key: 'type',     label: 'Type',     defaultDir: 'asc'  },
]

function _sortFiles(files, key, dir) {
  const d = dir === 'asc' ? 1 : -1
  if (key === 'name') {
    files.sort((a, b) => d * a.name.localeCompare(b.name))
  } else if (key === 'modified') {
    files.sort((a, b) => d * (new Date(a.mtime_iso) - new Date(b.mtime_iso)))
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

export function initLibraryPanel({ api, onOpenPart, onOpenAssembly, onNewPart, onNewAssembly }) {
  const mount = document.getElementById('library-panel-mount')
  if (!mount) return { refresh() {} }

  let _allEntries = []
  const _expanded = new Set()
  let _sortKey = 'modified'
  let _sortDir = 'desc'

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

  newPartBtn.addEventListener('click', () => onNewPart())
  newAsmBtn.addEventListener('click', () => onNewAssembly())
  importBtn.addEventListener('click', _handleImport)
  newFolderBtn.addEventListener('click', () => _showNewFolderInput(treeEl, '', 0))

  actionsEl.append(newPartBtn, newAsmBtn, importBtn, newFolderBtn)
  mount.appendChild(actionsEl)

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
  }
  _renderSortBar()

  // ── Tree container ──────────────────────────────────────────────────────────

  const treeEl = document.createElement('div')
  treeEl.className = 'lib-tree'
  mount.appendChild(treeEl)

  // ── Refresh ─────────────────────────────────────────────────────────────────

  async function refresh() {
    treeEl.innerHTML = '<div class="lib-loading">Loading…</div>'
    try {
      const files = await api.listLibraryFiles()
      _allEntries = Array.isArray(files) ? files : []
    } catch {
      treeEl.innerHTML = '<div class="lib-empty">Could not reach server.</div>'
      return
    }
    _render()
  }

  function _render() {
    treeEl.innerHTML = ''
    const tree = _buildTree(_allEntries, { sortKey: _sortKey, sortDir: _sortDir })
    if (!tree.children.length && !tree.files.length) {
      const empty = document.createElement('div')
      empty.className = 'lib-empty'
      empty.textContent = 'No files yet — create your first part above.'
      treeEl.appendChild(empty)
      return
    }
    _renderLevel(tree, treeEl, 0)
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

    const actEl = _makeActionsEl([
      { label: '+', title: 'New subfolder', fn: (e) => { e.stopPropagation(); childrenEl.style.display = ''; _expanded.add(folder.path); toggleEl.textContent = '▼'; _showNewFolderInput(childrenEl, folder.path, depth + 1) } },
      { label: '✎', title: 'Rename', fn: (e) => { e.stopPropagation(); _startRename(rowEl, nameEl, folder) } },
      { label: '×', title: 'Delete', danger: true, fn: async (e) => {
        e.stopPropagation()
        if (!confirm(`Delete folder "${folder.name}" and all its contents?`)) return
        await api.deleteLibraryItem(folder.path); await refresh()
      }},
    ])

    rowEl.append(toggleEl, iconEl, nameEl, actEl)

    const childrenEl = document.createElement('div')
    childrenEl.style.display = expanded ? '' : 'none'
    if (expanded) _renderLevel(folder, childrenEl, depth + 1)

    rowEl.addEventListener('click', () => {
      const isExpanded = _expanded.has(folder.path)
      if (isExpanded) { _expanded.delete(folder.path); childrenEl.style.display = 'none'; toggleEl.textContent = '▶' }
      else            { _expanded.add(folder.path);    childrenEl.style.display = '';     toggleEl.textContent = '▼'; if (!childrenEl.children.length) _renderLevel(folder, childrenEl, depth + 1) }
    })

    container.appendChild(rowEl)
    container.appendChild(childrenEl)
  }

  // ── File row ─────────────────────────────────────────────────────────────────

  function _renderFileRow(file, container, depth) {
    const rowEl = document.createElement('div')
    rowEl.className = `lib-tree-row lib-file-row${file.type === 'assembly' ? ' lib-file-assembly' : ''}`
    rowEl.style.paddingLeft = `${depth * 16 + 4}px`
    rowEl.title = file.path

    const iconEl = document.createElement('span')
    iconEl.textContent = file.type === 'assembly' ? '⬡' : '◈'
    iconEl.style.cssText = 'font-size:11px;margin-right:6px;flex-shrink:0;color:' + (file.type === 'assembly' ? '#388bfd' : '#3fb950')

    const nameEl = document.createElement('span')
    nameEl.className   = 'lib-row-name'
    nameEl.textContent = file.name

    const pathEl = document.createElement('span')
    pathEl.className = 'lib-row-path'
    const parentFolder = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/')) : ''
    pathEl.textContent = depth === 0 && parentFolder ? parentFolder + '/' : ''

    const mtimeEl = document.createElement('span')
    mtimeEl.className   = 'lib-row-mtime'
    mtimeEl.textContent = _relativeTime(file.mtime_iso)

    const actEl = _makeActionsEl([
      { label: '✎', title: 'Rename', fn: (e) => { e.stopPropagation(); _startRename(rowEl, nameEl, file) } },
      { label: '↗', title: 'Move',   fn: async (e) => { e.stopPropagation(); await _moveItem(file) } },
      { label: '×', title: 'Delete', danger: true, fn: async (e) => {
        e.stopPropagation()
        if (!confirm(`Delete "${file.name}"?`)) return
        await api.deleteLibraryItem(file.path); await refresh()
      }},
    ])

    rowEl.append(iconEl, nameEl, mtimeEl, actEl)
    rowEl.addEventListener('click', () => {
      if (file.type === 'assembly') onOpenAssembly(file.path, file.name)
      else                          onOpenPart(file.path, file.name)
    })
    container.appendChild(rowEl)
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
      b.addEventListener('click', fn)
      el.appendChild(b)
    }
    return el
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
      if (n.includes('/') || n.includes('\\')) { alert('Folder name cannot contain path separators.'); inp.focus(); return }
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
      if (newName.includes('/') || newName.includes('\\')) { alert('Name cannot contain path separators.'); inp.focus(); return }
      const dir = entry.path.includes('/') ? entry.path.slice(0, entry.path.lastIndexOf('/')) : ''
      const newPath = dir ? `${dir}/${newName}` : newName
      const conflict = _allEntries.some(e => e.path === newPath) ||
        (entry.type === 'folder' && _allEntries.some(e => e.path.startsWith(newPath + '/')))
      if (conflict) { alert(`"${newName}" already exists in this folder.`); inp.focus(); return }
      const result = await api.renameLibrary(entry.path, newName)
      if (result) await refresh()
      else { alert('Rename failed — a file with that name may already exist.'); await refresh() }
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

  function _pickFolderModal(title, excludePath) {
    return new Promise(resolve => {
      const seen = new Set([''])
      for (const e of _allEntries) {
        if (e.type === 'folder') seen.add(e.path)
        const parts = e.path.split('/')
        for (let i = 1; i < parts.length; i++) seen.add(parts.slice(0, i).join('/'))
      }
      const currentParent = excludePath.includes('/') ? excludePath.slice(0, excludePath.lastIndexOf('/')) : ''
      const folders = [...seen].filter(fp =>
        fp !== currentParent &&
        fp !== excludePath &&
        !fp.startsWith(excludePath + '/')
      ).sort()

      const overlay = document.createElement('div')
      overlay.style.cssText = 'position:fixed;inset:0;z-index:300;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center'

      const modal = document.createElement('div')
      modal.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:8px;width:320px;max-height:50vh;display:flex;flex-direction:column;overflow:hidden;font-family:monospace;font-size:12px'

      const hdr = document.createElement('div')
      hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #21262d'
      const hdrT = document.createElement('span'); hdrT.textContent = title; hdrT.style.cssText = 'color:#c9d1d9;font-size:12px'
      const hdrX = document.createElement('button'); hdrX.innerHTML = '&times;'; hdrX.style.cssText = 'background:none;border:none;color:#6e7681;font-size:16px;cursor:pointer'
      hdrX.addEventListener('click', () => { document.body.removeChild(overlay); resolve(null) })
      hdr.append(hdrT, hdrX)

      const list = document.createElement('div')
      list.style.cssText = 'flex:1;overflow-y:auto;padding:4px 8px'

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

  function _handleImport() {
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

  refresh()
  return { refresh }
}

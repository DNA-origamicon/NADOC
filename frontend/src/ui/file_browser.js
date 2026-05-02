/**
 * File browser modal — navigate workspace folders, manage files, open or save.
 *
 * openFileBrowser({ title, mode, fileType, suggestedName, suggestedExt, api })
 *   → Promise<{ path, name, overwrite } | null>
 *
 * mode       'open'  — click a file to resolve with its path
 *            'save'  — shows filename input; resolves with chosen path + overwrite flag
 * fileType   'part' | 'assembly' | 'all'  (filters which files are shown in open mode;
 *            in save mode all files are shown but the extension selector respects this)
 * suggestedName / suggestedExt  — pre-filled values for save mode
 */

const S = {
  bg:       '#161b22',
  border:   '#30363d',
  border2:  '#21262d',
  text:     '#c9d1d9',
  muted:    '#8b949e',
  dim:      '#484f58',
  hover:    '#21262d',
  accent:   '#58a6ff',
  green:    '#3fb950',
  red:      '#f85149',
  input:    '#0d1117',
}

function btn(label, style = '') {
  const b = document.createElement('button')
  b.textContent = label
  b.style.cssText = style
  return b
}

function inp(placeholder, value = '', style = '') {
  const i = document.createElement('input')
  i.type = 'text'; i.placeholder = placeholder; i.value = value
  i.style.cssText = [
    `background:${S.input};border:1px solid ${S.border};color:${S.text}`,
    'padding:3px 8px;border-radius:3px;font-family:var(--font-ui);font-size:12px;outline:none',
    style,
  ].filter(Boolean).join(';')
  i.addEventListener('focus', () => { i.style.borderColor = S.accent })
  i.addEventListener('blur',  () => { i.style.borderColor = S.border })
  return i
}

const _SORT_COLS = [
  { key: 'name',     label: 'Name',     defaultDir: 'asc'  },
  { key: 'modified', label: 'Modified', defaultDir: 'desc' },
  { key: 'type',     label: 'Type',     defaultDir: 'asc'  },
]

export function openFileBrowser({ title, mode, fileType = 'all', suggestedName = '', suggestedExt = '.nadoc', noOverwrite = false, api, autodetection = null }) {
  return new Promise((resolve) => {
    let _dir     = ''   // current workspace-relative directory path
    let _entries = []   // flat list from api.listLibraryFiles()
    let _newFolderActive = false
    let _done    = false
    let _sortKey = 'modified'
    let _sortDir = 'desc'

    // Track autodetection toggle state
    const _adState = { includeClusters: true, includeOverhangs: true }

    function _finish(result) {
      if (_done) return
      _done = true
      document.body.removeChild(overlay)
      if (result && autodetection) {
        result.includeClusters = _adState.includeClusters
        result.includeOverhangs = _adState.includeOverhangs
      }
      resolve(result)
    }

    // ── Overlay + modal ──────────────────────────────────────────────────────
    const overlay = document.createElement('div')
    overlay.style.cssText = `position:fixed;inset:0;z-index:300;background:rgba(0,0,0,0.72);display:flex;align-items:center;justify-content:center`

    const modal = document.createElement('div')
    modal.style.cssText = [
      `background:${S.bg};border:1px solid ${S.border};border-radius:8px`,
      `width:${autodetection ? 580 : 520}px;max-height:82vh;display:flex;flex-direction:column;overflow:hidden`,
      'font-family:var(--font-ui);font-size:12px',
    ].join(';')

    // ── Header ───────────────────────────────────────────────────────────────
    const headerEl = document.createElement('div')
    headerEl.style.cssText = `display:flex;align-items:center;justify-content:space-between;padding:14px 16px 0`
    const titleEl = document.createElement('span')
    titleEl.textContent = title
    titleEl.style.cssText = `color:${S.text};font-size:13px;font-weight:500`
    const closeBtn = btn('×', `background:none;border:none;color:${S.muted};font-size:18px;cursor:pointer;line-height:1;padding:0`)
    closeBtn.addEventListener('click', () => _finish(null))
    headerEl.append(titleEl, closeBtn)

    // ── Toolbar (breadcrumb + New Folder) ────────────────────────────────────
    const toolbarEl = document.createElement('div')
    toolbarEl.style.cssText = `display:flex;align-items:center;gap:8px;padding:10px 16px;border-bottom:1px solid ${S.border2}`

    const breadcrumbEl = document.createElement('div')
    breadcrumbEl.style.cssText = 'flex:1;display:flex;align-items:center;flex-wrap:wrap;gap:2px;min-width:0;overflow:hidden'

    const newFolderBtn = btn('+ Folder', [
      `flex-shrink:0;padding:3px 8px;background:${S.bg}`,
      `border:1px solid ${S.border};color:${S.muted};border-radius:3px;cursor:pointer;font-size:11px`,
    ].join(';'))
    newFolderBtn.addEventListener('mouseenter', () => { newFolderBtn.style.color = S.text })
    newFolderBtn.addEventListener('mouseleave', () => { newFolderBtn.style.color = S.muted })
    newFolderBtn.addEventListener('click', () => { _newFolderActive = true; _renderList() })

    toolbarEl.append(breadcrumbEl, newFolderBtn)

    // ── Sort bar ─────────────────────────────────────────────────────────────
    const sortBarEl = document.createElement('div')
    sortBarEl.style.cssText = `display:flex;align-items:center;gap:0;padding:3px 8px;border-bottom:1px solid ${S.border2}`

    // ── File list ────────────────────────────────────────────────────────────
    const listEl = document.createElement('div')
    listEl.style.cssText = 'flex:1;overflow-y:auto;padding:3px 8px;min-height:120px'

    // ── Save footer ──────────────────────────────────────────────────────────
    let nameInputEl = null, extSelectEl = null, footerErrorEl = null
    let footerEl = null
    if (mode === 'save') {
      footerEl = document.createElement('div')
      footerEl.style.cssText = `display:flex;flex-direction:column;gap:4px;padding:12px 16px;border-top:1px solid ${S.border2}`

      const footerRow = document.createElement('div')
      footerRow.style.cssText = 'display:flex;align-items:center;gap:8px'

      const nameLabel = document.createElement('span')
      nameLabel.textContent = 'Filename:'
      nameLabel.style.cssText = `color:${S.muted};flex-shrink:0;font-size:11px`

      nameInputEl = inp('filename', suggestedName, 'flex:1;min-width:0')

      extSelectEl = document.createElement('select')
      extSelectEl.style.cssText = [
        `flex-shrink:0;background:${S.input};border:1px solid ${S.border};color:${S.muted}`,
        'padding:3px 6px;border-radius:3px;font-family:var(--font-ui);font-size:11px;cursor:pointer',
      ].join(';')
      const exts = fileType === 'assembly' ? ['.nass'] : fileType === 'part' ? ['.nadoc'] : ['.nadoc', '.nass']
      for (const ext of exts) {
        const opt = document.createElement('option')
        opt.value = opt.textContent = ext
        if (ext === suggestedExt) opt.selected = true
        extSelectEl.appendChild(opt)
      }

      const cancelBtn = btn('Cancel', [
        `flex-shrink:0;padding:5px 12px;background:${S.bg};border:1px solid ${S.border}`,
        `color:${S.muted};border-radius:3px;cursor:pointer;font-size:11px`,
      ].join(';'))
      cancelBtn.addEventListener('click', () => _finish(null))

      const saveBtn = btn('Save', [
        `flex-shrink:0;padding:5px 14px;background:#1f3d2a;border:1px solid ${S.green}`,
        `color:${S.green};border-radius:3px;cursor:pointer;font-size:11px;font-weight:500`,
      ].join(';'))
      saveBtn.addEventListener('mouseenter', () => { saveBtn.style.background = '#2d5a3e' })
      saveBtn.addEventListener('mouseleave', () => { saveBtn.style.background = '#1f3d2a' })
      saveBtn.addEventListener('click', _commitSave)
      nameInputEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') _commitSave() })
      nameInputEl.addEventListener('input', () => {
        if (footerErrorEl) footerErrorEl.style.display = 'none'
        nameInputEl.style.borderColor = S.border
      })

      footerErrorEl = document.createElement('div')
      footerErrorEl.style.cssText = `display:none;color:${S.red};font-size:var(--text-xs);padding-left:2px`

      footerRow.append(nameLabel, nameInputEl, extSelectEl, cancelBtn, saveBtn)
      footerEl.append(footerRow, footerErrorEl)
    }

    // ── Autodetection panel ──────────────────────────────────────────────────
    let adPanelEl = null
    if (autodetection) {
      const { clusters = [], overhangs = [] } = autodetection
      const hasFeatures = clusters.length > 0 || overhangs.length > 0
      if (hasFeatures) {
        adPanelEl = document.createElement('div')
        adPanelEl.style.cssText = `border-bottom:1px solid ${S.border};overflow-y:auto;max-height:280px;flex-shrink:0`

        const adHeader = document.createElement('div')
        adHeader.style.cssText = `padding:8px 16px 6px;color:${S.muted};font-size:var(--text-xs);letter-spacing:0.06em;text-transform:uppercase;border-bottom:1px solid ${S.border2}`
        adHeader.textContent = 'Autodetected features'
        adPanelEl.appendChild(adHeader)

        function _makeFeatureSection({ key, label, count, description, items }) {
          const section = document.createElement('div')
          section.style.cssText = `padding:8px 16px;border-bottom:1px solid ${S.border2}`

          const headerRow = document.createElement('div')
          headerRow.style.cssText = 'display:flex;align-items:center;gap:8px'

          const checkbox = document.createElement('input')
          checkbox.type = 'checkbox'; checkbox.checked = true
          checkbox.style.cssText = 'cursor:pointer;accent-color:#58a6ff;flex-shrink:0'

          const labelEl = document.createElement('span')
          labelEl.style.cssText = `color:${S.text};font-size:12px;font-weight:500;flex:1`
          labelEl.textContent = `${label}  (${count})`

          const toggleBtn = document.createElement('button')
          toggleBtn.textContent = '▸ show'
          toggleBtn.style.cssText = `background:none;border:none;color:${S.muted};font-size:var(--text-xs);cursor:pointer;padding:0;flex-shrink:0`

          headerRow.append(checkbox, labelEl, toggleBtn)

          const descEl = document.createElement('div')
          descEl.style.cssText = `color:${S.muted};font-size:var(--text-xs);line-height:1.5;margin:4px 0 6px 20px;display:none`
          descEl.textContent = description

          const listBox = document.createElement('div')
          listBox.style.cssText = [
            `background:${S.input};border:1px solid ${S.border2};border-radius:3px`,
            'margin-left:20px;overflow-y:auto;max-height:100px;display:none',
          ].join(';')
          for (const item of items) {
            const row = document.createElement('div')
            row.style.cssText = `padding:3px 8px;color:${S.text};font-size:11px;border-bottom:1px solid ${S.border2}`
            row.textContent = item
            listBox.appendChild(row)
          }

          let expanded = false
          toggleBtn.addEventListener('click', () => {
            expanded = !expanded
            descEl.style.display  = expanded ? '' : 'none'
            listBox.style.display = expanded ? '' : 'none'
            toggleBtn.textContent = expanded ? '▾ hide' : '▸ show'
          })

          checkbox.addEventListener('change', () => {
            _adState[key] = checkbox.checked
            const dim = checkbox.checked ? S.text : S.dim
            labelEl.style.color = dim
            listBox.style.opacity = checkbox.checked ? '1' : '0.4'
          })

          section.append(headerRow, descEl, listBox)
          return section
        }

        if (clusters.length > 0) {
          adPanelEl.appendChild(_makeFeatureSection({
            key: 'includeClusters',
            label: 'Clusters',
            count: clusters.length,
            description: 'Groups of lattice-adjacent helices assigned as rigid-body clusters. Useful for multi-arm structures, hinge joints, and assembly arrangements.',
            items: clusters.map(c => `${c.name}  —  ${c.helix_ids?.length ?? 0} helices`),
          }))
        }

        if (overhangs.length > 0) {
          adPanelEl.appendChild(_makeFeatureSection({
            key: 'includeOverhangs',
            label: 'Overhangs',
            count: overhangs.length,
            description: 'Single-stranded overhangs at helix termini, used for staple attachment or structural flexibility.',
            items: overhangs.map(o => o.label ?? o.id),
          }))
        }
      }
    }

    modal.append(headerEl, ...(adPanelEl ? [adPanelEl] : []), toolbarEl, sortBarEl, listEl, ...(footerEl ? [footerEl] : []))
    overlay.appendChild(modal)
    // Backdrop clicks are intentionally ignored — user must click Cancel or Save.
    document.body.appendChild(overlay)

    if (mode === 'save') setTimeout(() => nameInputEl?.focus(), 40)

    // ── Commit save ──────────────────────────────────────────────────────────
    function _showFooterError(msg) {
      if (!footerErrorEl) return
      footerErrorEl.textContent = msg
      footerErrorEl.style.display = 'block'
      if (nameInputEl) nameInputEl.style.borderColor = S.red
    }

    async function _commitSave() {
      if (footerErrorEl) footerErrorEl.style.display = 'none'
      const stem = nameInputEl.value.trim()
      if (!stem) { nameInputEl.style.borderColor = S.red; nameInputEl.focus(); return }
      if (stem.includes('/') || stem.includes('\\')) {
        _showFooterError('Filename cannot contain path separators.')
        nameInputEl.focus()
        return
      }
      const ext      = extSelectEl.value
      const filename = `${stem}${ext}`
      const fullPath = _dir ? `${_dir}/${filename}` : filename
      const existing = _entries.find(e => e.path === fullPath && e.type !== 'folder')
      if (existing) {
        if (noOverwrite) {
          _showFooterError(`"${filename}" already exists. Choose a different name or folder.`)
          nameInputEl.focus(); nameInputEl.select()
          return
        }
        if (!confirm(`"${filename}" already exists. Overwrite?`)) return
      }
      _finish({ path: fullPath, name: stem, overwrite: !!existing })
    }

    // ── Breadcrumb ───────────────────────────────────────────────────────────
    function _renderBreadcrumb() {
      breadcrumbEl.innerHTML = ''
      const parts = _dir ? _dir.split('/') : []

      const crumb = (label, path, isLast) => {
        const el = document.createElement('span')
        el.textContent = label
        if (isLast) {
          el.style.cssText = `color:${S.text};font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`
        } else {
          el.style.cssText = `color:${S.accent};font-size:11px;cursor:pointer;white-space:nowrap`
          el.addEventListener('click', () => _navigateTo(path))
        }
        return el
      }
      const sep = () => {
        const s = document.createElement('span')
        s.textContent = '›'; s.style.cssText = `color:${S.dim};font-size:11px;flex-shrink:0`
        return s
      }

      breadcrumbEl.appendChild(crumb('workspace', '', parts.length > 0))
      let acc = ''
      for (let i = 0; i < parts.length; i++) {
        acc = acc ? `${acc}/${parts[i]}` : parts[i]
        breadcrumbEl.appendChild(sep())
        breadcrumbEl.appendChild(crumb(parts[i], acc, i === parts.length - 1))
      }
    }

    function _navigateTo(dir) {
      _dir = dir
      _newFolderActive = false
      _renderBreadcrumb()
      _renderList()
    }

    // ── Get direct children of current dir ───────────────────────────────────
    function _getChildren() {
      const prefix = _dir ? _dir + '/' : ''
      const folderSet = new Map()  // folderName → entry
      const files     = []

      for (const e of _entries) {
        if (prefix && !e.path.startsWith(prefix)) continue
        const rel = e.path.slice(prefix.length)
        if (!rel) continue
        const sep = rel.indexOf('/')

        if (sep === -1) {
          if (e.type === 'folder') {
            if (!folderSet.has(rel)) folderSet.set(rel, e)
          } else {
            const show = mode === 'save'
              || fileType === 'all'
              || e.type === fileType
            if (show) files.push(e)
          }
        } else {
          // Descendant — infer intermediate folder
          const sub        = rel.slice(0, sep)
          const folderPath = prefix + sub
          if (!folderSet.has(sub)) {
            const explicit = _entries.find(x => x.type === 'folder' && x.path === folderPath)
            folderSet.set(sub, explicit ?? { name: sub, path: folderPath, type: 'folder', mtime_iso: e.mtime_iso, size_bytes: 0 })
          }
        }
      }

      const folders = [...folderSet.values()]
      folders.sort((a, b) => a.name.localeCompare(b.name))
      const d = _sortDir === 'asc' ? 1 : -1
      if (_sortKey === 'name') {
        files.sort((a, b) => d * a.name.localeCompare(b.name))
      } else if (_sortKey === 'modified') {
        files.sort((a, b) => d * (new Date(a.mtime_iso) - new Date(b.mtime_iso)))
      } else if (_sortKey === 'type') {
        files.sort((a, b) => {
          const t = (a.type === b.type ? 0 : a.type === 'part' ? -1 : 1) * d
          return t !== 0 ? t : a.name.localeCompare(b.name)
        })
      }
      return { folders, files }
    }

    // ── Sort bar ─────────────────────────────────────────────────────────────
    function _renderSortBar() {
      sortBarEl.innerHTML = ''
      const prefixEl = document.createElement('span')
      prefixEl.textContent = 'Sort:'
      prefixEl.style.cssText = `color:${S.dim};font-size:var(--text-xs);margin-right:8px;flex-shrink:0;letter-spacing:0.5px;text-transform:uppercase`
      sortBarEl.appendChild(prefixEl)

      for (const col of _SORT_COLS) {
        const el = document.createElement('span')
        const isActive = _sortKey === col.key
        el.textContent = col.label + (isActive ? (_sortDir === 'asc' ? ' ↑' : ' ↓') : '')
        el.style.cssText = [
          `font-size:var(--text-xs);cursor:pointer;padding:2px 8px;border-radius:3px`,
          `color:${isActive ? S.accent : S.dim};user-select:none`,
          `text-transform:uppercase;letter-spacing:0.5px`,
        ].join(';')
        el.addEventListener('mouseenter', () => { if (_sortKey !== col.key) el.style.color = S.muted })
        el.addEventListener('mouseleave', () => { if (_sortKey !== col.key) el.style.color = S.dim })
        el.addEventListener('click', () => {
          if (_sortKey === col.key) {
            _sortDir = _sortDir === 'asc' ? 'desc' : 'asc'
          } else {
            _sortKey = col.key
            _sortDir = col.defaultDir
          }
          _renderSortBar()
          _renderList()
        })
        sortBarEl.appendChild(el)
      }
    }

    // ── Render list ───────────────────────────────────────────────────────────
    function _renderList() {
      listEl.innerHTML = ''
      const { folders, files } = _getChildren()

      // ".." row
      if (_dir) {
        const up = _makeRow({
          icon: '↑', label: '..', dim: 'parent folder', actions: [],
          onClick: () => { const parts = _dir.split('/'); parts.pop(); _navigateTo(parts.join('/')) },
        })
        listEl.appendChild(up)
      }

      // New-folder input row
      if (_newFolderActive) {
        const row = document.createElement('div')
        row.style.cssText = `display:flex;align-items:center;gap:8px;padding:3px 8px`
        const iconEl = document.createElement('span')
        iconEl.textContent = '📁'; iconEl.style.cssText = 'font-size:12px;flex-shrink:0;width:16px;text-align:center'
        const folderInp = inp('new folder name', '', 'flex:1')
        const okBtn  = btn('✓', `background:none;border:none;color:${S.green};cursor:pointer;font-size:14px;padding:0 4px`)
        const canBtn = btn('×', `background:none;border:none;color:${S.muted};cursor:pointer;font-size:14px;padding:0 2px`)
        const doCreate = async () => {
          const n = folderInp.value.trim()
          if (!n) { folderInp.focus(); return }
          if (n.includes('/') || n.includes('\\')) { alert('Folder name cannot contain path separators.'); folderInp.focus(); return }
          const path = _dir ? `${_dir}/${n}` : n
          await api.mkdirLibrary(path)
          _newFolderActive = false
          await _reload()
        }
        const doCancel = () => { _newFolderActive = false; _renderList() }
        folderInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') doCreate(); if (e.key === 'Escape') doCancel() })
        okBtn.addEventListener('click', doCreate)
        canBtn.addEventListener('click', doCancel)
        row.append(iconEl, folderInp, okBtn, canBtn)
        listEl.appendChild(row)
        setTimeout(() => folderInp.focus(), 30)
      }

      // Folder rows
      for (const folder of folders) {
        const folderName = folder.path.split('/').pop()
        const row = _makeRow({
          icon: '📁', label: folderName, dim: null,
          actions: [
            { label: '✎', title: 'Rename', fn: () => _startRename(row, folder) },
            { label: '×', title: 'Delete', color: S.red, fn: async () => {
              if (!confirm(`Delete folder "${folderName}" and all its contents?`)) return
              await api.deleteLibraryItem(folder.path); await _reload()
            }},
          ],
          onClick: () => _navigateTo(folder.path),
        })
        listEl.appendChild(row)
      }

      // Empty state
      if (!folders.length && !files.length && !_newFolderActive) {
        const empty = document.createElement('div')
        const lbl = fileType === 'part' ? 'parts' : fileType === 'assembly' ? 'assemblies' : 'files'
        empty.textContent = _dir ? 'Empty folder.' : `No ${lbl} on server yet.`
        empty.style.cssText = `color:${S.dim};padding:20px 8px;text-align:center`
        listEl.appendChild(empty)
      }

      // File rows
      for (const file of files) {
        const fileName = file.path.split('/').pop()
        const ms = Date.now() - new Date(file.mtime_iso).getTime()
        const hr = Math.floor(ms / 3600000)
        const ago = hr < 1 ? 'just now' : hr < 24 ? `${hr}h ago` : `${Math.floor(hr / 24)}d ago`
        const icon = file.type === 'assembly' ? '⬡' : '◈'

        const row = _makeRow({
          icon, label: fileName, dim: ago,
          actions: [
            { label: '✎', title: 'Rename', fn: () => _startRename(row, file) },
            { label: '↗', title: 'Move',   fn: () => _startMove(file) },
            { label: '×', title: 'Delete', color: S.red, fn: async () => {
              if (!confirm(`Delete "${fileName}"?`)) return
              await api.deleteLibraryItem(file.path); await _reload()
            }},
          ],
          onClick: mode === 'open'
            ? () => _finish({ path: file.path, name: file.name })
            : () => {
                if (nameInputEl)  nameInputEl.value  = file.name
                if (extSelectEl)  extSelectEl.value  = file.path.endsWith('.nass') ? '.nass' : '.nadoc'
              },
        })
        listEl.appendChild(row)
      }
    }

    // ── Row factory ───────────────────────────────────────────────────────────
    function _makeRow({ icon, label, dim, actions, onClick }) {
      const row = document.createElement('div')
      row.style.cssText = `display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:4px;cursor:pointer`
      row.addEventListener('mouseenter', () => { row.style.background = S.hover })
      row.addEventListener('mouseleave', () => { row.style.background = 'transparent' })
      row.addEventListener('click', onClick)

      const iconEl = document.createElement('span')
      iconEl.textContent = icon
      iconEl.style.cssText = 'font-size:12px;flex-shrink:0;width:16px;text-align:center'

      const nameEl = document.createElement('span')
      nameEl.textContent = label
      nameEl.style.cssText = `flex:1;color:${S.text};overflow:hidden;text-overflow:ellipsis;white-space:nowrap`

      row.append(iconEl, nameEl)

      if (dim) {
        const dimEl = document.createElement('span')
        dimEl.textContent = dim
        dimEl.style.cssText = `color:${S.dim};font-size:var(--text-xs);flex-shrink:0;margin-left:6px`
        row.appendChild(dimEl)
      }

      if (actions.length) {
        const actEl = document.createElement('span')
        actEl.style.cssText = 'display:flex;gap:2px;flex-shrink:0'
        actEl.addEventListener('click', (e) => e.stopPropagation())
        for (const { label: al, title: at, color, fn } of actions) {
          const ab = btn(al, `background:none;border:none;color:${S.dim};cursor:pointer;padding:0 3px;font-size:12px`)
          ab.title = at
          ab.addEventListener('mouseenter', () => { ab.style.color = color ?? S.accent })
          ab.addEventListener('mouseleave', () => { ab.style.color = S.dim })
          ab.addEventListener('click', fn)
          actEl.appendChild(ab)
        }
        row.appendChild(actEl)
      }
      return row
    }

    // ── Inline rename ─────────────────────────────────────────────────────────
    function _startRename(rowEl, entry) {
      const isFolder   = entry.type === 'folder'
      const currentName = entry.path.split('/').pop()

      rowEl.innerHTML = ''
      rowEl.style.cursor = 'default'

      const iconEl = document.createElement('span')
      iconEl.textContent = isFolder ? '📁' : (entry.type === 'assembly' ? '⬡' : '◈')
      iconEl.style.cssText = 'font-size:12px;flex-shrink:0;width:16px;text-align:center'

      const renameInp = inp('', currentName, 'flex:1')
      const okBtn  = btn('✓', `background:none;border:none;color:${S.green};cursor:pointer;font-size:14px;padding:0 4px`)
      const canBtn = btn('×', `background:none;border:none;color:${S.muted};cursor:pointer;font-size:14px;padding:0 2px`)

      const doRename = async () => {
        const newName = renameInp.value.trim()
        if (!newName || newName === currentName) { await _reload(); return }
        if (newName.includes('/') || newName.includes('\\')) { alert('Name cannot contain path separators.'); renameInp.focus(); return }
        const dir = entry.path.includes('/') ? entry.path.slice(0, entry.path.lastIndexOf('/')) : ''
        const newPath = dir ? `${dir}/${newName}` : newName
        const conflict = _entries.some(e => e.path === newPath) ||
          (entry.type === 'folder' && _entries.some(e => e.path.startsWith(newPath + '/')))
        if (conflict) { alert(`"${newName}" already exists in this folder.`); renameInp.focus(); return }
        const result = await api.renameLibrary(entry.path, newName)
        if (result) await _reload()
        else { alert('Rename failed — a file with that name may already exist.'); await _reload() }
      }
      const doCancel = () => _reload()

      renameInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') doRename(); if (e.key === 'Escape') doCancel() })
      okBtn.addEventListener('click', doRename)
      canBtn.addEventListener('click', doCancel)

      rowEl.append(iconEl, renameInp, okBtn, canBtn)
      setTimeout(() => { renameInp.focus(); renameInp.select() }, 30)
    }

    // ── Move ──────────────────────────────────────────────────────────────────
    async function _startMove(entry) {
      const destFolder = await _openFolderPicker(`Move "${entry.path.split('/').pop()}" to…`)
      if (destFolder === null) return
      const result = await api.moveLibrary(entry.path, destFolder)
      if (result) {
        // If the item moved out of current dir, reload
        await _reload()
      }
    }

    // ── Folder-picker sub-modal ───────────────────────────────────────────────
    function _openFolderPicker(subTitle) {
      return new Promise((res) => {
        // Collect all known folder paths (including root)
        const folderPaths = ['']
        const seen = new Set([''])
        for (const e of _entries) {
          const parts = e.path.split('/')
          for (let i = 1; i < parts.length; i++) {
            const fp = parts.slice(0, i).join('/')
            if (!seen.has(fp)) { seen.add(fp); folderPaths.push(fp) }
          }
          if (e.type === 'folder' && !seen.has(e.path)) { seen.add(e.path); folderPaths.push(e.path) }
        }
        folderPaths.sort()

        const pickerOverlay = document.createElement('div')
        pickerOverlay.style.cssText = `position:fixed;inset:0;z-index:400;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center`

        const pickerModal = document.createElement('div')
        pickerModal.style.cssText = [
          `background:${S.bg};border:1px solid ${S.border};border-radius:8px`,
          'width:340px;max-height:50vh;display:flex;flex-direction:column;overflow:hidden',
          'font-family:var(--font-ui);font-size:12px',
        ].join(';')

        const hdr = document.createElement('div')
        hdr.style.cssText = `display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid ${S.border2}`
        const hdrTitle = document.createElement('span')
        hdrTitle.textContent = subTitle; hdrTitle.style.cssText = `color:${S.text};font-size:12px`
        const hdrClose = btn('×', `background:none;border:none;color:${S.muted};font-size:16px;cursor:pointer`)
        hdrClose.addEventListener('click', () => { document.body.removeChild(pickerOverlay); res(null) })
        hdr.append(hdrTitle, hdrClose)

        const pickerList = document.createElement('div')
        pickerList.style.cssText = 'flex:1;overflow-y:auto;padding:3px 8px'

        for (const fp of folderPaths) {
          const row = document.createElement('div')
          row.style.cssText = `display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:4px;cursor:pointer`
          row.addEventListener('mouseenter', () => { row.style.background = S.hover })
          row.addEventListener('mouseleave', () => { row.style.background = 'transparent' })
          const iconEl = document.createElement('span')
          iconEl.textContent = fp === '' ? '🏠' : '📁'
          iconEl.style.cssText = 'font-size:12px;flex-shrink:0'
          const nameEl = document.createElement('span')
          nameEl.textContent = fp === '' ? 'workspace root' : fp
          nameEl.style.cssText = `color:${S.text};flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`
          row.append(iconEl, nameEl)
          row.addEventListener('click', () => { document.body.removeChild(pickerOverlay); res(fp) })
          pickerList.appendChild(row)
        }

        pickerModal.append(hdr, pickerList)
        pickerOverlay.appendChild(pickerModal)
        pickerOverlay.addEventListener('click', (e) => {
          if (e.target === pickerOverlay) { document.body.removeChild(pickerOverlay); res(null) }
        })
        document.body.appendChild(pickerOverlay)
      })
    }

    // ── Reload ────────────────────────────────────────────────────────────────
    async function _reload() {
      listEl.innerHTML = `<div style="color:${S.dim};padding:20px 8px;text-align:center">Loading…</div>`
      try {
        const files = await api.listLibraryFiles()
        _entries = Array.isArray(files) ? files : []
      } catch {
        listEl.innerHTML = `<div style="color:${S.red};padding:20px 8px;text-align:center">Could not reach server.</div>`
        return
      }
      _renderList()
    }

    // ── Boot ──────────────────────────────────────────────────────────────────
    _renderBreadcrumb()
    _renderSortBar()
    _reload()
  })
}

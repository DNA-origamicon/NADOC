// ── Recent files ─────────────────────────────────────────────────────────────
const LS_RECENT_KEY = 'nadoc:recent'
const RECENT_MAX    = 2

/**
 * Return the recent-files list: [{ name, content, type, ts }, ...] newest first.
 * `type` is 'nadoc' | 'cadnano' | 'scadnano'.
 */
export function getRecentFiles() {
  try {
    const raw = localStorage.getItem(LS_RECENT_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

/**
 * Add or update a recent-file entry.  Keeps only the newest RECENT_MAX entries.
 * @param {string} name     Display name (filename or design name).
 * @param {string} content  Raw file content string.
 * @param {'nadoc'|'cadnano'|'scadnano'} [type='nadoc']  File type.
 */
export function addRecentFile(name, content, type = 'nadoc') {
  try {
    let recent = getRecentFiles().filter(r => r.name !== name)
    recent.unshift({ name, content, type, ts: Date.now() })
    recent = recent.slice(0, RECENT_MAX)
    localStorage.setItem(LS_RECENT_KEY, JSON.stringify(recent))
  } catch { /* quota exceeded — ignore */ }
}

/** Clear the recent-files list. */
export function clearRecentFiles() {
  try { localStorage.removeItem(LS_RECENT_KEY) } catch { /* ignore */ }
}

// ── Recent protein imports (PDB codes + files) ───────────────────────────────
// Separate list from design recents.  Mixed entries, newest first:
//   { kind: 'code', code, ts }
//   { kind: 'file', name, content?, ts }   // content cached for re-import; omitted when too large
const LS_PROTEIN_RECENT_KEY = 'nadoc:recentProtein'
const PROTEIN_RECENT_MAX    = 8
const PROTEIN_CONTENT_CAP    = 3_000_000   // chars; above this we keep the name only

/** Recent protein imports, newest first. */
export function getRecentProteinImports() {
  try {
    const raw = localStorage.getItem(LS_PROTEIN_RECENT_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function _saveProteinRecents(list) {
  try {
    localStorage.setItem(LS_PROTEIN_RECENT_KEY, JSON.stringify(list.slice(0, PROTEIN_RECENT_MAX)))
  } catch {
    // Quota exceeded — retry once without cached file contents (codes + names only).
    try {
      const lean = list.slice(0, PROTEIN_RECENT_MAX).map(e =>
        e.kind === 'file' ? { kind: 'file', name: e.name, ts: e.ts } : e)
      localStorage.setItem(LS_PROTEIN_RECENT_KEY, JSON.stringify(lean))
    } catch { /* give up */ }
  }
}

/** Record a recently-used RCSB PDB code. */
export function addRecentProteinCode(code) {
  const c = String(code || '').trim().toUpperCase()
  if (!c) return
  const list = getRecentProteinImports().filter(e => !(e.kind === 'code' && e.code === c))
  list.unshift({ kind: 'code', code: c, ts: Date.now() })
  _saveProteinRecents(list)
}

/** Record a recently-imported protein file (content cached for re-import when small enough). */
export function addRecentProteinFile(name, content) {
  if (!name) return
  const entry = { kind: 'file', name, ts: Date.now() }
  if (typeof content === 'string' && content.length <= PROTEIN_CONTENT_CAP) entry.content = content
  const list = getRecentProteinImports().filter(e => !(e.kind === 'file' && e.name === name))
  list.unshift(entry)
  _saveProteinRecents(list)
}

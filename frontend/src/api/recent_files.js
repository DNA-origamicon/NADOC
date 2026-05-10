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

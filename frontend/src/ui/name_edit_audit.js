const entries = []
const MAX = 300

export function recordNameEdit(event, detail = {}) {
  entries.push({ at: performance.now(), event, ...detail })
  if (entries.length > MAX) entries.splice(0, entries.length - MAX)
}

if (typeof window !== 'undefined') {
  window.__nadocNameAudit = {
    snapshot: () => entries.map(entry => ({ ...entry })),
    clear: () => { entries.length = 0 },
  }
}

/** Each engine owns its run folder; the old shared setting is a migration fallback. */
export const RUN_DIR_EVENT = 'nadoc:run-dir-change'
const key = engine => `nadoc.runDir.${engine === 'lammps' ? 'oxdna' : engine}`
export function getRunDir(engine = 'namd') {
  try {
    const saved = localStorage.getItem(key(engine))
    // An empty value explicitly means default, even when a legacy preference exists.
    return (saved === null ? localStorage.getItem('nadoc.runDir') : saved) || null
  } catch { return null }
}
export function setRunDir(dir, engine = 'namd') {
  const value = dir || null
  try { localStorage.setItem(key(engine), value || '') } catch { /* unavailable storage */ }
  try { window.dispatchEvent(new CustomEvent(RUN_DIR_EVENT, { detail: { engine, path: value } })) } catch { /* no window */ }
  return value
}

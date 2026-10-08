// Shared lifetime for still/video capture, including overlapping exports.
let active = 0
const listeners = new Set()
function publish() { for (const listener of listeners) listener(active > 0) }

export function onMediaExportChange(listener) {
  listeners.add(listener)
  listener(active > 0)
  return () => listeners.delete(listener)
}

export async function withMediaExport(capture) {
  active++
  publish()
  try { return await capture() }
  finally { active--; publish() }
}

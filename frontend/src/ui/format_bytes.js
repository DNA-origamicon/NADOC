/**
 * Human-readable byte sizes (B / KB / MB / GB / TB) for disk-usage displays.
 *
 * Pure function — covered by format_bytes.test.js. Used by the welcome-screen
 * "Data on disk" column and the Help ▸ About-this-file panel, both of which can
 * surface multi-GB simulation footprints, so this scales past MB unlike the
 * MB-capped _fmtSize in md_panel.js.
 */

const _UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

export function formatBytes(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  let i = 0
  let v = n
  while (v >= 1024 && i < _UNITS.length - 1) {
    v /= 1024
    i++
  }
  // Whole bytes show no decimal; KB+ show one (dropping a trailing .0).
  const str = i === 0 ? String(Math.round(v)) : v.toFixed(1).replace(/\.0$/, '')
  return `${str} ${_UNITS[i]}`
}

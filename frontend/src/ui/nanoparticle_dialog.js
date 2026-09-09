import { showToast } from './toast.js'

export function parseNanoparticleDiameter(value) {
  const diameter = Number(value)
  return Number.isFinite(diameter) && diameter > 0 && diameter <= 1000 ? diameter : null
}

/** Prompt for an AuNP diameter. Shared by Tools, context menu, and Feature Log. */
export async function promptGoldNanosphereDiameter({ current = 10, title = 'Gold nanosphere diameter' } = {}) {
  const value = window.prompt(`${title} (nm)`, String(current))
  if (value == null) return null
  const diameter = parseNanoparticleDiameter(value)
  if (diameter == null) {
    showToast('Diameter must be greater than 0 and at most 1000 nm.', { severity: 'error' })
    return null
  }
  return diameter
}

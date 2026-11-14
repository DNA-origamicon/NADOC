/** Apply reversible presentation preferences without touching molecular state. */
const SCALE = { xs: 13, sm: 14, base: 15, md: 16, lg: 18, xl: 20 }
export function applyAppearance(values, doc = document) {
  const root = doc.documentElement
  root.style.setProperty('--nadoc-text-scale', String(values.textScale))
  for (const [name, size] of Object.entries(SCALE)) root.style.setProperty(`--text-${name}`, `${size * values.textScale}px`)
  root.dataset.nadocTheme = values.theme === 'system'
    ? (doc.defaultView.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : values.theme
  root.dataset.nadocContrast = String(values.highContrast)
  root.dataset.nadocMotion = values.reducedMotion ? 'reduced' : 'normal'
  root.dataset.nadocDensity = values.density
}

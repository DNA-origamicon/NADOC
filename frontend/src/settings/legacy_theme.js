/** Bridge legacy UI colors to theme tokens; molecular palette colors are untouched. */
const COLORS = {
  '#010409': '--color-bg-inset', '#0d1117': '--color-bg-canvas',
  '#161b22': '--color-bg-surface', '#21262d': '--color-bg-raised', '#2d333b': '--color-bg-elevated',
  '#e6edf3': '--color-text-primary', '#c9d1d9': '--color-text-secondary',
  '#8b949e': '--color-text-muted', '#b1bac4': '--color-text-muted',
  '#30363d': '--color-border-default', '#484f58': '--color-border-strong',
}
export function themedColorValue(value) {
  return value.replace(/#[0-9a-f]{6}\b|rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)/gi, (match, r, g, b) => {
    const hex = r === undefined ? match.toLowerCase() : '#' + [r, g, b].map(n => Number(n).toString(16).padStart(2, '0')).join('')
    return COLORS[hex] ? `var(${COLORS[hex]})` : match
  })
}
export function themeLegacyStyle(style) {
  if (!style || !/[#]|rgb\(/.test(style.cssText)) return
  for (const property of Array.from(style)) {
    if (property.startsWith('--') || !/color|background|border|shadow/.test(property)) continue
    const value = style.getPropertyValue(property)
    // Never rewrite data URIs or image filenames.
    if (value.includes('url(') || value.includes('var(')) continue
    const themed = themedColorValue(value)
    if (themed !== value) style.setProperty(property, themed, style.getPropertyPriority(property))
  }
}

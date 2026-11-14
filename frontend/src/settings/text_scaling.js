import { themeLegacyStyle } from './legacy_theme.js'

/** Scale legacy pixel-sized text alongside token-based text, without scaling canvases. */
export function scaledFontSize(value) {
  return /^\d+(?:\.\d+)?px$/.test(value.trim()) ? `calc(${value.trim()} * var(--nadoc-text-scale, 1))` : value
}
export function initTextScaling(doc = document) {
  const scaleStyle = (style, theme = true) => {
    if (theme) themeLegacyStyle(style)
    const current = style?.getPropertyValue('font-size')
    if (!current) return
    const scaled = scaledFontSize(current)
    if (scaled !== current) style.setProperty('font-size', scaled, style.getPropertyPriority('font-size'))
  }
  const rules = list => {
    for (const rule of list || []) {
      scaleStyle(rule.style)
      if (rule.cssRules) rules(rule.cssRules)
    }
  }
  for (const sheet of doc.styleSheets) { try { rules(sheet.cssRules) } catch { /* Cross-origin styles are owned by their provider. */ } }
  const scan = root => {
    if (root.nodeType !== 1) return
    scaleStyle(root.style, !['viewport-container', 'canvas'].includes(root.id))
    for (const el of root.querySelectorAll('[style]')) scaleStyle(el.style, !['viewport-container', 'canvas'].includes(el.id))
  }
  scan(doc.body)
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes') scaleStyle(record.target.style, !['viewport-container', 'canvas'].includes(record.target.id))
      else for (const node of record.addedNodes) scan(node)
    }
  })
  observer.observe(doc.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['style'] })
  return () => observer.disconnect()
}

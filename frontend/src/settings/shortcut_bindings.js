export function shortcutId(spec) {
  return `${spec.description || ''}|${spec.key}|${spec.ctrl ?? '*'}|${spec.shift ?? '*'}|${spec.alt ?? '*'}`
}
export function parseShortcut(text) {
  const parts = text.toLowerCase().split('+').map(part => part.trim())
  const key = parts.pop()
  if (!key || !parts.every(part => ['ctrl', 'cmd', 'shift', 'alt'].includes(part))) throw new Error('Use a key with optional Ctrl, Shift or Alt, for example Ctrl+Shift+K.')
  if (key.length > 1 && !/^(f([1-9]|1[0-2])|arrow(up|down|left|right)|escape|enter|tab|space|delete|backspace|home|end|pageup|pagedown)$/.test(key)) throw new Error(`Unknown shortcut key: ${key}`)
  return { key: key === 'space' ? ' ' : key, ctrl: parts.includes('ctrl') || parts.includes('cmd'), shift: parts.includes('shift'), alt: parts.includes('alt') }
}
export function formatShortcut(spec) {
  return [spec.ctrl && 'Ctrl', spec.shift && 'Shift', spec.alt && 'Alt', spec.key === ' ' ? 'Space' : spec.key].filter(Boolean).join('+')
}
export function validateShortcutConflicts(bindings, definitions) {
  const effective = definitions.map(spec => ({ ...spec, ...(bindings[shortcutId(spec)] ? parseShortcut(bindings[shortcutId(spec)]) : {}) }))
  for (let i = 0; i < definitions.length; i++) {
    if (!bindings[shortcutId(definitions[i])]) continue
    for (let j = 0; j < definitions.length; j++) {
      if (i === j) continue
      const a = effective[i], b = effective[j]
      if (a.key.toLowerCase() === b.key.toLowerCase() && ['ctrl', 'shift', 'alt'].every(key => a[key] == null || b[key] == null || a[key] === b[key])) throw new Error(`Shortcut conflict: ${a.description} and ${b.description}.`)
    }
  }
  return bindings
}

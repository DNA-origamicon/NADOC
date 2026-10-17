/** Sidebar sources can be parked or mounted in any shared view. Inspect only
 * explicit host visibility; reading layout here would force a large DOM flush. */
export function assemblyOverhangPanelVisible(element) {
  if (!element?.isConnected) return false
  for (let node = element; node; node = node.parentElement) {
    if (node.hidden || node.style.display === 'none' || node.classList.contains('hidden')
      || node.classList.contains('locked-inactive')) return false
  }
  return true
}

/** These lists depend on source content and identity, not placement or rendering.
 * Keep Design references rather than serializing thousands of repeated sources.
 * The resolver validates each instance's live source version before returning it. */
export function assemblyOverhangPanelInputs(assembly, resolve) {
  return { id: assembly?.id, rows: (assembly?.instances ?? []).map(instance => ({
    id: instance.id, name: instance.name, design: resolve(instance),
  })) }
}

export function sameAssemblyOverhangInputs(previous, next) {
  return previous?.id === next.id && previous?.rows.length === next.rows.length
    && next.rows.every((row, index) => {
      const before = previous.rows[index]
      return before.id === row.id && before.name === row.name && before.design === row.design
    })
}

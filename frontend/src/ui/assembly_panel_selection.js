/** Repaint existing rows for selection changes without rebuilding their controls. */
export function paintAssemblyPanelSelection(root, state) {
  const multi = new Set(state.multiSelectedInstanceIds ?? [])
  let activeRow = null
  for (const row of root.querySelectorAll('[data-instance-id]')) {
    const id = row.dataset.instanceId
    row.style.background = id === state.activeInstanceId ? '#1e3a5f'
      : multi.has(id) ? '#192c45' : 'transparent'
    if (id === state.activeInstanceId) activeRow = row
  }
  for (const row of root.querySelectorAll('[data-group-id]')) {
    const selected = row.dataset.groupId === state.activeGroupId
    row.style.background = selected ? '#3a2a5f' : 'transparent'
    row.style.borderLeftColor = selected ? '#8b5cf6' : '#3a2a5f'
  }
  return activeRow
}

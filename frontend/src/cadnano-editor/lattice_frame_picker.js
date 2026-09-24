/** Keep local-cell editing scoped to one explicit frame; helix IDs remain authority. */
export function frameOptions(design) {
  const options = []
  if (!design?.lattice_frames?.length || design.helices?.some(h => !h.lattice_frame_id)) {
    options.push({ id: '', label: 'Original lattice' })
  }
  for (const [index, frame] of (design?.lattice_frames ?? []).entries()) {
    const cluster = design.cluster_transforms?.find(c => c.id === frame.placement_cluster_id)
    options.push({ id: frame.id, label: `${index+1}: ${cluster?.name || 'Lattice'} · ${frame.plane}` })
  }
  return options
}

export function helicesInFrame(design, frameId) {
  return (design?.helices ?? []).filter(h => (h.lattice_frame_id ?? null) === frameId)
}

export function framePlane(design, frameId) {
  return design?.lattice_frames?.find(f => f.id === frameId)?.plane
    ?? helicesInFrame(design, frameId)[0]?.id?.split('_')[1] ?? 'XY'
}

export function createLatticeFramePicker(container, onChange) {
  const label = document.createElement('label')
  label.textContent = 'Lattice '
  label.style.cssText = 'position:absolute;left:8px;top:8px;z-index:5;background:#161b22;padding:4px;color:#c9d1d9'
  const select = document.createElement('select')
  select.setAttribute('aria-label', 'Lattice frame')
  select.style.cssText = 'color:#e6edf3;background:#21262d;border:1px solid #484f58;max-width:180px;padding:3px'
  label.style.maxWidth = 'calc(100% - 16px)'
  label.append(select)
  container.append(label)
  select.addEventListener('change', onChange)
  return {
    frameId: () => select.value || null,
    update(design) {
      const previous = select.value
      const options = frameOptions(design)
      select.replaceChildren(...options.map(item => {
        const option = document.createElement('option')
        option.value = item.id; option.textContent = item.label
        return option
      }))
      if (options.some(option => option.id === previous)) select.value = previous
      label.hidden = !design?.lattice_frames?.length
      return select.value !== previous
    },
  }
}

/** Editable command parameters for recorded solid-rod construction. */
const fields = {
  pathing: { label: 'Pathing', type: 'select', options: ['colocalized', 'interior', 'exterior'] },
  bend_scale: { label: 'Curvature scale', type: 'number', min: 0.5, max: 1.5, step: 0.01 },
  path_order: { label: 'Particle visit order (e.g. 1, 3, 2, 4)', type: 'text' },
  length_bp: { label: 'Length (bp)', type: 'number', integer: true, min: 1 },
  bp_index: { label: 'Attachment position (bp)', type: 'number', integer: true, min: 0 },
  scaffold_name: { label: 'Scaffold', type: 'select', options: ['M13mp18', 'p8064'] },
  sequence: { label: 'Sequence (5′ → 3′)', type: 'text' },
  spacer_nm: { label: 'Thiol spacer (nm)', type: 'number', min: 0, max: 100, step: 0.1 },
  roll_deg: { label: 'Rotation (degrees)', type: 'number', min: -180, max: 180, step: 1 },
  offset_nm: { label: 'Offset from particles (nm)', type: 'number', min: 0, step: 0.1 },
  phase_deg: { label: 'Attachment position around reachable circle (degrees)', type: 'number', step: 1 },
  duplex_roll_deg: { label: 'Duplex rotation (degrees)', type: 'number', step: 1 },
}

export function generatedFeatureSchema(entry) {
  return (entry.params?._generator?.editable ?? []).map(key => ({ key, ...fields[key] }))
}

export function canReplayGenerated(log, index) {
  const group = log[index]?.params?._generator?.group_id
  return !!group && log.slice(index).every(e => e.params?._generator?.group_id === group)
}

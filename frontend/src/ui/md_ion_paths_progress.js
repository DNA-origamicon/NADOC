// Fixed work weights, not elapsed-time estimates. Each stage advances from actual
// completed units; 100% is reserved for the fully applied representation.
export const ION_PATH_STAGES = [
  ['waiting', 1, 'Waiting for trajectory analysis'],
  ['topology', 5, 'Reading ion and nanopore topology'],
  ['coordinates', 14, 'Loading ion coordinates'],
  ['crossings', 8, 'Finding nanopore crossings'],
  ['rmsf_setup', 5, 'Preparing origami alignment'],
  ['rmsf', 8, 'Averaging origami positions'],
  ['atomistic_setup', 8, 'Preparing atomistic topology and alignment'],
  ['atomistic_average', 9, 'Averaging atom positions'],
  ['atomistic_topology', 2, 'Preparing atom bonds'],
  ['surface', 4, 'Computing and smoothing average surface'],
  ['windows', 4, 'Building crossing windows'],
  ['serialize', 2, 'Packing path data'],
]
export function ionPathsProgress(snapshot) {
  const stages = new Map((snapshot?.stages || []).map(s => [s.stage, s]))
  let percentage = 0, label = 'Preparing nanopore ion visualization'
  for (const [name, weight, title] of ION_PATH_STAGES) {
    const stage = stages.get(name)
    if (!stage) continue
    const fraction = stage.total > 0 ? Math.min(1, stage.done / stage.total) : 0
    percentage += weight * fraction
    label = title + (stage.total > 1 ? ` (${stage.done.toLocaleString()} / ${stage.total.toLocaleString()})` : '')
  }
  return { percentage, label }
}

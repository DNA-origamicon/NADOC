/** A folding objective only: no topology, temperature or routing inference. */
export function foldingPlan(design) {
  const stages = new Map(), undefinedClusters = []
  for (const cluster of design?.cluster_transforms ?? []) {
    const stage = cluster.folding_order
    if (!Number.isInteger(stage) || stage < 1 || stage > 999) {
      undefinedClusters.push(cluster)
      continue
    }
    if (!stages.has(stage)) stages.set(stage, [])
    stages.get(stage).push(cluster)
  }
  return {
    stages: [...stages].sort(([a], [b]) => a - b).map(([stage, clusters]) => ({ stage, clusters })),
    undefinedClusters,
  }
}

export function foldingPlanText(design) {
  const { stages, undefinedClusters } = foldingPlan(design)
  const names = clusters => clusters.map(c => c.name || c.id).join(', ')
  const ordered = stages.map(({ stage, clusters }) => `Stage ${stage}: ${names(clusters)}`).join(' → ')
  return [ordered || 'No folding stages assigned.',
    undefinedClusters.length ? `Undefined — default routing: ${names(undefinedClusters)}.` : ''].filter(Boolean).join('\n')
}

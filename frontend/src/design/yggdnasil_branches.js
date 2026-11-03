import { buildYggTree } from './yggdnasil_tree.js'
import { curvatureCatalog, curvatureSamples } from './yggdnasil_curvature.js'

/** Graft count-class limbs onto their existing zero-curvature radius vertices. */
export function buildYggBranches(atlas, options = {}) {
  const model = buildYggTree(atlas, options), catalogs = new Map()
  const roots = [...model.nodes]
  let branchCount = 0
  for (const root of roots) {
    if (root.routing.excluded) continue
    let catalog = catalogs.get(root.entry.id)
    if (!catalog) {
      catalog = curvatureSamples(curvatureCatalog(root.entry, model.length, { reserve: atlas.reserve }))
      catalogs.set(root.entry.id, catalog)
    }
    const zero = catalog.classes[0]
    if (!zero?.eligible || zero.angleRad !== 0) continue
    root.curvature = zero; root.rootId = root.id
    let previous = root
    const sign = root.lattice === 'square' ? -1 : 1
    const azimuth = ['Helix', 'Bond', 'Cell'].indexOf(root.center) * 2 * Math.PI / 3 + root.index * 2.399963
    for (const state of catalog.classes.slice(1)) {
      // A limb must remain connected to its zero state; never bridge rejected classes.
      if (!state.eligible) break
      const t = state.angleRad / catalog.frame.maxAngleRad
      const node = { ...root, id: `${root.id}:curve:${state.key}`, rootId: root.id,
        index: state.index, curvature: state, label: `${state.angleDeg.toFixed(1)}°`,
        position: [root.position[0] + sign * 12 * t,
          root.position[1] + (3 + 4 * Math.cos(azimuth)) * t,
          root.position[2] + 12 * Math.sin(azimuth) * t + 3 * t * t] }
      model.nodes.push(node)
      model.edges.push({ from: previous.id, to: node.id, parameter: 'curvature-counts',
        lattice: root.lattice, center: root.center, length: root.length,
        deltaLoops: state.loops - previous.curvature.loops, deltaSkips: state.skips - previous.curvature.skips,
        label: `ΔI ${state.loops - previous.curvature.loops}, ΔD ${state.skips - previous.curvature.skips}` })
      previous = node
    }
    if (previous !== root) branchCount++
  }
  return { ...model, catalogs, branchCount, structureCount: new Set(model.nodes.map(n => `${n.entry.id}:${n.curvature?.key || 'straight'}`)).size }
}

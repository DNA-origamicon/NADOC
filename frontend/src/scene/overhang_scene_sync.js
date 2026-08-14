import { initOverhangLocations } from './overhang_locations.js'
import { initOverhangLinkArcs } from './overhang_link_arcs.js'
import { initFlexibleArcs } from './flexible_arcs.js'
import { initUnligatedCrossoverMarkers } from './unligated_crossover_markers.js'
import {
  buildSpecMap,
  buildDomainMapFromDesign,
  buildJunctionMapFromDomains,
  buildRootMap,
} from './overhang_maps.js'

/** Owns reactive overhang overlays and the orientation lookup-map pipeline. */
export function initOverhangSceneSync({ scene, store, designRenderer, assemblyRenderer }) {
  const locations = initOverhangLocations(scene)
  const linkArcs = initOverhangLinkArcs(scene)
  const flexibleArcs = initFlexibleArcs(
    scene, designRenderer, () => store.getState().currentHelixAxes,
  )
  const unligatedMarkers = initUnligatedCrossoverMarkers(scene)
  let rootMap = new Map()

  function rebuildLocations() {
    if (!locations.isVisible()) return
    const state = store.getState()
    if (state.assemblyActive) {
      const instanceId = state.activeInstanceId
      const renderData = instanceId
        ? assemblyRenderer.getInstanceRenderData(instanceId)
        : null
      if (!renderData?.design || !renderData?.nucleotides || !renderData?.group) {
        locations.clear()
        return
      }
      locations.rebuild(renderData.design, renderData.nucleotides, {
        parentGroup: renderData.group, instanceId,
      })
      return
    }
    locations.rebuild(state.currentDesign, state.currentGeometry, {
      candidateGeometry: state.straightGeometry ?? state.currentGeometry,
    })
  }

  function rebuildMaps(design) {
    const specs = buildSpecMap(design)
    const domains = buildDomainMapFromDesign(design, specs)
    const junctions = buildJunctionMapFromDomains(domains)
    rootMap = buildRootMap(specs, junctions, designRenderer.getHelixCtrl())
  }

  store.subscribe((next, previous) => {
    const designChanged = next.currentDesign !== previous.currentDesign
    const geometryChanged = next.currentGeometry !== previous.currentGeometry
    const straightChanged = next.straightGeometry !== previous.straightGeometry
    if (designChanged || geometryChanged) {
      linkArcs.rebuild(next.currentDesign, next.currentGeometry)
      flexibleArcs.rebuild(next.currentDesign)
      unligatedMarkers.rebuild(
        next.currentDesign, next.currentGeometry, next.unligatedCrossoverIds,
      )
      rebuildMaps(next.currentDesign)
    } else if (next.unligatedCrossoverIds !== previous.unligatedCrossoverIds) {
      unligatedMarkers.rebuild(
        next.currentDesign, next.currentGeometry, next.unligatedCrossoverIds,
      )
    }
    if ((designChanged || geometryChanged || straightChanged) && !next.assemblyActive) {
      rebuildLocations()
    }
  })

  store.subscribe((next, previous) => {
    const modeChanged = next.assemblyActive !== previous.assemblyActive
    if (!modeChanged && !next.assemblyActive) return
    if (!modeChanged &&
        next.activeInstanceId === previous.activeInstanceId &&
        next.currentAssembly === previous.currentAssembly) return
    rebuildLocations()
  })
  assemblyRenderer.onRebuildComplete(rebuildLocations)

  const state = store.getState()
  if (state.currentDesign && state.currentGeometry) {
    linkArcs.rebuild(state.currentDesign, state.currentGeometry)
    flexibleArcs.rebuild(state.currentDesign)
    unligatedMarkers.rebuild(
      state.currentDesign, state.currentGeometry, state.unligatedCrossoverIds,
    )
    rebuildMaps(state.currentDesign)
  }

  return {
    locations,
    linkArcs,
    flexibleArcs,
    unligatedMarkers,
    rebuildLocations,
    getRootMap: () => rootMap,
  }
}

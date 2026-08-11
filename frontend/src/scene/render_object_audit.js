/** Inventory what Three.js can actually draw, including ancestor visibility.
 * Intended for Playwright/browser troubleshooting: scene membership alone is insufficient
 * because a retained mesh under a hidden parent is not visible, while an anonymously named
 * mesh under a stale occupancy root still is. */
export function auditRenderedObjects(scene) {
  const objects = []
  scene?.updateMatrixWorld?.(true)
  scene?.traverse?.((o) => {
    if (!(o?.isMesh || o?.isLine || o?.isLineSegments || o?.isPoints || o?.isSprite)) return
    let effectiveVisible = true
    let occupancy = false
    const path = []
    for (let p = o; p; p = p.parent) {
      if (p.visible === false) effectiveVisible = false
      if (String(p.name || '').startsWith('occupancyGhost')) occupancy = true
      if (p.name) path.push(p.name)
    }
    const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : [])
    const opacity = mats.length ? Math.max(...mats.map(m => Number(m?.opacity ?? 1))) : 1
    const drawCount = Number(o.count ?? o.geometry?.drawRange?.count ?? 0)
    const e = o.matrixWorld?.elements
    objects.push({
      uuid: o.uuid, name: o.name || '', type: o.type || '',
      path: path.reverse().join('/'), occupancy,
      visible: o.visible !== false, effectiveVisible: effectiveVisible && opacity > 0,
      opacity, drawCount: Number.isFinite(drawCount) ? drawCount : 0,
      world: e ? [e[12], e[13], e[14]].map(v => Math.round(v * 1e4) / 1e4) : null,
    })
  })
  const visible = objects.filter(o => o.effectiveVisible)
  const occ = visible.filter(o => o.occupancy)
  return {
    totalRenderables: objects.length,
    visibleRenderables: visible.length,
    visibleOccupancyRenderables: occ.length,
    occupancyUuids: occ.map(o => o.uuid).sort(),
    objects,
  }
}

/** Compact before/during/after comparison without discarding the detailed inventories. */
export function compareRenderedObjects(before, during, after) {
  const ids = x => new Set((x?.objects ?? []).filter(o => o.effectiveVisible).map(o => o.uuid))
  const a = ids(before); const b = ids(during); const c = ids(after)
  return {
    addedDuring: [...b].filter(x => !a.has(x)).sort(),
    leftAfter: [...c].filter(x => !a.has(x)).sort(),
    missingAfter: [...a].filter(x => !c.has(x)).sort(),
    occupancyVisibleAfter: after?.visibleOccupancyRenderables ?? 0,
    before, during, after,
  }
}

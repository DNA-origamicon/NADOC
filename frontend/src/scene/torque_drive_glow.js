import { initAnchorGlow, resolveAnchorEntries } from './anchor_glow.js'

/** An empty drive selection means all unanchored particles, as in the force resolver. */
export function resolveTorqueDriveEntries(refs, entries, design, fixed = [], all = false) {
  if (!all) return resolveAnchorEntries(refs, entries, design)
  const excluded = new Set(resolveAnchorEntries(fixed, entries, design))
  return entries.filter(entry => !excluded.has(entry))
}

export function initTorqueDriveGlow({ designRenderer, store }) {
  let enabled = false, visible = true, engine = 'oxdna', fixed = [], extraFixed = []
  let selection = { anchors: [], highlighted: [], glow: true }
  const glow = initAnchorGlow({ store,
    designRenderer: {
      getBackboneEntries: () => designRenderer.getBackboneEntries(),
      setAnchorGlow: entries => designRenderer.setTorqueDriveGlow(entries),
      clearAnchorGlow: () => designRenderer.clearTorqueDriveGlow(),
    },
    resolveEntries: (_, entries, design) => resolveTorqueDriveEntries(
      selection.highlighted, entries, design, [...fixed, ...extraFixed],
      !selection.anchors.length && selection.glow,
    ),
  })
  function refresh() {
    // A sentinel keeps the shared renderer's geometry/trajectory refresh active for
    // the implicit all-unanchored selection, which has no explicit descriptors.
    if (enabled && visible && engine === 'oxdna') glow.setAnchors([{ kind: 'drive-display' }])
    else glow.clear()
  }
  window.addEventListener('nadoc:anchors-change', ({ detail }) => {
    if (detail.engine === 'oxdna-drive') selection = detail
    else if (detail.engine === 'oxdna') fixed = detail.anchors || []
    else return
    refresh()
  })
  window.addEventListener('nadoc:torque-display', ({ detail }) => {
    enabled = detail.enabled
    extraFixed = detail.fixed || []
    refresh()
  })
  window.addEventListener('nadoc:simulation-engine', ({ detail }) => { engine = detail.engine; refresh() })
  window.addEventListener('nadoc:left-tab-change', ({ detail }) => {
    if (detail?.navigationOnly) return
    visible = detail?.activeTab === 'dynamics'
    refresh()
  })
  return { clear() { enabled = false; glow.clear() } }
}

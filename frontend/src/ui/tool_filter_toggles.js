// Tool Filter toggles — the `#view-tools .sf-btn[data-key]` button row (blunt
// ends / crossover locations / overhang locations) plus the single
// `toolFilters` → renderer-visibility subscriber.
//
// Extracted verbatim from main.js (banner `// ── Tool Filter toggles`). The
// buttons only flip `store.toolFilters[key]`; the reactions live in subscribers.
// This module owns the co-located visibility subscriber (crossover / overhang /
// extension locations). The `bluntEnds` reaction is NOT here — it lives in the
// assembly blunt-end sync region (main.js) and stays put; the button just sets
// state, so behaviour is preserved.
//
// `overhangHoverPicker` is created later in main()'s init order than the call
// site, so it's injected as a lazy getter (mirrors the existing lazy-getter
// convention). All other deps exist before the factory is invoked.

export function initToolFilterToggles({
  store,
  crossoverLocations,
  overhangLocations,
  designRenderer,
  cadnanoView,
  unfoldView,
  rebuildOverhangLocations,
  getOverhangHoverPicker,
}) {
  const _tfKeyMap = [
    ['bluntEnds',          'blunt'],
    ['crossoverLocations', 'xloc' ],
    ['overhangLocations',  'ovhg' ],
  ]
  for (const [storeKey, dataKey] of _tfKeyMap) {
    const btn = document.querySelector(`#view-tools .sf-btn[data-key="${dataKey}"]`)
    if (!btn) continue
    btn.addEventListener('click', () => {
      const tf = store.getState().toolFilters
      store.setState({ toolFilters: { ...tf, [storeKey]: !tf[storeKey] } })
    })
    store.subscribe(() => {
      btn.classList.toggle('active', !!store.getState().toolFilters[storeKey])
    })
  }

  // Sync toolFilters → tool visibility
  store.subscribe((newState, prevState) => {
    if (newState.toolFilters === prevState.toolFilters) return
    const tf = newState.toolFilters
    const prev = prevState.toolFilters ?? {}
    if (tf.crossoverLocations !== prev.crossoverLocations) {
      crossoverLocations.setVisible(tf.crossoverLocations)
      if (tf.crossoverLocations) {
        crossoverLocations.rebuild(store.getState().currentGeometry).then(() => {
          if (cadnanoView.isActive()) cadnanoView.reapplyPositions()
          else unfoldView.reapplyIfActive()
        })
      }
    }
    if (tf.overhangLocations !== prev.overhangLocations) {
      overhangLocations.setVisible(tf.overhangLocations)
      if (tf.overhangLocations) rebuildOverhangLocations()
      // Turning the overhang tool off in assembly mode drops any transient
      // hover label (hover-reveal is gated on this tool — see overhangHoverPicker.onHoverMove).
      else if (newState.assemblyActive) { getOverhangHoverPicker()?.reset() }
    }
    if (tf.extensionLocations !== prev.extensionLocations) {
      designRenderer.setExtensionsVisible(tf.extensionLocations)
    }
  })
}

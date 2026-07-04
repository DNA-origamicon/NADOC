// View legends — the Loop/Skip and MD-Segmentation legend overlays plus their
// View-menu toggle handlers.
//
// Extracted verbatim from main.js (banners `// ── Loop/Skip legend` +
// `// ── MD Segmentation legend + toggle`). Each handler toggles an underlying
// highlight/overlay module AND shows/hides a fixed-position legend div.
// Display-only; touches no topology.
//
// The two legends are a matched pair: `_resetForNewDesign` hides both together
// (and clears their View-menu pills + calls `mdSegmentation.hide()`), so that
// teardown is exposed here as `reset()`. `computeSegments` is imported directly
// (already a pure helper co-located with the overlay module), so it's not a dep.
//
// `setMenuToggle` is main.js's shared 43-use menu-pill util — injected, not
// moved. `loopSkipHighlight` / `mdSegmentation` are both created before this
// factory in main()'s init order, so they pass directly (no lazy getter needed).

import { computeSegments } from '../scene/md_segmentation_overlay.js'

export function initViewLegends({ store, loopSkipHighlight, mdSegmentation, setMenuToggle }) {
  // ── Loop/Skip legend ──
  // Anchored below the filter-view strip (menu-bar 29 px + strip ~24 px → ~58 px).
  // Earlier `top: 44px` placed it inside the strip's vertical band, hiding the
  // selectability/view toggles. `right: 308px` keeps it left of the 300 px
  // right-panel.
  const loopSkipLegend = document.createElement('div')
  loopSkipLegend.style.cssText = `
    position: fixed;
    top: 64px;
    right: 308px;
    display: none;
    background: rgba(8,16,26,0.90);
    border: 1px solid #2a5a8a;
    border-radius: 5px;
    padding: 8px 12px;
    font-family: var(--font-ui);
    font-size: 12px;
    color: #c8daf0;
    line-height: 1.9;
    z-index: 9000;
    pointer-events: none;
  `
  // jsdom does not reflect `display` set via a multi-prop cssText — set it
  // explicitly so the initial-hidden state is robust (harmless in the browser).
  loopSkipLegend.style.display = 'none'
  loopSkipLegend.innerHTML = `
    <div style="color:#5bc8ff;font-weight:bold;letter-spacing:.04em;margin-bottom:3px">LOOP / SKIP</div>
    <div><span style="display:inline-block;width:14px;height:14px;border-radius:50%;border:3px solid #ff8800;vertical-align:middle;margin-right:6px"></span>Loop &nbsp;(+1 bp)</div>
    <div><span style="color:#ff2222;font-size:15px;font-weight:bold;vertical-align:middle;margin-right:6px;line-height:1">✕</span>Skip &nbsp;(−1 bp)</div>
  `.trim()
  document.body.appendChild(loopSkipLegend)

  // Loop/skip visibility is held in the store (`showLoopSkips`) so the View-menu
  // item and the "loop/skip" view-tool pill drive the same state. Both entry
  // points just flip the key; this applier does the actual scene/legend work.
  function _applyLoopSkipVisibility(nowVisible) {
    loopSkipHighlight.setVisible(nowVisible)
    setMenuToggle('menu-view-loop-skip', nowVisible)
    loopSkipLegend.style.display = nowVisible ? 'block' : 'none'
    if (nowVisible) {
      const { currentDesign, currentGeometry, currentHelixAxes } = store.getState()
      loopSkipHighlight.rebuild(currentDesign, currentGeometry, currentHelixAxes)
    }
  }

  document.getElementById('menu-view-loop-skip')?.addEventListener('click', () => {
    store.setState({ showLoopSkips: !store.getState().showLoopSkips })
  })

  store.subscribe((newState, prevState) => {
    if (newState.showLoopSkips !== prevState.showLoopSkips) {
      _applyLoopSkipVisibility(newState.showLoopSkips)
    }
  })

  // ── MD Segmentation legend + toggle ──
  const mdSegLegend = document.createElement('div')
  mdSegLegend.style.cssText = `
    position: fixed;
    top: 64px;
    right: 308px;
    display: none;
    background: rgba(8,16,26,0.92);
    border: 1px solid #2a5a8a;
    border-radius: 5px;
    padding: 10px 14px;
    font-family: var(--font-ui);
    font-size: 12px;
    color: #c8daf0;
    line-height: 2.0;
    z-index: 9000;
    pointer-events: none;
    min-width: 220px;
  `
  mdSegLegend.style.display = 'none'
  mdSegLegend.innerHTML = `
    <div style="color:#5bc8ff;font-weight:bold;letter-spacing:.04em;margin-bottom:5px">MD SEGMENTATION</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#44cc66;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>Periodic &nbsp;— matches modal period</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#ffdd00;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>Minor deviation &nbsp;(1–2 xovers)</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#ff8800;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>Moderate deviation</div>
    <div><span style="display:inline-block;width:14px;height:14px;background:#ff4444;opacity:0.85;vertical-align:middle;margin-right:7px;border-radius:2px"></span>High deviation / End region</div>
    <div id="md-seg-legend-detail" style="margin-top:6px;font-size:10px;color:#8b949e;border-top:1px solid #21262d;padding-top:5px"></div>
  `.trim()
  document.body.appendChild(mdSegLegend)

  document.getElementById('menu-view-md-segmentation')?.addEventListener('click', () => {
    const { currentDesign } = store.getState()
    const nowVisible = mdSegmentation.toggle(currentDesign)
    setMenuToggle('menu-view-md-segmentation', nowVisible)
    mdSegLegend.style.display = nowVisible ? 'block' : 'none'
    if (nowVisible && currentDesign) {
      const { windows, modal } = computeSegments(currentDesign)
      const nPeriodic = windows.filter(w => w.category === 'periodic').length
      const detail    = document.getElementById('md-seg-legend-detail')
      if (detail) detail.textContent = `${nPeriodic} / ${windows.length} windows periodic  ·  modal = ${modal} xovers`
    }
  })

  // Called by main.js's `_resetForNewDesign` — hides both legends, clears their
  // View-menu pills, and hides the MD overlay. Verbatim port of the 5-line reset
  // block (order preserved).
  function reset() {
    store.setState({ showLoopSkips: false })   // hides highlight + legend + pills via subscriber
    mdSegmentation.hide()
    setMenuToggle('menu-view-md-segmentation', false)
    mdSegLegend.style.display = 'none'
  }

  return { reset, loopSkipLegend, mdSegLegend }
}

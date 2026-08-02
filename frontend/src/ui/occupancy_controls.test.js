import { describe, expect, it, vi } from 'vitest'

import {
  clusterLegendRows,
  normalizeOccupancyParams,
  occupancyFooterHtml,
  occupancyStateRowsHtml,
  occupancyStatusText,
} from './occupancy_controls.js'

const SWITCHING = {
  ready: true, verdict: 'switching', k: 2, transitions: 24,
  n_frames: 108, n_frames_torn: 0, silhouette: 0.58, basis: 'nt',
  variance_explained: [0.61, 0.14],
  confidence: { n_eff: 54, preliminary: false },
  clusters: [
    { rank: 0, population: 0.713, population_sem: 0.062, n_frames: 77, visits: 13,
      rmsd_spread_nm: 0.88, rmsd_to_top_nm: 0 },
    { rank: 1, population: 0.287, population_sem: 0.062, n_frames: 31, visits: 12,
      rmsd_spread_nm: 0.95, rmsd_to_top_nm: 0.93 },
  ],
}

const DRIFT = {
  ready: true, verdict: 'drift', k: 2, transitions: 1,
  n_frames: 50, n_frames_torn: 0, silhouette: 0.58, basis: 'nt',
  variance_explained: [0.78],
  confidence: { n_eff: 2.6, preliminary: true },
  clusters: [
    { rank: 0, population: 0.5, population_sem: 0.308, n_frames: 25, visits: 1,
      rmsd_spread_nm: 1.35, rmsd_to_top_nm: 0 },
    { rank: 1, population: 0.5, population_sem: 0.308, n_frames: 25, visits: 1,
      rmsd_spread_nm: 1.38, rmsd_to_top_nm: 4.88 },
  ],
}

const UNIMODAL = {
  ready: true, verdict: 'unimodal', k: 1, transitions: 0,
  n_frames: 108, n_frames_torn: 0, silhouette: 0.11, basis: 'nt',
  variance_explained: [0.27],
  confidence: { n_eff: 50, preliminary: false },
  clusters: [{ rank: 0, population: 1.0, population_sem: 0, n_frames: 108, visits: 1,
               rmsd_spread_nm: 1.1, rmsd_to_top_nm: 0 }],
}

describe('normalizeOccupancyParams', () => {
  it('clamps the state count to what the route accepts', () => {
    expect(normalizeOccupancyParams({ nClusters: 99 }).nClusters).toBe(6)
    expect(normalizeOccupancyParams({ nClusters: -4 }).nClusters).toBe(0)
    expect(normalizeOccupancyParams({ nClusters: '3' }).nClusters).toBe(3)
    expect(normalizeOccupancyParams({ nClusters: 'abc' }).nClusters).toBe(0)
  })

  it('only allows the two real bases, defaulting to all-nucleotide', () => {
    expect(normalizeOccupancyParams({ basis: 'bp' }).basis).toBe('bp')
    expect(normalizeOccupancyParams({ basis: 'axis' }).basis).toBe('nt')
    expect(normalizeOccupancyParams().basis).toBe('nt')
  })

  it('defaults maxFrames to the trajectory route\'s budget so the frame cache is shared', () => {
    expect(normalizeOccupancyParams().maxFrames).toBe(200)
    expect(normalizeOccupancyParams({ maxFrames: 0 }).maxFrames).toBe(200)
    expect(normalizeOccupancyParams({ maxFrames: 500 }).maxFrames).toBe(500)
  })
})

describe('occupancyStatusText', () => {
  it('reports switching with how often the states recur', () => {
    const s = occupancyStatusText(SWITCHING)
    expect(s.text).toMatch(/2 configurations/)
    expect(s.text).toMatch(/revisited 24 times/)
  })

  it('calls a drift a drift and refuses to call its counts likelihoods', () => {
    const s = occupancyStatusText(DRIFT)
    expect(s.text).toMatch(/Drift, not switching/)
    expect(s.text).toMatch(/not likelihoods/)
    expect(s.text).toMatch(/Sample longer/)
  })

  it('says unimodal plainly and points back at the flexibility map', () => {
    const s = occupancyStatusText(UNIMODAL)
    expect(s.text).toMatch(/Single configuration/)
    expect(s.text).toMatch(/flexibility map/)
  })

  it('surfaces torn-frame rejections rather than hiding them', () => {
    expect(occupancyStatusText({ ...SWITCHING, n_frames_torn: 4 }).text).toMatch(/4 torn rejected/)
    expect(occupancyStatusText(SWITCHING).text).not.toMatch(/torn/)
  })

  it('passes a not-ready reason straight through', () => {
    expect(occupancyStatusText({ ready: false, reason: 'no production or field run yet' }).text)
      .toBe('no production or field run yet')
    expect(occupancyStatusText(null).text).toBe('')
  })
})

describe('clusterLegendRows', () => {
  it('marks rank 0 as the design-coloured real model', () => {
    const rows = clusterLegendRows(SWITCHING, [null, 0xd29922])
    expect(rows[0].color).toBeNull()
    expect(rows[1].color).toBe(0xd29922)
  })

  it('formats populations as percentages with their error bars', () => {
    const rows = clusterLegendRows(SWITCHING, [null, 0xd29922])
    expect(rows[0].populationPct).toBe('71%')
    expect(rows[0].stderrPct).toBe('6%')
  })

  it('returns nothing for a not-ready response', () => {
    expect(clusterLegendRows({ ready: false }, [])).toEqual([])
    expect(clusterLegendRows(null, [])).toEqual([])
  })
})

describe('occupancyStateRowsHtml', () => {
  const COLORS = [0xd29922, 0xa371f7]

  it('gives EVERY state its own colour swatch, rank 0 included', () => {
    // The design's own per-strand colouring is hidden while this view is up, so a state
    // with no colour of its own would be unidentifiable.
    const html = occupancyStateRowsHtml(SWITCHING, COLORS, [true, true])
    expect(html).toMatch(/data-occ-color="0" value="#d29922"/)
    expect(html).toMatch(/data-occ-color="1" value="#a371f7"/)
    expect(html).not.toMatch(/design colours/)
  })

  it('emits a checkbox per state carrying its rank', () => {
    const html = occupancyStateRowsHtml(SWITCHING, COLORS, [true, true])
    expect(html).toMatch(/data-occ-vis="0"[^>]*checked/)
    expect(html).toMatch(/data-occ-vis="1"[^>]*checked/)
  })

  it('leaves a hidden state unchecked so the list matches the scene', () => {
    const html = occupancyStateRowsHtml(SWITCHING, COLORS, [true, false])
    const row1 = html.slice(html.indexOf('data-occ-vis="1"'))
    expect(row1.slice(0, row1.indexOf('>'))).not.toMatch(/checked/)
  })

  it('shows a percentage ± error for a switching ensemble', () => {
    const html = occupancyStateRowsHtml(SWITCHING, COLORS, [true, true])
    expect(html).toMatch(/71% ± 6%/)
    expect(html).toMatch(/0\.93 nm from state 1/)
    expect(html).toMatch(/13 visits/)
  })

  it('shows FRAME COUNTS, not percentages, for a drift', () => {
    // A drift's frame split is an artefact of where the run stopped; rendering it as a
    // likelihood would be the exact lie the verdict exists to prevent.
    const html = occupancyStateRowsHtml(DRIFT, COLORS, [true, true])
    expect(html).toMatch(/25 frames/)
    expect(html).not.toMatch(/50% ± /)
  })

  it('is empty for a not-ready response', () => {
    expect(occupancyStateRowsHtml({ ready: false }, [], [])).toBe('')
  })
})

describe('occupancyFooterHtml', () => {
  it('warns loudly when there are too few independent samples', () => {
    const html = occupancyFooterHtml(DRIFT)
    expect(html).toMatch(/⚠/)
    expect(html).toMatch(/2\.6 effectively independent samples/)
  })

  it('omits the warning when sampling is converged', () => {
    expect(occupancyFooterHtml(SWITCHING)).not.toMatch(/⚠/)
  })

  it('names the basis only when it is not the default', () => {
    expect(occupancyFooterHtml({ ...SWITCHING, basis: 'bp' })).toMatch(/base-pair midpoints/)
    expect(occupancyFooterHtml(SWITCHING)).not.toMatch(/base-pair midpoints/)
  })

  it("reports PC1's share so a weak mode is visible", () => {
    expect(occupancyFooterHtml(SWITCHING)).toMatch(/PC1 61% of variance/)
  })

  it('is empty for a not-ready response', () => {
    expect(occupancyFooterHtml({ ready: false })).toBe('')
  })
})

// ── The controller, without a DOM ─────────────────────────────────────────────────
describe('initOccupancyControls', () => {
  async function make(resp, { verdict } = {}) {
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const body = resp ?? { ...SWITCHING, verdict: verdict ?? 'switching' }
    const overlay = { setClusters: vi.fn().mockResolvedValue({ states: 2 }),
                      clear: vi.fn(), defaultColors: vi.fn((n) => Array.from({ length: n }, () => 0xd29922)) }
    const display = { displayOccupancy: vi.fn().mockResolvedValue({ ok: true }) }
    const api = { getOxdnaOccupancy: vi.fn().mockResolvedValue(body) }
    const ctrl = initOccupancyControls({
      api, getOverlay: () => overlay, getDisplay: () => display,
      getSelectedJobId: () => 'job1',
    })
    return { ctrl, overlay, display, api }
  }

  it('moves the model and draws ghosts for a switching ensemble', async () => {
    const { ctrl, overlay, display } = await make()
    const r = await ctrl.refresh()
    expect(r.ok).toBe(true)
    expect(display.displayOccupancy).toHaveBeenCalled()
    expect(overlay.setClusters).toHaveBeenCalled()
  })

  it('draws NO ghosts for a drift — superposing the ends of one path would mislead', async () => {
    const { ctrl, overlay, display } = await make(DRIFT)
    const r = await ctrl.refresh()
    expect(r.verdict).toBe('drift')
    expect(display.displayOccupancy).toHaveBeenCalled()   // the model still shows a real frame
    expect(overlay.setClusters).not.toHaveBeenCalled()
    expect(overlay.clear).toHaveBeenCalled()
  })

  it('draws no ghosts for a unimodal ensemble', async () => {
    const { ctrl, overlay } = await make(UNIMODAL)
    await ctrl.refresh()
    expect(overlay.setClusters).not.toHaveBeenCalled()
  })

  it('caches by parameter set and refetches only when asked', async () => {
    const { ctrl, api } = await make()
    await ctrl.refresh()
    await ctrl.refresh()
    expect(api.getOxdnaOccupancy).toHaveBeenCalledTimes(1)

    await ctrl.refresh({ refetch: true })
    expect(api.getOxdnaOccupancy).toHaveBeenCalledTimes(2)
    expect(api.getOxdnaOccupancy.mock.calls.at(-1)[1].refetch).toBe(true)
  })

  it('off() clears the ghosts and goes inactive', async () => {
    const { ctrl, overlay } = await make()
    await ctrl.refresh()
    ctrl.off()
    expect(overlay.clear).toHaveBeenCalled()
    expect(ctrl.isActive()).toBe(false)
  })

  it('does nothing without a selected job', async () => {
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const api = { getOxdnaOccupancy: vi.fn() }
    const ctrl = initOccupancyControls({ api, getSelectedJobId: () => null })
    expect((await ctrl.refresh()).ok).toBe(false)
    expect(api.getOxdnaOccupancy).not.toHaveBeenCalled()
  })

  it('reports a not-ready response without touching the model', async () => {
    const { ctrl, overlay, display } = await make({ ready: false, reason: 'sampling starting — no frames yet' })
    const r = await ctrl.refresh()
    expect(r.ok).toBe(false)
    expect(display.displayOccupancy).not.toHaveBeenCalled()
    expect(overlay.clear).toHaveBeenCalled()
  })
})

describe('re-toggling after off()', () => {
  it('re-shows the controls on a cached hit instead of returning early', async () => {
    // off() then on() hits the parameter cache; an early return there left the module
    // marked inactive with its parameter row hidden while the view was on screen.
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const overlay = { setClusters: vi.fn().mockResolvedValue({ states: 2 }),
                      clear: vi.fn(), defaultColors: (n) => Array.from({ length: n }, () => 0xd29922) }
    const api = { getOxdnaOccupancy: vi.fn().mockResolvedValue(SWITCHING) }
    const ctrl = initOccupancyControls({
      api, getOverlay: () => overlay, getDisplay: () => ({ displayOccupancy: vi.fn().mockResolvedValue({ ok: true }) }),
      getSelectedJobId: () => 'job1',
    })

    await ctrl.refresh()
    ctrl.off()
    expect(ctrl.isActive()).toBe(false)

    await ctrl.refresh()
    expect(ctrl.isActive()).toBe(true)
    expect(api.getOxdnaOccupancy).toHaveBeenCalledTimes(1)   // still served from cache
  })
})

describe('legend swatches match what is actually drawn', () => {
  async function run(resp, ghostResult) {
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const overlay = {
      setClusters: vi.fn().mockResolvedValue(ghostResult),
      clear: vi.fn(),
      defaultColors: (n) => Array.from({ length: n }, (_, i) => 0x100000 + i),
    }
    const ctrl = initOccupancyControls({
      api: { getOxdnaOccupancy: vi.fn().mockResolvedValue(resp) },
      getOverlay: () => overlay,
      getDisplay: () => ({ displayOccupancy: vi.fn().mockResolvedValue({ ok: true }) }),
      getSelectedJobId: () => 'job1',
    })
    return { ctrl, overlay }
  }

  it('gives a drift NO rows — nothing is drawn for it, so nothing may claim a colour', async () => {
    const { ctrl } = await run(DRIFT, { states: 0 })
    const r = await ctrl.refresh()
    expect(r.states).toBe(0)
  })

  it('reports the state count the overlay actually built', async () => {
    const { ctrl } = await run(SWITCHING, { states: 2 })
    expect((await ctrl.refresh()).states).toBe(2)
  })
})

describe('per-state toggles and colour pickers', () => {
  function mountDom() {
    document.body.innerHTML = `
      <input id="oxdna-jobs-occupancy-toggle" type="radio">
      <div id="oxdna-jobs-occupancy-params"></div>
      <select id="oxdna-jobs-occupancy-n"><option value="0" selected>auto</option><option value="3">3</option></select>
      <select id="oxdna-jobs-occupancy-basis"><option value="nt" selected>nt</option><option value="bp">bp</option></select>
      <button id="oxdna-jobs-occupancy-rerun"></button>
      <div id="oxdna-jobs-occupancy-status"></div>
      <div id="oxdna-jobs-occupancy-legend"></div>`
  }

  async function mount(resp = SWITCHING) {
    mountDom()
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const overlay = {
      setClusters: vi.fn().mockResolvedValue({ states: resp.clusters.length }),
      clear: vi.fn(),
      defaultColors: (n) => Array.from({ length: n }, (_, i) => 0x111111 * (i + 1)),
      setStateVisible: vi.fn(() => true),
      setStateColor: vi.fn(() => true),
    }
    const api = { getOxdnaOccupancy: vi.fn().mockResolvedValue(resp) }
    const ctrl = initOccupancyControls({
      api, getOverlay: () => overlay,
      getDisplay: () => ({ displayOccupancy: vi.fn().mockResolvedValue({ ok: true }) }),
      getSelectedJobId: () => 'job1',
    })
    await ctrl.refresh()
    return { ctrl, overlay, legend: document.getElementById('oxdna-jobs-occupancy-legend') }
  }

  it('renders one row per state into the scrollable box', async () => {
    const { legend } = await mount()
    expect(legend.querySelectorAll('.occ-state-row')).toHaveLength(2)
    expect(legend.style.display).not.toBe('none')
  })

  it('unchecking a row hides that state in the scene', async () => {
    const { overlay, legend } = await mount()
    const box = legend.querySelector('[data-occ-vis="1"]')
    box.checked = false
    box.dispatchEvent(new Event('change', { bubbles: true }))
    expect(overlay.setStateVisible).toHaveBeenCalledWith(1, false)
  })

  it('picking a colour recolours that state', async () => {
    const { overlay, legend } = await mount()
    const picker = legend.querySelector('[data-occ-color="0"]')
    picker.value = '#00ff80'
    picker.dispatchEvent(new Event('change', { bubbles: true }))
    expect(overlay.setStateColor).toHaveBeenCalledWith(0, 0x00ff80)
  })

  it('keeps the user\'s colours and toggles across a refetch of the SAME clustering', async () => {
    const { ctrl, overlay, legend } = await mount()
    legend.querySelector('[data-occ-color="1"]').value = '#abcdef'
    legend.querySelector('[data-occ-color="1"]').dispatchEvent(new Event('change', { bubbles: true }))
    const box = legend.querySelector('[data-occ-vis="0"]')
    box.checked = false
    box.dispatchEvent(new Event('change', { bubbles: true }))

    overlay.setClusters.mockClear()
    await ctrl.refresh({ refetch: true })

    const opts = overlay.setClusters.mock.calls.at(-1)[1]
    expect(opts.colors[1]).toBe(0xabcdef)
    expect(opts.visible[0]).toBe(false)
  })

  it('drops those choices when the CLUSTERING changes — state 3 becomes a different shape', async () => {
    const { ctrl, overlay, legend } = await mount()
    legend.querySelector('[data-occ-color="1"]').value = '#abcdef'
    legend.querySelector('[data-occ-color="1"]').dispatchEvent(new Event('change', { bubbles: true }))

    document.getElementById('oxdna-jobs-occupancy-n').value = '3'
    document.getElementById('oxdna-jobs-occupancy-n').dispatchEvent(new Event('change', { bubbles: true }))
    await new Promise((r) => setTimeout(r, 0))

    const opts = overlay.setClusters.mock.calls.at(-1)[1]
    expect(opts.colors[1]).not.toBe(0xabcdef)
  })

  it('off() forgets the per-state choices', async () => {
    const { ctrl, overlay, legend } = await mount()
    legend.querySelector('[data-occ-color="0"]').value = '#010203'
    legend.querySelector('[data-occ-color="0"]').dispatchEvent(new Event('change', { bubbles: true }))
    ctrl.off()

    overlay.setClusters.mockClear()
    await ctrl.refresh()
    expect(overlay.setClusters.mock.calls.at(-1)[1].colors[0]).not.toBe(0x010203)
  })

  it('renders no rows for a drift, so nothing offers a toggle for an undrawn state', async () => {
    const { legend } = await mount(DRIFT)
    expect(legend.querySelectorAll('.occ-state-row')).toHaveLength(0)
    expect(legend.innerHTML).toMatch(/⚠/)
  })
})

describe('state rows survive a narrow panel', () => {
  it('does not clip the per-state stats with nowrap', () => {
    // The panel is ~250px; nowrap silently hid "· N nm from state 1 · N visits" off the
    // right edge, which is where the comparison between states actually lives.
    const html = occupancyStateRowsHtml(SWITCHING, [0xd29922, 0xa371f7], [true, true])
    expect(html).not.toMatch(/white-space:nowrap/)
    expect(html).toMatch(/0\.93 nm from state 1/)
  })

  it('keeps the checkbox and colour picker from being squeezed by the text', () => {
    const html = occupancyStateRowsHtml(SWITCHING, [0xd29922, 0xa371f7], [true, true])
    expect((html.match(/flex:none/g) ?? []).length).toBe(4)   // 2 controls x 2 states
  })
})

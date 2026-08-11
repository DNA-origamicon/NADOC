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

  it('defaults the fit frame to fit-on-selection and rejects anything else', () => {
    // A scoped run left in the whole-structure fit clusters on where the region WAS.
    expect(normalizeOccupancyParams().fit).toBe('selection')
    expect(normalizeOccupancyParams({ fit: 'local' }).fit).toBe('local')
    expect(normalizeOccupancyParams({ fit: 'global' }).fit).toBe('global')
    expect(normalizeOccupancyParams({ fit: 'junction' }).fit).toBe('selection')
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

  // The fit frame is the difference between "what shape did this region take" and "where
  // did it sit" — invisible in the picture, so it has to be in the footer.
  it('names the fit frame for a scoped run and stays silent for an unscoped one', () => {
    expect(occupancyFooterHtml(SWITCHING)).not.toMatch(/fitted on/)
    const scoped = { ...SWITCHING, scoped: true, fit: 'selection', n_fit_points: 48 }
    expect(occupancyFooterHtml(scoped)).toMatch(/fitted on the selection \(48 points\)/)
    expect(occupancyFooterHtml({ ...scoped, fit: 'local', n_fit_points: 28 }))
      .toMatch(/junction frame \(28 duplex points\)/)
  })

  it('surfaces a DEGRADED fit rather than reporting the mode that was asked for', () => {
    const html = occupancyFooterHtml({
      ...SWITCHING, scoped: true, fit: 'selection', fit_requested: 'local', n_fit_points: 6,
      fit_note: 'no crossover extra bases in the selection — a junction frame is undefined',
    })
    expect(html).toMatch(/junction frame is undefined/)
  })
})

describe('occupancyFitLabel', () => {
  it('is empty unless the run was scoped', async () => {
    const { occupancyFitLabel } = await import('./occupancy_controls.js')
    expect(occupancyFitLabel({ fit: 'local', scoped: false })).toBe('')
    expect(occupancyFitLabel(null)).toBe('')
    expect(occupancyFitLabel({ scoped: true, fit: 'global' })).toBe('whole-structure frame')
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

  it('tears down a cached display that finishes after off()', async () => {
    let finishDisplay
    const { ctrl, display, overlay } = await make()
    await ctrl.refresh() // seed the response cache
    display.displayOccupancy.mockImplementationOnce(() => new Promise(resolve => {
      finishDisplay = () => resolve({ ok: true })
    }))
    display.stopAndRestore = vi.fn()

    const late = ctrl.refresh()
    ctrl.off()
    finishDisplay()

    await expect(late).resolves.toMatchObject({ ok: false, reason: 'superseded' })
    expect(display.stopAndRestore).toHaveBeenCalled()
    expect(overlay.clear).toHaveBeenCalled()
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

describe('scope: whole structure vs specific elements', () => {
  function mountScopeDom() {
    document.body.innerHTML = `
      <input id="oxdna-jobs-occupancy-toggle" type="radio">
      <div id="oxdna-jobs-occupancy-params"></div>
      <select id="oxdna-jobs-occupancy-n"><option value="0" selected>auto</option></select>
      <select id="oxdna-jobs-occupancy-basis"><option value="nt" selected>nt</option></select>
      <select id="oxdna-jobs-occupancy-scope">
        <option value="all" selected>Whole structure</option>
        <option value="selection">Specific elements</option>
      </select>
      <div id="oxdna-occupancy-scope-card">
        <div id="oxdna-occupancy-scope-toggle"></div>
        <div id="oxdna-occupancy-scope-body">
      <button id="oxdna-occupancy-scope-add"></button>
      <button id="oxdna-occupancy-scope-clear"></button>
      <div id="oxdna-occupancy-scope-list"></div>
      <input id="oxdna-occupancy-scope-glow" type="checkbox" checked>
      <div id="oxdna-occupancy-scope-status"></div>
        </div>
      </div>
      <button id="oxdna-jobs-occupancy-rerun"></button>
      <div id="oxdna-jobs-occupancy-status"></div>
      <div id="oxdna-jobs-occupancy-legend"></div>`
  }

  async function mount(selectionState = null) {
    mountScopeDom()
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const overlay = {
      setClusters: vi.fn().mockResolvedValue({ states: 2 }), clear: vi.fn(),
      defaultColors: (n) => Array.from({ length: n }, () => 0xd29922),
      setStateVisible: vi.fn(), setStateColor: vi.fn(),
    }
    const api = {
      getOxdnaOccupancy: vi.fn().mockResolvedValue(SWITCHING),
      postOxdnaOccupancy: vi.fn().mockResolvedValue({ ...SWITCHING, scoped: true }),
    }
    const ctrl = initOccupancyControls({
      api, getOverlay: () => overlay,
      getDisplay: () => ({ displayOccupancy: vi.fn().mockResolvedValue({ ok: true }) }),
      getSelectedJobId: () => 'job1',
      getAnchorSelection: () => selectionState,
    })
    return { ctrl, api, overlay }
  }

  const setScope = (v) => {
    const el = document.getElementById('oxdna-jobs-occupancy-scope')
    el.value = v
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  it('uses the plain GET for the whole structure', async () => {
    const { ctrl, api } = await mount()
    await ctrl.refresh()
    expect(api.getOxdnaOccupancy).toHaveBeenCalled()
    expect(api.postOxdnaOccupancy).not.toHaveBeenCalled()
  })

  it('uses nucleotide coordinates when the scope contains crossover extra bases', async () => {
    const { ctrl, api } = await mount({
      currentDesign: { helices: [], crossovers: [{ id: 'xo1' }, { id: 'xo2' }] },
      multiSelectedBaseKeys: ['__xb__:xo1:0', '__xb__:xo2:0'],
    })
    document.getElementById('oxdna-jobs-occupancy-basis').innerHTML =
      '<option value="bp" selected>bp</option><option value="nt">nt</option>'
    setScope('selection')
    document.getElementById('oxdna-occupancy-scope-add').click()
    await ctrl.refresh()

    expect(api.postOxdnaOccupancy).toHaveBeenCalled()
    expect(api.postOxdnaOccupancy.mock.calls.at(-1)[1]).toMatchObject({
      basis: 'nt',
      selection: { extra_bases: [['xo1', 0], ['xo2', 0]] },
    })
  })

  it('keeps occupancy options visible when the visualization is off', async () => {
    const { ctrl } = await mount()
    const params = document.getElementById('oxdna-jobs-occupancy-params')
    params.style.display = 'block'
    ctrl.off()
    expect(params.style.display).toBe('block')
  })

  it('keeps the selected scope options visible when the visualization is off', async () => {
    const { ctrl } = await mount()
    setScope('selection')
    ctrl.off()
    expect(document.getElementById('oxdna-occupancy-scope-card').style.display).not.toBe('none')
  })

  it('does not report an intentionally superseded scope request as failed', async () => {
    const { ctrl, api } = await mount()
    let finishFirst
    api.getOxdnaOccupancy
      .mockImplementationOnce((_id, { signal }) => new Promise((resolve) => {
        finishFirst = () => resolve(signal.aborted ? null : SWITCHING)
      }))
      .mockResolvedValueOnce(SWITCHING)

    const first = ctrl.refresh()
    const second = ctrl.refresh({ refetch: true })
    finishFirst()
    await Promise.all([first, second])

    expect(document.getElementById('oxdna-jobs-occupancy-status').textContent)
      .not.toMatch(/request failed/i)
  })

  it('shows the scope card only when specific elements are chosen', async () => {
    await mount()
    const card = document.getElementById('oxdna-occupancy-scope-card')
    expect(card.style.display).toBe('none')
    setScope('selection')
    expect(card.style.display).not.toBe('none')
    setScope('all')
    expect(card.style.display).toBe('none')
  })

  it('refuses to run with an empty scope, and says what to do', async () => {
    // Silently clustering the whole structure here would answer a different question
    // from the one the user asked.
    const { ctrl, api, overlay } = await mount()
    setScope('selection')
    const r = await ctrl.refresh()
    expect(r.ok).toBe(false)
    expect(r.reason).toBe('empty scope')
    expect(api.postOxdnaOccupancy).not.toHaveBeenCalled()
    expect(api.getOxdnaOccupancy).not.toHaveBeenCalled()
    expect(overlay.clear).toHaveBeenCalled()
    expect(document.getElementById('oxdna-jobs-occupancy-status').textContent)
      .toMatch(/Add selection to scope/)
  })

  it('POSTs the resolved selection once elements are picked', async () => {
    const { ctrl, api } = await mount({
      selectedObject: { type: 'cluster', id: 'c1' },
      multiSelectedClusterIds: [], multiSelectedStrandIds: [],
      multiSelectedDomainIds: [], multiSelectedOverhangIds: [], ctrlBeadNucs: [],
    })
    setScope('selection')
    document.getElementById('oxdna-occupancy-scope-add').click()
    await new Promise((r) => setTimeout(r, 0))
    await ctrl.refresh()

    expect(api.postOxdnaOccupancy).toHaveBeenCalled()
    expect(api.postOxdnaOccupancy.mock.calls.at(-1)[1].selection.cluster_ids).toEqual(['c1'])
  })

  it('a different scope is a different analysis — it must not reuse the cache', async () => {
    const { ctrl, api } = await mount({
      selectedObject: { type: 'cluster', id: 'c1' },
      multiSelectedClusterIds: [], multiSelectedStrandIds: [],
      multiSelectedDomainIds: [], multiSelectedOverhangIds: [], ctrlBeadNucs: [],
    })
    await ctrl.refresh()                       // whole structure → GET
    setScope('selection')
    document.getElementById('oxdna-occupancy-scope-add').click()
    await new Promise((r) => setTimeout(r, 0))  // adding auto-refreshes; let it settle
    await ctrl.refresh()                       // scoped → served from the scoped cache

    expect(api.getOxdnaOccupancy).toHaveBeenCalledTimes(1)
    expect(api.postOxdnaOccupancy).toHaveBeenCalledTimes(1)
  })

  it('exposes the shared anchor widget so the panel can clear it', async () => {
    const { ctrl } = await mount()
    expect(typeof ctrl.scope().getAnchors).toBe('function')
    expect(typeof ctrl.scope().clear).toBe('function')
  })
})

describe('one card per engine, one overlay', () => {
  it('derives every id from an engine prefix', async () => {
    const { occupancyIds } = await import('./occupancy_controls.js')
    expect(occupancyIds('oxdna').toggle).toBe('oxdna-jobs-occupancy-toggle')
    expect(occupancyIds('md').toggle).toBe('md-jobs-occupancy-toggle')
    expect(occupancyIds('md').scope.list).toBe('md-occupancy-scope-list')
    // The two engines must not collide on a single id, or one card would drive the other.
    const a = JSON.stringify(occupancyIds('oxdna'))
    const b = JSON.stringify(occupancyIds('md'))
    expect(a).not.toBe(b)
  })

  it('uses the injected fetch instead of branching on the engine', async () => {
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const fetchOccupancy = vi.fn().mockResolvedValue(UNIMODAL)
    const ctrl = initOccupancyControls({
      api: {}, engine: 'md', fetchOccupancy,
      getOverlay: () => ({ clear: vi.fn(), setClusters: vi.fn(), defaultColors: () => [] }),
      getDisplay: () => ({ displayOccupancy: vi.fn().mockResolvedValue({ ok: true }) }),
      getSelectedJobId: () => 'J1',
    })
    await ctrl.refresh()
    expect(fetchOccupancy).toHaveBeenCalled()
    expect(fetchOccupancy.mock.calls[0][0]).toMatchObject({ jobId: 'J1' })
  })

  it('main.js unions BOTH scope channels into the anchor halo', async () => {
    // The scope pickers are not engine tabs, so neither is ever `getSelected()`; the halo
    // has to name each channel explicitly. Listing only `occupancy` left the NAMD card
    // with chips but nothing lit in the 3D view — you could not see what you had picked.
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const MAIN = readFileSync(resolve(process.cwd(), 'src/main.js'), 'utf8')
    const i = MAIN.indexOf('_refreshAnchorGlow = ')
    const block = MAIN.slice(i, i + 900)
    expect(block).toMatch(/_anchorsByEngine\.occupancy/)
    expect(block).toMatch(/_anchorsByEngine\['md-occupancy'\]/)
  })

  it('a second engine claiming the overlay stands the first one down', async () => {
    // Both cards share ONE overlay; two active cards would leave the loser's list
    // describing states no longer on screen.
    const { initOccupancyControls } = await import('./occupancy_controls.js')
    const mk = (engine) => initOccupancyControls({
      api: {}, engine,
      fetchOccupancy: vi.fn().mockResolvedValue(UNIMODAL),
      getOverlay: () => ({ clear: vi.fn(), setClusters: vi.fn(), defaultColors: () => [] }),
      getDisplay: () => ({ displayOccupancy: vi.fn().mockResolvedValue({ ok: true }) }),
      getSelectedJobId: () => 'J1',
    })
    const oxdna = mk('oxdna')
    const md = mk('md')

    await oxdna.refresh()
    expect(oxdna.isActive()).toBe(true)

    await md.refresh()
    expect(md.isActive()).toBe(true)
    expect(oxdna.isActive(), 'the oxDNA card stood down').toBe(false)
  })
})

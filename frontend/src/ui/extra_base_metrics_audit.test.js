import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  initExtraBaseMetricsAudit,
  cpdMarkup,
  populationRows,
  renderExtraBaseMetricsAudit,
  sampleAuditMarkup,
  stableWindowCoverage,
  stateCloudSvg,
} from './extra_base_metrics_audit.js'

const bundle = {
  metric_panels: { hop_position: 'Hop position', pose_orientation: 'Pose / orientation', environment: 'Environment' },
  sources: [{ part: '2hb_0-1xT', role: 'asymmetric-single-long', n_frames: 100000,
    job: '/archive/job', topology_pass: true, cpd_reference: { production_ns: 161.8, n_frames: 1619,
      d_mid_A: { mean: 11.39, sd: 1.38, min: 7.44, max: 17.97 }, eta_deg: { mean: 31.5, sd: 95.6 },
      reactive_corner: { n: 0, total: 1619, d_max_A: 4.5 }, n_below_8A: 10, n_below_6A: 0, provenance: 'measured' },
    inserts: [{ crossover_id: 'abcdefgh-1', insert_k: 0,
      base: 'T', n_samples: 100, n_valid: 80, valid_fraction: .8, n_stable_samples: 60,
      stable_windows: [{ frame_start: 0, frame_stop: 59, n_samples: 60 }],
      state_cloud: { points: [[.5, -.3, 0, 1], [.7, -.1, 1, 2]] },
      failure_counts: { global_pairing: 20 }, panel_agreement_ari: { hop_position__pose_orientation: .7 },
      panels: { hop_position: { ready: true, verdict: 'switching', k: 2, silhouette: .4,
        transitions: 8, metrics: ['t_c1'], confidence: { preliminary: false },
        clusters: [{ population: .7, population_sem: .05, visits: 5, n_eff: 40 }] },
      pose_orientation: { ready: true, verdict: 'unimodal', k: 1, clusters: [] },
      environment: { ready: false, reason: 'insufficient' } } }] }],
}

beforeEach(() => { document.body.innerHTML = '<button id="menu-help-extra-base-metrics-audit"></button>' })

describe('extra-base metrics helpers', () => {
  it('reports stable coverage and publication status', () => {
    const insert = bundle.sources[0].inserts[0]
    expect(stableWindowCoverage(insert)).toBe(.6)
    expect(populationRows(insert.panels.hop_position)[0]).toMatchObject({ population: .7, publishable: true })
  })

  it('renders metrics, populations, windows and failures', () => {
    const root = document.createElement('div')
    renderExtraBaseMetricsAudit(root, bundle)
    expect(root.textContent).toContain('70.0% ± 5.0%')
    expect(root.textContent).toContain('global_pairing: 20')
    expect(root.textContent).toContain('Cross-metric ARI')
    expect(root.textContent).toContain('CPD weld-pair reaction coordinates')
    expect(root.querySelector('.xbma-state-cloud')).not.toBeNull()
    expect(root.querySelectorAll('.xbma-panel')).toHaveLength(3)
  })

  it('draws occupancy points and CPD reaction coordinate evidence', () => {
    expect(stateCloudSvg({ points: [[.5, -.3, 0, 1]] })).toContain('<circle')
    expect(cpdMarkup(bundle.sources[0].cpd_reference)).toContain('Reactive corner 0/1619')
  })

  it('renders real sampled-pair readouts and viewer mounts', () => {
    const sampled = {
      sample_index: 7, frame: 154, groups: [{ reciprocal_pair: true,
        directed_normal_separation_deg: 121.2,
        records: [{ side: 'i', crossover_id: 'abcdefgh-1', insert_k: 0, base: 'T',
          quality: { pose_rmsd_A: .4, source_pair_distance_A: 10, destination_pair_distance_A: 10.2 } }] }],
    }
    const markup = sampleAuditMarkup(sampled)
    expect(markup).toContain('121.2° directed-normal separation')
    expect(markup).toContain('DCD frame 154')
    expect(markup).toContain('pose RMSD 0.40 Å')
    expect(markup).toContain('arrows = directed slab normals')
  })

  it('uses one aligned i/i+1 panel and switches both medoids', () => {
    const setClusters = vi.fn()
    const setComparisonRepresentation = vi.fn()
    const comparisonViewerFactory = vi.fn(() => ({ setClusters, setRepresentation: setComparisonRepresentation, dispose: vi.fn() }))
    const side = (name, label) => ({
      side: name, label, ready: true, n_observations: 1000, n_fit_samples: 500,
      n_crossovers: 20, n_junctions: 20, k: 2, silhouette: .55,
      clusters: [
        { population: .75, n_crossovers: 18, center_A: [1, 2, 3], spread_A: 2,
          medoid: { frame: 100, crossover_id: 'abcdefgh-1', interhelix_A: 25, atoms_A: { "C1'": [1, 2, 3] }, atomistic: { fit_rmsd_A: .4, atoms: [] } } },
        { population: .25, n_crossovers: 9, center_A: [4, 5, 6], spread_A: 1,
          medoid: { frame: 200, crossover_id: 'ijklmnop-2', interhelix_A: 26, atoms_A: { "C1'": [4, 5, 6] }, atomistic: { fit_rmsd_A: .5, atoms: [] } } },
      ],
    })
    const pooledBundle = { metric_panels: bundle.metric_panels, sources: [{
      ...bundle.sources[0], inserts: [], pooled_positions: { ready: true,
        classification: 'lower reciprocal bp level = i/left; higher = i+1/right',
        n_unpaired_inserts: 2, max_fit_samples_per_side: 500,
        sides: [side('i', 'Left crossover · i'), side('i+1', 'Right crossover · i+1')] },
    }] }
    const root = document.createElement('div')
    const viewers = renderExtraBaseMetricsAudit(root, pooledBundle, { comparisonViewerFactory })
    expect(root.querySelectorAll('.xbma-pool-side')).toHaveLength(0)
    expect(root.textContent).toContain('1,000 stable positions')
    expect(root.textContent).not.toContain('Cross-metric ARI')
    expect(comparisonViewerFactory).toHaveBeenCalledTimes(1)
    expect(viewers).toHaveLength(1)
    expect(root.querySelector('[data-comparison-panel]')).not.toBeNull()
    expect(root.querySelector('.xbma-comparison-readout').textContent).toContain('Aligned C1′ separation')
    const compareSide = root.querySelector('[data-comparison-side="i+1"]')
    compareSide.value = '1'; compareSide.dispatchEvent(new Event('change'))
    expect(setClusters).toHaveBeenCalledWith({ i: 0, 'i+1': 1 })
    root.querySelector('[data-comparison-representation="atomistic"]').click()
    expect(setComparisonRepresentation).toHaveBeenCalledWith('atomistic')
  })
})

describe('Extra-Base Metrics Audit toggle', () => {
  it('opens from Help, switches metric focus, and closes cleanly', async () => {
    const setMenuToggle = vi.fn()
    const audit = initExtraBaseMetricsAudit({ setMenuToggle, fetchAudit: async () => bundle })
    document.getElementById('menu-help-extra-base-metrics-audit').click()
    await Promise.resolve(); await Promise.resolve()
    expect(audit.modal.classList.contains('visible')).toBe(true)
    const toggle = audit.modal.querySelector('[data-panel-toggle="environment"]')
    toggle.click()
    expect(audit.modal.querySelector('[data-metric-panel="environment"]').hidden).toBe(true)
    audit.modal.querySelector('.xbma-extra-only').click()
    expect(audit.modal.querySelector('.xbma-body').classList.contains('show-context')).toBe(true)
    audit.modal.querySelector('.xbma-close').click()
    expect(setMenuToggle).toHaveBeenLastCalledWith('menu-help-extra-base-metrics-audit', false)
  })

  it('loads a source catalog, suggested frame, selected crossover and 3D sample feed', async () => {
    const sourceBundle = structuredClone(bundle)
    sourceBundle.sources[0].source_id = 'fixture__trajectory'
    const catalog = {
      source_id: 'fixture__trajectory', n_samples: 2, frames: [100, 120],
      crossovers: [
        { crossover_id: 'abcdefgh-1', side: 'i', bp_level: 10, bases: ['T'] },
        { crossover_id: 'ijklmnop-2', side: 'i+1', bp_level: 11, bases: ['T'] },
      ],
      suggestions: [{ label: 'Left · cluster 1 medoid', sample_index: 1, frame: 120,
        crossover_ids: ['abcdefgh-1'] }],
    }
    const sampleResponse = {
      sample_index: 1, frame: 120, groups: [{ reciprocal_pair: true,
        directed_normal_separation_deg: 120,
        records: [{ side: 'i', crossover_id: 'abcdefgh-1', insert_k: 0, base: 'T', quality: {} }] }],
    }
    const fetchSamples = vi.fn(async () => sampleResponse)
    const viewer = { setRepresentation: vi.fn(), resetView: vi.fn(), dispose: vi.fn() }
    const sampleViewerFactory = vi.fn(() => viewer)
    const audit = initExtraBaseMetricsAudit({
      fetchAudit: async () => sourceBundle,
      fetchSampleCatalog: async () => catalog,
      fetchSamples,
      sampleViewerFactory,
    })
    document.getElementById('menu-help-extra-base-metrics-audit').click()
    await vi.waitFor(() => expect(fetchSamples).toHaveBeenCalled())
    expect(fetchSamples.mock.calls[0][0]).toMatchObject({
      source_id: 'fixture__trajectory', crossover_ids: ['abcdefgh-1'], sample_index: 1,
      include_reciprocal_partners: true,
    })
    expect(sampleViewerFactory).toHaveBeenCalledTimes(1)
    expect(audit.modal.querySelector('.xbma-sample-status').textContent).toContain('DCD frame 120')
    const exactFrame = audit.modal.querySelector('.xbma-sample-dcd-frame')
    exactFrame.value = '101'; exactFrame.dispatchEvent(new Event('change'))
    expect(audit.modal.querySelector('.xbma-sample-frame').value).toBe('0')
    expect(exactFrame.value).toBe('100')
    audit.modal.querySelector('[data-sample-representation="schematic"]').click()
    expect(viewer.setRepresentation).toHaveBeenLastCalledWith('schematic')
    audit.modal.querySelector('.xbma-sample-reset').click()
    expect(viewer.resetView).toHaveBeenCalled()
    audit.close()
    expect(viewer.dispose).toHaveBeenCalled()
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  initExtraBaseMetricsAudit,
  cpdMarkup,
  populationRows,
  renderExtraBaseMetricsAudit,
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
})

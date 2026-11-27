// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { fitTorsionalStiffness, initOxdnaTorque, initTorqueMetrics } from './oxdna_torsion.js'
import { torqueSelectionCenter } from '../scene/torque_selection_center.js'

it('edits the selected job with synchronized numerical and viewport axis controls', () => {
  document.body.innerHTML = '<details id="torque" open></details>'
  const mount = document.querySelector('#torque')
  const gizmo = { show: vi.fn(), select: vi.fn(), setPose: vi.fn(), setOnChange: vi.fn() }
  const onChange = vi.fn()
  const panel = initOxdnaTorque({ mount, gizmo, onChange,
    getDefaultCenter: () => [1, 2, 3], getSelectionCenter: () => [4, 5, 6],
  })
  panel.apply({ job_id: 'queued', run_config: {} }, true)
  mount.querySelector('[type=checkbox]').click()
  const x = mount.querySelector('[aria-label="Axis position X"]')
  expect(x.valueAsNumber).toBe(1)
  x.value = '9'
  x.dispatchEvent(new Event('input'))
  expect(gizmo.setPose).toHaveBeenLastCalledWith({
    kind: 'pose', position_nm: [9, 2, 3], rotation_deg: [0, 0, 0],
  })
  gizmo.setOnChange.mock.calls[0][0]({ kind: 'pose', position_nm: [7, 8, 9], rotation_deg: [23, 0, 0] })
  expect(x.valueAsNumber).toBe(7)
  expect(mount.querySelector('[aria-label="Axis rotation X"]').valueAsNumber).toBe(23)
  ;[...mount.querySelectorAll('button')].find(node => node.textContent === 'Center on Selection').click()
  expect(panel.settings()).toMatchObject({ drive: [], axis: { position_nm: [4, 5, 6], rotation_deg: [23, 0, 0] } })
  expect(onChange).toHaveBeenCalledTimes(4)
  expect(mount.querySelector('.oxdna-torsion-coordinates').open).toBe(false)
  expect(mount.textContent).not.toMatch(/Queue test|Fixed grip|Measure torque/)
})

it('centers a selected domain on the helical axis rather than on the backbone', () => {
  const state = { selection: { items: [{ kind: 'domain', strandId: 'strand', domainIndex: 0 }] },
    currentGeometry: [0, 4].map(z => ({ strand_id: 'strand', domain_index: 0, helix_id: 'helix',
      backbone_position: [2, 1, z], helical_site: { axis_point: [1, 1, z] } })),
  }
  expect(torqueSelectionCenter(state)).toEqual([1, 1, 2])
  state.currentGeometry = [[0, 0, 0], [1, 1, 0], [2, 0, 0]].map((point, i) => ({
    strand_id: 'strand', domain_index: 0, helix_id: 'helix', bp_index: i,
    backbone_position: [2, 1, i], helical_site: { axis_point: point },
  }))
  expect(torqueSelectionCenter(state)).toEqual([1, 1, 0])
})

it('restores arrow size and keeps the axis visible while another open sidebar has focus', () => {
  document.body.innerHTML = '<details id="torque" open></details>'
  const mount = document.querySelector('#torque')
  const gizmo = { show: vi.fn(), select: vi.fn(), setPose: vi.fn(), setOnChange: vi.fn(), setSize: vi.fn() }
  const onChange = vi.fn()
  const panel = initOxdnaTorque({ mount, gizmo, onChange })
  const torsion = { axis: { kind: 'pose', position_nm: [1, 2, 3], rotation_deg: [0, 0, 0] } }
  panel.apply({ job_id: 'queued', run_config: { torsion, torque_arrow_size: 150 } }, true)
  const slider = mount.querySelector('input[type=range]')
  expect(slider.valueAsNumber).toBe(150)
  expect(gizmo.setSize).toHaveBeenLastCalledWith(150)
  slider.value = '210'
  slider.dispatchEvent(new Event('input'))
  expect(gizmo.setSize).toHaveBeenLastCalledWith(210)
  expect(gizmo.select).toHaveBeenCalled()
  expect(panel.arrowSize()).toBe(210)
  expect(onChange).toHaveBeenCalledOnce()
  const navigate = openPanels => window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', {
    detail: { activeTab: 'scene', openPanels, navigationOnly: true },
  }))
  navigate(['scene', 'dynamics'])
  expect(gizmo.show).toHaveBeenLastCalledWith(true)
  navigate(['scene'])
  expect(gizmo.show).toHaveBeenLastCalledWith(false)
})

it('gives each helix equal weight when centering on a bundle', () => {
  const helixIds = ['h0', 'h1', 'h2', 'h3', 'h4', 'h5']
  const geometry = helixIds.flatMap((helix_id, i) => Array.from({ length: i + 1 }, () => ({
    helix_id, backbone_position: [i, 2, 0], helical_site: { axis_point: [i, 0, 0] },
  })))
  expect(torqueSelectionCenter({
    selection: { items: [{ kind: 'cluster', id: 'shaft' }] },
    currentDesign: { cluster_transforms: [{ id: 'shaft', helix_ids: helixIds }] },
    currentGeometry: geometry,
  })).toEqual([2.5, 0, 0])
})

it('makes the generated torque export available in Graphs and Metrics', async () => {
  document.body.innerHTML = '<div id="metrics"><button data-torque-generate>Generate</button><button data-torque-display>Display</button><button data-torque-export>Export</button><p role="status"></p><div data-torque-output></div></div>'
  const mount = document.querySelector('#metrics')
  let job = { job_id: 'j', status: 'completed', run_config: { torsion: {} } }
  const result = vi.fn(async () => ({ rows: [{}] }))
  const panel = initTorqueMetrics({ mount, getJob: () => job, result })
  const exportButton = mount.querySelector('[data-torque-export]')
  expect(exportButton.disabled).toBe(true)
  mount.querySelector('[data-torque-generate]').click()
  await vi.waitFor(() => expect(exportButton.disabled).toBe(false))
  expect(result).toHaveBeenCalledWith('j')
  job = { job_id: 'other' }
  panel.refresh()
  expect(mount.hidden).toBe(true)
})

it('fits the specimen reaction in pN nm per radian over the selected twist interval', () => {
  const points = [0, 1, 2, 3].map(twist_deg => ({ twist_deg, clamp_reaction_pn_nm: 6 + twist_deg * Math.PI / 180 * 120 }))
  points.push({ twist_deg: 5, clamp_reaction_pn_nm: 99 })
  const fit = fitTorsionalStiffness(points, 0, 3)
  expect(fit.slope).toBeCloseTo(120)
  expect(fit.r2).toBeCloseTo(1)
  expect(fitTorsionalStiffness(points, 1, 2)).toBeNull()
})

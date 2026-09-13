import { describe, expect, it, vi } from 'vitest'
vi.mock('./metric_graph.js', () => ({ buildChartSpec: value => value, drawChart: vi.fn(), SERIES_COLORS: ['blue'] }))
import { drawChart } from './metric_graph.js'
import { ionTransportSeries, openIonTransportPopup } from './ion_transport_popup.js'

describe('ionTransportSeries', () => {
  it('maps current and aperture crossings onto simulation time', () => {
    const series = ionTransportSeries({ series: {
      time_ns: [0.1, 0.2],
      current_nA: { total: [1, 2], 'Na+': [0.4, 0.5] },
      cumulative_crossings: { 'Na+': { net: [0, 1] } },
    } })
    expect(series.current[0].points).toEqual([[0.1, 1], [0.2, 2]])
    expect(series.crossings[0].points).toEqual([[0.1, 0], [0.2, 1]])
  })

  it('omits species that are not present in the simulated system', () => {
    const series = ionTransportSeries({
      species: { 'Na+': { n_ions: 12 }, 'Cl-': { n_ions: 10 }, 'Mg2+': { n_ions: 0 } },
      series: {
        time_ns: [0.1, 0.2],
        current_nA: { 'Na+': [1, 2], 'Cl-': [-1, -2], 'Mg2+': [0, 0], total: [0, 0] },
        cumulative_crossings: {
          'Na+': { net: [0, 1] }, 'Cl-': { net: [0, -1] }, 'Mg2+': { net: [0, 0] },
        },
      },
    })
    expect(series.current.map(item => item.label)).toEqual(['Na+', 'Cl-', 'total'])
    expect(series.crossings.map(item => item.label)).toEqual(['Na+ net', 'Cl- net'])
  })

  it('orders restart pieces chronologically and rebases cumulative counters', () => {
    // Legacy analysis concatenated cont1/cont2 before the base DCD, producing the
    // backwards 12 -> 0 ns jump visible as two apparent lines in the chart.
    const series = ionTransportSeries({ series: {
      time_ns: [6, 8, 10, 12, 0, 2, 4],
      current_nA: { 'Na+': [6, 8, 10, 12, 0, 2, 4] },
      cumulative_crossings: { 'Na+': { net: [0, 1, 2, 3, 3, 4, 5] } },
    } })
    expect(series.current[0].points.map(([time]) => time)).toEqual([0, 2, 4, 6, 8, 10, 12])
    expect(series.crossings[0].points).toEqual([
      [0, 0], [2, 1], [4, 2], [6, 2], [8, 3], [10, 4], [12, 5],
    ])
  })
})


it('reports data preparation and each plot separately before completing', async () => {
  const updates = []
  await openIonTransportPopup({ series: {} }, { onProgress: value => updates.push(value) })
  expect(updates.map(value => `${value.stage}:${value.done}`)).toEqual([
    'plot-series:0', 'plot-series:1', 'plot-current:0', 'plot-current:1',
    'plot-crossings:0', 'plot-crossings:1',
  ])
  expect(drawChart).toHaveBeenCalledTimes(2)
  expect(document.querySelector('[data-ion-transport-stage="plot-crossings"]').dataset.state).toBe('done')
  document.querySelector('[data-close]').click()
})

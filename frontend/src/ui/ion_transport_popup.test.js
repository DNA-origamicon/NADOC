import { describe, expect, it } from 'vitest'
import { ionTransportSeries } from './ion_transport_popup.js'

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
})

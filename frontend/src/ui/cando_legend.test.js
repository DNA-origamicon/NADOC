import { describe, it, expect, beforeEach } from 'vitest'
import {
  legendLabels, gradientCss, legendConfig, initCandoLegend,
} from './cando_legend.js'
import { viridisHex, deviationHex } from './cando_display.js'

describe('legendLabels', () => {
  it('formats finite bounds to fixed decimals', () => {
    expect(legendLabels(0.5, 1.37)).toEqual({ min: '0.50', max: '1.37' })
    expect(legendLabels(0, 5)).toEqual({ min: '0.00', max: '5.00' })
  })
  it('shows an em-dash for non-finite bounds', () => {
    expect(legendLabels(undefined, NaN)).toEqual({ min: '—', max: '—' })
    expect(legendLabels(1, Infinity)).toEqual({ min: '1.00', max: '—' })
  })
})

describe('gradientCss', () => {
  it('samples the ramp bottom→top with the low colour first (t=0)', () => {
    const css = gradientCss(viridisHex, 5)
    expect(css.startsWith('linear-gradient(to top, ')).toBe(true)
    // t=0 → viridis dark purple (#440154); t=1 → yellow (#fde725)
    const first = '#' + (viridisHex(0) & 0xffffff).toString(16).padStart(6, '0')
    const last = '#' + (viridisHex(1) & 0xffffff).toString(16).padStart(6, '0')
    expect(css).toContain(first)
    expect(css).toContain(last)
    expect(css.indexOf(first)).toBeLessThan(css.indexOf(last))
  })
})

describe('legendConfig', () => {
  it('returns a titled gradient for the colour-mapped modes', () => {
    const flex = legendConfig('flex')
    expect(flex.title).toBe('RMSF (nm)')
    expect(flex.gradient).toBe(gradientCss(viridisHex))
    const dev = legendConfig('deviation')
    expect(dev.title).toBe('Deviation (nm)')
    expect(dev.gradient).toBe(gradientCss(deviationHex))
  })
  it('gives the CanDo-cylinder output an RMSF jet legend (distinct from the flex viridis)', () => {
    const cando = legendConfig('cando')
    expect(cando.title).toBe('RMSF (nm)')
    expect(cando.gradient.startsWith('linear-gradient(to top, ')).toBe(true)
    // jet ramp ≠ viridis ramp (different colours for the same RMSF quantity)
    expect(cando.gradient).not.toBe(legendConfig('flex').gradient)
  })
  it('returns null for non-colour-mapped modes', () => {
    for (const m of ['off', 'deform', null, undefined]) {
      expect(legendConfig(m)).toBeNull()
    }
  })
})

describe('initCandoLegend controller', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="cando-legend" style="display:none">
        <div id="cando-legend-title"></div>
        <div id="cando-legend-max"></div>
        <div id="cando-legend-bar"></div>
        <div id="cando-legend-min"></div>
      </div>`
  })

  it('show(flex,...) reveals the legend with the RMSF title + bounds', () => {
    const lg = initCandoLegend()
    lg.show('flex', 0.5, 1.37)
    expect(document.getElementById('cando-legend').style.display).toBe('block')
    expect(document.getElementById('cando-legend-title').textContent).toBe('RMSF (nm)')
    expect(document.getElementById('cando-legend-max').textContent).toBe('1.37')
    expect(document.getElementById('cando-legend-min').textContent).toBe('0.50')
    expect(lg.isVisible()).toBe(true)
  })

  it('show(deviation,...) uses the deviation title', () => {
    const lg = initCandoLegend()
    lg.show('deviation', 0, 5.54)
    expect(document.getElementById('cando-legend-title').textContent).toBe('Deviation (nm)')
    expect(document.getElementById('cando-legend-max').textContent).toBe('5.54')
  })

  it('show() with a non-colour-mapped mode hides the legend', () => {
    const lg = initCandoLegend()
    lg.show('flex', 0.5, 1.0)
    lg.show('deform', 0, 0)
    expect(document.getElementById('cando-legend').style.display).toBe('none')
    expect(lg.isVisible()).toBe(false)
  })

  it('hide() collapses the legend', () => {
    const lg = initCandoLegend()
    lg.show('flex', 0.5, 1.0)
    lg.hide()
    expect(document.getElementById('cando-legend').style.display).toBe('none')
  })

  it('is a no-op when the legend root is absent', () => {
    document.body.innerHTML = ''
    const lg = initCandoLegend()
    expect(() => { lg.show('flex', 0, 1); lg.hide() }).not.toThrow()
    expect(lg.isVisible()).toBe(false)
  })
})

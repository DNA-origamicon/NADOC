import { it, expect, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { twoElectrodeSpec } from './namd_two_electrodes.js'
import { initNamdSurfaceCard } from './namd_surface_card.js'
import { capturePresetControls, applyPresetControls, presetControls } from './namd_setup_presets.js'
let card
afterEach(() => { card?.dispose(); document.body.replaceChildren() })
it('defines equal-area opposite charges without claiming voltage control', () => {
  const spec = twoElectrodeSpec({axis:'y',gap:10,width:12,depth:15,charge:-0.0413})
  expect(spec).toMatchObject({gap_nm:10,width_nm:12,depth_nm:15,working_charge_C_m2:-0.0413,counter_charge_C_m2:0.0413,model:'abstract_fixed_charge'})
  expect(() => twoElectrodeSpec({axis:'y',gap:'',width:12,depth:15,charge:0})).toThrow('finite')
  expect(() => twoElectrodeSpec({axis:'y',gap:1,width:12,depth:15,charge:0})).toThrow('between')
  expect(() => twoElectrodeSpec({axis:'y',gap:10,width:12,depth:15,charge:1})).toThrow('charge density')
})
it('excludes single-support modes both ways, round-trips presets and provides validated setup payloads', () => {
  const html = readFileSync('index.html', 'utf8')
  const source = new DOMParser().parseFromString(html, 'text/html')
  document.body.innerHTML = '<div id="marker"></div>'
  document.body.append(source.querySelector('#md-surface-body'))
  card = initNamdSurfaceCard()
  const el = id => document.getElementById(id)
  const pair = el('md-two-electrodes-enable')
  for (const id of ['md-hard-surface-enable','md-screening-enable','md-surface-enable']) {
    el(id).click(); pair.click()
    expect(el(id).checked).toBe(false)
    expect(pair.checked).toBe(true)
    expect(() => card.assertReady()).not.toThrow()
    el(id).click(); expect(pair.checked).toBe(false)
    expect(() => card.assertReady()).not.toThrow()
  }
  pair.click()
  el('md-peg-enable').click();expect(pair.checked).toBe(true)
  el('md-peg-enable').click()
  el('md-two-electrodes-gap').value = '15'
  const controls = presetControls(document.body, el('marker'))
  const saved = capturePresetControls(controls)
  card.restore(); expect(pair.checked).toBe(false)
  applyPresetControls(controls,saved)
  expect(pair.checked).toBe(true)
  expect(el('md-hard-surface-enable').checked).toBe(false)
  expect(el('md-two-electrodes-gap').value).toBe('15')
  expect(el('md-two-electrodes-counter').textContent).toBe('0.0413 C/m²')
  el('md-two-electrodes-charge').value = '0.025'
  el('md-two-electrodes-charge').dispatchEvent(new Event('input', {bubbles:true}))
  expect(el('md-two-electrodes-counter').textContent).toBe('-0.0250 C/m²')
  expect(el('md-two-electrodes-model').textContent).toBe('Fixed-charge walls')
  expect(() => card.assertReady()).not.toThrow()
})

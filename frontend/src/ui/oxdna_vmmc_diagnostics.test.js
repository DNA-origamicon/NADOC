import {describe,it,expect} from 'vitest'
import {vmmcDiagnostics} from './oxdna_vmmc_diagnostics.js'
import {vmmcResultView} from './oxdna_vmmc.js'
describe('VMMC sampling evidence',()=>{
 it('shows trapped sampling without treating zero as missing data',()=>{
  const view=vmmcDiagnostics({sampling_temperature_c:70,salt_concentration_M:.3,
   box_conditions:{concentration_uM:26.5686},replicas:[{tm_c:null,visited_pair_counts:1,
    observed_bound_unbound_transitions:0,recorded_samples:2001,pair_counts:[0,1,2],
    biased_counts:[100,0,0],biased_occupancy:[1,0,0],unbiased_probability:[1,0,0]}]})
  expect(view.textContent).toContain('26.569 µM')
  expect(view.textContent).toContain('Not bracketed')
  expect(view.querySelectorAll('tbody')[0].rows[0].cells[3].textContent).toBe('0')
  expect(view.querySelector('details').textContent).toContain('100.000')
 })
 it('renders older saved analyses with available replica evidence',()=>{
  const view=vmmcResultView({run_config:{vmmc_result:{status:'inconclusive',tm_c:null,
   temperatures_c:[60,80],duplex_yield:[0,0],replicas:[{tm_c:null,yields:[0,0],
    visited_pair_counts:1,observed_bound_unbound_transitions:0}]}}})
  expect(view.textContent).toContain('Tm unavailable')
  expect(view.textContent).toContain('older saved analysis')
  expect(view.querySelectorAll('polyline')).toHaveLength(2)
 })
})

// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { screeningPayload, initNamdSurfaceCharge, SCREENING_DEFAULTS } from './namd_surface_charge.js'
it('never writes wizard salt or temperature values', () => {
  expect(screeningPayload({enabled:false})).toEqual({})
  const surface=screeningPayload({enabled:true,...SCREENING_DEFAULTS,salt:300,temperature:298.15})
  expect(surface).toMatchObject({graphene_only:true,graphene_pore_diameter_nm:0,field:null})
  for(const key of ['salt_mode','ion_conc_mM','mg_conc_mM','temperature','graphene_temperature_K'])expect(surface).not.toHaveProperty(key)
  const wizard={salt_mode:'custom',ion_conc_mM:175,mg_conc_mM:0,stage_overrides:{'*':{langevintemp:305}}}
  expect({...wizard,...surface}).toMatchObject(wizard)
  for(const charge of ['',NaN,Infinity,1])expect(()=>screeningPayload({enabled:true,...SCREENING_DEFAULTS,charge})).toThrow()
})
it('restores charge geometry without reintroducing old saved salt settings',()=>{
  document.body.innerHTML='<input id="md-screening-enable" type="checkbox"><input id="md-screening-charge"><input id="md-screening-padding"><p id="md-screening-status"></p>'
  const card=initNamdSurfaceCharge()
  card.restore({graphene_only:true,graphene_pore_diameter_nm:0,graphene_charge_density_C_m2:-.02,ion_conc_mM:100,graphene_temperature_K:295,padding_nm:5})
  expect(card.payload().graphene_charge_density_C_m2).toBe(-.02)
  expect(card.payload()).not.toHaveProperty('ion_conc_mM')
  expect(document.querySelector('#md-screening-status').hidden).toBe(true)
  document.querySelector('#md-screening-charge').value='2'
  document.querySelector('#md-screening-charge').dispatchEvent(new Event('input'))
  expect(document.querySelector('#md-screening-status').textContent).toContain('0.5 C/m²')
  card.restore();expect(card.payload()).toEqual({})
})

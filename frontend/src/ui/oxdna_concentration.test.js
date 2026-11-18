import {describe,it,expect,vi} from 'vitest'
import {concentrationError,concentrationBoxNm,concentrationControl} from './oxdna_concentration.js'
import {oxdnaWizardPayload,oxdnaProductionPayload,validateOxdnaWizard,validateOxdnaProductionWizard} from './oxdna_job_wizard_model.js'
describe('DNA concentration',()=>{
 it('uses total strands, with volume inversely proportional to molarity',()=>{
  expect(concentrationBoxNm(2,26.568622)).toBeCloseTo(50,4)
  expect(concentrationBoxNm(2,12000)).toBeCloseTo(6.5171,3)
  expect(concentrationBoxNm(16,12000)).toBeCloseTo(2*concentrationBoxNm(2,12000))
 })
 it('rejects nonpositive/nonfinite values and permits inherited box',()=>{
  for(const v of [0,-1,NaN,Infinity])expect(concentrationError(v)).toBeTruthy()
  expect(concentrationError(null)).toBeNull();expect(concentrationBoxNm(null,12)).toBeNull()
  expect(validateOxdnaWizard({dna_concentration_uM:-1}).errors.dna_concentration_uM).toBeTruthy()
  expect(validateOxdnaProductionWizard({dna_concentration_uM:0}).errors.dna_concentration_uM).toBeTruthy()
 })
 it('submits the same concentration for relaxation and continuation',()=>{
  expect(oxdnaWizardPayload({dna_concentration_uM:12000}).dna_concentration_uM).toBe(12000)
  expect(oxdnaProductionPayload({dna_concentration_uM:12000}).dna_concentration_uM).toBe(12000)
 })
 it('shows a live box estimate and allows clearing back to inheritance',()=>{
  const change=vi.fn(),root=concentrationControl({strands:2,onChange:change,inherit:true})
  const input=root.querySelector('input');input.value='12000';input.dispatchEvent(new Event('input'))
  expect(root.textContent).toContain('6.52 nm');expect(change).toHaveBeenLastCalledWith(12000)
  input.value='';input.dispatchEvent(new Event('input'));expect(change).toHaveBeenLastCalledWith(null)
 })
})

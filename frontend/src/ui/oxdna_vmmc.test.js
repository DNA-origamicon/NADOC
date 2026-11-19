import {describe,it,expect} from 'vitest'
import {VMMC_DEFAULTS,vmmcError,vmmcStages,vmmcConfig} from './oxdna_vmmc.js'
describe('CPU VMMC protocol',()=>{
 it('validates ranges and independent replica counts',()=>{
  expect(vmmcError(VMMC_DEFAULTS)).toBeNull()
  for(const bad of [{replicas:1},{end_c:50},{temperature_c:90},{step_c:.001},{tuning_steps:NaN}])expect(vmmcError({...VMMC_DEFAULTS,...bad})).toBeTruthy()
 })
 it('separates tuning and equilibration from production on CPU',()=>{
  const stages=vmmcStages(vmmcConfig({replicas:3,tuning_rounds:2}),.3)
  expect(stages).toHaveLength(8)
  expect(stages.filter(s=>s.name.includes('_sample_'))).toHaveLength(3)
  expect(stages.every(s=>s.backend==='CPU'&&s.sim_type==='VMMC'&&s.salt_concentration===.3)).toBe(true)
 })
})

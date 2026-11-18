// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { thermalRecordedSettings, thermalRecordedPhysicsEditor, preserveThermalPhysics } from './oxdna_thermal_settings.js'
const job = () => ({backend:'CUDA',salt_concentration:.3,status:'running',current_stage_idx:0,
 run_config:{thermal_ramp:{start_c:25,end_c:30,step_c:5,block_steps:2000000000},thermal_progress:{huge:{diagnostic:'internal'}}},
 stages:[{name:'1_thermal',status:'running',steps:2000000000},{name:'2_thermal',status:'pending',steps:2000000000}],
 stage_specs:[{name:'1_thermal',dt:.0015,thermostat:'bussi',newtonian_steps:53,diff_coeff:null,salt_concentration:.3,sequence_dependent:false}]})
it('shows formatted recorded settings rather than current defaults or nested JSON',()=>{
 const view=thermalRecordedSettings(job())
 expect(view.textContent).toContain('2,000,000,000')
 expect(view.textContent).toContain('0.0015')
 expect(view.textContent).toContain('bussi')
 expect(view.textContent).toContain('Disabled')
 expect(view.textContent).not.toContain('brownian')
 expect(view.textContent).not.toContain('internal')
 expect(view.querySelectorAll('tbody tr')).toHaveLength(2)
 expect(view.querySelector('pre,textarea')).toBeNull()
})
it('labels missing stage physics honestly',()=>{
 const data=job();delete data.stage_specs
 expect(thermalRecordedSettings(data).textContent).toContain('No current defaults have been substituted')
})
it('preserves recorded physics on edit and changes salt and sequence mode through controls',()=>{
 const source=job(), config=preserveThermalPhysics({salt_concentration:.3,stage_overrides:{'1_production':{dt:.002}}},source)
 expect(config.stage_overrides['1_production']).toMatchObject({dt:.002,thermostat:'bussi',sequence_dependent:false})
 const changes=[];const view=thermalRecordedPhysicsEditor(config,(...args)=>changes.push(args))
 const salt=view.querySelector('[aria-label="Monovalent salt (M)"]');salt.value='.1';salt.dispatchEvent(new Event('change'))
 const sequence=view.querySelector('[aria-label="Sequence-dependent base strengths"]');sequence.value='true';sequence.dispatchEvent(new Event('change'))
 expect(changes).toEqual([['salt_concentration',.1],['sequence_dependent',true]])
 expect(source.stage_specs[0].dt).toBe(.0015)
})

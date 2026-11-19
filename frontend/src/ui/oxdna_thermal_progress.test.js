import { expect, it } from 'vitest'
import { thermalStageProgress } from './oxdna_thermal_progress.js'
const job = () => ({engine:'oxdna', status:'running', current_stage_idx:1, progress_fraction:.375,
  run_config:{thermal_ramp:{start_c:25,end_c:40,step_c:5}},
  stages:['done','running','pending','pending'].map((status,i)=>({name:`${i+1}_thermal`,status,steps:(i+1)*1000000}))})
it('uses the selected stage denominator and reverses stage-count overall progress',()=>{
  const source=job(), before=structuredClone(source)
  const result=thermalStageProgress(source,'2_thermal')
  expect(result).toMatchObject({status:'running',thermal_stage_label:'30 °C',current_step:1000000,steps:2000000,progress_fraction:.5,eta_seconds:null})
  expect(source).toEqual(before)
})
it('prefers matching live progress without adding resumed banked work twice',()=>{
  const source=job(); source.stages[1].completed_steps=400000
  expect(thermalStageProgress(source,'2_thermal',{current_stage_idx:1,stage_fraction:.325}).current_step).toBe(650000)
  expect(thermalStageProgress(source,'2_thermal',{current_stage_idx:0,stage_fraction:.99}).current_step).toBe(1000000)
})
it('shows completed and future stages independently of the running or failed parent',()=>{
  const source=job();source.status='failed'
  expect(thermalStageProgress(source,'1_thermal')).toMatchObject({status:'completed',progress_fraction:1,current_step:1000000})
  expect(thermalStageProgress(source,'2_thermal')).toMatchObject({status:'failed',progress_fraction:.5})
  expect(thermalStageProgress(source,'3_thermal')).toMatchObject({status:'queued',progress_fraction:0,current_step:0,steps:3000000})
})
it('preserves partial skipped progress and leaves parent/nonthermal selections alone',()=>{
  const source=job();source.stages[0].status='skipped';source.stages[0].completed_steps=12345
  expect(thermalStageProgress(source,'1_thermal')).toMatchObject({status:'skipped',current_step:12345})
  expect(thermalStageProgress(source,null)).toBeNull()
  expect(thermalStageProgress(null,'1_thermal')).toBeNull()
  expect(thermalStageProgress({...source,engine:'namd'},'1_thermal')).toBeNull()
})

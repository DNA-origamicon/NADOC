// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { initThermalSelection } from './oxdna_thermal_selection.js'
import { buildJobListModel } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'
const job={job_id:'tm',parent_job_id:'relax',engine:'oxdna',status:'running',current_stage_idx:1,
  run_config:{thermal_ramp:{start_c:25,end_c:35,step_c:5}},
  stages:['done','running','pending'].map((status,i)=>({name:`${i+1}_thermal`,status}))}
it('selects a real temperature stage, scopes all frame requests, and unloads the old range',()=>{
  const stopTrajectory=vi.fn(),host=document.createElement('div')
  const selection=initThermalSelection({stopTrajectory,host})
  selection.set(job)
  expect(selection.scope(job,'lineage')).toBe('thermal')
  expect(selection.set(job,'1_thermal')).toBe(true)
  expect(stopTrajectory).toHaveBeenCalledTimes(1)
  expect(selection.scope(job,'job')).toBe('thermal:1_thermal')
  expect(selection.stageFor('tm')).toBe('1_thermal')
  expect(host.textContent).toContain('25 °C only')
  selection.set(job,'3_thermal')
  expect(selection.hasTrajectory(job,j=>j.stages.some(s=>s.status==='done'||s.status==='running'))).toBe(false)
  const failed=structuredClone(job); failed.stages[2]={...failed.stages[2],status:'failed',started_at:1}
  expect(selection.hasTrajectory(failed,()=>false)).toBe(true)
  expect(selection.set(job,'../../other')).toBe(false)
  selection.set(job)
  expect(selection.scope(job)).toBe('thermal')
  expect(selection.scope({job_id:'ordinary'},'lineage')).toBe('lineage')
})
it('renders selectable temperature children with queued/running spinners and independent highlights',()=>{
 const list=document.createElement('div'),onThermalSelect=vi.fn()
 const ctx={engine:'oxdna',selectedId:'tm',selectedThermalStage:'2_thermal',thermalNumbers:new Map([['tm',2]])}
 renderJobList(list,buildJobListModel([job],ctx),{onThermalSelect})
 list.querySelector('.thermal-job-toggle').click()
 const child=list.querySelector('[data-thermal-stage="2_thermal"] button')
 expect(child.textContent).toContain('30C - Run 2')
 expect(child.getAttribute('aria-pressed')).toBe('true')
 expect(list.querySelectorAll('.thermal-job-state .nadoc-spinner')).toHaveLength(2)
 child.click()
 expect(onThermalSelect).toHaveBeenCalledWith('tm','2_thermal')
 expect(list.querySelectorAll('[data-job-id]')).toHaveLength(1)
})

it('the parent reports failure even when its final temperature is still queued',()=>{
 const failed={...job,status:'failed'}
 const rows=buildJobListModel([failed],{engine:'oxdna',productionState:()=> 'pending'}).rows
 expect(rows[0].statusKey).toBe('failed')
 const queued=buildJobListModel([{...job,status:'queued'}],{engine:'oxdna'}).rows
 expect(queued[0].isActive).toBe(true)
 expect(queued[0].statusKey).toBe('queued')
})

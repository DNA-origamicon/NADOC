// @vitest-environment jsdom
import {it,expect,afterEach,vi} from 'vitest'
import {initOxdnaJobWizard} from './oxdna_job_wizard.js'
afterEach(()=>document.body.replaceChildren())
for(const kind of ['run','surface_deposition','field']) it(`edits temperature and salt together for ${kind}`,async()=>{
 const updateJob=vi.fn(async()=>({}))
 const wizard=initOxdnaJobWizard({updateJob})
 wizard.openEditable({job_id:'child',parent_job_id:'parent',status:'queued',salt_concentration:.3,
  run_config:{kind},stages:[{name:'1_production',steps:1000}],stage_specs:[{name:'1_production',temperature:'310K',salt_concentration:.3}]})
 const salt=document.querySelector('[data-oxdna-salt]'), temp=document.querySelector('.oxdna-job-settings-view [data-job-temperature]')
 expect(salt.closest('.oxdna-conditions')).toBe(temp.closest('.oxdna-conditions'))
 expect(temp.value).toBe('310');expect(salt.value).toBe('0.3')
 salt.value='.2';salt.dispatchEvent(new Event('input'))
 temp.value='315';temp.dispatchEvent(new Event('change'))
 const save=[...document.querySelectorAll('button')].find(b=>b.textContent==='Save changes')
 save.click();await vi.waitFor(()=>expect(updateJob).toHaveBeenCalled())
 expect(updateJob.mock.calls[0][1]).toMatchObject({salt_concentration:.2,stages:[{temperature:'315K',salt_concentration:.2}]})
 wizard.close()
})
it('relaxation salt is beside temperature and updates all stages including prior overrides',()=>{
 const wizard=initOxdnaJobWizard({getInitialValues:()=>({stage_overrides:{'2_md_relax':{salt_concentration:.4}}})})
 wizard.open()
 const salt=document.querySelector('[data-oxdna-salt]')
 expect(salt.closest('.oxdna-conditions').querySelector('[data-job-temperature]')).not.toBeNull()
 salt.value='.2';salt.dispatchEvent(new Event('input'))
 const values=wizard.currentValues()
 expect(values.salt_concentration).toBe(.2)
 expect(Object.values(values.stage_overrides).every(s=>s.salt_concentration===.2)).toBe(true)
 wizard.close()
})

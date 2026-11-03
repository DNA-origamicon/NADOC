import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import {execFileSync} from 'node:child_process'
import {waitForMdJob} from './helpers/md_job_triggers.js'
const output=path.resolve('../.development-artifacts/cpd-relax-execution')
// Stop the batch on a failure so it can be diagnosed before spending GPU time on more jobs.
test.describe.configure({mode:'serial'})
let activeJob
let activeReview
test.afterEach(async({request})=>{
 if(!activeJob)return
 const job=await(await request.get(`/api/md/jobs/${activeJob}`)).json()
 if(job.status==='failed'){
  const saved=path.join(activeReview,`failed-${activeJob}`)
  fs.mkdirSync(saved,{recursive:true})
  fs.writeFileSync(path.join(saved,'job.json'),JSON.stringify(job,null,2))
  const pkg=path.resolve('../workspace/md_jobs',activeJob,job.package_subdir)
  if(fs.existsSync(pkg))for(const name of fs.readdirSync(pkg)){
   if(name.endsWith('.log')){
    const data=fs.readFileSync(path.join(pkg,name))
    fs.writeFileSync(path.join(saved,name),data.subarray(Math.max(0,data.length-250000)))
   }
  }
  const deleted=await request.delete(`/api/md/jobs/${activeJob}`)
  expect(deleted.ok()).toBe(true)
 }
 activeJob=null
})
for(const isomer of (process.env.NADOC_CPD_ISOMERS || 'cis-anti-I,cis-syn-I,trans-syn-I,trans-syn-II').split(',')) {
test(`CPD full relaxation: ${isomer}`,async({page,request})=>{
 test.skip(process.env.NADOC_RUN_CPD_RELAXATION !== '1','Explicit opt-in required: runs full NAMD relaxation on the local GPU')
 test.setTimeout(48*3600*1000)
 page.setDefaultTimeout(30000)
 page.setDefaultNavigationTimeout(30000)
 const review=path.join(output,isomer)
 activeReview=review
 fs.mkdirSync(review,{recursive:true})
 page.on('response',async r=>{if(r.url().includes('/api/md/jobs') && r.request().method()==='POST')console.log('JOB RESPONSE',r.status(),r.url())})
 await page.goto('/?doc=__e2e__cpd-package')
 await page.waitForFunction(()=>window.__nadocTest)
 await page.locator('[data-library-path$="CPD_1xT_isomers"]').click()
 await page.locator(`[data-library-path$="2hb_1xT_CPD_${isomer}.nadoc"]`).click()
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(!await page.locator('#simulate-body').isVisible())await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.evaluate(()=>window.__nadocMdPanel.deselectJob())
 let job
 if(process.env.NADOC_CPD_RESUME_JOB){
  job=await(await request.get(`/api/md/jobs/${process.env.NADOC_CPD_RESUME_JOB}`)).json()
 }else{
 await page.click('#md-jobs-new-btn')
 const modal=page.locator('.modal--wizard')
 await modal.getByRole('tab',{name:/What each stage runs/}).click()
 await page.screenshot({path:path.join(review,'wizard.png')})
 const response=page.waitForResponse(r=>r.url().endsWith('/api/md/jobs')&&r.request().method()==='POST')
 await modal.getByRole('button',{name:'Create job',exact:true}).click()
 const res=await response;job=await res.json()

 fs.writeFileSync(path.join(review,'created.json'),JSON.stringify(job,null,2))
 expect(res.ok(),JSON.stringify(job)).toBe(true)
 }
 activeJob=job.job_id
 let latest=job
 const onEvent = event => {
  fs.appendFileSync(path.join(review,'trigger-events.jsonl'),JSON.stringify({...event,at:new Date().toISOString()})+'\n')
  if(event.job)fs.writeFileSync(path.join(review,'job.json'),JSON.stringify(event.job,null,2))
  console.log('TRIGGER',isomer,event.type,event.job?.status,event.job?.current_segment_idx,event.job?.error||'')
 }
 const jobDir=path.resolve('../workspace/md_jobs',job.job_id)
 const prepared=await waitForMdJob(jobDir,{statuses:['queued','failed','stopped'],timeoutMs:10*60000,onEvent})
 expect(prepared.type).toBe('queued')
 latest=prepared.job
 console.log('FINAL JOB',latest.job_id,latest.status,latest.error)
 await expect(page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`)).toBeVisible()
 await page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`).click()
 await page.screenshot({path:path.join(review,'result.png')})
 expect(latest.status,latest.error).not.toBe('failed')
 expect(latest.status).toBe('queued')
 expect(latest.early_stop_relax).toBe(true)
 const audit=JSON.parse(execFileSync(path.resolve('../.venv/bin/python'),['scripts/audit_cpd_managed_package.py',`workspace/md_jobs/${job.job_id}`],{cwd:path.resolve('..'),env:{...process.env,PYTHONPATH:'.'},encoding:'utf8'}))
 fs.writeFileSync(path.join(review,'package-audit.json'),JSON.stringify(audit,null,2))
 expect(audit.chemistry[0].chirality.passed).toBe(true)
 expect(latest.namd_pid).toBeNull()
 expect(latest.runpod_pod_id).toBeNull()
 expect(latest.slurm_job_id).toBeNull()
 await expect(page.locator('#md-jobs-run-btn')).toBeEnabled()
 const startResponse=page.waitForResponse(r=>r.url().endsWith(`/md/jobs/${job.job_id}/start`)&&r.request().method()==='POST')
 try {await page.locator('#md-jobs-run-btn').click({timeout:15000})}catch(error){await page.screenshot({path:path.join(review,'click-blocked.png')});console.log(String(error));throw error}
 await page.waitForTimeout(2000)
 await page.screenshot({path:path.join(review,'after-run-click.png')})
 console.log('DIALOGS',await page.locator('.modal').allTextContents())
 const started=await startResponse
 expect(started.ok(),`Start returned HTTP ${started.status()}`).toBe(true)
 const outcome=await waitForMdJob(jobDir,{
  statuses:['failed','stopped','paused','completed'],
  timeoutMs:Number(process.env.NADOC_CPD_TIMEOUT_HOURS||6)*3600000,onEvent,
 })
 if(outcome.type==='time_limit'){
  await page.locator('#md-jobs-run-btn').click()
  fs.writeFileSync(path.join(review,'time-limit.json'),JSON.stringify(outcome,null,2))
 }
 latest=outcome.job
 await page.evaluate(()=>window.__nadocMdPanel.refresh())
 await page.screenshot({path:path.join(review,'finished.png')})
 expect(outcome.type).toBe('completed')
 expect(latest.status,latest.error||JSON.stringify(latest.decision)).toBe('completed')
 expect(latest.segments.every(s=>s.status==='done'||s.status==='completed'||s.skipped)).toBe(true)
 const completedAudit=JSON.parse(execFileSync(path.resolve('../.venv/bin/python'),['scripts/audit_cpd_managed_package.py',`workspace/md_jobs/${job.job_id}`,'--completed'],{cwd:path.resolve('..'),env:{...process.env,PYTHONPATH:'.'},encoding:'utf8'}))
 fs.writeFileSync(path.join(review,'completed-audit.json'),JSON.stringify(completedAudit,null,2))
 console.log('COMPLETED',isomer,'skipped',latest.segments.filter(s=>s.skipped).length)
})
}

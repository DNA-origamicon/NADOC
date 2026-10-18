import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import {execFileSync} from 'node:child_process'
const output=path.resolve('../.development-artifacts/cpd-managed-preparation')
let createdId
test.afterEach(async({request})=>{
 if(createdId && process.env.NADOC_RETAIN_CPD_REVIEW !== '1')await request.delete(`/api/md/jobs/${createdId}`)
 createdId=null
})
test('CPD wizard builds a real relaxation package before Run',async({page,request})=>{
 test.setTimeout(600000)
 fs.mkdirSync(output,{recursive:true})
 page.on('response',async r=>{if(r.url().includes('/api/md/jobs') && r.request().method()==='POST')console.log('JOB RESPONSE',r.status(),r.url())})
 await page.goto('/?doc=__e2e__cpd-package')
 await page.waitForFunction(()=>window.__nadocTest)
 await page.locator('[data-library-path$="CPD_1xT_isomers"]').click()
 await page.locator('[data-library-path$="2hb_1xT_CPD_trans-syn-II.nadoc"]').click()
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(!await page.locator('#simulate-body').isVisible())await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.evaluate(()=>window.__nadocMdPanel.deselectJob())
 await page.click('#md-jobs-new-btn')
 const modal=page.locator('.modal--wizard')
 await modal.getByRole('tab',{name:/What each stage runs/}).click()
 await page.screenshot({path:path.join(output,'wizard.png')})
 const response=page.waitForResponse(r=>r.url().endsWith('/api/md/jobs')&&r.request().method()==='POST')
 await modal.getByRole('button',{name:'Create job',exact:true}).click()
 const res=await response;const job=await res.json()
 createdId=job.job_id
 fs.writeFileSync(path.join(output,'created.json'),JSON.stringify(job,null,2))
 expect(res.ok(),JSON.stringify(job)).toBe(true)
 let latest=job
 await expect.poll(async()=>{
  latest=await(await request.get(`/api/md/jobs/${job.job_id}`)).json()
  fs.writeFileSync(path.join(output,'job.json'),JSON.stringify(latest,null,2))
  return latest.status
 },{timeout:480000,intervals:[2000,5000]}).not.toBe('preparing')
 console.log('FINAL JOB',latest.job_id,latest.status,latest.error)
 await expect(page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`)).toBeVisible()
 await page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`).click()
 await page.screenshot({path:path.join(output,'result.png')})
 expect(latest.status,latest.error).not.toBe('failed')
 expect(latest.status).toBe('queued')
 const audit=JSON.parse(execFileSync(path.resolve('../.venv/bin/python'),['scripts/audit_cpd_managed_package.py',`workspace/md_jobs/${job.job_id}`],{cwd:path.resolve('..'),env:{...process.env,PYTHONPATH:'.'},encoding:'utf8'}))
 fs.writeFileSync(path.join(output,'package-audit.json'),JSON.stringify(audit,null,2))
 expect(audit.chemistry[0].chirality.passed).toBe(true)
 expect(latest.namd_pid).toBeNull()
 expect(latest.runpod_pod_id).toBeNull()
 expect(latest.slurm_job_id).toBeNull()
 await expect(page.locator('#simulate-jobs-run-btn')).toBeEnabled()
})

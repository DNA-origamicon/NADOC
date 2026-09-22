// Explicit live check. Only screenshots/JSON under INSPECTOR_OUTPUT/browser;
// temporary browser context closes on failure. No workspace designs or downloads.
import {chromium,expect} from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
const root=process.env.INSPECTOR_OUTPUT
if(!root)throw Error('INSPECTOR_OUTPUT required')
const out=path.join(root,'browser');await fs.mkdir(out,{recursive:true})
const browser=await chromium.launch({headless:true})
const context=await browser.newContext({baseURL:'http://127.0.0.1:8766',viewport:{width:1600,height:1100}})
const page=await context.newPage(),errors=[],results={}
page.on('pageerror',e=>errors.push(e.message))
async function visibility(value){
 const [response]=await Promise.all([
  page.waitForResponse(r=>r.url().endsWith('/api/capture')&&r.request().method()==='POST'),
  page.locator('#visibility').selectOption(value)
 ])
 const c=await response.json()
 await expect(page.locator('#eyeImage')).toHaveAttribute('src',new RegExp(c.name+'/'))
}
async function terminal(timeout=180000){
 await expect(page.locator('#job')).toHaveText(/^(passed|failed|error|cancelled)/,{timeout})
 const s=await(await page.request.get('/api/status')).json()
 if(!['passed','failed'].includes(s.job.status))throw Error(JSON.stringify(s.job))
 return s.job
}
try{
 await page.goto('/')
 await expect(page.locator('#connection')).toContainText('Focused')
 await page.locator('#zoom').selectOption('2')
 if(!process.env.VISIBILITY_RESUME){
 await page.locator('#initial').click()
 await expect(page.locator('#job')).toContainText('running')
 await expect(page.locator('#eyeImage')).toHaveAttribute('src',/steady_fast-paint\/left.png/,{timeout:30000})
 await expect(page.locator('#live')).toContainText('3 cells')
 await page.screenshot({path:path.join(out,'paint-during-run.png'),fullPage:true})
 await expect(page.locator('#eyeImage')).toHaveAttribute('src',/steady_fast-erase\/left.png/,{timeout:30000})
 await page.screenshot({path:path.join(out,'erase-during-run.png'),fullPage:true})
 results.initial=await terminal()
 if(results.initial.status!=='passed')throw Error('Initial visual validation failed')
 }
 await visibility('normal')
 await expect(page.locator('#frameInfo')).toContainText('scene normal')
 await page.locator('#final').click()
 await expect(page.locator('#job')).toContainText('running')
 results.final=await terminal(240000)
 if(results.final.outcomes.length!==4)throw Error('Missing final profile')
 await visibility('hidden')
 await expect(page.locator('#frameInfo')).toContainText('scene hidden')
 await page.locator('#review').click()
 await expect(page.locator('#job')).toContainText('running')
 results.review=await terminal()
 if(results.review.status!=='passed')throw Error('Retained painting review failed')
 await expect(page.locator('#live')).toContainText('3 cells')
 await expect(page.locator('#live')).toContainText('Right: inactive')
 await page.screenshot({path:path.join(out,'retained-paint-review.png'),fullPage:true})
 results.browser_errors=errors
 if(errors.length)throw Error(errors.join('\n'))
 results.passed=true
 console.log(JSON.stringify(results,null,2))
}finally{
 await fs.writeFile(path.join(out,'visibility-validation.json'),JSON.stringify(results,null,2)+'\n')
 await context.close();await browser.close()
}

// Live paint-only review. Keeps screenshots/JSON only in INSPECTOR_OUTPUT/browser.
// No designs/downloads/persistent browser profile; closes context in finally.
import {chromium,expect} from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
const root=process.env.INSPECTOR_OUTPUT
if(!root)throw Error('INSPECTOR_OUTPUT required')
const out=path.join(root,'browser');await fs.mkdir(out,{recursive:true})
const browser=await chromium.launch({headless:true})
const context=await browser.newContext({baseURL:'http://127.0.0.1:8766',viewport:{width:1600,height:1100}})
const page=await context.newPage(),errors=[]
page.on('pageerror',e=>errors.push(e.message))
try{
 await page.goto('/')
 await expect(page.locator('#connection')).toContainText('Focused')
 await page.locator('#zoom').selectOption('2')
 await page.locator('#bounds').uncheck();await page.locator('#rays').uncheck()
 const [response]=await Promise.all([
  page.waitForResponse(r=>r.url().endsWith('/api/capture')&&r.request().method()==='POST'),
  page.locator('#visibility').selectOption('hidden')
 ])
 const capture=await response.json()
 await expect(page.locator('#eyeImage')).toHaveAttribute('src',new RegExp(capture.name+'/'))
 await page.locator('#review').click()
 await expect(page.locator('#job')).toContainText('running')
 await expect(page.locator('#job')).toHaveText(/^(passed|failed|error)/,{timeout:60000})
 const s=await(await page.request.get('/api/status')).json()
 if(s.job.status!=='passed')throw Error(JSON.stringify(s.job))
 if(!s.job.outcomes[0].checks.paint_trace_retained_after_release)throw Error('Release persistence missing')
 await expect(page.locator('#live')).toContainText('3 cells')
 await expect(page.locator('#live')).toContainText('Right: inactive')
 await page.screenshot({path:path.join(out,'retained-native-paint.png'),fullPage:true})
 if(errors.length)throw Error(errors.join('\n'))
 await fs.writeFile(path.join(out,'retained-review.json'),JSON.stringify({passed:true,job:s.job,errors},null,2)+'\n')
 console.log(JSON.stringify({passed:true,job:s.job.name}))
}finally{await context.close();await browser.close()}

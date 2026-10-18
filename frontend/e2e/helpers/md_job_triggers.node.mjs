import {test} from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {waitForMdJob} from './md_job_triggers.js'

function fixture(t){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'cpd-trigger-'))
 t.after(()=>fs.rmSync(dir,{recursive:true,force:true}))
 const put=status=>{
  fs.writeFileSync(path.join(dir,'job.json.tmp'),JSON.stringify({status,current_segment_idx:0}))
  fs.renameSync(path.join(dir,'job.json.tmp'),path.join(dir,'job.json'))
 }
 put('running')
 return {dir,put}
}
for(const status of ['completed','failed','paused','stopped'])test(`atomic replacement triggers ${status}`,async t=>{
 const {dir,put}=fixture(t)
 const pending=waitForMdJob(dir,{statuses:[status],timeoutMs:1000})
 put(status)
 assert.equal((await pending).type,status)
})
test('deadline fires without any file change',async t=>{
 const {dir}=fixture(t)
 const events=[]
 const result=await waitForMdJob(dir,{statuses:['completed'],timeoutMs:20,onEvent:e=>events.push(e)})
 assert.equal(result.type,'time_limit')
 assert.deepEqual(events.map(e=>e.type),['transition','time_limit'])
})
test('already-completed job triggers immediately',async t=>{
 const {dir,put}=fixture(t);put('completed')
 assert.equal((await waitForMdJob(dir,{statuses:['completed'],timeoutMs:1000})).type,'completed')
})

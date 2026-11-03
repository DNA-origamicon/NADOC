// Bridge the already-running browser test to filesystem triggers without restarting NAMD.
import fs from 'node:fs'
import path from 'node:path'
import {waitForMdJob} from './md_job_triggers.js'
const [jobId, workerPidText, hoursText = '6'] = process.argv.slice(2)
const workerPid = Number(workerPidText)
const root = path.resolve('..')
const review = path.join(root, '.development-artifacts/cpd-relax-execution/cis-anti-I')
const log = path.join(review, 'trigger-events.jsonl')
const event = await waitForMdJob(path.join(root, 'workspace/md_jobs', jobId), {
  statuses: ['completed','failed','paused','stopped'], timeoutMs: Number(hoursText)*3600000,
  onEvent: e => {
    fs.appendFileSync(log, JSON.stringify({...e, at:new Date().toISOString()})+'\n')
    console.log(JSON.stringify({type:e.type, jobId, status:e.job?.status,
      stage:e.job?.current_segment_idx, error:e.job?.error}))
  },
})
if(event.type === 'time_limit') {
  const response=await fetch(`http://127.0.0.1:8002/api/md/jobs/${jobId}/stop`,{method:'POST'})
  fs.writeFileSync(path.join(review,'time-limit.json'),JSON.stringify({event,stop_status:response.status},null,2))
}
// The old browser test wakes once to record its terminal screenshot and assertions.
process.kill(workerPid, 'SIGCONT')

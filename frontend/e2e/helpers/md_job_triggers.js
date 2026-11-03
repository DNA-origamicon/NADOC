import fs from 'node:fs'
import path from 'node:path'

/** Observe atomic job.json replacement events; no intervals or status requests. */
export function waitForMdJob(jobDir, {statuses, timeoutMs, onEvent = () => {}}) {
  return new Promise((resolve, reject) => {
    let last, signature, settled = false, timer, watcher
    const finish = (event) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      watcher?.close()
      onEvent(event)
      resolve(event)
    }
    const read = () => {
      if (settled) return
      try {
        last = JSON.parse(fs.readFileSync(path.join(jobDir, 'job.json'), 'utf8'))
        const next = JSON.stringify([last.status, last.current_segment_idx,
          last.minimization?.status, last.error, last.decision])
        if (next !== signature) {
          signature = next
          onEvent({type: 'transition', at: new Date().toISOString(), job: last})
        }
        if (statuses.includes(last.status)) finish({type: last.status, job: last})
      } catch (error) {
        if (error.code === 'ENOENT') finish({type: 'deleted', job: last})
        else { clearTimeout(timer); watcher?.close(); settled = true; reject(error) }
      }
    }
    watcher = fs.watch(jobDir, (_event, filename) => {
      if (!filename || String(filename) === 'job.json') read()
    })
    watcher.on('error', error => {clearTimeout(timer); watcher.close(); reject(error)})
    timer = setTimeout(() => finish({type: 'time_limit', job: last,
      deadline: new Date().toISOString()}), timeoutMs)
    read()
  })
}

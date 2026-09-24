import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'

/** One pipe, bounded outstanding requests, no subprocess or temporary file per frame. */
export function createShareBridge(command, args) {
  const child = spawn(command, args, { stdio: ['pipe', 'pipe', 'ignore'] })
  const pending = new Map(); let id = 0, closed = false, idle
  const close = (error = new Error('Sharing transport closed')) => {
    if (closed) return
    closed = true; clearTimeout(idle); child.kill()
    for (const value of pending.values()) value.reject(error)
    pending.clear()
  }
  const arm = () => { clearTimeout(idle); idle = setTimeout(() => close(), 30000); idle.unref() }
  createInterface({ input: child.stdout }).on('line', line => {
    try {
      const result = JSON.parse(line), waiter = pending.get(result.id)
      if (waiter) { pending.delete(result.id); if (!pending.size) arm(); waiter.resolve(result) }
    } catch { close(new Error('Invalid sharing transport response')) }
  })
  child.on('error', close); child.on('exit', () => close()); child.stdin.on('error', close); arm()
  return { get closed() { return closed }, close, request(path, options) {
    if (closed || pending.size >= 4) return Promise.reject(new Error('Sharing transport is busy or closed'))
    clearTimeout(idle)
    return new Promise((resolve, reject) => {
      const requestId = ++id
      pending.set(requestId, { resolve, reject })
      child.stdin.write(JSON.stringify({ id: requestId, path, lease: options.headers?.['X-NADOC-Broadcast'] ?? '', body: options.body ? Buffer.from(options.body).toString('base64') : '' }) + '\n')
    })
  } }
}

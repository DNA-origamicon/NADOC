// Persistent Windows-side control transport for frame packets from a WSL editor.
import { readFile } from 'node:fs/promises'
import { createInterface } from 'node:readline'
const config = JSON.parse(await readFile(process.argv[2], 'utf8'))
if (!/^http:\/\/(?:\d{1,3}\.){3}\d{1,3}:\d+$/.test(config.url) || !/^[a-f0-9]{64}$/.test(config.token)) throw new Error('Invalid local host configuration')
for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  let id
  try {
    const value = JSON.parse(line); id = value.id
    if (!/^\/host\/shares\/[a-f0-9]{32}\/broadcast\/(frame|camera|heartbeat|hold|pause|progress)$/.test(value.path) ||
      typeof value.body !== 'string' || (!value.path.endsWith('/frame') && value.body.length > 8192)) throw new Error('Invalid streaming action')
    const response = await fetch(config.url + value.path, { method: 'POST', headers: { Authorization: `Bearer ${config.token}`, 'X-NADOC-Broadcast': value.lease },
      body: value.body ? Buffer.from(value.body, 'base64') : undefined, signal: value.path.endsWith('/frame') ? undefined : AbortSignal.timeout(15000) })
    process.stdout.write(JSON.stringify({ id, status: response.status, value: await response.json() }) + '\n')
  } catch (error) { process.stdout.write(JSON.stringify({ id, status: 503, value: { error: error.message } }) + '\n') }
}

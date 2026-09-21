#!/usr/bin/env node
// Windows-side transport for a WSL editor. The host key never reaches a browser.
import { readFile } from 'node:fs/promises'
const [controlFile, path, method = 'GET', bodyFile = '', title = ''] = process.argv.slice(2)
try {
  if (!/^\/host\/(shares(?:\/[a-f0-9]{32})?|stop)$/.test(path) || !['GET', 'POST', 'DELETE'].includes(method)) throw new Error('Invalid host action')
  const config = JSON.parse(await readFile(controlFile, 'utf8'))
  if (!/^http:\/\/(?:\d{1,3}\.){3}\d{1,3}:\d+$/.test(config.url) || !/^[a-f0-9]{64}$/.test(config.token)) throw new Error('Invalid local host configuration')
  const response = await fetch(config.url + path, { method, headers: { Authorization: `Bearer ${config.token}`, ...(title ? { 'X-NADOC-Title': title } : {}) }, body: bodyFile ? await readFile(bodyFile) : undefined, signal: AbortSignal.timeout(15000) })
  console.log(JSON.stringify({ status: response.status, value: await response.json() }))
} catch (error) { console.error(error.message); process.exitCode = 1 }

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

test('WSL helper forwards perspective locks and drawing reads, but rejects unknown routes', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'nadoc-share-request-'))
  const received = [], token = 'a'.repeat(64), room = 'b'.repeat(32)
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk
    received.push({ path: req.url, method: req.method, body, authorization: req.headers.authorization })
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"ok":true}')
  })
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
    const control = join(dir, 'control.json'), body = join(dir, 'lock.json')
    await writeFile(control, JSON.stringify({ url: `http://127.0.0.1:${server.address().port}`, token }), { mode: 0o600 })
    const run = (...args) => promisify(execFile)(process.execPath, [fileURLToPath(new URL('./prepared_share_request.mjs', import.meta.url)), control, ...args])
    for (const locked of [true, false]) {
      await writeFile(body, JSON.stringify({ locked }))
      const result = await run(`/host/shares/${room}/broadcast/view-lock`, 'POST', body)
      assert.equal(JSON.parse(result.stdout).status, 200)
      assert.deepEqual(received.at(-1), { path: `/host/shares/${room}/broadcast/view-lock`, method: 'POST', body: JSON.stringify({ locked }), authorization: `Bearer ${token}` })
    }
    await run(`/host/shares/${room}/drawings`)
    assert.equal(received.at(-1).method, 'GET')
    assert.equal(received.at(-1).path, `/host/shares/${room}/drawings`)
    for (const path of ['/api/design', `/host/shares/${room}/broadcast/unknown`, `/host/shares/${room}/drawings/extra`]) {
      await assert.rejects(run(path), error => /Invalid host action/.test(error.stderr))
    }
    assert.equal(received.length, 3)
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve))
    await rm(dir, { recursive: true, force: true })
  }
})

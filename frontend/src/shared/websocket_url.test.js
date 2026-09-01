import { describe, expect, it } from 'vitest'
import { webSocketUrl } from './websocket_url.js'

describe('webSocketUrl', () => {
  it('uses a secure socket from an HTTPS page', () => {
    expect(webSocketUrl('/ws/md-run', {
      protocol: 'https:', host: 'compy5000.example.ts.net:5173',
    })).toBe('wss://compy5000.example.ts.net:5173/ws/md-run')
  })

  it('keeps localhost HTTP sockets unencrypted', () => {
    expect(webSocketUrl('ws/md-jobs/job-1', {
      protocol: 'http:', host: 'localhost:5173',
    })).toBe('ws://localhost:5173/ws/md-jobs/job-1')
  })
})

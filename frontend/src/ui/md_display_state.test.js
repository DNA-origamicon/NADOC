import { describe, it, expect } from 'vitest'
import {
  WS,
  targetStreamMode,
  sceneUsesAtomistic,
  sceneUsesNativeCg,
  decideReload,
  canReapplyFrame,
  shouldForceDisplayReload,
} from './md_display_state.js'

describe('targetStreamMode', () => {
  it('maps atomistic scene reprs to ballstick', () => {
    expect(targetStreamMode('vdw')).toBe('ballstick')
    expect(targetStreamMode('ballstick')).toBe('ballstick')
  })
  it('maps every CG/other repr to nadoc', () => {
    for (const r of ['full', 'beads', 'cylinders', 'hull-prism', 'surface', 'anything'])
      expect(targetStreamMode(r)).toBe('nadoc')
  })
})

describe('sceneUsesAtomistic / sceneUsesNativeCg', () => {
  it('atomistic = vdw|ballstick', () => {
    expect(sceneUsesAtomistic('vdw')).toBe(true)
    expect(sceneUsesAtomistic('ballstick')).toBe(true)
    expect(sceneUsesAtomistic('full')).toBe(false)
  })
  it('native CG = full|beads|cylinders', () => {
    expect(sceneUsesNativeCg('full')).toBe(true)
    expect(sceneUsesNativeCg('beads')).toBe(true)
    expect(sceneUsesNativeCg('cylinders')).toBe(true)
    expect(sceneUsesNativeCg('vdw')).toBe(false)
    expect(sceneUsesNativeCg('hull-prism')).toBe(false)
  })
})

describe('decideReload', () => {
  const base = {
    wsState: null,
    loadInFlight: false,
    loadConfigPath: null,
    currentConfig: null,
    requestedConfig: '/run/a.json',
    modeChanged: false,
    forceReload: false,
  }

  it('opens when there is no socket', () => {
    expect(decideReload(base)).toBe('open')
  })

  it('forceReload always opens, even when a matching load is in flight', () => {
    expect(decideReload({
      ...base, forceReload: true, loadInFlight: true,
      wsState: WS.OPEN, loadConfigPath: '/run/a.json', currentConfig: '/run/a.json',
    })).toBe('open')
  })

  it('waits when a load for the same target is in flight (CONNECTING) — the abort guard', () => {
    expect(decideReload({
      ...base, loadInFlight: true, wsState: WS.CONNECTING, loadConfigPath: '/run/a.json',
    })).toBe('wait-in-flight')
  })

  it('waits when a load for the same target is in flight (OPEN, not yet ready)', () => {
    expect(decideReload({
      ...base, loadInFlight: true, wsState: WS.OPEN, loadConfigPath: '/run/a.json',
    })).toBe('wait-in-flight')
  })

  it('does NOT wait when the in-flight load is for a different config', () => {
    expect(decideReload({
      ...base, loadInFlight: true, wsState: WS.CONNECTING, loadConfigPath: '/run/OLD.json',
    })).toBe('open')
  })

  it('does NOT wait when the in-flight load targets a different stream mode', () => {
    expect(decideReload({
      ...base, loadInFlight: true, wsState: WS.CONNECTING,
      loadConfigPath: '/run/a.json', modeChanged: true,
    })).toBe('open')
  })

  it('reuses an OPEN, ready socket serving the same target', () => {
    expect(decideReload({
      ...base, wsState: WS.OPEN, currentConfig: '/run/a.json',
    })).toBe('reuse-open')
  })

  it('opens when the open socket targets a different config', () => {
    expect(decideReload({
      ...base, wsState: WS.OPEN, currentConfig: '/run/OLD.json',
    })).toBe('open')
  })

  it('opens when the open socket targets the same config but the mode changed', () => {
    expect(decideReload({
      ...base, wsState: WS.OPEN, currentConfig: '/run/a.json', modeChanged: true,
    })).toBe('open')
  })

  it('opens (not reuse) when the socket is CLOSING/CLOSED', () => {
    expect(decideReload({ ...base, wsState: WS.CLOSING, currentConfig: '/run/a.json' })).toBe('open')
    expect(decideReload({ ...base, wsState: WS.CLOSED, currentConfig: '/run/a.json' })).toBe('open')
  })
})

describe('shouldForceDisplayReload', () => {
  const KEY = '/run/a.json|/run/a.dcd|relax_k0.5'

  it('forces a reload on first toggle-on when nothing was prewarmed', () => {
    // _displayKey/_displayJobId start null; no prewarm → must load fresh.
    expect(shouldForceDisplayReload({
      key: KEY, displayKey: null, displayJobId: null, jobId: 'job1', prewarmKey: null,
    })).toBe(true)
  })

  it('does NOT reload when the prewarm already warmed this exact key (the instant-toggle path)', () => {
    expect(shouldForceDisplayReload({
      key: KEY, displayKey: null, displayJobId: null, jobId: 'job1', prewarmKey: KEY,
    })).toBe(false)
  })

  it('still reloads when the prewarm warmed a different (stale) segment', () => {
    expect(shouldForceDisplayReload({
      key: KEY, displayKey: null, displayJobId: null, jobId: 'job1',
      prewarmKey: '/run/a.json|/run/a.dcd|relax_k0.1',
    })).toBe(true)
  })

  it('does NOT reload on a subsequent tick once the same key is already displayed', () => {
    expect(shouldForceDisplayReload({
      key: KEY, displayKey: KEY, displayJobId: 'job1', jobId: 'job1', prewarmKey: null,
    })).toBe(false)
  })

  it('reloads when the displayed job id differs even if the key string matches', () => {
    expect(shouldForceDisplayReload({
      key: KEY, displayKey: KEY, displayJobId: 'jobOLD', jobId: 'job1', prewarmKey: null,
    })).toBe(true)
  })
})

describe('canReapplyFrame', () => {
  it('allows a nadoc frame only while the scene is a native-CG repr', () => {
    expect(canReapplyFrame('nadoc', 'full')).toBe(true)
    expect(canReapplyFrame('nadoc', 'beads')).toBe(true)
    expect(canReapplyFrame('nadoc', 'ballstick')).toBe(false)
    expect(canReapplyFrame('nadoc', 'vdw')).toBe(false)
  })
  it('allows a ballstick frame only while the scene is atomistic', () => {
    expect(canReapplyFrame('ballstick', 'vdw')).toBe(true)
    expect(canReapplyFrame('ballstick', 'ballstick')).toBe(true)
    expect(canReapplyFrame('ballstick', 'full')).toBe(false)
  })
})

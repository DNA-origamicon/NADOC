import { describe, it, expect } from 'vitest'
import { WS, targetStreamMode, sceneUsesAtomistic, sceneUsesNativeCg, decideReload, canReapplyFrame, nextLivePollAction, mdReadinessIndicator, shouldForceDisplayReload, sceneUsesHeavy, solventRepMode, restorePlan, zipAtomIdentity, toBondPairs, mdDisplayReadinessFromMeta, atomFrameToCgPositions } from './md_display_state.js'

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

describe('atomFrameToCgPositions', () => {
  it('maps each identity-stamped phosphorus directly to one CG backbone position', () => {
    const out = atomFrameToCgPositions({
      type: 'frame', frame_idx: 17, n_frames: 20, time_ps: 4,
      atoms: [
        { element: 'P', helix_id: 'h0', bp_index: 2, direction: 'FORWARD', x: 1, y: 2, z: 3 },
        { element: 'C', helix_id: 'h0', bp_index: 2, direction: 'FORWARD', x: 9, y: 9, z: 9 },
        { element: 'P', helix_id: 'h1', bp_index: 7, direction: 'REVERSE', x: 4, y: 5, z: 6 },
      ],
    })
    expect(out).toMatchObject({ frame_idx: 17, n_frames: 20, time_ps: 4 })
    expect(out.positions).toEqual([
      { helix_id: 'h0', bp_index: 2, direction: 'FORWARD', copy: 0, x: 1, y: 2, z: 3 },
      { helix_id: 'h1', bp_index: 7, direction: 'REVERSE', copy: 0, x: 4, y: 5, z: 6 },
    ])
  })

  it('returns null rather than applying an empty or identity-less reskin', () => {
    expect(atomFrameToCgPositions(null)).toBeNull()
    expect(atomFrameToCgPositions({ atoms: [{ element: 'P', x: 1, y: 2, z: 3 }] })).toBeNull()
  })
})

describe('sceneUsesHeavy', () => {
  it('is true only for the atomistic + surface renderers', () => {
    expect(sceneUsesHeavy('vdw')).toBe(true)
    expect(sceneUsesHeavy('ballstick')).toBe(true)
    expect(sceneUsesHeavy('surface')).toBe(true)
  })
  it('is false for every design-renderer CG repr, INCLUDING hull-prism', () => {
    // hull-prism is drawn by the design renderer, so it is NOT heavy — this is the
    // case sceneUsesNativeCg misses (hence a dedicated predicate).
    for (const r of ['full', 'beads', 'cylinders', 'hull-prism', 'anything', undefined])
      expect(sceneUsesHeavy(r)).toBe(false)
  })
})

describe('solventRepMode', () => {
  it('draws one sphere per molecule in the nucleotide-level reps', () => {
    expect(solventRepMode('full')).toBe('sphere')
    expect(solventRepMode('beads')).toBe('sphere')
  })

  it('draws real atoms in the atomistic reps', () => {
    expect(solventRepMode('vdw')).toBe('atomistic')
    expect(solventRepMode('ballstick')).toBe('atomistic')
  })

  // THE trap. `cylinders` is in sceneUsesNativeCg, so anyone deriving this from
  // that predicate gets solvent in the coarse structural view, which the feature
  // deliberately excludes. Spelled out, and pinned.
  it('is OFF for cylinders, even though sceneUsesNativeCg includes it', () => {
    expect(sceneUsesNativeCg('cylinders')).toBe(true)
    expect(solventRepMode('cylinders')).toBe('off')
  })

  it('is off for every other repr', () => {
    for (const r of ['surface', 'hull-prism', 'anything', undefined, null])
      expect(solventRepMode(r)).toBe('off')
  })

  // The two modes are different wire payloads (3 vs 9 floats per molecule), so a
  // switch between them must invalidate cached frames rather than just re-render.
  it('distinguishes the two payload shapes', () => {
    expect(solventRepMode('beads')).not.toBe(solventRepMode('ballstick'))
  })
})

describe('restorePlan', () => {
  it('CG design reprs → show the native design, no heavy rebuild', () => {
    for (const r of ['full', 'beads', 'cylinders', 'hull-prism']) {
      expect(restorePlan(r)).toEqual({ showNativeCg: true, rebuildHeavy: false })
    }
  })
  it('atomistic reprs → keep the heavy rep (rebuild), hide the native CG design', () => {
    // The bug this pins: stopping a display in atomistic must NOT show native CG.
    for (const r of ['vdw', 'ballstick']) {
      expect(restorePlan(r)).toEqual({ showNativeCg: false, rebuildHeavy: true })
    }
  })
  it('surface → keep the heavy rep (rebuild), hide the native CG design', () => {
    expect(restorePlan('surface')).toEqual({ showNativeCg: false, rebuildHeavy: true })
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

describe('nextLivePollAction', () => {
  const T = 15000
  it('sends when no poll is outstanding', () => {
    expect(nextLivePollAction({ pending: false, waitedMs: 0, timeoutMs: T })).toBe('send')
    expect(nextLivePollAction({ pending: false, waitedMs: 999999, timeoutMs: T })).toBe('send')
  })
  it('skips (no stacking) while a poll is outstanding within the timeout', () => {
    expect(nextLivePollAction({ pending: true, waitedMs: 0, timeoutMs: T })).toBe('skip')
    expect(nextLivePollAction({ pending: true, waitedMs: T - 1, timeoutMs: T })).toBe('skip')
  })
  it('reports timeout once an outstanding poll passes the deadline', () => {
    expect(nextLivePollAction({ pending: true, waitedMs: T, timeoutMs: T })).toBe('timeout')
    expect(nextLivePollAction({ pending: true, waitedMs: T + 5000, timeoutMs: T })).toBe('timeout')
  })
})

describe('mdReadinessIndicator', () => {
  it('shows a warming state', () => {
    expect(mdReadinessIndicator('warming')).toEqual({ show: true, color: 'warn', text: 'warming…' })
  })
  it('shows a ready state', () => {
    expect(mdReadinessIndicator('ready')).toEqual({ show: true, color: 'ok', text: 'ready' })
  })
  it('shows an error state', () => {
    expect(mdReadinessIndicator('error')).toEqual({ show: true, color: 'err', text: 'error' })
  })
  it('hides for off/unknown/undefined', () => {
    for (const s of ['off', 'idle', undefined, null, 'whatever'])
      expect(mdReadinessIndicator(s).show).toBe(false)
  })

  it('hides remote status because Refresh owns remote readiness', () => {
    for (const t of ['runpod', 'alpine', null, 'something-new'])
      expect(mdReadinessIndicator('remote', t)).toEqual({ show: false, color: 'dim', text: '' })
  })
  it('the target changes only the remote wording, never the other states', () => {
    for (const s of ['warming', 'ready', 'error', 'waiting']) {
      expect(mdReadinessIndicator(s, 'alpine')).toEqual(mdReadinessIndicator(s, 'runpod'))
    }
  })
})

describe('zipAtomIdentity', () => {
  // Three atoms: two on the scaffold (same residue), one on a staple.
  const IDENT = {
    strands:    ['scaf', 'stap7'],
    helices:    ['h0', 'h1'],
    dirs:       ['FORWARD', 'REVERSE'],
    strand_idx: [0, 0, 1],
    helix_idx:  [0, 0, 1],
    dir_idx:    [0, 0, 1],
    bp:         [5, 5, 9],
  }
  const frame = () => [
    { serial: 0, element: 'P', x: 0, y: 0, z: 0 },
    { serial: 1, element: 'O', x: 1, y: 0, z: 0 },
    { serial: 2, element: 'C', x: 2, y: 0, z: 0 },
  ]

  it('gives every atom the identity the colour resolver keys on', () => {
    const atoms = zipAtomIdentity(frame(), IDENT)
    expect(atoms.map(a => a.strand_id)).toEqual(['scaf', 'scaf', 'stap7'])
    expect(atoms.map(a => a.helix_id)).toEqual(['h0', 'h0', 'h1'])
    expect(atoms.map(a => a.direction)).toEqual(['FORWARD', 'FORWARD', 'REVERSE'])
    expect(atoms.map(a => a.bp_index)).toEqual([5, 5, 9])
  })

  it('mutates in place and keeps the coordinates', () => {
    const atoms = frame()
    expect(zipAtomIdentity(atoms, IDENT)).toBe(atoms)
    expect(atoms[2]).toMatchObject({ serial: 2, element: 'C', x: 2 })
  })

  it('leaves atoms alone on a count mismatch rather than mis-assigning strands', () => {
    const atoms = zipAtomIdentity(frame().slice(0, 2), IDENT)
    expect(atoms.every(a => a.strand_id === undefined)).toBe(true)
  })

  it('is a no-op without identity (bead modes, or an unmappable topology)', () => {
    for (const id of [null, undefined, {}]) {
      const atoms = zipAtomIdentity(frame(), id)
      expect(atoms.every(a => a.strand_id === undefined)).toBe(true)
    }
    expect(zipAtomIdentity(null, IDENT)).toBe(null)
  })
})

describe('toBondPairs', () => {
  it('turns the ready message\'s flat serial list into a typed array', () => {
    const out = toBondPairs([0, 1, 1, 2, 3, 4])
    expect(ArrayBuffer.isView(out)).toBe(true)
    expect(Array.from(out)).toEqual([0, 1, 1, 2, 3, 4])
  })

  it('returns null (not []) when there is no topology, so a caller can tell them apart', () => {
    for (const v of [null, undefined, [], [7], 0, '']) {
      expect(toBondPairs(v)).toBe(null)
    }
  })

  it('truncates an odd tail rather than drawing a bond to atom 0', () => {
    // A lone trailing index would otherwise pair with `undefined` → NaN → a bond
    // anchored at the origin, spearing the whole model.
    expect(Array.from(toBondPairs([5, 6, 7]))).toEqual([5, 6])
  })

  it('passes a typed array straight through without recopying', () => {
    const given = Int32Array.from([2, 3])
    expect(toBondPairs(given)).toBe(given)
    expect(toBondPairs(new Int32Array(0))).toBe(null)
  })

  it('keeps large universe-global serials exact (Int32, not Float32)', () => {
    // A solvated origami PSF runs past a million atoms; serial IS the universe index.
    expect(Array.from(toBondPairs([1_048_577, 1_400_003]))).toEqual([1_048_577, 1_400_003])
  })
})

describe('mdDisplayReadinessFromMeta — why the display is empty', () => {
  it('a ready job needs no explanation', () => {
    expect(mdDisplayReadinessFromMeta({ ready: true })).toEqual({ state: 'ready', title: '' })
  })

  it('a remote run delegates its visible state to the Refresh dot', () => {
    const v = mdDisplayReadinessFromMeta({
      ready: false, not_ready_code: 'remote',
      not_ready_reason: 'This run’s trajectory is on the pod, not on this computer.',
    })
    expect(v.state).toBe('remote')
    expect(mdReadinessIndicator(v.state).show).toBe(false)
    expect(v.title).toMatch(/on the pod/)
  })

  it('a local run with no frames yet reads as waiting, not broken', () => {
    const v = mdDisplayReadinessFromMeta({
      ready: false, not_ready_code: 'pending', not_ready_reason: 'no frames yet',
    })
    expect(v.state).toBe('waiting')
    expect(mdReadinessIndicator('waiting')).toMatchObject({ show: true, color: 'dim' })
  })

  it('a finished run that wrote nothing is an error', () => {
    expect(mdDisplayReadinessFromMeta({ ready: false, not_ready_code: 'empty' }).state)
      .toBe('error')
  })

  it('no package is the one honest "nothing to see here"', () => {
    expect(mdDisplayReadinessFromMeta({ ready: false, not_ready_code: 'no_package' }).state)
      .toBe('off')
    expect(mdReadinessIndicator('off').show).toBe(false)
  })

  it('a failed request is an ERROR, not an absence', () => {
    // Saying "off" would claim the display had been assessed and found empty.
    expect(mdDisplayReadinessFromMeta(null).state).toBe('error')
    expect(mdDisplayReadinessFromMeta(undefined).state).toBe('error')
  })

  it('an older backend with no code still hides rather than crying error', () => {
    expect(mdDisplayReadinessFromMeta({ ready: false }).state).toBe('off')
  })

  it('every shown state has a label', () => {
    for (const s of ['warming', 'ready', 'error', 'waiting']) {
      const spec = mdReadinessIndicator(s)
      expect(spec.show).toBe(true)
      expect(spec.text.length).toBeGreaterThan(0)
    }
  })
})

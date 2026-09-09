import { describe, it, expect } from 'vitest'
import { beforeEach, afterEach, vi } from 'vitest'
import {
  solventFetchPlan, estimateShellFraction, SOLVENT_CHUNK,
  initMdSolventControls, tallyIonSpecies, ION_SPECIES,
} from './md_solvent_controls.js'

// Measured from the two real solvated jobs (see memory/project_md_viz_tools.md):
const TEN_HB = { nWatersTotal: 69688, nIons: 1005 }
const VOLTRON = { nWatersTotal: 883685, nIons: 15178 }

const GB = 1024 * 1024 * 1024

describe('estimateShellFraction', () => {
  it('grows with the radius and is bounded to [0,1]', () => {
    expect(estimateShellFraction(0)).toBe(0)
    expect(estimateShellFraction(5)).toBeGreaterThan(estimateShellFraction(4))
    expect(estimateShellFraction(1000)).toBe(1)
    expect(estimateShellFraction(-3)).toBe(0)
  })

  it('lands near the measured 5 A shell (~30% of the cell)', () => {
    expect(estimateShellFraction(5)).toBeCloseTo(0.30, 2)
  })

  it('survives junk input', () => {
    expect(estimateShellFraction(undefined)).toBe(0)
    expect(estimateShellFraction(NaN)).toBe(0)
  })
})

describe('solventFetchPlan', () => {
  describe('needed', () => {
    it('is false when the representation cannot draw solvent', () => {
      expect(solventFetchPlan({ repMode: 'off', water: true }).needed).toBe(false)
    })

    it('is false when every toggle is off', () => {
      expect(solventFetchPlan({ repMode: 'sphere' }).needed).toBe(false)
    })

    it('is true for the box alone', () => {
      expect(solventFetchPlan({ repMode: 'sphere', box: true }).needed).toBe(true)
    })
  })

  describe('payload size', () => {
    it('charges 12 bytes per molecule in sphere mode', () => {
      const p = solventFetchPlan({
        repMode: 'sphere', water: true, scope: 'all', ...TEN_HB, nIons: 0,
        availableBytes: 16 * GB,
      })
      expect(p.atomistic).toBe(false)
      expect(p.bytesPerFrame).toBe(TEN_HB.nWatersTotal * 12)
    })

    // O + 2 H instead of one sphere — three times the payload, which is what makes
    // whole-box atomistic the expensive case.
    it('charges 36 bytes per molecule in atomistic mode', () => {
      const sphere = solventFetchPlan({
        repMode: 'sphere', water: true, scope: 'all', ...TEN_HB, nIons: 0,
        availableBytes: 16 * GB,
      })
      const atom = solventFetchPlan({
        repMode: 'atomistic', water: true, scope: 'all', ...TEN_HB, nIons: 0,
        availableBytes: 16 * GB,
      })
      expect(atom.bytesPerFrame).toBe(sphere.bytesPerFrame * 3)
    })

    it('adds 12 bytes per ion and 96 for the cell', () => {
      const p = solventFetchPlan({
        repMode: 'sphere', ions: true, box: true, ...TEN_HB, availableBytes: 16 * GB,
      })
      expect(p.bytesPerFrame).toBe(TEN_HB.nIons * 12 + 96)
    })

    it('costs nothing for a box-only request beyond the 8 corners', () => {
      expect(solventFetchPlan({ repMode: 'sphere', box: true, ...TEN_HB }).bytesPerFrame)
        .toBe(96)
    })
  })

  describe('the shell is much cheaper than the whole cell', () => {
    it('estimates a fraction of the molecules', () => {
      const shell = solventFetchPlan({
        repMode: 'sphere', water: true, scope: 'shell', shellAng: 5,
        ...TEN_HB, availableBytes: 16 * GB,
      })
      const box = solventFetchPlan({
        repMode: 'sphere', water: true, scope: 'all',
        ...TEN_HB, availableBytes: 16 * GB,
      })
      expect(shell.nWaterEst).toBeLessThan(box.nWaterEst)
      expect(shell.nWaterEst).toBeGreaterThan(0)
    })

    it('a larger radius costs more', () => {
      const opts = { repMode: 'sphere', water: true, scope: 'shell', ...TEN_HB,
        availableBytes: 16 * GB }
      expect(solventFetchPlan({ ...opts, shellAng: 8 }).nWaterEst)
        .toBeGreaterThan(solventFetchPlan({ ...opts, shellAng: 4 }).nWaterEst)
    })
  })

  describe('the memory cap', () => {
    // The whole point: BROWSER_HEAP_CEILING_BYTES is a hard kill, not a slowdown,
    // so an unaffordable request must come back capped rather than be attempted.
    it('caps whole-box atomistic water on a large job', () => {
      const p = solventFetchPlan({
        repMode: 'atomistic', water: true, scope: 'all', ...VOLTRON,
        nFrames: 200, availableBytes: 24 * GB,
      })
      expect(p.capped).toBe(true)
      expect(p.maxWaters).toBeGreaterThan(0)
      expect(p.maxWaters).toBeLessThan(VOLTRON.nWatersTotal)
      expect(p.limitedBy).toBeTruthy()
    })

    it('does not cap a small sphere-mode shell', () => {
      const p = solventFetchPlan({
        repMode: 'sphere', water: true, scope: 'shell', shellAng: 5,
        ...TEN_HB, nFrames: 50, availableBytes: 24 * GB,
      })
      expect(p.capped).toBe(false)
      expect(p.maxWaters).toBeNull()
    })

    it('reports the capped count as the payload size, not the wish', () => {
      const p = solventFetchPlan({
        repMode: 'atomistic', water: true, ions: true, box: true, scope: 'all',
        ...VOLTRON, nFrames: 200, availableBytes: 24 * GB,
      })
      expect(p.bytesPerFrame).toBe(p.maxWaters * 36 + VOLTRON.nIons * 12 + 96)
      expect(p.nWaterEst).toBe(VOLTRON.nWatersTotal)   // the wish is still reported
      // …and the capped payload actually fits the window it was priced for.
      expect(p.bytesPerFrame * SOLVENT_CHUNK).toBeLessThanOrEqual(p.budgetBytes)
    })

    // A machine with almost no free RAM must bind on RAM, not silently use the
    // fixed budget — this is the case that would otherwise kill the tab.
    it('binds on free RAM when that is the tighter limit', () => {
      const p = solventFetchPlan({
        repMode: 'atomistic', water: true, scope: 'all', ...VOLTRON,
        nFrames: 200, availableBytes: 256 * 1024 * 1024,
      })
      expect(p.capped).toBe(true)
      expect(p.limitedBy).toBe('ram')
    })

    it('falls back to the heap ceiling when free RAM is unknown', () => {
      const p = solventFetchPlan({
        repMode: 'atomistic', water: true, scope: 'all', ...VOLTRON,
        nFrames: 200, availableBytes: null,
      })
      expect(p.capped).toBe(true)
      expect(p.limitedBy).toBe('heap')
    })

    it('ions alone are never capped — they are tiny even on the largest job', () => {
      const p = solventFetchPlan({
        repMode: 'atomistic', ions: true, box: true, ...VOLTRON,
        nFrames: 200, availableBytes: null,
      })
      expect(p.capped).toBe(false)
      expect(p.maxWaters).toBeNull()
    })
  })

  it('exposes a chunk size matching the DNA prebuild', () => {
    expect(SOLVENT_CHUNK).toBe(32)
  })

  it('handles a job with no solvent at all', () => {
    const p = solventFetchPlan({ repMode: 'sphere', water: true, ions: true,
      nWatersTotal: 0, nIons: 0 })
    expect(p.nWaterEst).toBe(0)
    expect(p.capped).toBe(false)
    expect(p.bytesPerFrame).toBe(0)
  })
})

// ── live ("Display MD") transport ────────────────────────────────────────────
//
// Two transports feed the same overlay: the REST trajectory route (fetched and
// cached here) and the live WebSocket, which pushes one already-current frame at
// us. These pin the seam — the live view must REQUEST solvent over the socket and
// must never fetch, because its frame index means nothing to the REST route.
describe('live transport', () => {
  const IDS = [
    ['md-jobs-solvent-opts', 'div'], ['md-jobs-water-toggle', 'input'],
    ['md-jobs-water-opts', 'div'], ['md-jobs-water-scope-shell', 'input'],
    ['md-jobs-water-scope-box', 'input'], ['md-jobs-water-shell', 'input'],
    ['md-jobs-water-count', 'div'], ['md-jobs-ions-toggle', 'input'],
    ['md-jobs-ions-legend', 'div'], ['md-jobs-box-toggle', 'input'],
    ['md-jobs-solvent-status', 'div'],
  ]

  let setSolvent, api, made

  beforeEach(() => {
    localStorage.clear()
    for (const [id, tag] of IDS) {
      const el = document.createElement(tag)
      el.id = id
      if (tag === 'input') el.type = id.includes('scope') ? 'radio' : 'checkbox'
      if (id === 'md-jobs-water-shell') { el.type = 'number'; el.value = '5' }
      document.body.appendChild(el)
    }
    document.getElementById('md-jobs-water-scope-shell').checked = true
    setSolvent = vi.fn(() => true)
    api = {
      getMdSolventMeta: vi.fn(async () => ({ ready: true, n_waters: 1000, n_ions: 10,
                                             species: { NA: 8, CL: 1, MG: 1 } })),
      getMdFramesSolventBin: vi.fn(async () => null),
      cancelMdAnalysis: vi.fn(),
    }
    made = initMdSolventControls({
      api,
      getSolventOverlay: () => ({ setIonSpecies: vi.fn(), setMode: vi.fn(), setFrame: vi.fn(),
                                  setWaterVisible: vi.fn(), setIonsVisible: vi.fn(), clear: vi.fn() }),
      getBoxOverlay: () => ({ setCorners: vi.fn(), hide: vi.fn() }),
      getCurrentRepr: () => 'full',
      getLiveDisplay: () => ({ setSolvent }),
    })
  })

  afterEach(() => { document.body.innerHTML = '' })

  it('requests simulation graphene with all optional overlays off and stops on disable', () => {
    const controls = initMdSolventControls({
      api, simulationGraphene: true, getCurrentRepr: () => 'full',
      getLiveDisplay: () => ({ setSolvent }),
    })
    controls.setEnabled(true, 'live')
    expect(setSolvent.mock.calls.at(-1)[0]).toMatchObject({ water: false, ions: false, box: true })
    controls.setEnabled(false)
    expect(setSolvent.mock.calls.at(-1)[0]).toBeNull()
  })

  it('requests solvent over the socket instead of fetching', () => {
    made.setEnabled(true, 'live')
    document.getElementById('md-jobs-box-toggle').checked = true
    document.getElementById('md-jobs-box-toggle').dispatchEvent(new Event('change'))
    expect(setSolvent).toHaveBeenCalled()
    expect(setSolvent.mock.calls.at(-1)[0]).toMatchObject({ box: true })
    // The live frame index is a stream position, not a composite trajectory index —
    // fetching against it would return some other frame's solvent.
    expect(api.getMdFramesSolventBin).not.toHaveBeenCalled()
  })

  it('tells the stream to stop when every toggle goes off', () => {
    made.setEnabled(true, 'live')
    const box = document.getElementById('md-jobs-box-toggle')
    box.checked = true
    box.dispatchEvent(new Event('change'))
    setSolvent.mockClear()
    box.checked = false
    box.dispatchEvent(new Event('change'))
    expect(setSolvent).toHaveBeenCalledWith(null)
  })

  it('tells the stream to stop when the view is disabled', () => {
    made.setEnabled(true, 'live')
    document.getElementById('md-jobs-ions-toggle').checked = true
    document.getElementById('md-jobs-ions-toggle').dispatchEvent(new Event('change'))
    setSolvent.mockClear()
    made.setEnabled(false)
    expect(setSolvent).toHaveBeenCalledWith(null)
  })

  it('forwards the shell radius and the cap in wire (snake_case) form', () => {
    made.setEnabled(true, 'live')
    document.getElementById('md-jobs-water-shell').value = '8'
    const w = document.getElementById('md-jobs-water-toggle')
    w.checked = true
    w.dispatchEvent(new Event('change'))
    const sent = setSolvent.mock.calls.at(-1)[0]
    expect(sent).toHaveProperty('shell_ang', 8)
    expect(sent).toHaveProperty('max_waters')
    expect(sent).not.toHaveProperty('shellAng')
  })

  it('sends shell_ang null for the whole cell', () => {
    made.setEnabled(true, 'live')
    document.getElementById('md-jobs-water-scope-box').checked = true
    document.getElementById('md-jobs-water-scope-shell').checked = false
    const w = document.getElementById('md-jobs-water-toggle')
    w.checked = true
    w.dispatchEvent(new Event('change'))
    expect(setSolvent.mock.calls.at(-1)[0].shell_ang).toBeNull()
  })

  it('ignores a live blob while the trajectory transport is active', () => {
    made.setEnabled(true, 'traj')
    expect(() => made.liveBlob(new ArrayBuffer(8))).not.toThrow()
  })

  it('does not touch the socket in trajectory mode', () => {
    made.setEnabled(true, 'traj')
    document.getElementById('md-jobs-box-toggle').checked = true
    document.getElementById('md-jobs-box-toggle').dispatchEvent(new Event('change'))
    expect(setSolvent).not.toHaveBeenCalled()
  })
})

// A scene-representation change used to invalidate the whole solvent cache and refetch
// unconditionally.  But solventRepMode() collapses the SEVEN scene reps onto THREE modes,
// so most rep changes don't touch the wire format at all — and every buffered frame was
// being re-downloaded for nothing.  These pin which changes really are wire-format flips.
describe('representation change → cache invalidation', () => {
  const IDS = [
    ['md-jobs-solvent-opts', 'div'], ['md-jobs-water-toggle', 'input'],
    ['md-jobs-water-opts', 'div'], ['md-jobs-water-scope-shell', 'input'],
    ['md-jobs-water-scope-box', 'input'], ['md-jobs-water-shell', 'input'],
    ['md-jobs-water-count', 'div'], ['md-jobs-ions-toggle', 'input'],
    ['md-jobs-ions-legend', 'div'], ['md-jobs-box-toggle', 'input'],
    ['md-jobs-solvent-status', 'div'],
  ]

  let api, made, repr

  // Let the not-awaited _fetchAround settle so `_inflight` clears before the next act.
  const settle = () => new Promise(r => setTimeout(r, 0))

  const changeRepr = async (next) => {
    repr = next
    window.dispatchEvent(new CustomEvent('nadoc:representation-change',
                                         { detail: { representation: next } }))
    await settle()
  }

  beforeEach(async () => {
    localStorage.clear()
    for (const [id, tag] of IDS) {
      const el = document.createElement(tag)
      el.id = id
      if (tag === 'input') el.type = id.includes('scope') ? 'radio' : 'checkbox'
      if (id === 'md-jobs-water-shell') { el.type = 'number'; el.value = '5' }
      document.body.appendChild(el)
    }
    document.getElementById('md-jobs-water-scope-shell').checked = true
    repr = 'full'
    api = {
      getMdSolventMeta: vi.fn(async () => ({ ready: true, n_waters: 1000, n_ions: 10,
                                             species: { NA: 8, CL: 1, MG: 1 } })),
      getMdFramesSolventBin: vi.fn(async () => null),
      cancelMdAnalysis: vi.fn(),
    }
    made = initMdSolventControls({
      api,
      getSolventOverlay: () => ({ setIonSpecies: vi.fn(), setMode: vi.fn(), setFrame: vi.fn(),
                                  setWaterVisible: vi.fn(), setIonsVisible: vi.fn(), clear: vi.fn() }),
      getBoxOverlay: () => ({ setCorners: vi.fn(), hide: vi.fn() }),
      getCurrentRepr: () => repr,
      getLiveDisplay: () => ({ setSolvent: vi.fn(() => true) }),
    })
    await made.setJob('job-1', { stride: 1, nFrames: 20 })
    made.setEnabled(true, 'traj')
    document.getElementById('md-jobs-water-toggle').checked = true
    document.getElementById('md-jobs-water-toggle').dispatchEvent(new Event('change'))
    await settle()
    // One fetch has happened for the initial 'sphere' (full) view; count from here.
    expect(api.getMdFramesSolventBin).toHaveBeenCalledTimes(1)
    api.getMdFramesSolventBin.mockClear()
  })

  afterEach(() => { document.body.innerHTML = '' })

  it('does not refetch when the wire mode is unchanged (full → beads, both sphere)', async () => {
    await changeRepr('beads')
    expect(api.getMdFramesSolventBin).not.toHaveBeenCalled()
  })

  it('does not refetch between two reps that both draw no solvent (cylinders → hull-prism)', async () => {
    await changeRepr('cylinders')       // sphere → off: a real change, clears the scene
    api.getMdFramesSolventBin.mockClear()
    await changeRepr('hull-prism')      // off → off: nothing to do
    expect(api.getMdFramesSolventBin).not.toHaveBeenCalled()
  })

  // 3 floats per molecule vs 9 — the payload really is a different shape, so the cached
  // frames are unusable and this one MUST refetch.
  it('refetches when the wire mode flips (full → vdw, sphere → atomistic)', async () => {
    await changeRepr('vdw')
    expect(api.getMdFramesSolventBin).toHaveBeenCalledTimes(1)
    expect(api.getMdFramesSolventBin.mock.calls[0][2]).toMatchObject({ atomistic: true })
  })

  // Same 'atomistic' payload; only whether the overlay draws the O-H bonds differs, which
  // is a redraw of the frames already in hand.
  it('does not refetch on vdw → ballstick', async () => {
    await changeRepr('vdw')
    api.getMdFramesSolventBin.mockClear()
    await changeRepr('ballstick')
    expect(api.getMdFramesSolventBin).not.toHaveBeenCalled()
  })
})

// ── the ion legend ───────────────────────────────────────────────────────────
//
// The legend and the render answered to two different sources of truth: the render
// draws whatever ions MDAnalysis finds in the PSF, while the legend read the counts
// `charge_audit.json` recorded when the package was built. A job whose audit is missing,
// still being written, or whose counter-ion isn't one the audit tracks got a screen full
// of ions under the words "no ions in this job". These pin the precedence that fixes it.

describe('tallyIonSpecies', () => {
  it('counts each species code against the payload\'s own table', () => {
    expect(tallyIonSpecies(Uint8Array.from([0, 0, 2, 1, 2, 2]), ION_SPECIES))
      .toEqual({ NA: 2, CL: 1, MG: 3, K: 0, CA: 0 })
  })

  it('falls back to the canonical table when the payload carries none', () => {
    expect(tallyIonSpecies(Uint8Array.from([3, 4]), null))
      .toEqual({ NA: 0, CL: 0, MG: 0, K: 1, CA: 1 })
  })

  it('reads zero of everything from an empty census', () => {
    expect(tallyIonSpecies(Uint8Array.from([]), ION_SPECIES))
      .toEqual({ NA: 0, CL: 0, MG: 0, K: 0, CA: 0 })
  })

  it('ignores a code the table does not cover', () => {
    expect(tallyIonSpecies(Uint8Array.from([0, 99]), ION_SPECIES).NA).toBe(1)
  })
})

describe('ion legend precedence', () => {
  const MAGIC = 0x4E534C56
  const IDS = [
    ['md-jobs-solvent-opts', 'div'], ['md-jobs-water-toggle', 'input'],
    ['md-jobs-water-opts', 'div'], ['md-jobs-water-scope-shell', 'input'],
    ['md-jobs-water-scope-box', 'input'], ['md-jobs-water-shell', 'input'],
    ['md-jobs-water-count', 'div'], ['md-jobs-ions-toggle', 'input'],
    ['md-jobs-ions-legend', 'div'], ['md-jobs-box-toggle', 'input'],
    ['md-jobs-solvent-status', 'div'],
  ]

  /** One sphere-mode frame carrying `codes.length` ions, in the real wire layout. */
  function packIonFrame(codes) {
    const h = {
      frame_ids: [0], atomistic: false, n_waters_total: 0,
      n_ions: codes.length, n_ions_total: codes.length, has_box: false,
      shell_nm: null, capped: false,
      species_table: ['NA', 'CL', 'MG', 'K', 'CA'],
      ion_species: codes, per_frame_nw: [0], n_serials: 0,
    }
    const hb = new TextEncoder().encode(JSON.stringify(h))
    const pad = (4 - (hb.length % 4)) % 4
    const floats = codes.length * 3
    const buf = new ArrayBuffer(20 + hb.length + pad + floats * 4)
    const dv = new DataView(buf)
    dv.setUint32(0, MAGIC, true); dv.setUint32(4, 2, true)
    dv.setUint32(8, 1, true); dv.setUint32(12, 0, true)
    dv.setUint32(16, hb.length, true)
    new Uint8Array(buf, 20, hb.length).set(hb)
    return buf
  }

  const settle = () => new Promise(r => setTimeout(r, 0))
  const legend = () => document.getElementById('md-jobs-ions-legend')

  let api, made, meta

  /** Turn Ions on and let the (unawaited) fetch land. */
  async function turnIonsOn() {
    const t = document.getElementById('md-jobs-ions-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await settle()
  }

  async function boot() {
    api = {
      getMdSolventMeta: vi.fn(async () => meta),
      getMdFramesSolventBin: vi.fn(async () => null),
      cancelMdAnalysis: vi.fn(),
    }
    made = initMdSolventControls({
      api,
      getSolventOverlay: () => ({ setIonSpecies: vi.fn(), setMode: vi.fn(), setFrame: vi.fn(),
                                  setWaterVisible: vi.fn(), setIonsVisible: vi.fn(), clear: vi.fn() }),
      getBoxOverlay: () => ({ setCorners: vi.fn(), hide: vi.fn() }),
      getCurrentRepr: () => 'full',
      getLiveDisplay: () => ({ setSolvent: vi.fn(() => true) }),
    })
    await made.setJob('job-1', { stride: 1, nFrames: 20 })
    made.setEnabled(true, 'traj')
  }

  beforeEach(() => {
    localStorage.clear()
    for (const [id, tag] of IDS) {
      const el = document.createElement(tag)
      el.id = id
      if (tag === 'input') el.type = id.includes('scope') ? 'radio' : 'checkbox'
      if (id === 'md-jobs-water-shell') { el.type = 'number'; el.value = '5' }
      document.body.appendChild(el)
    }
    document.getElementById('md-jobs-water-scope-shell').checked = true
    meta = { ready: true, n_waters: 1000, n_ions: 10, species: { NA: 8, CL: 1, MG: 1 } }
  })

  afterEach(() => { document.body.innerHTML = '' })

  it('shows the audit counts before any frame has landed', async () => {
    await boot()
    await turnIonsOn()
    expect(legend().style.display).toBe('')
    expect(legend().textContent).toContain('Na⁺ 8')
    expect(legend().textContent).not.toContain('no ions')
  })

  // The regression: a package whose charge audit is missing or half-written answers
  // `{ready:false, species:{}}`. `{}` is truthy, so the panel used to read it as a
  // positive "this job contains nothing" and print the negative claim.
  it('says NOTHING when the audit is not ready', async () => {
    meta = { ready: false, n_waters: 0, n_ions: 0, species: {} }
    await boot()
    await turnIonsOn()
    expect(legend().style.display).toBe('none')
    expect(legend().textContent).not.toContain('no ions')
  })

  it('retries the audit on the next setJob while it is unready', async () => {
    meta = { ready: false, n_waters: 0, n_ions: 0, species: {} }
    await boot()
    expect(api.getMdSolventMeta).toHaveBeenCalledTimes(1)
    meta = { ready: true, n_waters: 1000, n_ions: 3, species: { NA: 0, CL: 0, MG: 3 } }
    await made.setJob('job-1', { stride: 1, nFrames: 20 })   // same job, still fetches
    expect(api.getMdSolventMeta).toHaveBeenCalledTimes(2)
    await turnIonsOn()
    expect(legend().textContent).toContain('Mg²⁺ 3')
  })

  it('stops retrying once the audit is ready', async () => {
    await boot()
    await made.setJob('job-1', { stride: 1, nFrames: 20 })
    expect(api.getMdSolventMeta).toHaveBeenCalledTimes(1)
  })

  it('a landed frame overrides an audit that claims no ions', async () => {
    meta = { ready: true, n_waters: 1000, n_ions: 0, species: { NA: 0, CL: 0, MG: 0 } }
    await boot()
    api.getMdFramesSolventBin.mockResolvedValue(packIonFrame([2, 2, 2]))
    await turnIonsOn()
    expect(legend().style.display).toBe('')
    expect(legend().textContent).toContain('Mg²⁺ 3')
    expect(legend().textContent).not.toContain('no ions')
  })

  // The audit only tracks Na/Cl/Mg. A K+ or Ca2+ job is invisible to it, but the frame
  // carries the real species codes.
  it('reports a species the audit does not track', async () => {
    meta = { ready: true, n_waters: 1000, n_ions: 0, species: { NA: 0, CL: 0, MG: 0 } }
    await boot()
    api.getMdFramesSolventBin.mockResolvedValue(packIonFrame([3, 3]))
    await turnIonsOn()
    expect(legend().textContent).toContain('K⁺ 2')
  })

  // Measured beats estimated in BOTH directions — an audit that over-promises is
  // corrected by the frame too.
  it('a landed frame overrides an audit that over-counts', async () => {
    await boot()
    api.getMdFramesSolventBin.mockResolvedValue(packIonFrame([0, 1]))
    await turnIonsOn()
    expect(legend().textContent).toContain('Na⁺ 1')
    expect(legend().textContent).toContain('Cl⁻ 1')
    expect(legend().textContent).not.toContain('Na⁺ 8')
  })

  it('only claims "no ions" once a frame has actually measured none', async () => {
    meta = { ready: true, n_waters: 1000, n_ions: 0, species: { NA: 0, CL: 0, MG: 0 } }
    await boot()
    api.getMdFramesSolventBin.mockResolvedValue(packIonFrame([]))
    await turnIonsOn()
    expect(legend().textContent).toContain('no ions in this job')
  })
})

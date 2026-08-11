import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'

vi.mock('../api/client.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    patchOverhang: vi.fn(async () => ({})),
    generateOverhangRandomSequence: vi.fn(async () => ({})),
    createOverhangBinding: vi.fn(async () => ({})),
    createConnectionVersion: vi.fn(async () => ({})),
    createAndApplyConnectionVersion: vi.fn(async () => ({})),
    applyConnectionVersion: vi.fn(async () => ({})),
  }
})

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { patchOverhang, generateOverhangRandomSequence, createOverhangBinding } from '../api/client.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

const IDA = 'ovhg_h1_5_5p', IDB = 'ovhg_h2_9_3p'
function design(seqA, seqB) {
  return {
    currentDesign: {
      overhangs: [
        { id: IDA, label: 'OH1', sequence: seqA, sub_domains: [{ id: 'sdA', start_bp_offset: 0, length_bp: 4 }] },
        { id: IDB, label: 'OH2', sequence: seqB, sub_domains: [{ id: 'sdB', start_bp_offset: 0, length_bp: 4 }] },
      ],
      // Backing domains so overhangRcOfPartner (register-aware Gen) can resolve the
      // overhang→domain register. No duplex → it does a full RC over the 4 bp.
      strands: [
        { id: 'sA', domains: [{ helix_id: 'h1', start_bp: 5, end_bp: 8, direction: 'FORWARD', overhang_id: IDA }] },
        { id: 'sB', domains: [{ helix_id: 'h2', start_bp: 9, end_bp: 12, direction: 'FORWARD', overhang_id: IDB }] },
      ],
      overhang_connections: [], overhang_bindings: [],
    },
  }
}
const tick = async () => { await Promise.resolve(); await Promise.resolve() }

describe('overhang connections — per-side Gen, warning, Pair', () => {
  let store
  beforeAll(() => {
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-list': 'div', 'oconn-details': 'div', 'oconn-popover': 'div',
      'oconn-seq-row-a': 'div', 'oconn-seq-input-a': 'input', 'oconn-seq-gen-a': 'button',
      'oconn-seq-row-b': 'div', 'oconn-seq-input-b': 'input', 'oconn-seq-gen-b': 'button',
      'oconn-pair-warning': 'div',
    })
    store = createMockStore(design(null, null))
    initOverhangConnectionsPanel({ store })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // expand
  })

  // Set the design + select both overhangs + a direct (root-to-root) variant.
  function setup(seqA, seqB, { direct = true } = {}) {
    store.setState(design(seqA, seqB))
    const a = document.getElementById('oconn-select-a'); a.value = IDA; a.dispatchEvent(new Event('change'))
    const b = document.getElementById('oconn-select-b'); b.value = IDB; b.dispatchEvent(new Event('change'))
    const variant = direct ? 'root-to-root' : 'root-to-root-ssdna-linker'
    document.querySelector(`#oconn-popover [data-variant="${variant}"]`).dispatchEvent(new Event('click'))
  }
  beforeEach(() => { patchOverhang.mockClear(); generateOverhangRandomSequence.mockClear(); createOverhangBinding.mockClear() })

  it('warns ONLY when the two overhangs share NO complementary region', () => {
    setup('AAAA', 'GGGG')   // RC(AAAA)=TTTT vs GGGG → 0 complementary bases
    const warn = document.getElementById('oconn-pair-warning')
    expect(warn.hidden).toBe(false)
    expect(warn.textContent).toMatch(/no complementary region/i)
  })

  it('no warning when the direct overhangs ARE complementary', () => {
    setup('AAAA', 'TTTT')   // RC(AAAA)=TTTT → complementary
    expect(document.getElementById('oconn-pair-warning').hidden).toBe(true)
  })

  it('no warning on a PARTIAL complementary overlap (a real, partial pairing)', () => {
    setup('AAAA', 'TTGG')   // RC(AAAA)=TTTT vs TTGG → 2 complementary bases
    expect(document.getElementById('oconn-pair-warning').hidden).toBe(true)
  })

  it('Gen on B (direct) fills B with the reverse complement of A', async () => {
    setup('AAAA', null)
    document.getElementById('oconn-seq-gen-b').dispatchEvent(new Event('click'))
    await tick()
    expect(patchOverhang).toHaveBeenCalledWith(IDB, { sequence: 'TTTT' })
    expect(generateOverhangRandomSequence).not.toHaveBeenCalled()
  })

  it('Gen on A when B is empty generates a random sequence', async () => {
    setup(null, null)
    document.getElementById('oconn-seq-gen-a').dispatchEvent(new Event('click'))
    await tick()
    expect(generateOverhangRandomSequence).toHaveBeenCalledWith(IDA)
    expect(patchOverhang).not.toHaveBeenCalled()
  })

  it('Gen stays random for a LINKER type even when the other side has a sequence', async () => {
    setup('AAAA', null, { direct: false })
    document.getElementById('oconn-seq-gen-b').dispatchEvent(new Event('click'))
    await tick()
    expect(generateOverhangRandomSequence).toHaveBeenCalledWith(IDB)
    expect(patchOverhang).not.toHaveBeenCalled()
  })

  it('Connect with only B missing fills B with RC(A), then routes through apply (not the old direct binding)', async () => {
    setup('AAAA', null)
    document.getElementById('oconn-generate').dispatchEvent(new Event('click'))
    await tick()
    // Connect defers the staple re-derivation (apply re-derives once with the final topology).
    expect(patchOverhang).toHaveBeenCalledWith(IDB, { sequence: 'TTTT', deferReassign: true })
    // Connect now creates a version + APPLIES it (backend makes the OverhangBinding
    // at the root sub-domains) — same path as end-to-root, not _createBindingForPair.
    expect(createOverhangBinding).not.toHaveBeenCalled()
  })

  it('Pair with both present but non-complementary overwrites B with RC(A)', async () => {
    setup('AAAA', 'GGGG')
    document.getElementById('oconn-generate').dispatchEvent(new Event('click'))
    await tick()
    expect(patchOverhang).toHaveBeenCalledWith(IDB, { sequence: 'TTTT', deferReassign: true })
  })

  it('Pair with neither present generates A then sets B = RC(A)', async () => {
    // mock the random gen to actually assign A so _pair can read it back + RC it
    generateOverhangRandomSequence.mockImplementationOnce(async () => {
      store.setState(design('AAAA', null))
    })
    setup(null, null)
    document.getElementById('oconn-generate').dispatchEvent(new Event('click'))
    await tick()
    expect(generateOverhangRandomSequence).toHaveBeenCalledWith(IDA, { deferReassign: true })
    expect(patchOverhang).toHaveBeenCalledWith(IDB, { sequence: 'TTTT', deferReassign: true })
  })
})

import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'

vi.mock('../api/client.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    patchOverhang: vi.fn(async () => ({})),
    generateOverhangRandomSequence: vi.fn(async () => ({})),
    createOverhangBinding: vi.fn(async () => ({})),
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
      strands: [], overhang_connections: [], overhang_bindings: [],
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

  it('warns when both direct overhangs have non-complementary sequences', () => {
    setup('AAAA', 'GGGG')   // RC(AAAA)=TTTT ≠ GGGG → not complementary
    const warn = document.getElementById('oconn-pair-warning')
    expect(warn.hidden).toBe(false)
    expect(warn.textContent).toMatch(/not complementary/i)
  })

  it('no warning when the direct overhangs ARE complementary', () => {
    setup('AAAA', 'TTTT')   // RC(AAAA)=TTTT → complementary
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

  it('Pair with only B missing fills B with RC(A) and creates the binding', async () => {
    setup('AAAA', null)
    document.getElementById('oconn-generate').dispatchEvent(new Event('click'))
    await tick()
    expect(patchOverhang).toHaveBeenCalledWith(IDB, { sequence: 'TTTT' })
    expect(createOverhangBinding).toHaveBeenCalledWith({ sub_domain_a_id: 'sdA', sub_domain_b_id: 'sdB' })
  })

  it('Pair with both present but non-complementary overwrites B with RC(A)', async () => {
    setup('AAAA', 'GGGG')
    document.getElementById('oconn-generate').dispatchEvent(new Event('click'))
    await tick()
    expect(patchOverhang).toHaveBeenCalledWith(IDB, { sequence: 'TTTT' })
  })

  it('Pair with neither present generates A then sets B = RC(A)', async () => {
    // mock the random gen to actually assign A so _pair can read it back + RC it
    generateOverhangRandomSequence.mockImplementationOnce(async () => {
      store.setState(design('AAAA', null))
    })
    setup(null, null)
    document.getElementById('oconn-generate').dispatchEvent(new Event('click'))
    await tick()
    expect(generateOverhangRandomSequence).toHaveBeenCalledWith(IDA)
    expect(patchOverhang).toHaveBeenCalledWith(IDB, { sequence: 'TTTT' })
  })
})

/**
 * Tests for strand_sequence_dialog — the strand right-click "Edit sequence…" dialog.
 * The pure cores live in strand_sequence_pairing.js and are tested there; here we
 * cover the factory wiring (jsdom). createModal/createButton are stubbed, but the
 * real body element is kept so the rendered rows can be asserted on.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const modalOpen = vi.fn()
const modalClose = vi.fn()
let lastModalOpts = null
vi.mock('./primitives/modal.js', () => ({
  createModal: vi.fn((opts) => {
    lastModalOpts = opts
    return { open: modalOpen, close: modalClose, isOpen: () => true, body: opts.body }
  }),
}))
// createButton returns an object whose .click() invokes the wired onClick, and
// which carries a real `disabled` field so the Apply-gating assertions work.
vi.mock('./primitives/button.js', () => ({
  createButton: vi.fn(({ label, onClick }) => ({
    label, disabled: false, style: {}, __onClick: onClick, click: () => onClick?.(),
  })),
}))

import { initStrandSequenceDialog } from './strand_sequence_dialog.js'
import { createButton } from './primitives/button.js'

// A staple over an 8-bp scaffold: partner CCCCAAAA, correct complement GGGGTTTT.
const DUPLEX_CTX = {
  strand_id: 'stap', strand_type: 'staple', is_scaffold: false,
  length: 8, sequence: null, derived: 'GGGGTTTT', partner: 'CCCCAAAA',
  segments: [{ start: 0, length: 8, kind: 'duplex', overhang_id: null, editable: true }],
}

// 8 duplex nt + an 8-nt overhang tip.
const OVERHANG_CTX = {
  strand_id: 'stap', strand_type: 'staple', is_scaffold: false,
  length: 16, sequence: 'GGGGTTTTCCCCAAAA', derived: 'GGGGTTTTCCCCAAAA',
  partner: 'CCCCAAAA--------',
  segments: [
    { start: 0, length: 8, kind: 'duplex', overhang_id: null, editable: true },
    { start: 8, length: 8, kind: 'overhang', overhang_id: 'oh_a', editable: true },
  ],
}

const SCAFFOLD_CTX = {
  strand_id: 'scaf', strand_type: 'scaffold', is_scaffold: true,
  length: 8, sequence: 'AAAACCCC', derived: null, partner: '--------',
  segments: [{ start: 0, length: 8, kind: 'duplex', overhang_id: null, editable: true }],
}

function setup(ctx, { patchResult = { ok: true } } = {}) {
  const api = {
    getStrandSequenceContext: vi.fn(async () => ctx),
    patchStrand: vi.fn(async () => patchResult),
  }
  const showToast = vi.fn()
  const dlg = initStrandSequenceDialog({ api, showToast })
  return { dlg, api, showToast }
}

const btn = (label) => createButton.mock.results
  .map(r => r.value).filter(Boolean).find(b => b.label === label)

const body       = () => lastModalOpts.body
const textarea   = () => body().querySelector('textarea')
const partnerRow = () => body().querySelector('.seqdlg__row--partner')
const statusEl   = () => body().querySelector('.seqdlg__status')
const errorEl    = () => body().querySelector('.seqdlg__error')
const noteEl     = () => body().querySelector('.seqdlg__note')

beforeEach(() => {
  vi.clearAllMocks()
  lastModalOpts = null
  document.body.innerHTML = ''
})

describe('opening', () => {
  it('fetches the context for the requested strand and opens the modal', async () => {
    const { dlg, api } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    expect(api.getStrandSequenceContext).toHaveBeenCalledWith('stap')
    expect(modalOpen).toHaveBeenCalled()
  })

  it('prefills the derived sequence when the strand has none yet', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    expect(textarea().value).toBe('GGGGTTTT')
  })

  it('prefills the existing sequence in preference to the derived one', async () => {
    const { dlg } = setup({ ...DUPLEX_CTX, sequence: 'AAAAAAAA' })
    await dlg.open('stap')
    expect(textarea().value).toBe('AAAAAAAA')
  })

  it('renders the paired scaffold bases above the field', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    expect(partnerRow().textContent).toBe('CCCCAAAA')
  })

  it('hides the partner row when nothing pairs (scaffold strand)', async () => {
    const { dlg } = setup(SCAFFOLD_CTX)
    await dlg.open('scaf')
    expect(partnerRow().style.display).toBe('none')
  })

  it('does nothing without a strand id', async () => {
    const { dlg, api } = setup(DUPLEX_CTX)
    await dlg.open(null)
    expect(api.getStrandSequenceContext).not.toHaveBeenCalled()
  })

  it('toasts instead of throwing when the context fetch fails', async () => {
    const api = {
      getStrandSequenceContext: vi.fn(async () => { throw new Error('boom') }),
      patchStrand: vi.fn(),
    }
    const showToast = vi.fn()
    await initStrandSequenceDialog({ api, showToast }).open('stap')
    expect(showToast).toHaveBeenCalled()
    expect(modalOpen).not.toHaveBeenCalled()
  })
})

describe('live mismatch feedback', () => {
  it('reports all-paired for the derived sequence', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    expect(statusEl().textContent).toContain('8/8 nt')
    expect(statusEl().textContent).toContain('all paired')
  })

  it('counts mismatches as the user types', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'AGGGTATT'          // two positions broken
    textarea().dispatchEvent(new Event('input'))
    expect(statusEl().textContent).toContain('2 mismatches')
  })

  it('singularises a lone mismatch', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'AGGGTTTT'
    textarea().dispatchEvent(new Event('input'))
    expect(statusEl().textContent).toContain('1 mismatch')
    expect(statusEl().textContent).not.toContain('mismatches')
  })

  it('marks the offending scaffold characters, not the matching ones', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'AGGGTTTT'
    textarea().dispatchEvent(new Event('input'))
    const flagged = [...partnerRow().querySelectorAll('.seqdlg__ch--mismatch')]
      .map(s => s.textContent).join('')
    expect(flagged).toBe('C')              // only position 0
  })

  it('leaves Apply enabled when there are mismatches — any bases are allowed', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'AAAAAAAA'
    textarea().dispatchEvent(new Event('input'))
    expect(btn('Apply').disabled).toBe(false)
  })

  it('disables Apply and explains when the length is wrong', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'GGGG'
    textarea().dispatchEvent(new Event('input'))
    expect(btn('Apply').disabled).toBe(true)
    expect(errorEl().textContent).toContain('8')
  })

  it('disables Apply on an invalid character', async () => {
    const { dlg } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'GGGGTTTX'
    textarea().dispatchEvent(new Event('input'))
    expect(btn('Apply').disabled).toBe(true)
    expect(errorEl().textContent).toContain('X')
  })
})

describe('applying', () => {
  it('sends the normalized sequence and closes', async () => {
    const { dlg, api } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = ' aaaa aaaa '
    await btn('Apply').__onClick()
    expect(api.patchStrand).toHaveBeenCalledWith('stap', { sequence: 'AAAAAAAA' })
    expect(modalClose).toHaveBeenCalled()
  })

  it('reads the field at click time, not from a prior input event (LESSONS H4)', async () => {
    const { dlg, api } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    // Value changed with NO input event fired — a blur-commit race would miss this.
    textarea().value = 'TTTTTTTT'
    await btn('Apply').__onClick()
    expect(api.patchStrand).toHaveBeenCalledWith('stap', { sequence: 'TTTTTTTT' })
  })

  it('does not call the API when the length is wrong', async () => {
    const { dlg, api } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'GGG'
    await btn('Apply').__onClick()
    expect(api.patchStrand).not.toHaveBeenCalled()
    expect(modalClose).not.toHaveBeenCalled()
    expect(errorEl().textContent).toContain('8')
  })

  it('keeps the dialog open and shows the error when the API rejects', async () => {
    const api = {
      getStrandSequenceContext: vi.fn(async () => DUPLEX_CTX),
      patchStrand: vi.fn(async () => { throw new Error('422 bad length') }),
    }
    const dlg = initStrandSequenceDialog({ api, showToast: vi.fn() })
    await dlg.open('stap')
    await btn('Apply').__onClick()
    expect(modalClose).not.toHaveBeenCalled()
    expect(errorEl().textContent).toContain('422')
    expect(btn('Apply').disabled).toBe(false)
  })

  it('treats a null response (client.js failure signal) as an error', async () => {
    const { dlg } = setup(DUPLEX_CTX, { patchResult: null })
    await dlg.open('stap')
    await btn('Apply').__onClick()
    expect(modalClose).not.toHaveBeenCalled()
    expect(errorEl().textContent).toBeTruthy()
  })

  it('toasts the mismatch count on success', async () => {
    const { dlg, showToast } = setup(DUPLEX_CTX)
    await dlg.open('stap')
    textarea().value = 'AAAAAAAA'
    await btn('Apply').__onClick()
    expect(showToast.mock.calls[0][0]).toContain('mismatch')
  })
})

describe('overhang spans', () => {
  it('shades the overhang run in the partner row', async () => {
    const { dlg } = setup(OVERHANG_CTX)
    await dlg.open('stap')
    const shaded = [...partnerRow().querySelectorAll('.seqdlg__ch--overhang')]
      .map(s => s.textContent).join('')
    expect(shaded).toBe('--------')
  })

  it('explains that the overhang is written back', async () => {
    const { dlg } = setup(OVERHANG_CTX)
    await dlg.open('stap')
    expect(noteEl().textContent).toContain('writes them back')
  })

  it('sends an edited overhang span straight through', async () => {
    const { dlg, api } = setup(OVERHANG_CTX)
    await dlg.open('stap')
    textarea().value = 'GGGGTTTT' + 'TTTTTTTT'
    await btn('Apply').__onClick()
    expect(api.patchStrand).toHaveBeenCalledWith('stap', { sequence: 'GGGGTTTTTTTTTTTT' })
  })

  it('restores a read-only overhang span, so the two stores cannot desync', async () => {
    const locked = {
      ...OVERHANG_CTX,
      segments: [OVERHANG_CTX.segments[0], { ...OVERHANG_CTX.segments[1], editable: false }],
    }
    const { dlg, api } = setup(locked)
    await dlg.open('stap')
    textarea().value = 'GGGGTTTT' + 'TTTTTTTT'   // user typed over the locked tip
    await btn('Apply').__onClick()
    expect(api.patchStrand).toHaveBeenCalledWith('stap', { sequence: 'GGGGTTTTCCCCAAAA' })
  })

  it('points at the Domain Designer for an override-backed overhang', async () => {
    const locked = {
      ...OVERHANG_CTX,
      segments: [OVERHANG_CTX.segments[0], { ...OVERHANG_CTX.segments[1], editable: false }],
    }
    const { dlg } = setup(locked)
    await dlg.open('stap')
    expect(noteEl().textContent).toContain('Domain Designer')
  })
})

describe('reset to derived', () => {
  it('loads the derived sequence back into the field', async () => {
    const { dlg } = setup({ ...DUPLEX_CTX, sequence: 'AAAAAAAA' })
    await dlg.open('stap')
    expect(textarea().value).toBe('AAAAAAAA')
    btn('Reset to derived').click()
    expect(textarea().value).toBe('GGGGTTTT')
    expect(statusEl().textContent).toContain('all paired')
  })

  it('is hidden when there is nothing to derive from', async () => {
    const { dlg } = setup(SCAFFOLD_CTX)
    await dlg.open('scaf')
    expect(btn('Reset to derived').style.display).toBe('none')
  })
})

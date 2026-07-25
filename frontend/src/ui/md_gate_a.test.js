import { describe, it, expect, afterEach } from 'vitest'
import { gateAMessage, openGateAModal } from './md_gate_a.js'

const A1 = { skipped: false, tier: 'a1', vram_mb: 12288, recommended_shell_nm: 1.5 }
const A2 = { skipped: false, tier: 'a2', vram_mb: 12288, recommended_shell_nm: 1.1, estimated_atoms: 1_800_000 }
const A3 = { skipped: false, tier: 'a3', vram_mb: 12288, tightest_shell_nm: 0.8, tightest_atoms: 9_000_000, required_vram_mb: 34_000 }

// ── Pure message builder ────────────────────────────────────────────────────────

describe('gateAMessage', () => {
  it('no gate for ok / skipped / missing', () => {
    expect(gateAMessage({ tier: 'ok' })).toBeNull()
    expect(gateAMessage({ skipped: true, tier: 'ok' })).toBeNull()
    expect(gateAMessage(null)).toBeNull()
  })
  it('A1 → a non-blocking notice (auto-fit), no modal fields', () => {
    const m = gateAMessage(A1)
    expect(m.isNotice).toBe(true)
    expect(m.notice).toMatch(/15 Å water jacket/i)
    expect(m.canProceed).toBeUndefined()
  })
  it('A2 → a proceed/cancel decision naming the tight shell', () => {
    const m = gateAMessage(A2)
    expect(m.canProceed).toBe(true)
    expect(m.proceedLabel).toMatch(/11 Å/)
    expect(m.lines.join(' ')).toMatch(/tighter than the usual 15 Å/i)
  })
  it('A3 → a hard stop (no proceed)', () => {
    const m = gateAMessage(A3)
    expect(m.canProceed).toBe(false)
    expect(m.title).toMatch(/too large/i)
    expect(m.lines.join(' ')).toMatch(/33\.2 GB of GPU memory/)   // 34000 MB / 1024
  })
})

// ── DOM modal (promise-based) ───────────────────────────────────────────────────

describe('openGateAModal (DOM)', () => {
  afterEach(() => { document.body.innerHTML = '' })
  const modal = () => document.querySelector('[data-testid="gate-a-modal"]')
  const btn = (choice) => document.querySelector(`[data-testid="gate-a-modal"] button[data-choice="${choice}"]`)

  it('A1 / ok resolve true with no modal', async () => {
    await expect(openGateAModal(A1)).resolves.toBe(true)
    await expect(openGateAModal({ tier: 'ok' })).resolves.toBe(true)
    expect(modal()).toBeNull()
  })
  it('A2 accept → resolves true; the modal shows both buttons', async () => {
    const p = openGateAModal(A2)
    expect(modal().dataset.tier).toBe('a2')
    expect(btn('proceed')).toBeTruthy()
    btn('proceed').click()
    await expect(p).resolves.toBe(true)
    expect(modal()).toBeNull()
  })
  it('A2 cancel → resolves false', async () => {
    const p = openGateAModal(A2)
    btn('cancel').click()
    await expect(p).resolves.toBe(false)
  })
  it('A3 hard stop → only a Close button, resolves false', async () => {
    const p = openGateAModal(A3)
    expect(btn('proceed')).toBeNull()
    expect(btn('cancel').textContent).toBe('Close')
    btn('cancel').click()
    await expect(p).resolves.toBe(false)
  })
  it('Escape resolves false', async () => {
    const p = openGateAModal(A2)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(p).resolves.toBe(false)
    expect(modal()).toBeNull()
  })
})

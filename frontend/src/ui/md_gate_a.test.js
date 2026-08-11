import { describe, it, expect, afterEach } from 'vitest'
import { gateAMessage, openGateAModal } from './md_gate_a.js'

const A3 = {
  skipped: false,
  tier: 'a3',
  vram_mb: 12_288,
  current_atoms: 9_000_000,
  current_vram_mb: 34_000,
}

describe('gateAMessage', () => {
  it('has no gate for a fitting, skipped, or missing estimate', () => {
    expect(gateAMessage({ tier: 'ok' })).toBeNull()
    expect(gateAMessage({ skipped: true, tier: 'ok' })).toBeNull()
    expect(gateAMessage(null)).toBeNull()
  })

  it('hard-stops a fully solvated system that does not fit', () => {
    const m = gateAMessage(A3)
    expect(m.canProceed).toBe(false)
    expect(m.title).toMatch(/fully solvated system does not fit/i)
    expect(m.lines.join(' ')).toMatch(/33\.2 GB/)
    expect(m.lines.join(' ')).toMatch(/implicit-solvent protocol/i)
  })
})

describe('openGateAModal', () => {
  afterEach(() => { document.body.innerHTML = '' })
  const modal = () => document.querySelector('[data-testid="gate-a-modal"]')
  const btn = (choice) => document.querySelector(
    `[data-testid="gate-a-modal"] button[data-choice="${choice}"]`,
  )

  it('lets a fitting estimate pass without a modal', async () => {
    await expect(openGateAModal({ tier: 'ok' })).resolves.toBe(true)
    expect(modal()).toBeNull()
  })

  it('shows only Close for an oversized full box', async () => {
    const p = openGateAModal(A3)
    expect(modal().dataset.tier).toBe('a3')
    expect(btn('proceed')).toBeNull()
    expect(btn('cancel').textContent).toBe('Close')
    btn('cancel').click()
    await expect(p).resolves.toBe(false)
  })

  it('Escape resolves false', async () => {
    const p = openGateAModal(A3)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(p).resolves.toBe(false)
    expect(modal()).toBeNull()
  })
})

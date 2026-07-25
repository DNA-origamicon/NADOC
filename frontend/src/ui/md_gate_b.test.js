import { describe, it, expect, afterEach, vi } from 'vitest'
import { gateBMessage, hasPendingGpuDecision, openGpuDecisionModal } from './md_gate_b.js'

const DECISION = {
  gate: 'gpu_resident', severity: 'decision',
  title: "Couldn't use the fastest GPU mode",
  message: 'It can still finish in a slower GPU mode — about 3× longer.',
  technical_reason: 'FATAL ERROR: CUDA error … buildTileLists …',
  retry_hint: true, degrade_target: 'offload',
  checks: [
    { label: 'GPU found', ok: true },
    { label: 'Fastest GPU mode started', ok: false },
  ],
  options: [
    { id: 'offload', label: 'Run in slower GPU mode', primary: true },
    { id: 'cancel', label: 'Cancel', primary: false },
  ],
}

// ── Pure predicate ─────────────────────────────────────────────────────────────

describe('hasPendingGpuDecision', () => {
  it('true only for a paused job with a gpu_resident decision', () => {
    expect(hasPendingGpuDecision({ status: 'paused', decision: DECISION })).toBe(true)
    expect(hasPendingGpuDecision({ status: 'running', decision: DECISION })).toBe(false)
    expect(hasPendingGpuDecision({ status: 'paused', decision: null })).toBe(false)
    expect(hasPendingGpuDecision({ status: 'paused', decision: { gate: 'other' } })).toBe(false)
    expect(hasPendingGpuDecision(undefined)).toBe(false)
  })
})

// ── Pure message builder ───────────────────────────────────────────────────────

describe('gateBMessage', () => {
  it('derives title, message, checks and options from the payload', () => {
    const m = gateBMessage(DECISION)
    expect(m.title).toBe(DECISION.title)
    expect(m.lines[0]).toBe(DECISION.message)
    expect(m.checks).toHaveLength(2)
    expect(m.options.map(o => o.id)).toEqual(['offload', 'cancel'])
    expect(m.technicalReason).toContain('buildTileLists')
  })
  it('adds a newer-build line when retry_hint is set', () => {
    expect(gateBMessage(DECISION).lines.some(l => /newer NAMD build/i.test(l))).toBe(true)
    expect(gateBMessage({ ...DECISION, retry_hint: false }).lines
      .some(l => /newer NAMD build/i.test(l))).toBe(false)
  })
  it('falls back to a single Close option for a malformed payload', () => {
    const m = gateBMessage({})
    expect(m.options).toEqual([{ id: 'cancel', label: 'Close', primary: false }])
    expect(m.checks).toEqual([])
  })
})

// ── DOM modal ──────────────────────────────────────────────────────────────────

describe('openGpuDecisionModal (DOM)', () => {
  afterEach(() => { document.body.innerHTML = '' })

  const btn = (choice) =>
    document.querySelector(`[data-testid="gpu-decision-modal"] button[data-choice="${choice}"]`)

  it('renders the decision with a button per option', () => {
    openGpuDecisionModal({ decision: DECISION })
    expect(document.querySelector('[data-testid="gpu-decision-modal"]')).toBeTruthy()
    expect(btn('offload').textContent).toMatch(/slower GPU mode/i)
    expect(btn('cancel')).toBeTruthy()
    // check-trail renders both marks
    expect(document.body.textContent).toContain('Fastest GPU mode started')
  })

  it('calls onChoose with the option id, then closes', async () => {
    const onChoose = vi.fn().mockResolvedValue({ ok: true })
    openGpuDecisionModal({ decision: DECISION, onChoose })
    btn('offload').click()
    await Promise.resolve(); await Promise.resolve()
    expect(onChoose).toHaveBeenCalledWith('offload')
    expect(document.querySelector('[data-testid="gpu-decision-modal"]')).toBeNull()
  })

  it('shows an inline error and stays open when the choice fails', async () => {
    const onChoose = vi.fn().mockRejectedValue(new Error('nope'))
    openGpuDecisionModal({ decision: DECISION, onChoose })
    btn('offload').click()
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(document.querySelector('[data-testid="gpu-decision-modal"]')).toBeTruthy()
    expect(document.body.textContent).toMatch(/Couldn.t apply that choice/i)
  })

  it('Escape dismisses (hide) and fires onDismiss, not onChoose', () => {
    const onDismiss = vi.fn(); const onChoose = vi.fn()
    openGpuDecisionModal({ decision: DECISION, onChoose, onDismiss })
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(document.querySelector('[data-testid="gpu-decision-modal"]')).toBeNull()
    expect(onDismiss).toHaveBeenCalledTimes(1)
    expect(onChoose).not.toHaveBeenCalled()
  })
})

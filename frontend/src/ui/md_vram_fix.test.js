import { describe, it, expect, afterEach } from 'vitest'
import { shouldShowFixButton, fixMessage, openVramFixModal } from './md_vram_fix.js'

const VRAM_OK = {
  failure_kind: 'vram_oom', remedy: 'downsize',
  is_vram_failure: true, vram_detected: true, profile_available: true,
  vram_mb: 12288, current_atoms: 8_859_879, current_vram_mb: 29200,
  max_atoms: 3_160_000, feasible: true, recommended_shell_nm: 1.5,
  estimated_atoms: 1_310_000, estimated_vram_mb: 4300,
  log_excerpt: 'FATAL ERROR: ... out of memory',
}
const INSTABILITY = {
  failure_kind: 'instability', remedy: 'gentle',
  error: 'NAMD failed for X', log_excerpt: 'Constraint failure in RATTLE',
}
const GPU_ERR = {
  failure_kind: 'gpu_error', remedy: 'retry',
  error: 'NAMD failed', log_excerpt: 'CUDA error buildTileLists',
}

const TIMESTEP_PINNED = {
  failure_kind: 'timestep_pinned', remedy: 'none',
  error: '4 fs production was pinned in the Advanced card, but this package was built '
       + 'with the declash ladder (crossover extra bases / extensions), which never '
       + 'builds the hydrogen-mass-repartitioned PSF that rigidBonds-all 4 fs requires.',
  log_excerpt: null,
}

describe('fixMessage — pinned production timestep', () => {
  it('uses the "ended prematurely" title so a stopped run is unmistakable', () => {
    expect(fixMessage(TIMESTEP_PINNED).title).toBe('NAMD run ended prematurely')
  })

  it('leads with the server\'s specific reason, not a generic string', () => {
    const m = fixMessage(TIMESTEP_PINNED)
    expect(m.lines[0]).toBe(TIMESTEP_PINNED.error)
    expect(m.lines.join(' ')).toMatch(/declash/i)
  })

  it('falls back to a readable line when the server sent no error text', () => {
    const m = fixMessage({ failure_kind: 'timestep_pinned', remedy: 'none' })
    expect(m.lines[0]).toMatch(/cannot run on this package/i)
  })

  it('offers NO one-click apply — a remedy here would recreate the silent downgrade', () => {
    const m = fixMessage(TIMESTEP_PINNED)
    expect(m.canApply).toBe(false)
    expect(m.action).toBeNull()
  })

  it('names both ways out: re-prep for 4 fs, or pin 1 fs', () => {
    const body = fixMessage(TIMESTEP_PINNED).lines.join(' ')
    expect(body).toMatch(/geometric \+ Fix B/i)
    expect(body).toMatch(/1 fs/)
  })

  it('still gets a Fix button, so the failure is reachable from the job list', () => {
    expect(shouldShowFixButton({ status: 'failed', failure_kind: 'timestep_pinned' })).toBe(true)
  })
})

describe('shouldShowFixButton', () => {
  it('shows for any failed job that has a classified failure kind', () => {
    expect(shouldShowFixButton({ status: 'failed', failure_kind: 'vram_oom' })).toBe(true)
    expect(shouldShowFixButton({ status: 'failed', failure_kind: 'instability' })).toBe(true)
    expect(shouldShowFixButton({ status: 'failed', failure_kind: 'other' })).toBe(true)
    expect(shouldShowFixButton({ status: 'failed', failure_kind: null })).toBe(false)
    expect(shouldShowFixButton({ status: 'running', failure_kind: 'vram_oom' })).toBe(false)
    expect(shouldShowFixButton(undefined)).toBe(false)
  })
})

describe('fixMessage', () => {
  it('vram_oom feasible → downsize refit with the recommended shell', () => {
    const m = fixMessage(VRAM_OK)
    expect(m.canApply).toBe(true)
    expect(m.shellAng).toBe(15)
    expect(m.action).toEqual({ type: 'refit', body: {} })
    expect(m.applyLabel).toContain('15 Å')
    expect(m.lines.join(' ')).toMatch(/8,859,879 atoms/)
  })

  it('vram_oom infeasible → no apply', () => {
    const m = fixMessage({
      ...VRAM_OK, remedy: 'none', feasible: false, recommended_shell_nm: null,
      tightest_shell_nm: 0.8, tightest_atoms: 5_000_000, required_vram_mb: 19400,
    })
    expect(m.canApply).toBe(false)
    expect(m.lines.join(' ')).toMatch(/too large for this GPU/)
  })

  it('instability → gentle refit (force_soft)', () => {
    const m = fixMessage(INSTABILITY)
    expect(m.canApply).toBe(true)
    expect(m.action).toEqual({ type: 'refit', body: { force_soft: true } })
    expect(m.applyLabel).toMatch(/gentle/i)
    expect(m.shellAng).toBeUndefined()    // no shell input for this remedy
  })

  it('gpu_error → retry (resume)', () => {
    const m = fixMessage(GPU_ERR)
    expect(m.canApply).toBe(true)
    expect(m.action).toEqual({ type: 'retry' })
    expect(m.applyLabel).toMatch(/Retry/i)
  })

  it('host_oom → retry, and does NOT claim GPU memory', () => {
    const m = fixMessage({ failure_kind: 'host_oom', remedy: 'retry', log_excerpt: 'cudaHostAlloc' })
    expect(m.canApply).toBe(true)
    expect(m.action).toEqual({ type: 'retry' })
    expect(m.title).toMatch(/host|CPU/i)
    // Must not offer a water-shell / shell input (wrong remedy for a host OOM).
    expect(m.shellAng).toBeUndefined()
    expect(m.lines.join(' ')).toMatch(/host|CPU RAM|pinned/i)
  })

  it('other → no apply, surfaces the error + log', () => {
    const m = fixMessage({ failure_kind: 'other', remedy: 'none', error: 'boom', log_excerpt: 'X' })
    expect(m.canApply).toBe(false)
    expect(m.logExcerpt).toBe('X')
  })

  it('vram could not be read → no apply', () => {
    const m = fixMessage({ failure_kind: 'vram_oom', remedy: 'none', vram_detected: false })
    expect(m.canApply).toBe(false)
    expect(m.title).toMatch(/Could not read GPU/)
  })
})

describe('openVramFixModal (DOM)', () => {
  afterEach(() => { document.body.innerHTML = '' })

  function applyBtn(modal, re) {
    return [...modal.querySelectorAll('button')].find(b => re.test(b.textContent))
  }

  it('downsize: edits shell and refits with water_shell_nm in nm', async () => {
    let action = null
    openVramFixModal({ advice: VRAM_OK, onApply: async (a) => { action = a } })
    const modal = document.querySelector('[data-testid="vram-fix-modal"]')
    const input = modal.querySelector('input[type="number"]')
    expect(input.value).toBe('15')
    input.value = '12'
    applyBtn(modal, /Re-run/).click()
    await new Promise(r => setTimeout(r, 0))
    expect(action).toEqual({ type: 'refit', body: { water_shell_nm: 1.2 } })
    expect(document.querySelector('[data-testid="vram-fix-modal"]')).toBeFalsy()
  })

  it('instability: applies force_soft refit, no shell input', async () => {
    let action = null
    openVramFixModal({ advice: INSTABILITY, onApply: async (a) => { action = a } })
    const modal = document.querySelector('[data-testid="vram-fix-modal"]')
    expect(modal.querySelector('input[type="number"]')).toBeFalsy()
    applyBtn(modal, /gentle/i).click()
    await new Promise(r => setTimeout(r, 0))
    expect(action).toEqual({ type: 'refit', body: { force_soft: true } })
  })

  it('gpu_error: applies a retry action', async () => {
    let action = null
    openVramFixModal({ advice: GPU_ERR, onApply: async (a) => { action = a } })
    const modal = document.querySelector('[data-testid="vram-fix-modal"]')
    applyBtn(modal, /Retry/).click()
    await new Promise(r => setTimeout(r, 0))
    expect(action).toEqual({ type: 'retry' })
  })

  it('renders the log excerpt and shows only Close when not fixable', () => {
    openVramFixModal({ advice: { failure_kind: 'other', remedy: 'none', error: 'boom', log_excerpt: 'TRACE LINE' } })
    const modal = document.querySelector('[data-testid="vram-fix-modal"]')
    expect(modal.querySelector('pre').textContent).toContain('TRACE LINE')
    const labels = [...modal.querySelectorAll('button')].map(b => b.textContent)
    expect(labels).toContain('Close')
    expect(labels.some(t => /Re-run|Retry/.test(t))).toBe(false)
  })
})

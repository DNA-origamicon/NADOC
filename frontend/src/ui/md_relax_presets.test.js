import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  initRelaxPresets, pickInitial, noteFor, applyDefaultsTo, presetIdForProtocol,
  PRESET_FALLBACK,
} from './md_relax_presets.js'
import { resetControlToDefault } from './form_defaults.js'

const CATALOGUE = {
  default: 'standard',
  presets: [
    // Mirrors the real catalogue since 2026-07-30: the vacuum tier ships, and GBIS is
    // the host-gated one (it needs a non-CUDA NAMD build).
    { id: 'fast_shape', label: 'Fast Shape Check (Vacuum)', summary: 'No solvent.',
      available: true, unavailable_reason: '',
      reference: 'MMB 1811 (2018) §3.2', defaults: { water_shell_nm: 0 },
      protocol: 'vacuum_enrgmd_namd', is_default: false },
    { id: 'implicit_gbis', label: 'Implicit Solvent (GBIS)', summary: 'Continuum solvent.',
      available: false, unavailable_reason: 'Needs a non-CUDA NAMD build.',
      reference: 'NAMD GBIS', defaults: { protocol: 'implicit_gbis_namd' },
      protocol: 'implicit_gbis_namd', is_default: false },
    { id: 'standard', label: 'Standard (Aksimentiev)', summary: 'Explicit MgCl2.',
      available: true, unavailable_reason: '', reference: 'MMB 1811 (2018)',
      defaults: { padding_nm: 1.2, early_stop_relax: true },
      protocol: 'equilibrium_aware_namd', is_default: true },
    { id: 'full_physics', label: 'Slow (full physics)', summary: 'Solvent-first.',
      available: true, unavailable_reason: '', reference: 'ACS Nano 13 (2019)',
      defaults: { padding_nm: 1.5, early_stop_relax: false },
      protocol: 'equilibrium_aware_namd', is_default: false },
  ],
}

describe('pickInitial', () => {
  it('starts on the catalogue default', () => {
    expect(pickInitial(CATALOGUE)).toBe('standard')
  })
  it('honours a preferred id when it is available', () => {
    expect(pickInitial(CATALOGUE, 'full_physics')).toBe('full_physics')
  })
  it('refuses to start on an unavailable preset', () => {
    expect(pickInitial(CATALOGUE, 'implicit_gbis')).toBe('standard')
  })
  it('survives an empty catalogue', () => {
    expect(pickInitial({ presets: [] })).toBe(null)
  })
})

describe('noteFor', () => {
  it('shows summary plus reference for an available preset', () => {
    expect(noteFor(CATALOGUE.presets[2])).toBe('Explicit MgCl2. — MMB 1811 (2018)')
  })
  it('leads with the reason for an unavailable one', () => {
    expect(noteFor(CATALOGUE.presets[1]))
      .toBe('Not available in this build. Needs a non-CUDA NAMD build.')
  })
  it('is empty for no preset', () => {
    expect(noteFor(null)).toBe('')
  })
})

describe('applyDefaultsTo', () => {
  it('fills untouched fields', () => {
    const out = applyDefaultsTo(CATALOGUE.presets[3], { mg_conc_mM: 12.5 }, new Set())
    expect(out).toEqual({ mg_conc_mM: 12.5, padding_nm: 1.5, early_stop_relax: false })
  })
  it('never overwrites a field the user touched', () => {
    const out = applyDefaultsTo(CATALOGUE.presets[3],
      { padding_nm: 3.0, early_stop_relax: true }, new Set(['padding_nm', 'early_stop_relax']))
    expect(out.padding_nm).toBe(3.0)
    expect(out.early_stop_relax).toBe(true)
  })
  it('does not mutate the input', () => {
    const cur = { padding_nm: 9 }
    applyDefaultsTo(CATALOGUE.presets[2], cur, new Set())
    expect(cur).toEqual({ padding_nm: 9 })
  })
})

describe('initRelaxPresets', () => {
  let selectEl, noteEl

  beforeEach(() => {
    document.body.innerHTML = '<select id="s"></select><div id="n"></div>'
    selectEl = document.getElementById('s')
    noteEl = document.getElementById('n')
  })

  it('renders every preset, disabling the unavailable one', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    const opts = [...selectEl.options]
    expect(opts.map(o => o.value))
      .toEqual(['fast_shape', 'implicit_gbis', 'standard', 'full_physics'])
    expect(opts[1].disabled).toBe(true)          // implicit_gbis — host-gated
    expect(opts[1].textContent).toContain('unavailable')
    expect(opts[0].disabled).toBe(false)         // fast_shape ships now
    expect(opts[2].disabled).toBe(false)
    expect(ui.id()).toBe('standard')
  })

  it('defaults to Standard and shows its note', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    expect(selectEl.value).toBe('standard')
    expect(noteEl.textContent).toContain('Explicit MgCl2')
  })

  it('survives a generic form reset — the selected preset is the HTML default too', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    resetControlToDefault(selectEl)      // what closing/switching a design does
    expect(selectEl.value).toBe('standard')
    expect(selectEl.value).toBe(ui.id()) // display and sent id can never disagree
  })

  it('updates the note and fires onChange on selection', async () => {
    const onChange = vi.fn()
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE, onChange })
    await ui.load()
    selectEl.value = 'full_physics'
    selectEl.dispatchEvent(new Event('change'))
    expect(ui.id()).toBe('full_physics')
    expect(noteEl.textContent).toContain('Solvent-first')
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'full_physics' }))
  })

  it('rejects a scripted selection of an unavailable preset', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    selectEl.value = 'implicit_gbis'
    selectEl.dispatchEvent(new Event('change'))
    expect(ui.id()).toBe('standard')
    expect(selectEl.value).toBe('standard')
  })

  it('falls back to a usable menu when the backend is unreachable', async () => {
    const ui = initRelaxPresets({
      selectEl, noteEl, fetchPresets: async () => { throw new Error('offline') },
    })
    await ui.load()
    expect(ui.id()).toBe(PRESET_FALLBACK.default)
    expect(selectEl.options.length).toBe(1)
  })

  it('applies the current preset defaults under touched fields', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load('full_physics')
    expect(ui.applyDefaultsTo({ padding_nm: 2.5 }, new Set(['padding_nm'])).padding_nm).toBe(2.5)
    expect(ui.applyDefaultsTo({}, new Set()).padding_nm).toBe(1.5)
  })
})


describe('derived protocol (the merge)', () => {
  let selectEl, noteEl
  beforeEach(() => {
    document.body.innerHTML = '<select id="s"></select><div id="n"></div>'
    selectEl = document.getElementById('s'); noteEl = document.getElementById('n')
  })

  it('reports the protocol of whichever preset is selected', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    expect(ui.protocol()).toBe('equilibrium_aware_namd')
    selectEl.value = 'fast_shape'
    selectEl.dispatchEvent(new Event('change'))
    expect(ui.protocol()).toBe('vacuum_enrgmd_namd')
  })

  it('has no way to express a preset/protocol contradiction', async () => {
    // the whole point of the merge: protocol is a function of the preset, not a
    // second control that can disagree with it
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    for (const p of CATALOGUE.presets) {
      selectEl.value = p.id
      selectEl.dispatchEvent(new Event('change'))
      if (p.available) expect(ui.protocol()).toBe(p.protocol)
    }
  })

  it('falls back to the explicit protocol when nothing is loaded', () => {
    const ui = initRelaxPresets({ selectEl: null, noteEl: null, fetchPresets: async () => ({}) })
    expect(ui.protocol()).toBe('equilibrium_aware_namd')
  })
})

describe('presetIdForProtocol', () => {
  it('maps a protocol back to the preset that runs it', () => {
    expect(presetIdForProtocol(CATALOGUE, 'vacuum_enrgmd_namd')).toBe('fast_shape')
  })
  it('prefers an AVAILABLE preset', () => {
    // implicit_gbis is the only preset claiming its protocol, but it is host-gated —
    // restoring a draft onto a preset the user cannot run would dead-end the panel.
    expect(presetIdForProtocol(CATALOGUE, 'implicit_gbis_namd')).toBe(null)
    // standard and full_physics both claim the explicit protocol; the first available wins.
    expect(presetIdForProtocol(CATALOGUE, 'equilibrium_aware_namd')).toBe('standard')
  })
  it('returns null for the retired legacy protocol', () => {
    expect(presetIdForProtocol(CATALOGUE, 'mgh_slow_release')).toBe(null)
  })
})

describe('preset defaults reach the Advanced controls', () => {
  // Regression: the panel always sends every Advanced field, so the backend saw
  // padding_nm in model_fields_set on EVERY request, treated it as an explicit user
  // choice, and never applied the preset's own value.  Standard asks for the tutorial's
  // 2.0 nm; jobs were silently built at 1.2.  The panel now writes the preset's settings
  // into the inputs, so what the user sees is what runs.  These pin the pure half of
  // that contract (applyDefaultsTo); the DOM wiring lives in md_jobs_panel.
  const standard = CATALOGUE.presets.find(p => p.id === 'standard')
  const fullPhysics = CATALOGUE.presets.find(p => p.id === 'full_physics')

  it('supplies the padding the preset actually asks for', () => {
    expect(applyDefaultsTo(standard, {}, new Set()).padding_nm).toBe(1.2)
    expect(applyDefaultsTo(fullPhysics, {}, new Set()).padding_nm).toBe(1.5)
  })

  it('never overwrites a field the user edited by hand', () => {
    const out = applyDefaultsTo(standard, { padding_nm: 3.7 }, new Set(['padding_nm']))
    expect(out.padding_nm).toBe(3.7)
  })

  it('leaves fields the preset says nothing about alone', () => {
    const out = applyDefaultsTo(standard, { threads: 8 }, new Set())
    expect(out.threads).toBe(8)
  })
})

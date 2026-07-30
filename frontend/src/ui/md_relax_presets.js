/**
 * Relax-protocol preset dropdown.
 *
 * The backend owns the catalogue (`backend/core/md_presets.py`); this module only
 * renders it, shows the selected preset's summary, and reports which id to send.
 *
 * Two behaviours worth keeping:
 *  - an UNAVAILABLE preset is rendered but disabled, with its reason in the note, rather
 *    than hidden. A menu that silently omits a tier reads as "this build can't do that"
 *    only if you already knew the tier existed.
 *  - selecting a preset does NOT overwrite fields the user has already touched; the
 *    backend applies preset defaults only to fields the request did not set, and
 *    `applyDefaultsTo` mirrors that on the client so the panel shows what will happen.
 */

export const PRESET_FALLBACK = {
  presets: [{
    id: 'standard',
    label: 'Standard (Aksimentiev)',
    summary: 'Explicit MgCl₂, full water box, ENM ladder.',
    available: true,
    unavailable_reason: '',
    reference: '',
    defaults: {},
    protocol: 'equilibrium_aware_namd',
    is_default: true,
  }],
  default: 'standard',
}

/** Pure: which option should start selected. */
export function pickInitial (catalogue, preferred = null) {
  const list = catalogue?.presets ?? []
  const byId = id => list.find(p => p.id === id)
  const wanted = byId(preferred)
  if (wanted && wanted.available) return wanted.id
  const dflt = byId(catalogue?.default)
  if (dflt && dflt.available) return dflt.id
  return (list.find(p => p.available) ?? list[0])?.id ?? null
}

/**
 * Pure: which preset runs a given engine protocol.
 *
 * Used to restore a draft that recorded only `protocol` (the panel's control is the
 * preset now). A retired protocol — `mgh_slow_release`, which is the same ladder with
 * the topology gate off — matches nothing and returns null, so the caller falls back to
 * the default. That is the right answer, not a loss.
 */
export function presetIdForProtocol (catalogue, protocol) {
  return (catalogue?.presets ?? [])
    .find(p => p.protocol === protocol && p.available)?.id ?? null
}

/** Pure: the note shown under the dropdown for a given preset. */
export function noteFor (preset) {
  if (!preset) return ''
  if (!preset.available) return `Not available in this build. ${preset.unavailable_reason}`
  return preset.reference ? `${preset.summary} — ${preset.reference}` : preset.summary
}

/**
 * Pure: preset defaults merged UNDER the fields the user has explicitly touched.
 * `touched` is a Set of field names.
 */
export function applyDefaultsTo (preset, current, touched = new Set()) {
  const out = { ...current }
  for (const [k, v] of Object.entries(preset?.defaults ?? {})) {
    if (!touched.has(k)) out[k] = v
  }
  return out
}

export function initRelaxPresets ({ selectEl, noteEl, fetchPresets, onChange = null }) {
  let catalogue = PRESET_FALLBACK
  let currentId = catalogue.default

  function render () {
    if (!selectEl) return
    selectEl.innerHTML = ''
    for (const p of catalogue.presets) {
      const opt = document.createElement('option')
      opt.value = p.id
      opt.textContent = p.available ? p.label : `${p.label} — unavailable`
      opt.disabled = !p.available
      if (p.id === currentId) {
        opt.selected = true
        // Also the option's HTML *default*, so a generic form reset (closing or
        // switching designs runs resetControlsToDefaults over this panel) lands back
        // on the chosen preset.  Options built here have no `selected` attribute, so
        // without this the reset fell through to index 0 — the retired vacuum tier,
        // shown greyed-out and disagreeing with the id the panel would actually send.
        opt.defaultSelected = true
      }
      selectEl.appendChild(opt)
    }
    if (noteEl) noteEl.textContent = noteFor(current())
  }

  function current () {
    return catalogue.presets.find(p => p.id === currentId) ?? null
  }

  async function load (preferred = null) {
    try {
      const got = await fetchPresets()
      if (got?.presets?.length) catalogue = got
    } catch {
      catalogue = PRESET_FALLBACK   // offline / old backend: keep the panel usable
    }
    currentId = pickInitial(catalogue, preferred)
    render()
    return currentId
  }

  if (selectEl) {
    selectEl.addEventListener('change', () => {
      const picked = catalogue.presets.find(p => p.id === selectEl.value)
      if (picked && !picked.available) {        // disabled options can still be scripted
        selectEl.value = currentId
        return
      }
      currentId = selectEl.value
      if (noteEl) noteEl.textContent = noteFor(current())
      onChange?.(current())
    })
  }

  return {
    load,
    render,
    current,
    id: () => currentId,
    catalogue: () => catalogue,
    protocol: () => current()?.protocol ?? 'equilibrium_aware_namd',
    idForProtocol: (proto) => presetIdForProtocol(catalogue, proto),
    applyDefaultsTo: (values, touched) => applyDefaultsTo(current(), values, touched),
  }
}

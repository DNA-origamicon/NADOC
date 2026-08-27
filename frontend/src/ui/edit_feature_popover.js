/**
 * Edit-feature popover — schema-driven editor for feature_log entries.
 *
 * Replaces the `window.prompt()` chains in feature_log_panel.js (one prompt
 * per parameter, cancel any one and you lose the others). Each editable
 * `op_kind` declares its field schema below; the popover builds inputs from
 * the schema, validates, and resolves to a clean params object (or null on
 * cancel). Built on the existing `createModal` primitive so style + escape
 * handling match the rest of the app.
 *
 * Usage:
 *   const newParams = await editFeature({
 *     title:        'Edit F3 — Polymerize',
 *     opKind:       'assembly-polymerize',
 *     currentParams: entry.params,
 *   })
 *   if (newParams) await api.editFeature(...)
 *
 * Schema field types:
 *   { key, label, type: 'number', min?, max?, step?, integer? }
 *   { key, label, type: 'text', placeholder?, allowBlank? }
 *   { key, label, type: 'select', options: [...] }
 *
 * Adding a new op_kind: extend OP_SCHEMAS below. If a key isn't in the schema
 * (e.g. a future op kind), the popover refuses with a clear toast message —
 * caller can fall back to whatever path they had before.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { showToast } from './toast.js'

// ── Schemas ──────────────────────────────────────────────────────────────────
//
// One entry per editable op_kind / feature_type. Keys roughly mirror what the
// backend's edit endpoint expects to receive for that op.
//
// Add new ops here as their edit semantics stabilize. The popover only renders
// fields listed in the schema — unknown params pass through unchanged from
// currentParams when computing the patch.

// Shared schema for the design-mode "edit length_bp" path.
const _LENGTH_BP_SCHEMA = [
  { key: 'length_bp', label: 'Length (bp)', type: 'number', integer: true, min: 1 },
]

const OP_SCHEMAS = {
  // design-mode bundle / extrude — single editable parameter
  'bundle-create':                  _LENGTH_BP_SCHEMA,
  'extrude-segment':                _LENGTH_BP_SCHEMA,
  'extrude-continuation':           _LENGTH_BP_SCHEMA,
  'extrude-deformed-continuation':  _LENGTH_BP_SCHEMA,
  'overhang-extrude':               _LENGTH_BP_SCHEMA,
  // assembly-mode polymerize
  'assembly-polymerize': [
    { key: 'count',     label: 'Chain length',  type: 'number', integer: true, min: 2 },
    { key: 'direction', label: 'Direction',     type: 'select', options: ['forward', 'backward', 'both'] },
  ],
  'assembly-polymerize-periodic': [
    { key: 'count',     label: 'Chain length',  type: 'number', integer: true, min: 2 },
    { key: 'direction', label: 'Direction',     type: 'select', options: ['forward', 'backward', 'both'] },
  ],
  // assembly-mode overhang connection (linker definition)
  'assembly-overhang-connection-add': [
    { key: 'length_value',    label: 'Length value',     type: 'number' },
    { key: 'length_unit',     label: 'Length unit',      type: 'select', options: ['bp', 'nm'] },
    { key: 'bridge_sequence', label: 'Bridge sequence',  type: 'text',   placeholder: 'blank for none', allowBlank: true },
  ],
  'assembly-overhang-connection-patch': [
    { key: 'length_value',    label: 'Length value',     type: 'number' },
    { key: 'length_unit',     label: 'Length unit',      type: 'select', options: ['bp', 'nm'] },
    { key: 'bridge_sequence', label: 'Bridge sequence',  type: 'text',   placeholder: 'blank for none', allowBlank: true },
  ],
}

export function isEditable(opKind) {
  return Object.prototype.hasOwnProperty.call(OP_SCHEMAS, opKind)
}

/**
 * Open the popover and resolve with a new params object, or null on cancel.
 */
export function editFeature({ title, opKind, currentParams = {} }) {
  const schema = OP_SCHEMAS[opKind]
  if (!schema) {
    showToast(`Edit not supported for ${opKind}.`, { severity: 'error' })
    return Promise.resolve(null)
  }
  return new Promise((resolve) => {
    let resolved = false
    const inputs = new Map()  // key → input element

    function _resolveOnce(value) {
      if (resolved) return
      resolved = true
      resolve(value)
    }

    // Build the body: one labelled row per field.
    const body = document.createElement('div')
    body.style.cssText = 'display:flex;flex-direction:column;gap:10px;min-width:280px'

    const rowStyle = 'display:flex;flex-direction:column;gap:4px'
    const labelStyle = 'font-size:var(--text-xs);color:var(--color-text-muted)'
    const inputStyle = [
      'background:var(--color-bg-canvas)',
      'border:1px solid var(--color-border-default)',
      'border-radius:var(--radius-sm)',
      'color:var(--color-text-primary)',
      'font-family:var(--font-ui)', 'font-size:var(--text-sm)',
      'padding:5px 8px', 'outline:none',
    ].join(';')

    for (const field of schema) {
      const row = document.createElement('div')
      row.style.cssText = rowStyle
      const lbl = document.createElement('label')
      lbl.textContent = field.label
      lbl.style.cssText = labelStyle
      row.appendChild(lbl)

      const cur = currentParams[field.key]
      let inp
      if (field.type === 'select') {
        inp = document.createElement('select')
        inp.style.cssText = inputStyle
        for (const opt of field.options) {
          const o = document.createElement('option')
          o.value = opt; o.textContent = opt
          inp.appendChild(o)
        }
        inp.value = cur != null ? String(cur) : field.options[0]
      } else {
        inp = document.createElement('input')
        inp.style.cssText = inputStyle
        inp.type = field.type === 'number' ? 'number' : 'text'
        if (field.type === 'number') {
          if (field.min  != null) inp.min  = String(field.min)
          if (field.max  != null) inp.max  = String(field.max)
          if (field.step != null) inp.step = String(field.step)
          else if (field.integer) inp.step = '1'
        }
        if (field.placeholder) inp.placeholder = field.placeholder
        inp.value = cur != null ? String(cur) : ''
      }
      // Enter on a field commits; Escape cancels via modal.
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); _onSave() }
      })
      inputs.set(field.key, inp)
      row.appendChild(inp)
      lbl.htmlFor = inp.id = `_edit-${opKind}-${field.key}`
      body.appendChild(row)
    }

    function _readField(field) {
      const inp = inputs.get(field.key)
      const raw = inp.value
      if (field.type === 'number') {
        const n = field.integer ? parseInt(raw, 10) : parseFloat(raw)
        if (!Number.isFinite(n)) return { error: `${field.label} must be a number.` }
        if (field.min != null && n < field.min) return { error: `${field.label} must be ≥ ${field.min}.` }
        if (field.max != null && n > field.max) return { error: `${field.label} must be ≤ ${field.max}.` }
        return { value: n }
      }
      if (field.type === 'select') {
        if (!field.options.includes(raw)) return { error: `${field.label} must be one of: ${field.options.join(', ')}.` }
        return { value: raw }
      }
      // text
      const t = raw.trim()
      if (!field.allowBlank && t === '') return { error: `${field.label} cannot be blank.` }
      return { value: t === '' ? null : t }
    }

    function _onSave() {
      const out = {}
      for (const field of schema) {
        const r = _readField(field)
        if (r.error) {
          showToast(r.error, { severity: 'error' })
          inputs.get(field.key)?.focus()
          return
        }
        out[field.key] = r.value
      }
      _resolveOnce(out)
      modal.close()
    }

    const cancelBtn = createButton({
      label: 'Cancel',
      variant: 'default',
      onClick: () => { _resolveOnce(null); modal.close() },
    })
    const saveBtn = createButton({
      label: 'Save',
      variant: 'primary',
      onClick: _onSave,
    })

    const modal = createModal({
      title,
      size: 'sm',
      body,
      actions: [cancelBtn, saveBtn],
      onClose: () => { _resolveOnce(null) },
    })
    modal.open()

    // Focus the first input.
    setTimeout(() => {
      const first = schema[0] && inputs.get(schema[0].key)
      first?.focus?.()
      first?.select?.()
    }, 0)
  })
}

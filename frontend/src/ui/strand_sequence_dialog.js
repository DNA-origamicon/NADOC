/**
 * strand_sequence_dialog.js — hand-edit one strand's sequence.
 *
 * Opened from the strand right-click menu in the 3D viewport, in the cadnano
 * editor, and from either spreadsheet's Sequence cell. Shows the strand 5'→3'
 * in a monospace field with, for a staple whose scaffold is already sequenced,
 * the PAIRED SCAFFOLD BASES on the row above — mismatched positions highlighted.
 * Mismatches never block Apply: the user is allowed to enter any bases.
 *
 * The partner row reads 3'→5' left-to-right: it is laid out in the edited
 * strand's 5'→3' index order and pairs antiparallel to it. The header says so.
 *
 * Both editors have their own api module (`api/client.js` vs
 * `cadnano-editor/api.js`), and each already refreshes its own store after a
 * mutation, so the api is INJECTED rather than imported. Required members:
 *   getStrandSequenceContext(strandId) -> context payload
 *   patchStrand(strandId, { sequence })
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import {
  normalizeSequence, mismatchFlags, mismatchCount, validateStrandSequence,
  decorateSequence, preserveReadOnlySpans,
} from './strand_sequence_pairing.js'

/** Ruler tick row: a `|` every 10 nt with the position under it. */
function _rulerText(length) {
  let out = ''
  for (let i = 0; i < length; i += 10) {
    const label = String(i)
    out += '|' + label.padEnd(Math.min(10, length - i) - 1, ' ')
  }
  return out.slice(0, length)
}

/**
 * @param {object} deps
 * @param {{getStrandSequenceContext: Function, patchStrand: Function}} deps.api
 * @param {(msg: string, opts?: object) => void} [deps.showToast]
 * @returns {{ open: (strandId: string) => Promise<void>, isOpen: () => boolean }}
 */
export function initStrandSequenceDialog({ api, showToast } = {}) {
  let _ctrl = null
  let _ctx = null            // last sequence-context payload
  let _textarea = null
  let _partnerRow = null
  let _rulerRow = null
  let _statusEl = null
  let _errEl = null
  let _applyBtn = null
  let _resetBtn = null

  const _toast = (msg, opts) => { try { showToast?.(msg, opts) } catch { /* non-fatal */ } }

  // ── Live redraw of the partner row + counters ──────────────────────────
  function _refresh() {
    if (!_ctx || !_textarea) return
    const typed = normalizeSequence(_textarea.value)
    const flags = mismatchFlags(typed, _ctx.partner ?? '')

    // The partner row is coloured by the TYPED strand's mismatches, so the user
    // sees which scaffold base their entry fails to pair with.
    if (_partnerRow) {
      _partnerRow.textContent = ''
      if (_ctx.partner) {
        const runs = decorateSequence(_ctx.partner, _ctx.segments ?? [], flags)
        for (const run of runs) {
          _partnerRow.appendChild(el('span', {
            className: 'seqdlg__ch'
              + (run.mismatch ? ' seqdlg__ch--mismatch' : '')
              + (run.kind === 'overhang' ? ' seqdlg__ch--overhang' : ''),
            text: run.text,
          }))
        }
      }
    }

    const n = mismatchCount(typed, _ctx.partner ?? '')
    const v = validateStrandSequence(typed, _ctx.length)
    if (_statusEl) {
      const bits = [`${typed.length}/${_ctx.length} nt`]
      if (_ctx.partner && _ctx.partner.replace(/-/g, '').length) {
        bits.push(n === 0 ? 'all paired' : `${n} mismatch${n === 1 ? '' : 'es'}`)
      }
      _statusEl.textContent = bits.join(' · ')
      _statusEl.classList.toggle('seqdlg__status--warn', n > 0)
    }
    if (_errEl) _errEl.textContent = v.ok ? '' : (v.error ?? '')
    if (_applyBtn) _applyBtn.disabled = !v.ok
    if (_resetBtn) _resetBtn.style.display = _ctx.derived ? '' : 'none'
  }

  // ── Build once ────────────────────────────────────────────────────────
  function _build() {
    if (_ctrl) return

    const headerEl = el('div', { className: 'seqdlg__meta' })
    const partnerLabel = el('div', {
      className: 'seqdlg__rowlabel',
      text: "Scaffold (3'→5')",
    })
    _partnerRow = el('div', { className: 'seqdlg__row seqdlg__row--partner' })
    _textarea = el('textarea', {
      className: 'seqdlg__row seqdlg__input',
      attrs: { spellcheck: 'false', autocomplete: 'off', rows: '1', wrap: 'off' },
    })
    _rulerRow = el('div', { className: 'seqdlg__row seqdlg__row--ruler' })

    // One horizontally scrollable track keeps the three rows character-aligned.
    const track = el('div', {
      className: 'seqdlg__track',
      children: [_partnerRow, _textarea, _rulerRow],
    })

    _textarea.addEventListener('input', _refresh)
    // Keep the partner/ruler rows in step when the field scrolls sideways.
    _textarea.addEventListener('scroll', () => {
      const x = _textarea.scrollLeft
      if (_partnerRow) _partnerRow.style.transform = `translateX(${-x}px)`
      if (_rulerRow)   _rulerRow.style.transform   = `translateX(${-x}px)`
    })

    _statusEl = el('div', { className: 'seqdlg__status' })
    _errEl    = el('div', { className: 'seqdlg__error' })
    const noteEl = el('div', { className: 'seqdlg__note' })

    const bodyEl = el('div', {
      className: 'seqdlg',
      children: [headerEl, partnerLabel, track, _statusEl, _errEl, noteEl],
    })
    bodyEl._headerEl = headerEl
    bodyEl._partnerLabel = partnerLabel
    bodyEl._noteEl = noteEl

    _resetBtn = createButton({
      label: 'Reset to derived',
      variant: 'default',
      onClick: () => {
        if (!_ctx?.derived) return
        _textarea.value = _ctx.derived
        _refresh()
        _textarea.focus()
      },
    })
    const cancelBtn = createButton({
      label: 'Cancel', variant: 'default', onClick: () => _ctrl.close(),
    })
    _applyBtn = createButton({ label: 'Apply', variant: 'primary', onClick: _apply })

    _ctrl = createModal({
      title: 'Edit Sequence',
      size: 'lg',
      body: bodyEl,
      actions: [_resetBtn, cancelBtn, _applyBtn],
      className: 'seqdlg-modal',
    })
    _ctrl._bodyEl = bodyEl
  }

  // ── Commit ────────────────────────────────────────────────────────────
  async function _apply() {
    if (!_ctx || !_textarea) return
    // Read the field HERE, inside the click handler — never trust a prior blur
    // to have committed it (LESSONS H4: blur-commit races click handlers).
    let typed = normalizeSequence(_textarea.value)
    // Read-only spans (overhang bases owned by sub-domain overrides) round-trip
    // verbatim, so the dialog can never desync the strand from the OverhangSpec.
    typed = preserveReadOnlySpans(typed, _ctx.sequence ?? '', _ctx.segments ?? [])

    const v = validateStrandSequence(typed, _ctx.length)
    if (!v.ok) { if (_errEl) _errEl.textContent = v.error ?? ''; return }

    _applyBtn.disabled = true
    try {
      const res = await api.patchStrand(_ctx.strand_id, { sequence: typed })
      if (res === null) {                       // client.js signals failure with null
        if (_errEl) _errEl.textContent = 'Could not save the sequence.'
        _applyBtn.disabled = false
        return
      }
      _ctrl.close()
      const n = mismatchCount(typed, _ctx.partner ?? '')
      _toast(n > 0
        ? `Sequence set (${typed.length} nt, ${n} mismatch${n === 1 ? '' : 'es'}).`
        : `Sequence set (${typed.length} nt).`)
    } catch (err) {
      if (_errEl) _errEl.textContent = err?.message ?? 'Could not save the sequence.'
      _applyBtn.disabled = false
    }
  }

  // ── Open ──────────────────────────────────────────────────────────────
  async function open(strandId) {
    if (!strandId) return
    let ctx
    try {
      ctx = await api.getStrandSequenceContext(strandId)
    } catch (err) {
      _toast(`Could not read that strand: ${err?.message ?? 'unknown error'}`, { severity: 'error' })
      return
    }
    if (!ctx) {
      _toast('Could not read that strand.', { severity: 'error' })
      return
    }
    _ctx = ctx
    _build()

    const body = _ctrl._bodyEl
    const kind = ctx.is_scaffold ? 'scaffold'
      : ctx.strand_type === 'oh_binder' ? 'OH binder'
      : ctx.strand_type === 'linker' ? 'linker' : 'staple'
    body._headerEl.textContent = `${kind} · ${ctx.length} nt · 5'→3'`

    // No partner anywhere (scaffold strand, or the scaffold has no sequence yet)
    // → drop the partner row entirely rather than showing a row of dashes.
    const hasPartner = !!(ctx.partner && ctx.partner.replace(/-/g, '').length)
    body._partnerLabel.style.display = hasPartner ? '' : 'none'
    _partnerRow.style.display = hasPartner ? '' : 'none'

    const lockedOverhang = (ctx.segments ?? []).some(
      s => s.kind === 'overhang' && s.editable === false)
    body._noteEl.textContent = lockedOverhang
      ? 'Shaded overhang bases come from sub-domain overrides and are kept as-is — '
        + 'edit them in the Domain Designer.'
      : ((ctx.segments ?? []).some(s => s.kind === 'overhang')
          ? 'Shaded bases are the overhang tip; saving writes them back to the overhang.'
          : '')

    _rulerRow.textContent = _rulerText(ctx.length)
    _textarea.value = ctx.sequence ?? ctx.derived ?? ''
    _textarea.style.width = `${Math.max(ctx.length, 1)}ch`
    _partnerRow.style.transform = 'translateX(0px)'
    _rulerRow.style.transform = 'translateX(0px)'
    if (_errEl) _errEl.textContent = ''

    _refresh()
    _ctrl.open()
    _textarea.focus()
    _textarea.setSelectionRange?.(0, 0)
  }

  return { open, isOpen: () => !!_ctrl?.isOpen() }
}

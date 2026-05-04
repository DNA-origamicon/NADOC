/**
 * Keyframe text popup — modal dialog for editing the per-keyframe text overlay.
 *
 * Built lazily on first open; reused thereafter.
 *
 * Returns a promise resolving to the new patch (subset of keyframe text fields)
 * on OK, null on Cancel, or a "clear" patch (text:"") on Clear.
 */

const FONT_FAMILIES = [
  'sans-serif',
  'serif',
  'monospace',
  'Arial',
  'Helvetica',
  'Georgia',
  'Times New Roman',
  'Courier New',
  'Verdana',
  'Tahoma',
]

let _root      = null
let _resolve   = null
let _textEl    = null
let _fontEl    = null
let _sizeEl    = null
let _colorEl   = null
let _boldEl    = null
let _italicEl  = null
let _alignEls  = null   // { left, center, right }
let _previewEl = null

function _build() {
  const overlay = document.createElement('div')
  overlay.style.cssText = [
    'position:fixed;inset:0;z-index:10000',
    'background:rgba(0,0,0,0.5);display:none',
    'align-items:center;justify-content:center',
    'font-family:var(--font-ui)',
  ].join(';')

  const card = document.createElement('div')
  card.style.cssText = [
    'background:#161b22;border:1px solid #30363d;border-radius:6px',
    'padding:14px 16px;min-width:340px;max-width:480px',
    'color:#c9d1d9;font-size:var(--text-sm)',
    'box-shadow:0 8px 24px rgba(0,0,0,0.4)',
  ].join(';')

  const title = document.createElement('div')
  title.textContent = 'Keyframe Text'
  title.style.cssText = 'font-weight:600;font-size:13px;margin-bottom:10px;color:#e6edf3'

  // ── Text input ────────────────────────────────────────────────────────────
  const textLbl = _label('Text')
  const text = document.createElement('textarea')
  text.rows = 3
  text.placeholder = 'Caption shown during this keyframe'
  text.style.cssText = [
    'width:100%;box-sizing:border-box;resize:vertical',
    'background:#0d1117;border:1px solid #30363d;border-radius:3px',
    'color:#c9d1d9;padding:6px 8px;font-family:var(--font-ui);font-size:var(--text-sm)',
    'margin-bottom:10px',
  ].join(';')
  text.addEventListener('keydown', e => e.stopPropagation())

  // ── Font / size / color row ───────────────────────────────────────────────
  const row1 = document.createElement('div')
  row1.style.cssText = 'display:grid;grid-template-columns:1fr 70px 70px;gap:8px;margin-bottom:10px'

  const font = document.createElement('select')
  font.style.cssText = _selStyle
  for (const f of FONT_FAMILIES) {
    const opt = document.createElement('option')
    opt.value = f; opt.textContent = f; opt.style.fontFamily = f
    font.appendChild(opt)
  }
  font.addEventListener('keydown', e => e.stopPropagation())

  const size = document.createElement('input')
  size.type = 'number'; size.min = '8'; size.max = '128'; size.step = '1'
  size.style.cssText = _inpStyle
  size.addEventListener('keydown', e => e.stopPropagation())

  const color = document.createElement('input')
  color.type = 'color'
  color.style.cssText = 'width:100%;height:26px;background:#0d1117;border:1px solid #30363d;border-radius:3px;padding:1px;cursor:pointer'
  color.addEventListener('keydown', e => e.stopPropagation())

  row1.append(_wrap('Font', font), _wrap('Size', size), _wrap('Color', color))

  // ── Style + alignment row ─────────────────────────────────────────────────
  const row2 = document.createElement('div')
  row2.style.cssText = 'display:flex;gap:14px;align-items:center;margin-bottom:12px'

  const bold   = _checkbox('Bold')
  const italic = _checkbox('Italic')

  const alignBox = document.createElement('div')
  alignBox.style.cssText = 'display:flex;gap:0;margin-left:auto'
  const aLeft   = _alignBtn('⟸',  'left',   'Align left')
  const aCenter = _alignBtn('═',  'center', 'Align center')
  const aRight  = _alignBtn('⟹', 'right',  'Align right')
  alignBox.append(aLeft.btn, aCenter.btn, aRight.btn)

  row2.append(bold.wrap, italic.wrap, alignBox)

  // ── Preview ───────────────────────────────────────────────────────────────
  const previewWrap = document.createElement('div')
  previewWrap.style.cssText = [
    'background:#0d1117;border:1px solid #30363d;border-radius:3px',
    'padding:18px 12px;margin-bottom:12px;min-height:60px',
    'display:flex;align-items:center',
  ].join(';')
  const preview = document.createElement('div')
  preview.style.cssText = 'width:100%;line-height:1.2;word-wrap:break-word;white-space:pre-wrap'
  previewWrap.appendChild(preview)

  // ── Buttons ───────────────────────────────────────────────────────────────
  const btnRow = document.createElement('div')
  btnRow.style.cssText = 'display:flex;gap:8px;justify-content:flex-end'

  const clearBtn = document.createElement('button')
  clearBtn.textContent = 'Clear text'
  clearBtn.style.cssText = _btnStyle('#3d1c1c', '#c93c3c', '#c93c3c')
  clearBtn.style.marginRight = 'auto'

  const cancelBtn = document.createElement('button')
  cancelBtn.textContent = 'Cancel'
  cancelBtn.style.cssText = _btnStyle('#21262d', '#30363d', '#c9d1d9')

  const okBtn = document.createElement('button')
  okBtn.textContent = 'OK'
  okBtn.style.cssText = _btnStyle('#162420', '#3fb950', '#3fb950')

  btnRow.append(clearBtn, cancelBtn, okBtn)

  card.append(title, textLbl, text, row1, row2, previewWrap, btnRow)
  overlay.appendChild(card)
  document.body.appendChild(overlay)

  _root      = overlay
  _textEl    = text
  _fontEl    = font
  _sizeEl    = size
  _colorEl   = color
  _boldEl    = bold.input
  _italicEl  = italic.input
  _alignEls  = { left: aLeft, center: aCenter, right: aRight }
  _previewEl = preview

  // Live preview updates
  const updatePreview = () => {
    preview.textContent = text.value || 'Preview'
    preview.style.fontFamily = font.value
    preview.style.fontSize   = `${size.value}px`
    preview.style.color      = color.value
    preview.style.fontWeight = bold.input.checked ? '700' : '400'
    preview.style.fontStyle  = italic.input.checked ? 'italic' : 'normal'
    preview.style.textAlign  = _activeAlign()
  }
  text.addEventListener('input', updatePreview)
  font.addEventListener('change', updatePreview)
  size.addEventListener('input', updatePreview)
  color.addEventListener('input', updatePreview)
  bold.input.addEventListener('change', updatePreview)
  italic.input.addEventListener('change', updatePreview)
  for (const a of [aLeft, aCenter, aRight]) {
    a.btn.addEventListener('click', () => { _setAlign(a.value); updatePreview() })
  }

  // Buttons
  cancelBtn.addEventListener('click', () => _close(null))
  okBtn.addEventListener('click', () => _close(_collectPatch()))
  clearBtn.addEventListener('click', () => _close({
    text: '',
    text_font_family: font.value,
    text_font_size_px: parseInt(size.value, 10) || 24,
    text_color: color.value,
    text_bold: bold.input.checked,
    text_italic: italic.input.checked,
    text_align: _activeAlign(),
  }))
  overlay.addEventListener('click', e => { if (e.target === overlay) _close(null) })
  document.addEventListener('keydown', _onKeyDown)
}

function _onKeyDown(e) {
  if (!_root || _root.style.display === 'none') return
  if (e.key === 'Escape') { e.stopPropagation(); _close(null) }
}

function _activeAlign() {
  for (const k of ['left', 'center', 'right']) {
    if (_alignEls[k].btn.classList.contains('is-active')) return k
  }
  return 'center'
}

function _setAlign(value) {
  for (const k of ['left', 'center', 'right']) {
    _alignEls[k].btn.classList.toggle('is-active', k === value)
    _alignEls[k].btn.style.background = k === value ? '#1f6feb' : '#21262d'
    _alignEls[k].btn.style.color      = k === value ? '#ffffff' : '#8b949e'
  }
}

function _collectPatch() {
  return {
    text: _textEl.value,
    text_font_family: _fontEl.value,
    text_font_size_px: parseInt(_sizeEl.value, 10) || 24,
    text_color: _colorEl.value,
    text_bold: _boldEl.checked,
    text_italic: _italicEl.checked,
    text_align: _activeAlign(),
  }
}

function _close(result) {
  if (_root) _root.style.display = 'none'
  const r = _resolve
  _resolve = null
  if (r) r(result)
}

// ── Style helpers ─────────────────────────────────────────────────────────────

const _selStyle = [
  'width:100%;box-sizing:border-box',
  'background:#0d1117;border:1px solid #30363d;border-radius:3px',
  'color:#c9d1d9;padding:3px 4px;font-size:var(--text-xs)',
].join(';')

const _inpStyle = [
  'width:100%;box-sizing:border-box',
  'background:#0d1117;border:1px solid #30363d;border-radius:3px',
  'color:#c9d1d9;padding:3px 4px;font-family:var(--font-ui);font-size:var(--text-xs)',
].join(';')

function _btnStyle(bg, border, color) {
  return [
    `background:${bg};border:1px solid ${border};color:${color}`,
    'border-radius:3px;font-size:12px;cursor:pointer;padding:5px 12px',
  ].join(';')
}

function _label(text) {
  const s = document.createElement('div')
  s.textContent = text
  s.style.cssText = 'font-size:11px;color:#8b949e;margin-bottom:4px'
  return s
}

function _wrap(labelText, control) {
  const w = document.createElement('div')
  const lbl = _label(labelText)
  w.append(lbl, control)
  return w
}

function _checkbox(labelText) {
  const wrap = document.createElement('label')
  wrap.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;font-size:12px;color:#c9d1d9;user-select:none'
  const input = document.createElement('input')
  input.type = 'checkbox'
  wrap.append(input, document.createTextNode(labelText))
  return { wrap, input }
}

function _alignBtn(symbol, value, title) {
  const btn = document.createElement('button')
  btn.textContent = symbol
  btn.title = title
  btn.style.cssText = [
    'background:#21262d;border:1px solid #30363d;color:#8b949e',
    'padding:4px 10px;font-size:14px;cursor:pointer',
    'border-radius:0',
  ].join(';')
  if (value === 'left')   btn.style.borderTopLeftRadius  = btn.style.borderBottomLeftRadius  = '3px'
  if (value === 'right')  btn.style.borderTopRightRadius = btn.style.borderBottomRightRadius = '3px'
  return { btn, value }
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Open the popup, prefilled with `current` keyframe text fields.
 *
 * @param {object} current — { text, text_font_family, text_font_size_px,
 *                             text_color, text_bold, text_italic, text_align }
 * @returns {Promise<object|null>} resolves with the patch (text fields) or null on cancel
 */
export function openKeyframeTextPopup(current = {}) {
  if (!_root) _build()
  _textEl.value     = current.text ?? ''
  _fontEl.value     = current.text_font_family ?? 'sans-serif'
  _sizeEl.value     = current.text_font_size_px ?? 24
  _colorEl.value    = current.text_color ?? '#ffffff'
  _boldEl.checked   = !!current.text_bold
  _italicEl.checked = !!current.text_italic
  _setAlign(current.text_align || 'center')

  // Trigger preview render
  _previewEl.textContent  = _textEl.value || 'Preview'
  _previewEl.style.fontFamily = _fontEl.value
  _previewEl.style.fontSize   = `${_sizeEl.value}px`
  _previewEl.style.color      = _colorEl.value
  _previewEl.style.fontWeight = _boldEl.checked ? '700' : '400'
  _previewEl.style.fontStyle  = _italicEl.checked ? 'italic' : 'normal'
  _previewEl.style.textAlign  = _activeAlign()

  _root.style.display = 'flex'
  _textEl.focus()
  _textEl.select()

  return new Promise(resolve => { _resolve = resolve })
}

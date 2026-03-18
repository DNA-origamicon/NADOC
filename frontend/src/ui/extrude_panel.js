/**
 * Extrude panel — three UI styles for the extrude action.
 *
 * All three styles invoke the same doExtrude() function, which
 * reads length from the shared length input and calls onExtrude({cells, lengthBp}).
 *
 * Style A — Blender-like:     small square, single-letter shortcut key [E]
 * Style B — Fusion 360-like:  solid blue rectangle [▲ Extrude]
 * Style C — SOLIDWORKS-like:  split button [▲ Extrude | ▼]
 *
 * The panel also validates that at least one cell is selected before
 * allowing the extrude action.
 */

export function initExtrudePanel(container, { getSelectedCells, onExtrude } = {}) {
  container.innerHTML = `
    <div class="extrude-length-row">
      <label class="extrude-label">Length</label>
      <input id="extrude-length-val" type="number" min="1" step="1" value="42"
             class="extrude-number">
      <div class="extrude-unit-toggle">
        <button id="unit-bp"  class="unit-btn active" title="Base pairs">bp</button>
        <button id="unit-nm"  class="unit-btn"        title="Nanometres">nm</button>
      </div>
    </div>

    <div class="extrude-status" id="extrude-status"></div>

    <div style="padding:6px 0 2px;font-size:11px;color:#8b949e;letter-spacing:0.05em;text-transform:uppercase">
      Strand filter
    </div>
    <div style="display:flex;gap:6px;padding-bottom:8px">
      <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:12px;color:#c9d1d9">
        <input type="radio" name="extrude-filter" value="both" checked style="cursor:pointer"> Both
      </label>
      <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:12px;color:#c9d1d9">
        <input type="radio" name="extrude-filter" value="scaffold" style="cursor:pointer"> Scaffold
      </label>
      <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:12px;color:#c9d1d9">
        <input type="radio" name="extrude-filter" value="staples" style="cursor:pointer"> Staples
      </label>
    </div>

    <div class="extrude-btns-section">
      <div class="extrude-style-label">Style A — Blender</div>
      <div class="extrude-style-a-row">
        <button id="extrude-a" class="extrude-btn-a" title="Extrude (E)">E</button>
        <span class="extrude-hint">Extrude&nbsp;<span class="key">E</span></span>
      </div>

      <div class="extrude-style-label" style="margin-top:12px">Style B — Fusion 360</div>
      <button id="extrude-b" class="extrude-btn-b">
        <span class="extrude-icon-b">▲</span> Extrude
      </button>

      <div class="extrude-style-label" style="margin-top:12px">Style C — SOLIDWORKS</div>
      <div class="extrude-split">
        <button id="extrude-c-main" class="extrude-btn-c-main">
          <span class="extrude-icon-c">▲</span> Extrude
        </button>
        <button id="extrude-c-drop" class="extrude-btn-c-drop" title="Options">▼</button>
      </div>
    </div>
  `

  const lengthInput = container.querySelector('#extrude-length-val')
  const unitBp      = container.querySelector('#unit-bp')
  const unitNm      = container.querySelector('#unit-nm')
  const statusEl    = container.querySelector('#extrude-status')

  function _getStrandFilter() {
    const checked = container.querySelector('input[name="extrude-filter"]:checked')
    return checked?.value ?? 'both'
  }

  const BDNA_RISE = 0.334  // nm/bp

  let _unit = 'bp'  // 'bp' or 'nm'

  function _getLengthBp() {
    const val = parseFloat(lengthInput.value)
    if (isNaN(val) || val <= 0) return null
    if (_unit === 'bp') return Math.round(val)
    return Math.max(1, Math.round(val / BDNA_RISE))
  }

  function _setUnit(u) {
    _unit = u
    unitBp.classList.toggle('active', u === 'bp')
    unitNm.classList.toggle('active', u === 'nm')
    if (u === 'bp') {
      lengthInput.min = '1'
      lengthInput.step = '1'
      lengthInput.value = Math.round(parseFloat(lengthInput.value))
    } else {
      lengthInput.min = '0.334'
      lengthInput.step = '0.334'
      lengthInput.value = (parseFloat(lengthInput.value) * BDNA_RISE).toFixed(2)
    }
  }

  function _setStatus(msg, isError = false) {
    statusEl.textContent = msg
    statusEl.style.color = isError ? '#f85149' : '#3fb950'
  }

  async function doExtrude() {
    const cells = getSelectedCells?.() ?? []
    if (!cells.length) {
      _setStatus('Select at least one cell first.', true)
      return
    }
    const lengthBp = _getLengthBp()
    if (!lengthBp) {
      _setStatus('Enter a valid length.', true)
      return
    }
    _setStatus('Extruding…')
    try {
      const strandFilter = _getStrandFilter()
      await onExtrude?.({ cells, lengthBp, strandFilter })
      _setStatus(`${cells.length} helix${cells.length > 1 ? 'es' : ''} created (${lengthBp} bp)`)
    } catch (err) {
      _setStatus(err.message ?? 'Extrude failed.', true)
    }
  }

  unitBp.addEventListener('click', () => _setUnit('bp'))
  unitNm.addEventListener('click', () => _setUnit('nm'))

  container.querySelector('#extrude-a').addEventListener('click', doExtrude)
  container.querySelector('#extrude-b').addEventListener('click', doExtrude)
  container.querySelector('#extrude-c-main').addEventListener('click', doExtrude)
  container.querySelector('#extrude-c-drop').addEventListener('click', () => {
    // Placeholder for future options dropdown — for now same action.
    doExtrude()
  })

  // Keyboard shortcut E (Blender style) — only when not in an input.
  document.addEventListener('keydown', e => {
    if (e.key === 'e' && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
      doExtrude()
    }
  })

  return { doExtrude }
}

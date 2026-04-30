/**
 * Right-click context menu for assembly PartInstances.
 *
 * Usage:
 *   const ctx = initAssemblyContextMenu({ api, onMoveRotate, onDefineConnector })
 *   ctx.show(inst, clientX, clientY)
 *   ctx.hide()
 */

const _REPR_OPTIONS = [
  { value: 'full',       label: 'Full (CG)' },
  { value: 'beads',      label: 'Beads' },
  { value: 'cylinders',  label: 'Cylinders' },
  { value: 'hull-prism', label: 'Hull Prism' },
  { value: 'vdw',        label: 'VDW (atomistic)' },
  { value: 'ballstick',  label: 'Ball+Stick (atomistic)' },
]
const _ATOMISTIC = new Set(['vdw', 'ballstick'])

function _divider() {
  const hr = document.createElement('hr')
  hr.style.cssText = 'border:none;border-top:1px solid #21262d;margin:3px 0'
  return hr
}

function _item(label, onClick) {
  const el = document.createElement('div')
  el.textContent = label
  el.style.cssText = 'padding:5px 12px;cursor:pointer;user-select:none;white-space:nowrap'
  el.addEventListener('mouseenter', () => { el.style.background = '#21262d' })
  el.addEventListener('mouseleave', () => { el.style.background = '' })
  el.addEventListener('click', onClick)
  return el
}

export function initAssemblyContextMenu({ api, onMoveRotate, onDefineConnector }) {
  let _el   = null

  function hide() {
    if (_el) { _el.remove(); _el = null }
    document.removeEventListener('pointerdown', _onOutside, true)
    document.removeEventListener('keydown',     _onKey,     true)
  }

  function _onOutside(e) {
    if (_el && !_el.contains(e.target)) hide()
  }

  function _onKey(e) {
    if (e.key === 'Escape') { e.stopPropagation(); hide() }
  }

  function show(inst, clientX, clientY) {
    hide()

    const el = document.createElement('div')
    el.style.cssText = [
      'position:fixed;z-index:9998',
      `left:${clientX}px;top:${clientY}px`,
      'background:#0d1117;border:1px solid #30363d;border-radius:6px',
      'padding:4px 0;min-width:200px',
      'box-shadow:0 4px 20px rgba(0,0,0,0.7)',
      'font-size:11px;color:#c9d1d9',
    ].join(';')

    // ── Header ──────────────────────────────────────────────────────────────
    const hdr = document.createElement('div')
    hdr.textContent = inst.name || 'Part'
    hdr.style.cssText = 'padding:5px 12px 4px;font-weight:600;font-size:10px;color:#8b949e;user-select:none'
    el.appendChild(hdr)

    el.appendChild(_divider())

    // ── Representation ───────────────────────────────────────────────────────
    const reprRow = document.createElement('div')
    reprRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 12px'
    const reprLbl = document.createElement('span')
    reprLbl.textContent = 'Repr'
    reprLbl.style.cssText = 'color:#8b949e;flex-shrink:0;font-size:10px'
    const reprSel = document.createElement('select')
    reprSel.style.cssText = [
      'flex:1;background:#161b22;color:#c9d1d9',
      'border:1px solid #30363d;border-radius:3px',
      'font-size:10px;padding:2px 4px;cursor:pointer',
    ].join(';')
    for (const { value, label } of _REPR_OPTIONS) {
      const opt = document.createElement('option')
      opt.value = value; opt.text = label
      opt.selected = (inst.representation ?? 'full') === value
      reprSel.appendChild(opt)
    }
    reprSel.addEventListener('change', async () => {
      const repr = reprSel.value
      if (_ATOMISTIC.has(repr)) {
        const ok = window.confirm(
          'Atomistic rendering computes all-atom geometry and can be slow for large designs.\n\nApply anyway?',
        )
        if (!ok) { reprSel.value = inst.representation ?? 'full'; return }
      }
      hide()
      await api.patchInstance(inst.id, { representation: repr })
    })
    reprRow.append(reprLbl, reprSel)
    el.appendChild(reprRow)

    el.appendChild(_divider())

    // ── Move / Rotate ────────────────────────────────────────────────────────
    el.appendChild(_item('Move / Rotate', () => { hide(); onMoveRotate() }))

    // ── Define Connector ────────────────────────────────────────────────────
    el.appendChild(_item('Define Connector', () => { hide(); onDefineConnector(inst.id) }))

    el.appendChild(_divider())

    // ── Fixed toggle ─────────────────────────────────────────────────────────
    const fixedEl = document.createElement('div')
    fixedEl.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;user-select:none'
    fixedEl.addEventListener('mouseenter', () => { fixedEl.style.background = '#21262d' })
    fixedEl.addEventListener('mouseleave', () => { fixedEl.style.background = '' })

    const chk = document.createElement('input')
    chk.type = 'checkbox'
    chk.checked = !!inst.fixed
    chk.style.cssText = 'accent-color:#3fb950;cursor:pointer;flex-shrink:0'

    const fixedLbl = document.createElement('span')
    fixedLbl.textContent = 'Fixed (anchored)'

    fixedEl.append(chk, fixedLbl)
    fixedEl.addEventListener('click', async (e) => {
      e.stopPropagation()
      const newVal = !chk.checked
      chk.checked = newVal
      await api.patchInstance(inst.id, { fixed: newVal })
    })
    el.appendChild(fixedEl)

    const jointsEl = document.createElement('div')
    jointsEl.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;user-select:none'
    jointsEl.addEventListener('mouseenter', () => { jointsEl.style.background = '#21262d' })
    jointsEl.addEventListener('mouseleave', () => { jointsEl.style.background = '' })

    const jointsChk = document.createElement('input')
    jointsChk.type = 'checkbox'
    jointsChk.checked = !!inst.allow_part_joints
    jointsChk.style.cssText = 'accent-color:#3fb950;cursor:pointer;flex-shrink:0'

    const jointsLbl = document.createElement('span')
    jointsLbl.textContent = 'Allow Part Joints'

    jointsEl.append(jointsChk, jointsLbl)
    jointsEl.addEventListener('click', async (e) => {
      e.stopPropagation()
      const newVal = !jointsChk.checked
      jointsChk.checked = newVal
      await api.patchInstance(inst.id, { allow_part_joints: newVal })
    })
    el.appendChild(jointsEl)

    document.body.appendChild(el)
    _el = el

    // Clamp to viewport so menu never clips off-screen
    const rect = el.getBoundingClientRect()
    if (clientX + rect.width  > window.innerWidth)  el.style.left = `${clientX - rect.width}px`
    if (clientY + rect.height > window.innerHeight) el.style.top  = `${clientY - rect.height}px`

    // Dismiss on outside click or Escape (use capture so menu-internal clicks aren't swallowed)
    setTimeout(() => {
      document.addEventListener('pointerdown', _onOutside, true)
      document.addEventListener('keydown',     _onKey,     true)
    }, 0)
  }

  return { show, hide }
}

/**
 * Protein → overhang attachment modal (Phase 2).
 *
 * Self-contained dialog (no docked-panel layout surgery): pick an imported
 * protein + an overhang and attach; lists existing attachments with
 * visibility + detach controls.  Pose editing (gizmo) is Phase 4.
 *
 * Reads overhangs / attachments / embedded assets from the current design in
 * the store; the session protein library comes from the API. Mutations call the
 * API client (which syncs the design) then re-render and invoke `onChanged` so
 * the protein renderer re-fetches placed geometry.
 */

const WRAP = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10001;display:flex;align-items:center;justify-content:center;'
const DIALOG = 'background:#0d1117;border:1px solid #30363d;border-radius:8px;width:460px;max-height:80vh;overflow:auto;padding:16px;color:#c9d1d9;font:13px system-ui,sans-serif;'
const SELECT = 'width:100%;margin:4px 0 10px;padding:5px;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;'
const BTN = 'padding:6px 12px;background:#238636;color:#fff;border:none;border-radius:5px;cursor:pointer;'
const BTN_DIS = 'padding:6px 12px;background:#30363d;color:#8b949e;border:none;border-radius:5px;cursor:not-allowed;'

export function openProteinAttachModal({ store, api, onChanged }) {
  const backdrop = document.createElement('div')
  backdrop.style.cssText = WRAP
  const dialog = document.createElement('div')
  dialog.style.cssText = DIALOG
  backdrop.appendChild(dialog)
  document.body.appendChild(backdrop)

  const close = () => backdrop.remove()
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close() })

  async function render() {
    const design = store.getState().currentDesign
    const lib = (await api.listProteinLibrary())?.assets ?? []
    const overhangs = (design?.overhangs ?? []).filter(o => !o.auxiliary_endpoint)
    const attachments = design?.protein_attachments ?? []
    const assetsById = new Map((design?.protein_assets ?? []).map(a => [a.id, a]))
    for (const a of lib) if (!assetsById.has(a.id)) assetsById.set(a.id, a)

    dialog.innerHTML = ''

    const h = document.createElement('div')
    h.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'
    h.innerHTML = '<h3 style="margin:0;font-size:15px;">Attach Protein to Overhang</h3>'
    const x = document.createElement('button')
    x.textContent = '✕'
    x.style.cssText = 'background:none;border:none;color:#8b949e;font-size:16px;cursor:pointer;'
    x.onclick = close
    h.appendChild(x)
    dialog.appendChild(h)

    if (!design) {
      dialog.appendChild(_hint('Load a design first (File ▸ Open or New Part).'))
      return
    }

    // ── Attach form ──────────────────────────────────────────────────────────
    if (!lib.length) {
      dialog.appendChild(_hint('No proteins imported. Use File ▸ Import Protein (PDB)… first.'))
    } else if (!overhangs.length) {
      dialog.appendChild(_hint('This design has no overhangs to attach to.'))
    } else {
      dialog.appendChild(_label('Protein'))
      const protSel = document.createElement('select')
      protSel.style.cssText = SELECT
      for (const a of lib) {
        const o = document.createElement('option')
        o.value = a.id
        o.textContent = `${a.name} (${a.atom_count} atoms)`
        protSel.appendChild(o)
      }
      dialog.appendChild(protSel)

      dialog.appendChild(_label('Overhang'))
      const ohSel = document.createElement('select')
      ohSel.style.cssText = SELECT
      for (const o of overhangs) {
        const opt = document.createElement('option')
        opt.value = o.id
        opt.textContent = o.label || o.id
        ohSel.appendChild(opt)
      }
      dialog.appendChild(ohSel)

      const attachBtn = document.createElement('button')
      attachBtn.textContent = 'Attach'
      attachBtn.style.cssText = BTN
      attachBtn.onclick = async () => {
        attachBtn.disabled = true
        attachBtn.style.cssText = BTN_DIS
        const res = await api.createProteinAttachment(protSel.value, ohSel.value)
        if (!res) {
          attachBtn.textContent = 'Attach failed'
          attachBtn.disabled = false
          return
        }
        onChanged?.()
        await render()
      }
      dialog.appendChild(attachBtn)
    }

    // ── Existing attachments ───────────────────────────────────────────────────
    const hr = document.createElement('hr')
    hr.style.cssText = 'border:none;border-top:1px solid #30363d;margin:14px 0 8px;'
    dialog.appendChild(hr)
    const lbl = document.createElement('div')
    lbl.style.cssText = 'font-weight:600;margin-bottom:6px;'
    lbl.textContent = `Attachments (${attachments.length})`
    dialog.appendChild(lbl)

    if (!attachments.length) {
      dialog.appendChild(_hint('None yet.'))
    }
    for (const att of attachments) {
      const asset = assetsById.get(att.asset_id)
      const oh = overhangs.find(o => o.id === att.target?.overhang_id)
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #21262d;'

      const vis = document.createElement('input')
      vis.type = 'checkbox'
      vis.checked = att.visible !== false
      vis.title = 'Visible'
      vis.onchange = async () => {
        await api.patchProteinAttachment(att.id, { visible: vis.checked })
        onChanged?.()
        await render()
      }
      row.appendChild(vis)

      const text = document.createElement('span')
      text.style.cssText = 'flex:1;'
      text.textContent = `${asset?.name ?? att.asset_id.slice(0, 8)} → ${oh?.label || att.target?.overhang_id}`
      row.appendChild(text)

      const del = document.createElement('button')
      del.textContent = 'Detach'
      del.style.cssText = 'padding:3px 8px;background:#30363d;color:#f85149;border:none;border-radius:4px;cursor:pointer;'
      del.onclick = async () => {
        await api.deleteProteinAttachment(att.id)
        onChanged?.()
        await render()
      }
      row.appendChild(del)
      dialog.appendChild(row)
    }
  }

  render()
  return { close }
}

function _label(t) {
  const el = document.createElement('div')
  el.style.cssText = 'font-size:12px;color:#8b949e;'
  el.textContent = t
  return el
}

function _hint(t) {
  const el = document.createElement('div')
  el.style.cssText = 'color:#8b949e;font-style:italic;padding:6px 0;'
  el.textContent = t
  return el
}

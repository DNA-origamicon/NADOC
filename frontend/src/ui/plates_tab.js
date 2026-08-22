/** Controller for the 96-well plate and IDT tube tab. */
import { buildStapleColorMap } from '../scene/helix_renderer.js'
import { strandLengthNt } from '../scene/strand_length.js'
import { hexFromInt } from '../scene/color_util.js'
import { STAPLE_PALETTE } from '../scene/helix_renderer/palette.js'
import { initPlateView } from './plate_view.js'
import { buildIdtStrandNames } from './idt_order.js'

export function initPlatesTab({ api, designRenderer, selectionManager, store }) {
  const PLATE_STAPLE_PALETTE = STAPLE_PALETTE
  const canvasEl  = document.getElementById('plate-canvas')
  const wrapEl    = document.getElementById('plate-canvas-wrap')
  const toolbarEl = document.getElementById('plate-toolbar')
  const tubesEl   = document.getElementById('plate-tubes')
  const paneEl    = document.getElementById('tab-content-plates')
  if (canvasEl && wrapEl && paneEl) {
    const _layoutSig = layout => JSON.stringify(layout ?? null)
    // Tracks what plate_view already renders. A response to our own save has
    // this same signature and must not reset pan/zoom; undo/redo has a different
    // signature and must refresh even though strand topology did not change.
    let _renderedLayoutSig = _layoutSig(null)
    const MOD_NAMES = {
      cy3: 'Cy3', cy5: 'Cy5', fam: 'FAM', tamra: 'TAMRA', bhq1: 'BHQ-1',
      bhq2: 'BHQ-2', atto488: 'ATTO488', atto550: 'ATTO550', biotin: 'Biotin',
    }

    // Strand length in nt (domain bp + loop/skip deltas) — mirrors the cadnano
    // spreadsheet's strandLength().

    const plateView = initPlateView(canvasEl, {
      wrapEl,
      toolbarEl,
      getTubesContainer: () => tubesEl,
      enableGroupMode: true,
      onSaveLayout: (layout) => {
        _renderedLayoutSig = _layoutSig(layout)
        api.savePlateLayout(layout)
      },
      onStrandClick: (sid) => {
        // Select the canonical strand ref; all linked views follow it. Empty well clears.
        if (sid) selectionManager.selectStrand(sid)
        else selectionManager.clearSelection()
      },
    })

    // Build the normalized staple list from the current design + store colors.
    function _buildRecords() {
      const { currentDesign, currentGeometry, strandColors, strandGroups } = store.getState()
      const design = currentDesign
      if (!design) return { records: [], saved: null }
      const idtNames = buildIdtStrandNames(design, strandGroups, design.plate_layout)
      const helixById = Object.fromEntries((design.helices ?? []).map(h => [h.id, h]))

      // Effective per-strand colors (hex ints): strandColors + group overrides.
      const eff = { ...(strandColors ?? {}) }
      for (const g of strandGroups ?? []) {
        if (g.color) {
          const hex = parseInt(g.color.replace('#', ''), 16)
          for (const sid of g.strandIds) eff[sid] = hex
        }
      }
      // Palette map = the SAME per-strand palette the 3D scene paints (staples
      // with no explicit colour). Compute it directly from geometry so it never
      // depends on the renderer being in a built state; fall back to the live
      // controller map, then to the index-based palette (matches the scene's
      // STAPLE_PALETTE[strand_index] formula).
      const strandIdxOf = new Map((design.strands ?? []).map((s, i) => [s.id, i]))
      const paletteMap = (currentGeometry && currentGeometry.length)
        ? buildStapleColorMap(currentGeometry, design)
        : (designRenderer.getHelixCtrl()?.getPaletteColors() ?? new Map())

      // group order (array index = display order) + group id
      const groupOf = new Map()
      ;(strandGroups ?? []).forEach((g, i) => {
        for (const sid of g.strandIds) if (!groupOf.has(sid)) groupOf.set(sid, { order: i, id: g.id })
      })

      // first modification per strand
      const modOf = new Map()
      for (const e of design.extensions ?? []) {
        if (e.modification && !modOf.has(e.strand_id)) modOf.set(e.strand_id, e.modification)
      }

      const records = []
      let stapleIdx = 0
      for (const s of design.strands ?? []) {
        if (s.strand_type !== 'staple' || s.is_reference) continue
        stapleIdx += 1
        // Resolve exactly as the scene's nucColor: override (strandColors +
        // groups) wins, else the palette slot. Never falls back to a flat grey
        // — every staple gets its scene colour.
        let color
        if (s.id in eff) {
          color = hexFromInt(eff[s.id])
        } else {
          const pm = paletteMap.get(s.id)
          color = (pm != null)
            ? hexFromInt(pm)
            : hexFromInt(PLATE_STAPLE_PALETTE[(strandIdxOf.get(s.id) ?? 0) % PLATE_STAPLE_PALETTE.length])
        }
        const grp = groupOf.get(s.id)
        const mod = modOf.get(s.id) || null
        records.push({
          strandId:   s.id,
          color,
          lengthNt:   strandLengthNt(s, helixById),
          groupId:    grp?.id ?? null,
          groupOrder: grp ? grp.order : Infinity,
          hasMod:     !!mod,
          modName:    mod ? (MOD_NAMES[mod] || mod) : null,
          sequence:   s.sequence || '',
          name:       idtNames[s.id] || `S${stapleIdx}`,
        })
      }
      return { records, saved: design.plate_layout ?? null }
    }

    // Refresh only when the inputs that affect the plate change — NOT when only
    // plate_layout changes (our own saves), which would reset the view.
    let _lastSig = null
    function _inputsSig(design, strandColors, strandGroups) {
      if (!design) return 'null'
      const strands = (design.strands ?? [])
        .filter(s => s.strand_type === 'staple' && !s.is_reference)
        .map(s => `${s.id}:${s.color || ''}:${s.domains?.length ?? 0}`)
      const exts = (design.extensions ?? []).map(e => `${e.strand_id}:${e.modification || ''}`)
      return JSON.stringify([design.id, strands, exts,
        strandGroups, Object.entries(strandColors ?? {})])
    }
    function _refresh() {
      const { records, saved } = _buildRecords()
      plateView.setData(records, saved)
      _renderedLayoutSig = _layoutSig(saved)
    }

    // Refresh + re-fit the plates whenever the tab becomes visible.
    const _vis = new MutationObserver(() => {
      if (paneEl.hasAttribute('hidden')) return
      _lastSig = _inputsSig(...(() => { const s = store.getState(); return [s.currentDesign, s.strandColors, s.strandGroups] })())
      _refresh()
      plateView.resetView()
    })
    _vis.observe(paneEl, { attributes: true, attributeFilter: ['hidden'] })

    // Refresh on relevant design/color/group changes while the pane is visible.
    store.subscribe((s) => {
      if (paneEl.hasAttribute('hidden')) return
      const sig = _inputsSig(s.currentDesign, s.strandColors, s.strandGroups)
      const layoutSig = _layoutSig(s.currentDesign?.plate_layout)
      if (sig === _lastSig && layoutSig === _renderedLayoutSig) return
      _lastSig = sig
      _refresh()
    })
  }
}

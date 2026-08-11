/**
 * Per-region representation overrides — resolution + editing (Path A).
 *
 * Mixed representation lets ONE structure render different regions at different
 * detail: e.g. a focal duplex at full bead-and-base detail against a coarse
 * cylinder-bundle background (publication figures).
 *
 * MODEL — overrides are stored as duplex COLUMNS (helix + bp ranges), not strand
 * ids, for two reasons:
 *   1. Position-stable: a strand break/merge/crossover reassigns strand ids but
 *      leaves nucleotide positions in place, so column-based overrides survive.
 *   2. Both strands: a cylinder represents the whole duplex (the scaffold gets no
 *      cylinder of its own), so a region's rep must cover BOTH the staple and the
 *      scaffold at each column — otherwise a staple→cylinders override would draw
 *      the duplex cylinder over the scaffold's still-full beads.
 *
 * The renderer consumes a per-column rep map; the UI computes column segments
 * from a strand/cluster selection. Pure / display-only.
 */

/** Per-column key (one duplex position; both strands share it). */
export function colKey(helixId, bp) {
  return `${helixId}:${bp}`
}

/**
 * Walk every override column in list order (last-wins), invoking cb(colKey, rep).
 * Shared by resolveRepOverrides + repColumnsByRep so the column model stays single-source.
 */
function _forEachOverrideColumn(design, cb) {
  for (const ov of design?.representation_overrides ?? []) {
    const rep = ov.representation ?? 'full'
    for (const seg of ov.segments ?? []) {
      const lo = Math.min(seg.bp_start, seg.bp_end)
      const hi = Math.max(seg.bp_start, seg.bp_end)
      for (let bp = lo; bp <= hi; bp++) cb(colKey(seg.helix_id, bp), rep)
    }
  }
}

/**
 * Resolve all overrides into a per-column rep map.
 * Overrides apply in list order; the LAST override covering a column wins.
 * Columns absent from the map follow the design's global representation.
 *
 * @param {object} design  currentDesign (representation_overrides)
 * @returns {{ columnRep: Map<string,'full'|'cylinders'|'surface'|'vdw'|'ballstick'> }}
 */
export function resolveRepOverrides(design) {
  const columnRep = new Map()
  _forEachOverrideColumn(design, (key, rep) => columnRep.set(key, rep))
  return { columnRep }
}

/**
 * Group overridden columns by the overlay reps that need a separate renderer.
 * Last-wins per column (a column ends up in exactly one set).
 * @returns {{ vdw:Set<string>, ballstick:Set<string>, stick:Set<string>, surface:Set<string> }}  ("helixId:bp")
 */
export function repColumnsByRep(design) {
  const vdw = new Set(), ballstick = new Set(), stick = new Set(), surface = new Set()
  const all = new Map()
  _forEachOverrideColumn(design, (key, rep) => all.set(key, rep))
  for (const [key, rep] of all) {
    if (rep === 'vdw') vdw.add(key)
    else if (rep === 'ballstick') ballstick.add(key)
    else if (rep === 'stick') stick.add(key)
    else if (rep === 'surface') surface.add(key)
  }
  return { vdw, ballstick, stick, surface }
}

// ── Selection → segments (UI helpers) ────────────────────────────────────────

/** Column footprint of the given strands' domains → segments. */
export function strandsToSegments(design, strandIds) {
  const sel = new Set(strandIds)
  const segs = []
  for (const s of design?.strands ?? []) {
    if (!sel.has(s.id)) continue
    for (const d of s.domains ?? []) {
      segs.push({ helix_id: d.helix_id, bp_start: Math.min(d.start_bp, d.end_bp), bp_end: Math.max(d.start_bp, d.end_bp) })
    }
  }
  return segs
}

/** Column footprint of the given domains → segments. domainRefs: [{strandId, domainIndex}]. */
export function domainsToSegments(design, domainRefs) {
  const strandById = new Map((design?.strands ?? []).map(s => [s.id, s]))
  const segs = []
  for (const { strandId, domainIndex } of domainRefs ?? []) {
    const d = strandById.get(strandId)?.domains?.[domainIndex]
    if (d) segs.push({ helix_id: d.helix_id, bp_start: Math.min(d.start_bp, d.end_bp), bp_end: Math.max(d.start_bp, d.end_bp) })
  }
  return segs
}

/**
 * Build a "Representation ▸" context-menu item with a flyout submenu of the
 * available reps. Reusable across the different right-click menus (strand,
 * domain, cluster, overhang, flexible). The flyout is a DOM child of the item so
 * a parent menu's "click outside to dismiss" (menu.contains(target)) still treats
 * clicks inside it as inside.
 *
 * @param {object} o
 * @param {(rep:string|null)=>void} o.apply   called with the chosen rep (null = reset)
 * @param {()=>void} o.dismiss                 dismiss the owning menu before applying
 * @returns {HTMLElement} the menu item (caller appends it, usually after a separator)
 */
export function createRepresentationMenuItem({ apply, dismiss }) {
  const item = document.createElement('div')
  item.style.cssText = 'padding:6px 14px;color:#eef;cursor:pointer;display:flex;' +
                       'justify-content:space-between;align-items:center;gap:14px'
  const label = document.createElement('span'); label.textContent = 'Representation'
  const arrow = document.createElement('span'); arrow.textContent = '▸'; arrow.style.color = '#8899aa'
  item.appendChild(label); item.appendChild(arrow)

  const fly = document.createElement('div')
  fly.style.cssText = 'position:fixed;display:none;background:#1e2a3a;border:1px solid #3a4a5a;' +
                      'border-radius:6px;padding:4px 0;min-width:128px;z-index:10000;' +
                      'box-shadow:0 4px 16px rgba(0,0,0,0.5);font-family:var(--font-ui);font-size:12px'
  const _opt = (text, rep, color) => {
    const o = document.createElement('div')
    o.textContent = text
    o.style.cssText = `padding:6px 14px;color:${color || '#eef'};cursor:pointer`
    o.addEventListener('mouseenter', () => { o.style.background = '#2a3a4a' })
    o.addEventListener('mouseleave', () => { o.style.background = 'transparent' })
    o.addEventListener('click', e => { e.stopPropagation(); dismiss?.(); apply(rep) })
    fly.appendChild(o)
  }
  _opt('Full detail', 'full')
  _opt('Cylinders', 'cylinders')
  _opt('Surface', 'surface')
  _opt('VDW', 'vdw')
  _opt('Ball & Stick', 'ballstick')
  _opt('Stick', 'stick')
  _opt('Reset to global', null, '#ffcc99')
  item.appendChild(fly)

  let _hideT = null
  const showFly = () => {
    if (_hideT) { clearTimeout(_hideT); _hideT = null }
    fly.style.display = 'block'
    const r = item.getBoundingClientRect()
    const fr = fly.getBoundingClientRect()
    let left = r.right - 2
    if (left + fr.width > window.innerWidth) left = r.left - fr.width + 2   // flip to the left
    let top = r.top - 4
    if (top + fr.height > window.innerHeight) top = window.innerHeight - fr.height - 8
    fly.style.left = `${Math.max(8, left)}px`
    fly.style.top  = `${Math.max(8, top)}px`
  }
  const hideFly = () => { _hideT = setTimeout(() => { fly.style.display = 'none' }, 200) }
  item.addEventListener('mouseenter', () => { item.style.background = '#2a3a4a'; showFly() })
  item.addEventListener('mouseleave', () => { item.style.background = 'transparent'; hideFly() })
  fly.addEventListener('mouseenter', () => { if (_hideT) { clearTimeout(_hideT); _hideT = null } })
  fly.addEventListener('mouseleave', hideFly)
  item.addEventListener('click', e => { e.stopPropagation(); showFly() })
  return item
}

/** Column footprint of the given overhangs (their single-stranded domains) → segments. */
export function overhangsToSegments(design, overhangIds) {
  const ids = new Set(overhangIds)
  const segs = []
  for (const s of design?.strands ?? []) {
    for (const d of s.domains ?? []) {
      if (d.overhang_id && ids.has(d.overhang_id)) {
        segs.push({ helix_id: d.helix_id, bp_start: Math.min(d.start_bp, d.end_bp), bp_end: Math.max(d.start_bp, d.end_bp) })
      }
    }
  }
  return segs
}

/** Column footprint of the given clusters (whole member helices + sub-domains). */
export function clustersToSegments(design, clusterIds) {
  const sel = new Set(clusterIds)
  const helixById = new Map((design?.helices ?? []).map(h => [h.id, h]))
  const strandById = new Map((design?.strands ?? []).map(s => [s.id, s]))
  const segs = []
  for (const c of design?.cluster_transforms ?? []) {
    if (!sel.has(c.id)) continue
    for (const hid of c.helix_ids ?? []) {
      const h = helixById.get(hid)
      if (h) segs.push({ helix_id: hid, bp_start: h.bp_start, bp_end: h.bp_start + h.length_bp - 1 })
    }
    for (const dr of c.domain_ids ?? []) {
      const d = strandById.get(dr.strand_id)?.domains?.[dr.domain_index]
      if (d) segs.push({ helix_id: d.helix_id, bp_start: Math.min(d.start_bp, d.end_bp), bp_end: Math.max(d.start_bp, d.end_bp) })
    }
  }
  return segs
}

// ── Segment set algebra (for merge/edit) ─────────────────────────────────────

/** segments → Map<helixId, Set<bp>>. */
function _segColumns(segments) {
  const m = new Map()
  for (const seg of segments ?? []) {
    const lo = Math.min(seg.bp_start, seg.bp_end)
    const hi = Math.max(seg.bp_start, seg.bp_end)
    let set = m.get(seg.helix_id)
    if (!set) { set = new Set(); m.set(seg.helix_id, set) }
    for (let bp = lo; bp <= hi; bp++) set.add(bp)
  }
  return m
}

/** Map<helixId, Set<bp>> → compressed segments (consecutive bps → one range). */
function _columnsToSegments(cols) {
  const segs = []
  for (const [helixId, set] of cols) {
    const sorted = [...set].sort((a, b) => a - b)
    let i = 0
    while (i < sorted.length) {
      let j = i
      while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++
      segs.push({ helix_id: helixId, bp_start: sorted[i], bp_end: sorted[j] })
      i = j + 1
    }
  }
  return segs
}

/**
 * Edit the overrides list for a column selection (merge semantics — used by the UI).
 *
 * A column carries at most one rep, so assigning first REMOVES the selected
 * columns from every existing override, then adds them to an override of the
 * chosen rep (merging into an existing same-rep override). `rep === null` just
 * removes them (Reset to global). Empty overrides are dropped. Returns a NEW
 * array; never mutates the input.
 */
export function editOverridesForSegments(overrides, segments, rep) {
  const removal = _segColumns(segments)
  if (!removal.size) return (overrides ?? []).map(o => ({ ...o }))

  const out = (overrides ?? []).map(ov => {
    const cols = _segColumns(ov.segments)
    for (const [h, bps] of removal) {
      const set = cols.get(h)
      if (set) for (const bp of bps) set.delete(bp)
    }
    return { ...ov, segments: _columnsToSegments(cols) }
  })

  if (rep) {
    const target = out.find(ov => ov.representation === rep)
    if (target) {
      const cols = _segColumns(target.segments)
      for (const [h, bps] of removal) {
        let set = cols.get(h)
        if (!set) { set = new Set(); cols.set(h, set) }
        for (const bp of bps) set.add(bp)
      }
      target.segments = _columnsToSegments(cols)
    } else {
      out.push({ name: '', representation: rep, segments: _columnsToSegments(removal) })
    }
  }

  return out.filter(ov => ov.segments?.length)
}

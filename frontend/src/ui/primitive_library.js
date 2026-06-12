/**
 * Primitives panel — the right-sidebar "Primitives" section shown when the user
 * picks Tools → Add Primitive. Lists the pre-validated DNA-origami building
 * blocks as a scrollable, hover-highlighted, single-select card list.
 *
 * Source of the list: the backend `GET /primitives` endpoint (scans
 * workspace/Primitives/ for now — see workspace/Primitives/README.md for the
 * planned in-repo registry). The static `primitive_catalog.js` is the offline
 * FALLBACK rendered immediately so the panel is never empty, then upgraded in
 * place when the fetch resolves.
 *
 * Each card shows a static poster thumbnail that swaps to the looping preview GIF
 * while hovered (best practice — never autoplay a wall of GIFs). Primitives with
 * no generated preview fall back to the inline SVG cross-section schematic.
 *
 * Scope today is intentionally tiny: activate() reveals the section and the user
 * can highlight a primitive — selecting does NOT instantiate anything yet (the
 * placement UX isn't finalized). This module owns panel visibility, collapse
 * state, the card list, and the selection highlight; nothing about topology.
 *
 * @param {object} [deps]
 * @param {object} [deps.store]  reserved for future instantiation; unused today.
 * @param {object} [deps.api]    api client (uses `api.listPrimitives()`).
 * @returns {{ activate: Function, hide: Function, isActive: () => boolean, getSelected: () => string|null }}
 */
import { PRIMITIVES, primitiveMeta, primitiveThumbSvg } from './primitive_catalog.js'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { latticeCompatible } from '../scene/primitive_placement_logic.js'
import { showToast } from './toast.js'

const _NOOP_API = {
  activate() {},
  hide() {},
  isActive: () => false,
  getSelected: () => null,
}

// Normalize either source into one card shape the renderer understands.
function _fromCatalog(p) {
  return {
    id: p.id, name: p.name, shortName: p.shortName, description: p.description,
    meta: primitiveMeta(p), helixCount: p.helixCount, posterUrl: null, previewUrl: null,
  }
}
function _fromApi(p) {
  return {
    id: p.id, name: p.name, shortName: p.short_name, description: p.description,
    meta: primitiveMeta({ lattice: p.lattice, helixCount: p.helix_count }),
    helixCount: p.helix_count, posterUrl: p.poster_url, previewUrl: p.preview_url,
    placement: p.placement ?? null,
  }
}

export function initPrimitiveLibrary({ store, api, placement } = {}) {
  const panel = document.getElementById('primitives-panel')
  const heading = document.getElementById('primitives-panel-heading')
  const arrow = document.getElementById('primitives-panel-arrow')
  const body = document.getElementById('primitives-panel-body')
  const listEl = document.getElementById('primitives-list')
  if (!panel || !listEl) return _NOOP_API

  // Inline placement controls (revealed when a primitive with a placement spec is selected).
  const placeBox = document.getElementById('primitive-placement')
  const placeName = document.getElementById('primitive-placement-name')
  const planeSel = document.getElementById('primitive-plane')
  const lenInput = document.getElementById('primitive-length')
  const placeCancel = document.getElementById('primitive-place-cancel')

  let _active = false
  let _selectedId = null
  let _cardsById = new Map()   // id → normalized card (carries .placement)

  // ── Collapse / expand (persisted) ──────────────────────────────────────────
  let _collapsed = getSectionCollapsed('tools', 'primitives-panel', false)
  if (body) body.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)
  heading?.addEventListener('click', () => {
    _collapsed = !_collapsed
    if (body) body.style.display = _collapsed ? 'none' : ''
    if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('tools', 'primitives-panel', _collapsed)
  })

  // ── Card list ──────────────────────────────────────────────────────────────
  function _thumbHtml(c) {
    if (c.posterUrl) {
      const anim = c.previewUrl ? ` data-anim="${c.previewUrl}"` : ''
      return `<img class="primitive-thumb-img" src="${c.posterUrl}"${anim} alt="" draggable="false">`
    }
    return primitiveThumbSvg(c.helixCount)
  }

  function _render(cards) {
    listEl.innerHTML = cards.map(
      (c) => `
      <button type="button" class="primitive-card" data-primitive-id="${c.id}" role="option" aria-selected="false">
        <span class="primitive-thumb">${_thumbHtml(c)}</span>
        <span class="primitive-card-body">
          <span class="primitive-card-title">${c.name}<span class="primitive-card-badge">${c.shortName}</span></span>
          <span class="primitive-card-desc">${c.description}</span>
          <span class="primitive-card-meta">${c.meta}</span>
        </span>
      </button>`,
    ).join('')

    _cardsById = new Map(cards.map((c) => [c.id, c]))
    for (const card of listEl.querySelectorAll('.primitive-card')) {
      const c = _cardsById.get(card.dataset.primitiveId)
      card.addEventListener('click', () => _select(card.dataset.primitiveId))
      // Poster → looping GIF in the small thumb; plus a larger workspace-corner
      // preview, both on hover. Capture poster/anim once (src mutates on hover).
      const img = card.querySelector('.primitive-thumb-img[data-anim]')
      const poster = img?.getAttribute('src') ?? null
      const anim = img?.getAttribute('data-anim') ?? null
      card.addEventListener('mouseenter', () => {
        if (img && anim) img.src = anim
        _showZoom(c)
      })
      card.addEventListener('mouseleave', () => {
        if (img && poster) img.src = poster
        _hideZoom()
      })
    }
    if (_selectedId) _applySelection(_selectedId)   // survive a re-render
  }

  // ── Workspace-corner hover zoom ─────────────────────────────────────────────
  let _zoom = null
  function _ensureZoom() {
    if (_zoom) return _zoom
    let box = document.getElementById('primitive-preview-zoom')
    if (!box) {
      box = document.createElement('div')
      box.id = 'primitive-preview-zoom'
      box.className = 'primitive-preview-zoom'
      box.innerHTML =
        '<img alt="" draggable="false"><div class="ppz-svg"></div><div class="ppz-caption"></div>'
      document.body.appendChild(box)
    }
    box._img = box.querySelector('img')
    box._svg = box.querySelector('.ppz-svg')
    box._caption = box.querySelector('.ppz-caption')
    _zoom = box
    return box
  }

  function _showZoom(c) {
    if (!c) return
    const box = _ensureZoom()
    const src = c.previewUrl ?? c.posterUrl
    if (src) {
      box._img.src = src
      box._img.style.display = ''
      box._svg.style.display = 'none'
    } else {
      box._svg.innerHTML = primitiveThumbSvg(c.helixCount, { size: 240 })
      box._svg.style.display = ''
      box._img.style.display = 'none'
      box._img.removeAttribute('src')
    }
    box._caption.textContent = c.name
    box.style.display = 'block'
    _positionZoom(box)
  }

  function _hideZoom() {
    if (_zoom) _zoom.style.display = 'none'
  }

  // Pin to the upper-right of the workspace: against the right edge of
  // #viewport-container (i.e. just left of the right panel, where the cursor is)
  // and below the selectable strip (#filter-view-strip's bottom), constrained to
  // the visible workspace so it never spills over the left sidebar.
  function _positionZoom(box) {
    const container = document.getElementById('viewport-container')
    if (!container) { box.style.display = 'none'; return }
    const cr = container.getBoundingClientRect()
    const strip = document.getElementById('filter-view-strip')
    const sr = strip?.getBoundingClientRect()
    const top = (sr ? sr.bottom : cr.top) + 12
    const maxW = Math.max(140, cr.width - 24)
    const maxH = Math.max(140, cr.bottom - top - 12)
    box.style.left = 'auto'
    box.style.right = `${Math.max(12, window.innerWidth - cr.right + 12)}px`
    box.style.top = `${top}px`
    const w = Math.min(340, maxW)
    box._img.style.width = `${w}px`
    box._img.style.maxHeight = `${maxH}px`
    box._svg.style.width = `${Math.min(240, w)}px`
  }

  function _applySelection(id) {
    for (const card of listEl.querySelectorAll('.primitive-card')) {
      const on = card.dataset.primitiveId === id
      card.classList.toggle('is-selected', on)
      card.setAttribute('aria-selected', on ? 'true' : 'false')
    }
  }

  // ── Placement ────────────────────────────────────────────────────────────────

  function _currentLength() {
    return Math.max(1, parseInt(lenInput?.value ?? '', 10) || 1)
  }

  // Build the placement spec the slice-plane consumes from a card + chosen plane/length.
  function _specFor(c, plane, lengthBp) {
    const p = c.placement
    return {
      cells: p.cells, anchorCell: p.anchor_cell,
      lengthBp, plane,
      strandFilter: p.strand_filter ?? 'both',
      ligateAdjacent: p.ligate_adjacent ?? true,
      latticeType: p.lattice ?? 'HONEYCOMB',
    }
  }

  // Enter placement mode for a selected primitive: prefill the controls and arm the
  // slice-plane footprint. Guards lattice compatibility against the current design.
  function _enterPlacement(c) {
    const p = c?.placement
    if (!p || !p.cells?.length || !placement?.enter) return   // no spec → highlight only
    const d = store?.getState?.().currentDesign
    const empty = !(d?.helices?.length)
    if (!latticeCompatible(d?.lattice_type, p.lattice, empty)) {
      showToast(
        `${c.name} is ${p.lattice}; the current design is ${d?.lattice_type}. Lattices can't be mixed.`,
        { severity: 'error' },
      )
      _exitPlacement()
      return
    }
    const plane = p.plane || 'XY'
    if (planeSel) planeSel.value = plane
    if (lenInput) lenInput.value = String(p.length_bp || 1)
    if (placeName) placeName.textContent = `Place: ${c.name}`
    if (placeBox) placeBox.style.display = 'block'
    placement.enter(_specFor(c, plane, _currentLength()))
  }

  // Leave placement mode + clear the highlight (we exit after a single placement).
  function _exitPlacement() {
    _selectedId = null
    _applySelection(null)
    if (placeBox) placeBox.style.display = 'none'
  }

  planeSel?.addEventListener('change', () => {
    const c = _selectedId && _cardsById.get(_selectedId)
    if (c?.placement) placement?.enter?.(_specFor(c, planeSel.value, _currentLength()))
  })
  lenInput?.addEventListener('input', () => placement?.setLength?.(_currentLength()))
  placeCancel?.addEventListener('click', () => { _exitPlacement(); placement?.cancel?.() })

  // Selecting a card highlights it and arms placement (if it carries a placement spec).
  function _select(id) {
    _selectedId = id
    _applySelection(id)
    _enterPlacement(_cardsById.get(id))
  }

  // Render the static fallback immediately, then upgrade to the live catalog.
  _render(PRIMITIVES.map(_fromCatalog))
  api?.listPrimitives?.().then((list) => {
    if (Array.isArray(list) && list.length) _render(list.map(_fromApi))
  }).catch(() => { /* keep the fallback */ })

  function activate() {
    _active = true
    panel.style.display = 'block'
  }

  function hide() {
    _active = false
    panel.style.display = 'none'
    _hideZoom()
    _exitPlacement()
  }

  return {
    activate, hide, isActive: () => _active, getSelected: () => _selectedId,
    // Called by the host after a placement commits (exit-after-one-placement) or to
    // tear down placement mode externally (e.g. Escape).
    exitPlacement: _exitPlacement,
  }
}

/**
 * NADOC Origami Editor — main entry point.
 *
 * Initialises the sliceview (SVG lattice picker) and pathview (Canvas strand
 * editor), fetches the current design, and keeps both views in sync with the
 * backend via BroadcastChannel + direct API polls.
 */

import { editorStore }   from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import { fetchDesign, addHelixAtCell, deleteHelix, autoScaffold, scaffoldDomainPaint } from './api.js'
import { initSliceview }  from './sliceview.js'
import { initPathview }   from './pathview.js'

// ── DOM refs ────────────────────────────────────────────────────────────────
const loadingOverlay  = document.getElementById('loading-overlay')
const origamiNameEl   = document.getElementById('origami-name')
const statusStrandEl  = document.getElementById('status-strand-info')
const statusRightEl   = document.getElementById('status-right')
const sliceSvg        = document.getElementById('sliceview-svg')
const pathCanvas      = document.getElementById('pathview-canvas')
const pathContainer   = document.getElementById('pathview-container')

// ── Tool buttons ────────────────────────────────────────────────────────────
const toolBtns = {
  select: document.getElementById('tool-select'),
  pencil: document.getElementById('tool-pencil'),
  erase:  document.getElementById('tool-erase'),
}
for (const [tool, btn] of Object.entries(toolBtns)) {
  btn.addEventListener('click', () => {
    editorStore.setState({ selectedTool: tool })
  })
}

document.getElementById('btn-autoscaffold').addEventListener('click', async () => {
  await autoScaffold()
})

document.getElementById('open-3d-btn').addEventListener('click', () => {
  // Try to focus an existing NADOC 3D tab; fall back to opening a new one
  window.open('/', '_blank')
})

// Keyboard shortcuts
window.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  if (e.key === 's' || e.key === 'S') editorStore.setState({ selectedTool: 'select' })
  if (e.key === 'p' || e.key === 'P') editorStore.setState({ selectedTool: 'pencil' })
  if (e.key === 'e' || e.key === 'E') editorStore.setState({ selectedTool: 'erase' })
})

// ── Init views ──────────────────────────────────────────────────────────────
const sliceContainerEl = document.getElementById('sliceview-container')
const sliceview = initSliceview(sliceSvg, sliceContainerEl, {
  onAddHelix:    ({ row, col }) => addHelixAtCell(row, col),
  onRemoveHelix: (helixId)     => deleteHelix(helixId),
})

const pathview = initPathview(pathCanvas, pathContainer, {
  onPaintScaffold: (helixId, loBp, hiBp) => scaffoldDomainPaint(helixId, loBp, hiBp),
  onStrandHover:   (info) => {
    editorStore.setState({ hoveredStrand: info })
  },
})

// ── Store subscriptions ──────────────────────────────────────────────────────
editorStore.subscribe((state, prev) => {
  // Update tool button active states + notify pathview
  if (state.selectedTool !== prev.selectedTool) {
    for (const [tool, btn] of Object.entries(toolBtns)) {
      btn.classList.toggle('active', tool === state.selectedTool)
    }
    pathview.setTool(state.selectedTool)
  }

  // Update origami name in toolbar
  if (state.design !== prev.design) {
    const name = state.design?.metadata?.name ?? 'Untitled'
    origamiNameEl.textContent = name
    document.title = `NADOC — ${name}`
    sliceview.update(state.design)
    pathview.update(state.design)
  }

  // Update status bar strand hover info
  if (state.hoveredStrand !== prev.hoveredStrand) {
    if (state.hoveredStrand) {
      const { strandType, strandId, ntCount } = state.hoveredStrand
      const label = strandType === 'SCAFFOLD' ? 'Scaffold' : `Staple ${strandId}`
      statusStrandEl.textContent = `${label} — ${ntCount} nt`
    } else {
      statusStrandEl.textContent = '—'
    }
  }

  // Loading overlay
  if (state.loading !== prev.loading) {
    loadingOverlay.classList.toggle('hidden', !state.loading)
  }
})

// ── BroadcastChannel ────────────────────────────────────────────────────────
nadocBroadcast.onMessage(({ type }) => {
  if (type === 'design-changed') {
    fetchDesign()
  }
})

// ── Initial load ─────────────────────────────────────────────────────────────
;(async () => {
  loadingOverlay.classList.remove('hidden')
  await fetchDesign()
  loadingOverlay.classList.add('hidden')
})()

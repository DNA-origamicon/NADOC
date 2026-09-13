import { createModal } from './primitives/modal.js'
import { NAMD_PEG_DEFAULTS, namdPegFormSpec, namdPegEstimate } from './namd_peg_surface_model.js'
import './namd_peg_surfaces.css'

const element = (tag, text, cls) => {
  const node = document.createElement(tag)
  if (text) node.textContent = text
  if (cls) node.className = cls
  return node
}
const button = (label, action, cls = 'btn') => {
  const node = element('button', label, cls); node.type = 'button'
  node.addEventListener('click', action)
  return node
}

/** Workspace-level surface library: works in blank, part and assembly documents. */
export function initNamdPegSurfaces({ api, host = document.getElementById('namd-peg-surfaces') }) {
  if (!host) return null
  const launch = host.querySelector('[data-new-surface]')
  const menu = document.getElementById('menu-namd-peg-surfaces')
  const library = host.querySelector('select')
  const openSaved = host.querySelector('[data-open-surface]')
  const status = host.querySelector('[role=status]')
  let records = [], modal = null, revision = 0, busy = false, activeId = null, pending = null
  let form, setup, review, message, summary, back, next, save, opener, formLibrary, dirty = false, libraryRevision = 0, disposed = false
  const setBusy = value => {
    busy = value
    if (formLibrary) formLibrary.disabled = value
    if (form) for (const field of form.elements) field.disabled = value
    if (back) back.disabled = value
    if (next) next.disabled = value
    if (save) save.disabled = value
    if (!value && form) repaint()
  }
  async function refresh() {
    const token = ++libraryRevision
    try {
      const result = await api.listNamdPegSurfaces()
      if (disposed || token !== libraryRevision) return
      records = result
      if (!Array.isArray(records)) throw new Error('Could not load surface drafts. Try opening the library again.')
      library.replaceChildren(new Option(records.length ? 'Select a saved surface…' : 'No saved surfaces yet', ''))
      for (const record of records) library.add(new Option(`${record.spec.name} · draft`, record.id))
      if (formLibrary) {
        formLibrary.replaceChildren(new Option('New surface', ''))
        for (const record of records) formLibrary.add(new Option(`${record.spec.name} · draft`, record.id))
        formLibrary.value = activeId || ''
      }
      openSaved.disabled = !library.value
      status.textContent = ''
    } catch (error) { status.textContent = error.message }
  }
  function field(label, key, options = {}) {
    const wrap = element('label', '', 'namd-peg-field')
    wrap.append(element('span', label))
    const input = element(options.choices ? 'select' : 'input')
    input.name = key
    if (options.choices) for (const [value, title] of options.choices) input.add(new Option(title, value))
    else {
      input.type = options.type || 'number'
      if (input.type === 'number') { input.step = options.step || 'any'; input.required = true }
      for (const attr of ['min', 'max', 'maxLength']) if (options[attr] != null) input[attr] = options[attr]
    }
    input.value = pending[key]
    wrap.append(input)
    return wrap
  }
  function repaint() {
    const material = form.elements.material.value, atomistic = form.elements.representation.value === 'atomistic'
    const hide = (key, hidden) => {
      form.elements[key].closest('label').hidden = hidden
      form.elements[key].disabled = busy || hidden
    }
    for (const key of ['pore_diameter_nm', 'layers']) hide(key, material !== 'graphene')
    hide('repeat_units', !atomistic); hide('segments', atomistic)
    try {
      pending = namdPegFormSpec(form)
      const estimate = namdPegEstimate(pending)
      summary.textContent = Number.isFinite(estimate.chains) && estimate.chains > 0
        ? `${estimate.chains.toLocaleString()} requested chains · ${estimate.area.toFixed(1)} nm² coating area`
        : 'Choose a patch size and density that include at least one chain.'
    } catch (error) { summary.textContent = error.message }
  }
  function showSetup() {
    revision++; setup.hidden = false; review.hidden = true
    back.hidden = true; save.hidden = true; next.hidden = false; message.textContent = ''
    repaint()
  }
  function drawReview(result) {
    review.replaceChildren(element('h3', 'Review NAMD surface draft'))
    review.append(element('p', `${result.spec.name} · ${result.summary.chains.toLocaleString()} PEG chains`))
    review.append(element('p', 'Graft layout preview (top view). Sites are schematic; PEG conformations and atom positions are not built.', 'namd-peg-note'))
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('viewBox', '-110 -110 220 220')
    svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'PEG graft layout preview')
    const shape = (tag, attrs) => {
      const node = document.createElementNS(svg.namespaceURI, tag)
      for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v)
      svg.append(node)
    }
    const size = result.spec.size_nm
    shape(result.spec.shape === 'circle' ? 'circle' : 'rect', result.spec.shape === 'circle'
      ? { cx: 0, cy: 0, r: 100, class: 'namd-peg-patch' }
      : { x: -100, y: -100, width: 200, height: 200, class: 'namd-peg-patch' })
    if (result.spec.pore_diameter_nm) shape('circle', { cx: 0, cy: 0,
      r: result.spec.pore_diameter_nm/size*100, class: 'namd-peg-pore' })
    for (const [x, y] of result.preview.local_sites_nm) shape('circle', { cx: x/size*200, cy: -y/size*200, r: 2.5, class: 'namd-peg-graft' })
    review.append(svg, element('p', `${result.summary.preview_sites} of ${result.summary.chains} intended sites shown. Normal ${result.spec.normal_axis}; plane position ${result.spec.position_nm} nm.`, 'namd-peg-note'))
    review.append(element('h4', 'Before this surface can run in NAMD'))
    const barriers = element('ul')
    for (const barrier of result.barriers) barriers.append(element('li', barrier.message))
    review.append(barriers, element('p', 'Saving creates an editable surface draft. It does not create or start a simulation.'))
    setup.hidden = true; review.hidden = false; back.hidden = false; next.hidden = true; save.hidden = false
    save.textContent = activeId ? 'Save changes' : 'Create surface draft'
    back.focus()
  }
  async function reviewSetup() {
    if (busy) return
    if (!form.reportValidity()) return
    let spec
    try { spec = namdPegFormSpec(form) } catch (e) { message.textContent = e.message; return }
    const token = ++revision
    setBusy(true); message.textContent = 'Reviewing surface…'
    try {
      const result = await api.reviewNamdPegSurface(spec)
      if (disposed || token !== revision) return
      if (!result) throw new Error('Surface review failed. Check your values and retry.')
      pending = result.spec
      drawReview(result); message.textContent = ''
    } catch (e) { if (token === revision) message.textContent = e.message }
    finally { setBusy(false) }
  }
  async function saveDraft() {
    if (busy || review.hidden) return
    setBusy(true); message.textContent = 'Saving surface draft…'
    try {
      const result = await api.saveNamdPegSurface(pending, activeId)
      if (!result) throw new Error('Surface was not saved. Your settings are still here; retry.')
      if (disposed) return
      activeId = result.id; pending = result.spec; dirty = false
      await refresh()
      library.value = result.id; openSaved.disabled = false
      message.textContent = 'Surface draft saved. You can reopen it from PEG surfaces in the NAMD sidebar.'
      status.textContent = `${result.spec.name} saved · simulation setup incomplete`
      save.textContent = 'Save changes'
    } catch (e) { message.textContent = e.message }
    finally { setBusy(false) }
  }
  function open(record = null, resume = false) {
    if (modal?.isOpen()) return
    opener = document.activeElement
    if (!resume || !pending) {
      activeId = record?.id || null
      pending = { ...NAMD_PEG_DEFAULTS, ...record?.spec }; dirty = false
    }
    form = element('form'); form.addEventListener('submit', e => { e.preventDefault(); reviewSetup() })
    setup = element('section'); review = element('section'); review.hidden = true
    const picker = element('label', '', 'namd-peg-field')
    picker.append(element('span', 'Open saved surface'))
    formLibrary = element('select'); formLibrary.add(new Option('New surface', ''))
    for (const item of records) formLibrary.add(new Option(`${item.spec.name} · draft`, item.id))
    formLibrary.value = activeId || ''
    formLibrary.addEventListener('change', () => {
      if (busy) return
      const selected = records.find(r => r.id === formLibrary.value)
      dirty = false; modal.close(); open(selected)
    })
    picker.append(formLibrary); setup.append(picker)

    setup.append(element('p', 'Design a PEG-coated support directly for NAMD. No oxDNA job or DNA document is required.', 'namd-peg-note'))
    form.append(field('Surface name', 'name', { type: 'text', maxLength: 100 }))
    form.append(element('h3', '1 · Support and graft layout'))
    const support = element('div', '', 'namd-peg-grid')
    support.append(
      field('Support', 'material', { choices: [['hard_wall', 'Hard barrier'], ['graphene', 'Graphene']] }),
      field('Allowed-side normal', 'normal_axis', { choices: ['+z', '-z', '+y', '-y', '+x', '-x'].map(v => [v, v.toUpperCase()]) }),
      field('Plane position (nm)', 'position_nm', { min: -10000, max: 10000 }),
      field('Patch shape', 'shape', { choices: [['square', 'Square'], ['circle', 'Circle']] }),
      field('Patch width / diameter (nm)', 'size_nm', { min: 2, max: 1000 }),
      field('Graft density (chains/nm²)', 'density_per_nm2', { min: .000001, max: 10 }),
      field('Pore diameter (nm; 0 = no pore)', 'pore_diameter_nm', { min: 0, max: 1000 }),
      field('Graphene layers', 'layers', { min: 1, max: 6, step: 1 }),
      field('Layout seed', 'seed', { min: 0, max: 4294967295, step: 1 }),
    )
    form.append(support, element('h3', '2 · PEG chains'))
    const chains = element('div', '', 'namd-peg-grid')
    chains.append(
      field('PEG representation', 'representation', { choices: [['atomistic', 'Atomistic PEG'], ['coarse_grained', 'Coarse-grained PEG']] }),
      field('Ethylene-oxide repeat units / chain', 'repeat_units', { min: 1, max: 10000, step: 1 }),
      field('Statistical segments / chain', 'segments', { min: 2, max: 1000, step: 1 }),
      field('Grafted and free end groups', 'end_groups', { type: 'text', maxLength: 200 }),
    )
    form.append(chains, element('p', 'Statistical segments and chemical repeat units are different quantities. Changing representation does not convert a molecular model.', 'namd-peg-note'))
    const assets = element('details'); assets.append(element('summary', 'Topology and force-field references (optional draft notes)'))
    assets.append(field('PEG topology / coordinate reference', 'topology_reference', { type: 'text', maxLength: 500 }),
      field('Force-field reference', 'parameter_reference', { type: 'text', maxLength: 500 }),
      element('p', 'References are saved as notes; files and compatibility have not been validated.', 'namd-peg-note'))
    form.append(assets); setup.append(form)
    summary = element('p', '', 'namd-peg-estimate'); summary.setAttribute('aria-live', 'polite')
    setup.append(summary)
    message = element('p'); message.setAttribute('role', 'status')
    back = button('Back to edit', showSetup); back.hidden = true
    next = button('Review surface', reviewSetup, 'btn btn--primary')
    save = button('Create surface draft', saveDraft, 'btn btn--primary'); save.hidden = true
    const close = button('Close', () => modal.close())
    modal = createModal({ title: activeId ? 'Edit NAMD PEG surface' : 'New NAMD PEG surface',
      size: 'lg', className: 'modal--namd-peg', body: [setup, review, message],
      actions: [close, back, next, save], onClose: () => {
        if (busy) return false
        if (dirty) pending = Object.fromEntries(Object.keys(NAMD_PEG_DEFAULTS).map(key => [key, form.elements.namedItem(key).value]))
        launch.textContent = dirty ? 'Continue surface draft…' : 'New PEG surface…'
        fresh.hidden = !dirty
        revision++; opener?.focus()
      } })
    modal.root.setAttribute('aria-label', 'NAMD PEG surface setup')
    // Keep keyboard navigation inside the dialog; Escape uses the common modal lifecycle.
    modal.root.addEventListener('keydown', e => {
      if (e.key !== 'Tab') return
      const nodes = [...modal.root.querySelectorAll('button, input, select, summary')]
        .filter(n => !n.disabled && !n.closest('[hidden]') && (n.offsetParent !== null))
      const first = nodes[0], last = nodes.at(-1)
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
    })
    const edited = () => { dirty = true; repaint() }
    form.addEventListener('input', edited); form.addEventListener('change', edited)
    repaint(); modal.open(); form.elements.name.focus()
  }
  const newSurface = () => { open(null, dirty); refresh() }
  const load = () => { const record = records.find(r => r.id === library.value); if (record) open(record) }
  const select = () => { openSaved.disabled = !library.value }
  launch.addEventListener('click', newSurface)
  menu?.addEventListener('click', newSurface)
  openSaved.addEventListener('click', load)
  library.addEventListener('change', select)
  // A separate explicit action starts fresh without silently overwriting a saved draft.
  const fresh = button('Start another surface', () => { pending = null; open() })
  fresh.hidden = true
  host.append(fresh)
  refresh()
  return { open, refresh, dispose() {
    disposed = true; revision++; busy = false
    modal?.close(); launch.removeEventListener('click', newSurface)
    menu?.removeEventListener('click', newSurface)
    openSaved.removeEventListener('click', load); library.removeEventListener('change', select); fresh.remove()
  } }
}

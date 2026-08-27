import { createButton, createModal, el } from './primitives/index.js'
import { initWizardTargetStep } from './md_job_wizard_target.js'
import { oxdnaConfigDocument, oxdnaRunpodPlanShape, oxdnaStagePlan, oxdnaWizardDefaults, oxdnaWizardPayload } from './oxdna_job_wizard_model.js'

const TABS = [['target', 'Where it runs'], ['settings', 'Parameters & options'], ['config', 'Full configuration']]
const FIELDS = [
  { key: 'interaction_type', label: 'Force-field version', type: 'select',
    options: [['DNA2', 'oxDNA2 (recommended)'], ['DNA', 'oxDNA1 (legacy)']],
    help: 'oxDNA2 improves major/minor-groove geometry and is NADOC’s default. oxDNA1 is available for reproducing legacy studies.' },
  { key: 'backend', label: 'MD backend', type: 'select', options: [['CUDA', 'CUDA (GPU)'], ['CPU', 'CPU']], local: true, help: 'MC is always CPU. This selects the backend for MD relaxation and equilibration.' },
  { key: 'device', label: 'CUDA device', type: 'text', local: true },
  { key: 'salt_concentration', label: 'Salt concentration', unit: 'M', type: 'number', min: .01, step: .05 },
  { key: 'mc_steps', label: 'MC relaxation', unit: 'steps', type: 'number', min: 100, step: 500 },
  { key: 'md_relax_steps', label: 'MD relaxation', unit: 'steps', type: 'number', min: 100, step: 100000 },
  { key: 'equil_steps', label: 'Equilibration', unit: 'steps', type: 'number', min: 100, step: 10000 },
  { key: 'min_bp_retained', label: 'Base-pair retention gate', type: 'number', min: 0, max: 1, step: .05, help: 'Stops a stage when retained designed base pairs fall below this fraction.' },
  { key: 'max_relax_retries', label: 'Escalating MD retries', type: 'number', min: 0, max: 3, step: 1, help: 'Retries a stuck backbone with longer runs and stronger force caps.' },
]

const EDITABLE_STAGE_FIELDS = new Set([
  'backend', 'steps', 'temperature', 'salt_concentration', 'device', 'ensemble',
  'delta_translation', 'delta_rotation', 'dt', 'thermostat', 'bussi_tau',
  'newtonian_steps', 'max_backbone_force', 'max_backbone_force_far',
  'external_forces', 'min_bp_retained', 'print_conf_interval', 'print_energy_every',
])
const ROW_LABELS = {
  sim_type: 'Simulation type', interaction_type: 'Force-field version', backend: 'Backend',
  steps: 'Steps', temperature: 'Temperature', salt_concentration: 'Salt concentration (M)',
  device: 'CUDA device', ensemble: 'Ensemble', delta_translation: 'MC translation delta',
  delta_rotation: 'MC rotation delta', dt: 'Time step', thermostat: 'Thermostat',
  bussi_tau: 'Bussi tau', newtonian_steps: 'Newtonian steps',
  max_backbone_force: 'Backbone force cap', max_backbone_force_far: 'Far-force cap',
  external_forces: 'External forces', forces_file: 'Forces file', min_bp_retained: 'BP retention gate',
  conf_file: 'Starting configuration', last_conf_file: 'Final configuration',
  trajectory_file: 'Trajectory file', energy_file: 'Energy file',
  print_conf_interval: 'Configuration interval', print_energy_every: 'Energy interval',
  topology: 'Topology',
}

export function initOxdnaJobWizard({ api = {}, launch = async () => null, getInitialValues = () => ({}) } = {}) {
  let modal, targetStep, currentTab = 'target', values = oxdnaWizardDefaults(), busy = false
  const panels = {}, tabs = {}
  let previousBtn, nextBtn, createBtn, configPre, stageSummary, stageTable, engineDetails

  function renderSettings() {
    const grid = el('div', { className: 'wizard-field-grid' })
    panels.settings.replaceChildren(el('details', { attrs: { open: true }, children: [
      el('summary', { text: 'Engine versions & installation' }), engineDetails,
    ] }), grid)
    for (const field of FIELDS) {
      if (field.local && targetStep?.target !== 'local') continue
      const input = field.type === 'select' ? el('select') : el('input', { attrs: { type: field.type, min: field.min, max: field.max, step: field.step } })
      input.dataset.oxdnaField = field.key
      if (field.options) for (const [value, label] of field.options) input.append(el('option', { text: label, attrs: { value } }))
      input.value = values[field.key]
      input.addEventListener('input', () => {
        values[field.key] = field.type === 'number' ? Number(input.value) : input.value
        renderConfig(); targetStep?.refreshSizing?.()
      })
      grid.append(el('label', { className: 'wizard-field', children: [
        el('span', { className: 'wizard-field__label', text: field.label }), input,
        field.unit ? el('span', { className: 'wizard-field__unit', text: field.unit }) : null,
        field.help ? el('span', { className: 'wizard-field__help', text: field.help }) : null,
      ] }))
    }
  }

  function renderConfig() {
    if (!configPre) return
    configPre.textContent = oxdnaConfigDocument(values, targetStep?.payloadFields?.() || {})
    const stages = oxdnaStagePlan(values)
    stageSummary.textContent = `${stages.length} stages · ${stages.reduce((n, s) => n + s.steps, 0).toLocaleString()} scheduled steps`
    renderStageTable(stages)
  }

  function displayValue(value) {
    if (value == null) return '—'
    if (typeof value === 'boolean') return value ? 'true' : 'false'
    return String(value)
  }

  function parseEdit(text, previous) {
    const raw = String(text).trim()
    if (!raw) return undefined
    if (raw.toLowerCase() === '(none)') return null
    if (typeof previous === 'boolean') return raw.toLowerCase() === 'true'
    if (typeof previous === 'number') {
      const number = Number(raw)
      return Number.isFinite(number) ? number : previous
    }
    return raw
  }

  function setStageValue(stage, key, value) {
    values.stage_overrides ||= {}
    values.stage_overrides[stage] ||= {}
    if (value === undefined) delete values.stage_overrides[stage][key]
    else values.stage_overrides[stage][key] = value
    if (!Object.keys(values.stage_overrides[stage]).length) delete values.stage_overrides[stage]
    renderConfig(); targetStep?.refreshSizing?.()
  }

  function editStageCell(td, stage, key, value) {
    if (td.querySelector('input')) return
    const input = el('input', { className: 'wizard-cell__input', attrs: {
      type: 'text', value: '', placeholder: displayValue(value),
      'aria-label': `${ROW_LABELS[key] || key} on ${stage}`,
    } })
    let finished = false
    const finish = commit => {
      if (finished) return
      finished = true
      if (commit) setStageValue(stage, key, parseEdit(input.value, value))
      else renderConfig()
    }
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); finish(true) }
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); finish(false) }
    })
    input.addEventListener('blur', () => finish(true))
    td.replaceChildren(input); input.focus(); input.select()
  }

  function editEveryStage(key, stages) {
    const first = stages.find(stage => stage[key] != null)?.[key]
    const next = window.prompt(`Set ${ROW_LABELS[key] || key} for every applicable stage.\nBlank restores defaults.`, '')
    if (next === null) return
    const parsed = parseEdit(next, first)
    for (const stage of stages) if (stage[key] != null) setStageValue(stage.name, key, parsed)
  }

  function renderStageTable(stages) {
    if (!stageTable) return
    const keys = [...new Set(stages.flatMap(stage => Object.keys(stage)))]
      .filter(key => !['name', 'purpose'].includes(key))
    const head = el('tr', { children: [el('th', { className: 'param', text: 'Parameter' }),
      ...stages.map(stage => el('th', { className: 'wizard-col', children: [
        el('div', { className: 'wizard-col__name', text: stage.name }),
        el('div', { className: 'wizard-col__meta', text: `${Number(stage.steps).toLocaleString()} steps` }),
      ] }))] })
    const body = el('tbody')
    for (const key of keys) {
      const editable = EDITABLE_STAGE_FIELDS.has(key)
      body.append(el('tr', { children: [
        el('th', { className: 'param', children: [document.createTextNode(ROW_LABELS[key] || key),
          editable ? el('button', { className: 'wizard-row-all', text: '⋯', attrs: {
            type: 'button', title: `Set ${ROW_LABELS[key] || key} for every applicable stage`,
          }, on: { click: () => editEveryStage(key, stages) } }) : null] }),
        ...stages.map((stage, index) => {
          const present = stage[key] != null
          const overridden = Object.prototype.hasOwnProperty.call(values.stage_overrides?.[stage.name] || {}, key)
          const changed = index > 0 && displayValue(stage[key]) !== displayValue(stages[index - 1][key])
          const classes = ['wizard-cell', !present ? 'wizard-cell--absent' : '', changed ? 'wizard-cell--changed' : '',
            overridden ? 'wizard-cell--overridden' : '', !editable || !present ? 'wizard-cell--locked' : ''].filter(Boolean)
          const td = el('td', { className: classes.join(' '), text: displayValue(stage[key]), attrs: {
            title: editable && present ? 'Click to edit this stage. Blank restores the protocol value.' : 'Resolved by the job builder.',
          } })
          if (editable && present) {
            td.tabIndex = 0
            td.addEventListener('click', () => editStageCell(td, stage.name, key, stage[key]))
            td.addEventListener('keydown', event => { if (event.key === 'Enter') editStageCell(td, stage.name, key, stage[key]) })
          }
          return td
        }),
      ] }))
    }
    stageTable.replaceChildren(el('table', { children: [el('thead', { children: [head] }), body] }))
  }

  async function renderEngineDetails() {
    if (!engineDetails) return
    engineDetails.textContent = 'Detecting installed oxDNA engine…'
    const info = await api.getOxdnaAvailable?.().catch(() => null)
    if (!engineDetails) return
    engineDetails.innerHTML = info?.available
      ? `<strong>Installed engine</strong><br>${info.oxdna_bin || 'oxDNA'}<br>Build: ${info.build_flavor === 'adaptive-memory' ? 'NADOC adaptive-memory (large assemblies)' : 'Upstream oxDNA'}<br>${info.cuda_capable ? 'CUDA and CPU backends available' : 'CPU backend only'}${info.dnanm_capable ? '<br>DNANM hybrid support available' : ''}<br><br><strong>Target behavior</strong><br>Runpod uses NADOC’s adaptive-memory CUDA build for large assemblies. Local uses the binary shown above; Alpine will use the cluster build configured during backend wiring.<br><br><strong>Interaction models</strong><br>oxDNA2 / DNA2 — current NADOC default; improved groove geometry and salt-dependent electrostatics.<br>oxDNA1 / DNA — legacy model for reproducing older studies.`
      : '<strong>Engine not detected.</strong> Set <code>$OXDNA_BIN</code> or install oxDNA. Configuration remains available, but Run stays unavailable.'
  }

  function paint() {
    for (const [id] of TABS) {
      const selected = id === currentTab
      panels[id].hidden = !selected
      tabs[id].classList.toggle('is-selected', selected)
      tabs[id].setAttribute('aria-selected', String(selected))
    }
    const index = TABS.findIndex(([id]) => id === currentTab)
    previousBtn.style.display = index ? '' : 'none'
    nextBtn.style.display = index < TABS.length - 1 ? '' : 'none'
    createBtn.style.display = index === TABS.length - 1 ? '' : 'none'
    const ready = targetStep?.isReady?.() ?? true
    nextBtn.disabled = currentTab === 'target' && !ready
    createBtn.disabled = busy || !ready
    if (currentTab === 'settings') renderSettings()
    if (currentTab === 'config') renderConfig()
  }

  function selectTab(id) {
    if (id !== 'target' && !targetStep.isReady()) return
    currentTab = id; paint()
  }
  function step(delta) {
    const i = TABS.findIndex(([id]) => id === currentTab)
    selectTab(TABS[Math.max(0, Math.min(TABS.length - 1, i + delta))][0])
  }
  async function submit() {
    if (busy || !targetStep.isReady()) return
    busy = true; paint()
    try { if (await launch(oxdnaWizardPayload(values, targetStep.payloadFields()))) modal.close() }
    finally { busy = false; paint() }
  }

  function build() {
    previousBtn = createButton({ label: '← Previous', variant: 'ghost', onClick: () => step(-1) })
    nextBtn = createButton({ label: 'Next →', variant: 'primary', onClick: () => step(1) })
    createBtn = createButton({ label: 'Create job', variant: 'primary', onClick: () => void submit() })
    const cancel = createButton({ label: 'Cancel', variant: 'ghost', onClick: () => modal.close() })
    panels.target = el('section', { className: 'wizard-pane wizard-tabpanel' })
    panels.settings = el('section', { className: 'wizard-pane wizard-tabpanel' })
    engineDetails = el('div', { className: 'wizard-note' })
    configPre = el('pre', { className: 'oxdna-wizard-config' })
    stageTable = el('div', { className: 'wizard-stages' })
    stageSummary = el('div', { className: 'wizard-totals' })
    panels.config = el('section', { className: 'wizard-pane wizard-tabpanel', children: [stageSummary,
      el('p', { className: 'oxdna-wizard-note', text: 'Click an editable cell to override that stage. Blue cells change from the previous stage; amber cells are your overrides.' }),
      stageTable, el('details', { children: [el('summary', { text: 'Config document' }), configPre] })] })
    for (const [id, label] of TABS) tabs[id] = el('button', { className: 'wizard-tab', text: label, attrs: { type: 'button', role: 'tab' }, on: { click: () => selectTab(id) } })
    targetStep = initWizardTargetStep({ mount: panels.target, fetchHardware: api.fetchHardware,
      fetchAvailability: api.fetchAvailability, getSlurmPreview: api.getSlurmPreview, getTotalNs: () => 0,
      getJobPreview: api.getRunpodJobPreview, getVolumes: api.getRunpodVolumes, setVolume: api.setRunpodVolume,
      getPlanShape: () => oxdnaRunpodPlanShape(values), fsApi: api.fsApi,
      onChange: () => { renderSettings(); renderConfig(); paint() } })
    modal = createModal({ title: 'New oxDNA job', size: 'xl', className: 'modal--wizard modal--oxdna-wizard',
      body: el('div', { className: 'wizard', children: [el('div', { className: 'wizard-tabbar', children: [
        el('div', { className: 'wizard-tabs', attrs: { role: 'tablist' }, children: Object.values(tabs) })] }),
      panels.target, panels.settings, panels.config] }), actions: [cancel, previousBtn, nextBtn, createBtn] })
  }

  function open() {
    if (!modal) build()
    values = oxdnaWizardDefaults(getInitialValues())
    currentTab = 'target'; targetStep.render(); renderSettings()
    void renderEngineDetails()
    renderConfig(); paint(); modal.open()
  }
  return { open, close: () => modal?.close(), isOpen: () => !!modal?.isOpen?.(), currentValues: () => ({ ...values }) }
}

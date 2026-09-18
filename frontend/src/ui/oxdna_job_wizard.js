import { createButton, createModal, el } from './primitives/index.js'
import { initWizardTargetStep } from './md_job_wizard_target.js'
import { formatBytes } from './format_bytes.js'
import {
  oxdnaConfigDocument, oxdnaRunpodPlanShape, oxdnaStagePlan, oxdnaWizardDefaults, oxdnaWizardPayload, validateOxdnaWizard,
  oxdnaProductionDefaults, oxdnaProductionPayload, oxdnaProductionParents, oxdnaProductionStagePlan, validateOxdnaProductionWizard,
} from './oxdna_job_wizard_model.js'

const ALL_TABS = [['target', 'Where it runs'], ['settings', 'Parameters & options'], ['config', 'Full configuration']]
const PRODUCTION_TABS = [['settings', 'Run parameters'], ['config', 'Summary']]
const PRODUCTION_FIELDS = [
  { key: 'steps', label: 'Production steps', unit: 'steps', type: 'number', min: 1000, step: 1_000_000 },
  { key: 'steps_per_frame', label: 'Steps / frame', unit: 'steps', type: 'number', min: 1, step: 1000,
    help: 'oxDNA print_conf_interval — simulation steps between saved trajectory frames.' },
]
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
  { key: 'seed', label: 'Random seed', type: 'number', min: 1, step: 1, readOnly: true,
    help: 'This is the recorded base seed for the job. Copied jobs receive a new seed, which is preserved when their settings are edited.' },
]

const ENGINE_VARIANTS = [
  ['auto', 'Automatic', 'Choose the compatible build from the design and execution target.'],
  ['adaptive-memory', 'NADOC adaptive-memory', 'CUDA build for very large assemblies with compact adaptive neighbour lists.'],
  ['dnanm', 'Protein-capable DNANM', 'Hybrid DNA–protein build with the DNANM interaction model.'],
  ['upstream', 'Standard upstream oxDNA', 'General-purpose upstream engine without a required NADOC or protein extension.'],
]

const EDITABLE_STAGE_FIELDS = new Set([
  'backend', 'steps', 'temperature', 'salt_concentration', 'device', 'ensemble',
  'delta_translation', 'delta_rotation', 'dt', 'thermostat', 'diff_coeff', 'refresh_vel', 'bussi_tau',
  'newtonian_steps', 'max_backbone_force', 'max_backbone_force_far',
  'external_forces', 'min_bp_retained', 'print_conf_interval', 'print_energy_every',
])
const ROW_LABELS = {
  sim_type: 'Simulation type', interaction_type: 'Force-field version', backend: 'Backend',
  steps: 'Steps', temperature: 'Temperature', salt_concentration: 'Salt concentration (M)',
  device: 'CUDA device', ensemble: 'Ensemble', delta_translation: 'MC translation delta',
  delta_rotation: 'MC rotation delta', dt: 'Time step', thermostat: 'Thermostat',
  diff_coeff: 'Diffusion coefficient', refresh_vel: 'Refresh velocities',
  use_average_seq: 'Use built-in average strengths', seq_dep_file: 'Sequence parameter file',
  bussi_tau: 'Bussi tau', newtonian_steps: 'Newtonian steps',
  max_backbone_force: 'Backbone force cap', max_backbone_force_far: 'Far-force cap',
  external_forces: 'External forces', forces_file: 'Forces file', min_bp_retained: 'BP retention gate',
  conf_file: 'Starting configuration', last_conf_file: 'Final configuration',
  trajectory_file: 'Trajectory file', energy_file: 'Energy file',
  print_conf_interval: 'Configuration interval', print_energy_every: 'Energy interval',
  topology: 'Topology',
}

export function initOxdnaJobWizard({ api = {}, launch = async () => null, spawnProduction = async () => null,
  updateJob = async () => null, getInitialValues = () => ({}), getInitialTarget = () => 'local',
  getJobs = () => [], getPartPath = () => null, estimateRunSize = () => null,
  onParentChange = () => {} } = {}) {
  let modal, targetStep, currentTab = 'target', values = oxdnaWizardDefaults(), busy = false
  let editJob = null, derivedEditor = null, derivedError = null
  let mode = 'relax', parentJobId = null
  const panels = {}, tabs = {}
  let previousBtn, nextBtn, createBtn, closeBtn, configPre, stageSummary, stageTable,
    engineDetails, validationNote, wizardShell, readOnlyPanel, sourceMount

  function tabsForMode() { return mode === 'production' ? PRODUCTION_TABS : ALL_TABS }

  function renderSettings() {
    if (mode === 'production') return renderProductionSettings()
    const grid = el('div', { className: 'wizard-field-grid' })
    panels.settings.replaceChildren(el('details', { attrs: { open: true }, children: [
      el('summary', { text: 'Engine versions & installation' }), engineDetails,
    ] }), el('h3', { text: 'Engine build' }), el('div', {
      className: 'oxdna-engine-options', children: ENGINE_VARIANTS.map(([value, label, explanation]) => {
        const selected = values.engine_variant === value
        return el('button', { className: `wizard-preset${selected ? ' is-selected' : ''}`,
          attrs: { type: 'button', 'aria-pressed': String(selected) }, on: { click: () => {
            values.engine_variant = value; renderSettings(); renderConfig()
          } }, children: [el('div', { className: 'wizard-preset__label', text: label }),
            el('div', { className: 'wizard-preset__summary', text: explanation })] })
      }),
    }), el('h3', { text: 'Protocol options' }), grid)
    for (const field of FIELDS) {
      if (field.local && targetStep?.target !== 'local') continue
      if (field.readOnly && values[field.key] == null) continue
      const input = field.type === 'select' ? el('select') : el('input', { attrs: { type: field.type, min: field.min, max: field.max, step: field.step } })
      input.dataset.oxdnaField = field.key
      if (field.options) for (const [value, label] of field.options) input.append(el('option', { text: label, attrs: { value } }))
      input.value = values[field.key]
      if (field.readOnly) {
        input.readOnly = true
        input.setAttribute('aria-readonly', 'true')
      }
      input.addEventListener('input', () => {
        if (field.readOnly) return
        values[field.key] = field.type === 'number' ? Number(input.value) : input.value
        renderConfig(); paintValidation(); targetStep?.refreshSizing?.()
      })
      grid.append(el('label', { className: 'wizard-field', children: [
        el('span', { className: 'wizard-field__label', text: field.label }), input,
        field.unit ? el('span', { className: 'wizard-field__unit', text: field.unit }) : null,
        field.help ? el('span', { className: 'wizard-field__help', text: field.help }) : null,
      ] }))
    }
  }

  function renderProductionSettings() {
    const grid = el('div', { className: 'wizard-field-grid' })
    panels.settings.replaceChildren(el('h3', { text: 'Production run' }), grid)
    for (const field of PRODUCTION_FIELDS) {
      const input = el('input', { attrs: { type: field.type, min: field.min, step: field.step } })
      input.dataset.oxdnaField = field.key
      input.value = values[field.key]
      input.addEventListener('input', () => {
        values[field.key] = Number(input.value)
        renderConfig(); paintValidation()
      })
      grid.append(el('label', { className: 'wizard-field', children: [
        el('span', { className: 'wizard-field__label', text: field.label }), input,
        field.unit ? el('span', { className: 'wizard-field__unit', text: field.unit }) : null,
        field.help ? el('span', { className: 'wizard-field__help', text: field.help }) : null,
      ] }))
    }
  }

  function paintValidation() {
    if (!validationNote) return
    const result = mode === 'production' ? validateOxdnaProductionWizard(values) : validateOxdnaWizard(values)
    validationNote.textContent = result.valid ? '' : Object.values(result.errors)[0]
    validationNote.hidden = result.valid
    const ready = mode === 'production' ? true : (targetStep?.isReady?.() ?? true)
    if (createBtn) createBtn.disabled = busy || !ready || !result.valid
  }

  function renderConfig() {
    if (!configPre) return
    if (mode === 'production') return renderProductionConfig()
    configPre.textContent = oxdnaConfigDocument(values, targetStep?.payloadFields?.() || {})
    const stages = oxdnaStagePlan(values)
    stageSummary.textContent = `${stages.length} stages · ${stages.reduce((n, s) => n + s.steps, 0).toLocaleString()} scheduled steps`
    renderStageTable(stages)
  }

  /** Read-only summary — production has exactly 2 editable knobs (steps, steps_per_frame) already
   *  shown on the settings tab; backend/device/salt are inherited from the parent with no override
   *  field on RunRequest, so the editable per-stage table (which invites editing those) doesn't fit. */
  function renderProductionConfig() {
    const parentJob = getJobs().find(j => j.job_id === parentJobId) || {}
    const [stage] = oxdnaProductionStagePlan(values, parentJob)
    const { frames = 0, bytes = 0 } = estimateRunSize(stage.steps, stage.print_conf_interval, parentJobId) || {}
    stageSummary.textContent = `1 stage · ${stage.steps.toLocaleString()} scheduled steps`
      + (frames ? ` · ~${frames.toLocaleString()} frames${bytes > 0 ? ` · ~${formatBytes(bytes)} trajectory` : ''}` : '')
    stageTable.replaceChildren()
    const lines = [
      `continue_from = ${parentJob.job_id || '(none selected)'}`,
      `steps = ${stage.steps}`,
      `steps_per_frame = ${stage.print_conf_interval}`,
      `backend = ${stage.backend ?? '(inherited)'}`,
      `device = ${stage.device ?? '(inherited)'}`,
      `salt_concentration = ${stage.salt_concentration ?? '(inherited)'}`,
    ]
    configPre.textContent = `# ${stage.name}: ${stage.purpose}\n${lines.join('\n')}`
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
    renderConfig(); paintValidation(); targetStep?.refreshSizing?.()
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
          const present = stage[key] != null || (stage.sim_type === 'MD' && ['diff_coeff', 'max_backbone_force', 'max_backbone_force_far'].includes(key))
          const overridden = Object.prototype.hasOwnProperty.call(values.stage_overrides?.[stage.name] || {}, key)
          const changed = index > 0 && displayValue(stage[key]) !== displayValue(stages[index - 1][key])
          const classes = ['wizard-cell', !present ? 'wizard-cell--absent' : '', changed ? 'wizard-cell--changed' : '',
            overridden ? 'wizard-cell--overridden' : '', !editable || !present ? 'wizard-cell--locked' : ''].filter(Boolean)
          const td = el('td', { className: classes.join(' '), text: displayValue(stage[key]), attrs: {
            title: editable && present ? (key === 'diff_coeff' ? 'Required for John/Brownian/Langevin; ignored by Bussi. Enter a positive value.' : key === 'refresh_vel' ? 'true generates new velocities; false carries velocities from the preceding stage.' : key === 'bussi_tau' ? 'Coupling time in integration steps. Scale with timestep changes to preserve physical coupling time.' : 'Click to edit. Blank restores the protocol value; (none) removes a force cap.') : 'Resolved by the job builder.',
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

  function modeButton(id, label, help) {
    const selected = mode === id
    return el('button', { className: `wizard-mode${selected ? ' is-selected' : ''}`,
      attrs: { type: 'button', 'aria-pressed': String(selected) },
      on: { click: () => setMode(id) },
      children: [el('div', { className: 'wizard-mode__label', text: label }),
        el('div', { className: 'wizard-mode__help', text: help })] })
  }

  function setMode(newMode) {
    if (mode === newMode) return
    mode = newMode
    if (mode === 'production') {
      values = oxdnaProductionDefaults({ parentJobId })
      targetStep.setChoice({ target: 'local' })
      if (parentJobId) onParentChange(parentJobId)
    } else {
      values = oxdnaWizardDefaults(getInitialValues())
      targetStep.setChoice({ target: getInitialTarget() || 'local' })
    }
    currentTab = tabsForMode()[0][0]
    targetStep.render()
    renderSettings(); renderConfig(); paint()
  }

  /** Mode toggle + "Continue from" parent picker — always visible above the tab bar,
   *  mirroring NAMD's renderSource()/modeButton() (md_job_wizard.js). Overridable
   *  regardless of how open() seeded the mode. */
  function renderSource() {
    if (!sourceMount) return
    if (editJob) { sourceMount.replaceChildren(); return }   // editing an existing job's kind is fixed
    const modes = el('div', { className: 'wizard-modes', children: [
      modeButton('relax', 'Relaxation', 'Relax a fresh structure from its designed topology.'),
      modeButton('production', 'Production', 'Continue sampling from an already-relaxed structure.'),
    ] })
    const children = [modes]
    if (mode === 'production') {
      const parents = oxdnaProductionParents(getJobs(), getPartPath(), { includeJobId: parentJobId })
      if (!parents.length) {
        children.push(el('div', { className: 'wizard-note', children: [
          el('p', { text: 'No completed relaxation for this design yet. Production starts from equilibrated coordinates, so a relaxation has to finish first.' }),
          createButton({ label: 'Set up a relaxation instead', variant: 'ghost', onClick: () => setMode('relax') }),
        ] }))
      } else {
        if (!parents.some(j => j.job_id === parentJobId)) {
          parentJobId = parents[0].job_id
          onParentChange(parentJobId)
        }
        const select = el('select', { attrs: { 'aria-label': 'Continue from' } })
        for (const job of parents) {
          select.append(el('option', { text: `${job.design_name || job.job_id} — ${job.job_id}`, attrs: { value: job.job_id } }))
        }
        select.value = parentJobId
        // Re-sync the shared Anchors/Electric-field/Hard-surface/PEG panels to whichever
        // job is chosen HERE, not whatever's selected in the main list — those are
        // independent once the wizard is open (fixes stale/false capture-strand state).
        select.addEventListener('change', () => {
          parentJobId = select.value
          onParentChange(parentJobId)
          renderConfig(); paintValidation()
        })
        children.push(el('label', { className: 'wizard-field', children: [
          el('span', { className: 'wizard-field__label', text: 'Continue from' }), select,
        ] }))
      }
    }
    sourceMount.replaceChildren(...children)
  }

  function paint() {
    const activeTabs = tabsForMode()
    for (const [id] of ALL_TABS) {
      const activeEntry = activeTabs.find(([activeId]) => activeId === id)
      const inMode = !!activeEntry
      const selected = inMode && id === currentTab
      panels[id].hidden = !selected
      // .wizard-tab sets its own `display: flex` (author CSS), which beats the native
      // `[hidden] { display: none }` UA rule — the `hidden` property alone is a no-op
      // here, so the actual show/hide has to go through an inline style too.
      tabs[id].hidden = !inMode
      tabs[id].style.display = inMode ? '' : 'none'
      if (activeEntry) tabs[id].textContent = activeEntry[1]   // production relabels settings/config
      tabs[id].classList.toggle('is-selected', selected)
      tabs[id].setAttribute('aria-selected', String(selected))
    }
    const index = activeTabs.findIndex(([id]) => id === currentTab)
    if (derivedEditor) {
      previousBtn.style.display = 'none'
      nextBtn.style.display = 'none'
      createBtn.style.display = ''
      createBtn.disabled = busy
      return
    }
    previousBtn.style.display = index ? '' : 'none'
    nextBtn.style.display = index < activeTabs.length - 1 ? '' : 'none'
    createBtn.style.display = index === activeTabs.length - 1 ? '' : 'none'
    const ready = mode === 'production' ? true : (targetStep?.isReady?.() ?? true)
    nextBtn.disabled = currentTab === 'target' && !ready
    const validation = mode === 'production' ? validateOxdnaProductionWizard(values) : validateOxdnaWizard(values)
    createBtn.disabled = busy || !ready || !validation.valid
    renderSource()
    if (currentTab === 'settings') renderSettings()
    if (currentTab === 'config') renderConfig()
  }

  function selectTab(id) {
    if (mode !== 'production' && id !== 'target' && !targetStep.isReady()) return
    currentTab = id; paint()
  }
  function step(delta) {
    const activeTabs = tabsForMode()
    const i = activeTabs.findIndex(([id]) => id === currentTab)
    selectTab(activeTabs[Math.max(0, Math.min(activeTabs.length - 1, i + delta))][0])
  }
  async function submit() {
    if (busy || (!derivedEditor && mode !== 'production' && !targetStep.isReady())) return
    busy = true; paint()
    try {
      let payload
      if (derivedEditor) {
        try {
          payload = JSON.parse(derivedEditor.value)
          derivedError.textContent = ''
          derivedError.hidden = true
        } catch {
          derivedError.textContent = 'Enter valid JSON before saving.'
          derivedError.hidden = false
          return
        }
      } else if (mode === 'production') {
        payload = oxdnaProductionPayload(values)
      } else {
        payload = oxdnaWizardPayload(values, targetStep.payloadFields())
      }
      const saved = editJob
        ? await updateJob(editJob.job_id, payload)
        : mode === 'production'
          ? await spawnProduction(parentJobId, payload)
          : await launch(payload)
      if (saved) modal.close()
    }
    finally { busy = false; paint() }
  }

  function build() {
    previousBtn = createButton({ label: '← Previous', variant: 'ghost', onClick: () => step(-1) })
    nextBtn = createButton({ label: 'Next →', variant: 'primary', onClick: () => step(1) })
    createBtn = createButton({ label: 'Create job', variant: 'primary', onClick: () => void submit() })
    closeBtn = createButton({ label: 'Cancel', variant: 'ghost', onClick: () => modal.close() })
    panels.target = el('section', { className: 'wizard-pane wizard-tabpanel' })
    panels.settings = el('section', { className: 'wizard-pane wizard-tabpanel' })
    engineDetails = el('div', { className: 'wizard-note' })
    configPre = el('pre', { className: 'oxdna-wizard-config' })
    stageTable = el('div', { className: 'wizard-stages' })
    stageSummary = el('div', { className: 'wizard-totals' })
    validationNote = el('div', { className: 'wizard-note oxdna-wizard-validation', attrs: { role: 'alert' } })
    panels.config = el('section', { className: 'wizard-pane wizard-tabpanel', children: [validationNote, stageSummary,
      el('p', { className: 'oxdna-wizard-note', text: 'Click an editable cell to override that stage. Blue cells change from the previous stage; amber cells are your overrides.' }),
      stageTable, el('details', { children: [el('summary', { text: 'Config document' }), configPre] })] })
    for (const [id, label] of ALL_TABS) tabs[id] = el('button', { className: 'wizard-tab', text: label, attrs: { type: 'button', role: 'tab' }, on: { click: () => selectTab(id) } })
    targetStep = initWizardTargetStep({ mount: panels.target, fetchHardware: api.fetchHardware,
      fetchAvailability: api.fetchAvailability, getSlurmPreview: api.getSlurmPreview, getTotalNs: () => 0,
      getJobPreview: api.getRunpodJobPreview, getVolumes: api.getRunpodVolumes, setVolume: api.setRunpodVolume,
      getPlanShape: () => oxdnaRunpodPlanShape(values), fsApi: api.fsApi,
      onChange: () => { renderSettings(); renderConfig(); paint() } })
    sourceMount = el('div', { className: 'wizard-source' })
    wizardShell = el('div', { className: 'wizard', children: [sourceMount, el('div', { className: 'wizard-tabbar', children: [
        el('div', { className: 'wizard-tabs', attrs: { role: 'tablist' }, children: Object.values(tabs) })] }),
      panels.target, panels.settings, panels.config] })
    readOnlyPanel = el('section', { className: 'wizard-pane oxdna-job-settings-view' })
    readOnlyPanel.hidden = true
    modal = createModal({ title: 'New oxDNA job', size: 'xl', className: 'modal--wizard modal--oxdna-wizard',
      body: [wizardShell, readOnlyPanel], actions: [closeBtn, previousBtn, nextBtn, createBtn] })
  }

  function open(initialMode = 'relax', { parentJobId: seedParentId = null } = {}) {
    if (!modal) build()
    editJob = null
    derivedEditor = null
    modal.header.querySelector('.modal__title').textContent = 'New oxDNA job'
    wizardShell.hidden = false
    readOnlyPanel.hidden = true
    closeBtn.textContent = 'Cancel'
    createBtn.textContent = 'Create job'
    mode = initialMode === 'production' ? 'production' : 'relax'
    parentJobId = seedParentId
    if (mode === 'production') {
      values = oxdnaProductionDefaults({ parentJobId })
      targetStep.setChoice({ target: 'local' })
      if (parentJobId) onParentChange(parentJobId)
    } else {
      values = oxdnaWizardDefaults(getInitialValues())
      targetStep.setChoice({ target: getInitialTarget() || 'local' })
    }
    currentTab = tabsForMode()[0][0]
    targetStep.render(); renderSource(); renderSettings()
    void renderEngineDetails()
    renderConfig(); paint(); modal.open()
  }

  function openEditable(job = {}) {
    if (!modal) build()
    editJob = job
    derivedEditor = null
    modal.header.querySelector('.modal__title').textContent = 'Edit oxDNA job'
    const kind = job.run_config?.kind || (job.parent_job_id ? 'run' : 'relax')
    if (kind !== 'relax' || job.parent_job_id) {
      wizardShell.hidden = true
      readOnlyPanel.hidden = false
      closeBtn.textContent = 'Cancel'
      createBtn.textContent = 'Save changes'
      currentTab = 'config'
      const config = { ...(job.run_config || {}) }
      if (config.surface_strands?.built) {
        config.surface_strands = { ...config.surface_strands }
        delete config.surface_strands.built
      }
      const editable = {
        ...config,
        seed: job.random_seed ?? config.seed ?? null,
        execution_target: job.execution_target || config.execution_target || 'local',
        cluster_name: job.cluster_name || config.cluster_name || null,
        partition: job.partition || config.partition || null,
        slurm_resources: job.requested_resources || config.slurm_resources || null,
        runpod_gpu_key: job.runpod_gpu_key || config.runpod_gpu_key || null,
        runpod_budget_usd: job.runpod_budget_usd || config.runpod_budget_usd || null,
        runpod_volume_id: job.runpod_volume_id || config.runpod_volume_id || null,
        backend: job.backend,
        device: job.device,
        salt_concentration: job.salt_concentration,
        stages: (job.stages || []).map(stage => ({
          name: stage.name, kind: stage.kind, steps: stage.steps,
        })),
      }
      derivedError = el('div', { className: 'wizard-note oxdna-wizard-validation', attrs: { role: 'alert' } })
      derivedError.hidden = true
      derivedEditor = el('textarea', { className: 'oxdna-wizard-config', attrs: {
        rows: 24, spellcheck: 'false', 'aria-label': 'Editable oxDNA job configuration',
        style: 'box-sizing:border-box;width:100%;resize:vertical',
      } })
      derivedEditor.value = JSON.stringify(editable, null, 2)
      readOnlyPanel.replaceChildren(
        el('div', { className: 'wizard-note', text: 'Edit runtime, engine, target, or stage parameters below. The copied topology and force layout remain frozen.' }),
        derivedError, derivedEditor,
      )
      paint(); modal.open()
      return
    }
    wizardShell.hidden = false
    readOnlyPanel.hidden = true
    closeBtn.textContent = 'Cancel'
    createBtn.textContent = 'Save changes'
    mode = 'relax'
    values = oxdnaWizardDefaults({
      ...(job.run_config || {}),
      seed: job.random_seed ?? job.run_config?.seed,
    })
    targetStep.setChoice({
      target: job.execution_target || job.run_config?.execution_target || 'local',
      partition: job.partition || job.run_config?.partition || null,
    })
    currentTab = 'target'
    targetStep.render(); renderSource(); renderSettings()
    void renderEngineDetails()
    renderConfig(); paint(); modal.open()
  }

  function openReadOnly(job = {}) {
    if (!modal) build()
    editJob = null
    derivedEditor = null
    modal.header.querySelector('.modal__title').textContent = 'oxDNA job settings'
    wizardShell.hidden = true
    readOnlyPanel.hidden = false
    closeBtn.textContent = 'Close'
    previousBtn.style.display = 'none'
    nextBtn.style.display = 'none'
    createBtn.style.display = 'none'
    const config = { ...(job.run_config || {}) }
    // Writer-resolved build output can contain thousands of capture-particle indices;
    // the settings view shows the user's input, not that generated bookkeeping.
    if (config.surface_strands?.built) {
      config.surface_strands = { ...config.surface_strands }
      delete config.surface_strands.built
    }
    readOnlyPanel.replaceChildren(
      el('div', { className: 'wizard-note', text: 'Read-only snapshot of the settings recorded when this job was created.' }),
      el('pre', { className: 'oxdna-wizard-config', text: JSON.stringify({
        job_id: job.job_id,
        kind: config.kind || (job.parent_job_id ? 'run' : 'relax'),
        execution_target: job.execution_target || config.execution_target || 'local',
        backend: job.backend,
        device: job.device,
        salt_concentration: job.salt_concentration,
        ...config,
        seed: job.random_seed ?? config.seed ?? 'not recorded',
        stages: (job.stages || []).map(stage => ({
          name: stage.name, kind: stage.kind, steps: stage.steps,
        })),
      }, null, 2) }),
    )
    modal.open()
  }
  return { open, openEditable, openReadOnly, close: () => modal?.close(), isOpen: () => !!modal?.isOpen?.(), currentValues: () => ({ ...values }) }
}

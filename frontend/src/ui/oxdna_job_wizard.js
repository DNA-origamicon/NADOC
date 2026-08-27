import { createButton, createModal, el } from './primitives/index.js'
import { initWizardTargetStep } from './md_job_wizard_target.js'
import { oxdnaConfigDocument, oxdnaRunpodPlanShape, oxdnaStagePlan, oxdnaWizardDefaults, oxdnaWizardPayload } from './oxdna_job_wizard_model.js'

const TABS = [['target', 'Where it runs'], ['settings', 'Parameters & options'], ['config', 'Full configuration']]
const FIELDS = [
  { key: 'backend', label: 'MD backend', type: 'select', options: [['CUDA', 'CUDA (GPU)'], ['CPU', 'CPU']], local: true, help: 'MC is always CPU. This selects the backend for MD relaxation and equilibration.' },
  { key: 'device', label: 'CUDA device', type: 'text', local: true },
  { key: 'salt_concentration', label: 'Salt concentration', unit: 'M', type: 'number', min: .01, step: .05 },
  { key: 'mc_steps', label: 'MC relaxation', unit: 'steps', type: 'number', min: 100, step: 500 },
  { key: 'md_relax_steps', label: 'MD relaxation', unit: 'steps', type: 'number', min: 100, step: 100000 },
  { key: 'equil_steps', label: 'Equilibration', unit: 'steps', type: 'number', min: 100, step: 10000 },
  { key: 'min_bp_retained', label: 'Base-pair retention gate', type: 'number', min: 0, max: 1, step: .05, help: 'Stops a stage when retained designed base pairs fall below this fraction.' },
  { key: 'max_relax_retries', label: 'Escalating MD retries', type: 'number', min: 0, max: 3, step: 1, help: 'Retries a stuck backbone with longer runs and stronger force caps.' },
]

export function initOxdnaJobWizard({ api = {}, launch = async () => null, getInitialValues = () => ({}) } = {}) {
  let modal, targetStep, currentTab = 'target', values = oxdnaWizardDefaults(), busy = false
  const panels = {}, tabs = {}
  let previousBtn, nextBtn, createBtn, configPre, stageSummary

  function renderSettings() {
    const grid = el('div', { className: 'wizard-field-grid' })
    panels.settings.replaceChildren(grid)
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
    configPre = el('pre', { className: 'oxdna-wizard-config' })
    stageSummary = el('div', { className: 'wizard-totals' })
    panels.config = el('section', { className: 'wizard-pane wizard-tabpanel', children: [stageSummary,
      el('p', { className: 'oxdna-wizard-note', text: 'Every resolved stage parameter is shown below. This is the configuration the job request represents.' }), configPre] })
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
    currentTab = 'target'; targetStep.render(); renderSettings(); renderConfig(); paint(); modal.open()
  }
  return { open, close: () => modal?.close(), isOpen: () => !!modal?.isOpen?.(), currentValues: () => ({ ...values }) }
}

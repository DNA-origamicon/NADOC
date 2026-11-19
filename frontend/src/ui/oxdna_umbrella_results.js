/** Shared entry point for the job menu and metrics card's saved VMMC analysis. */
import {createModal, el} from './primitives/index.js'
import {vmmcResultView} from './oxdna_vmmc.js'

export function openUmbrellaResults(job) {
  const modal = createModal({
    title: `Umbrella results · ${job.design_name || job.job_id}`,
    className: 'oxdna-umbrella-results', size: 'lg',
    body: vmmcResultView(job),
  })
  modal.open()
  return modal
}

export function umbrellaResultActions(job) {
  return job?.run_config?.vmmc_melting
    ? [{label: 'Show umbrella results', onClick: () => openUmbrellaResults(job)}]
    : []
}

export function umbrellaResultsButton(job) {
  const [action] = umbrellaResultActions(job)
  if (!action) return null
  return el('button', {className: 'btn btn--sm', text: action.label,
    attrs: {type: 'button'}, on: {click: action.onClick}})
}
